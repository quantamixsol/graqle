"""R25-EU04 Q16.5 — Feedback trend tracking (Layer B OBSERVATION ONLY) — CG-MKT-04.

VERITAS Pillar 16 Part 1 Q16.5: "Feedback trend tracking with Welford
running statistics + 2-sigma drift alarm."

This module ships **Layer B** of the Q16.5 substrate per the binding
Research-Team patent-novelty decision (Q-PATENT 2026-05-22):

    The drift indicator is an OBSERVATION, not a TRIGGER. No code path
    in v0.57.0+ allows `drift_indicator` to invoke `calibrate()` or
    modify any reasoning-pipeline state. Operator decides whether to
    re-run calibration manually via `graq calibrate --refresh`.

The CRITICAL invariant — enforced by the mandatory test
``test_q165_no_active_recalibration_path.py`` — is: **no symbol named
``calibrate`` is called from this module**. The AST audit there will
fail the build if a future contributor accidentally wires the drift
indicator to a recalibration call.

This keeps R25-EU04 patent-clean under existing EP26167849.4 Claim 4
(which is per-call). Our drift indicator is cross-call observation only.

The maths (per R25-EU04 § Q16.5):

    Welford running statistics over rolling 30-day window W_30:
      M_n = M_{n-1} + (x_n - M_{n-1}) / n           (running mean)
      S_n = S_{n-1} + (x_n - M_{n-1}) · (x_n - M_n)  (running M2)
      σ_n = sqrt(S_n / (n-1))                        (running stdev)

    Drift indicator (passive observation):
      d = (M_today - M_baseline) / σ_baseline

    drift_alert_emitted_at = (|d| ≥ 2.0)   → emit observation, NOT trigger

This module ships **AC-Q165-1 + AC-Q165-2 + AC-Q165-3 + AC-Q165-5** of
the R25-EU04 M1 phase. The 2-sigma adversarial-corpus math test
(AC-Q165-4) + PeriodicAssessment-FeedbackTrend linkage (AC-Q165-6/7)
ship in PR-010e-1 fast-follow-on.

References:
    - R25-EU04 § "Q16.5" (Research repo)
    - VERITAS Pillar 16 Part 1 Q16.5 (Andrii Matiash, 2026-05-12)
    - Q-PATENT 2026-05-22 decision (observation-only boundary)
    - EP26167849.4 Claim 4 (per-call calibration; our drift is cross-call)
    - CG-MKT-04 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - Sibling: :mod:`graqle.compliance.periodic_assessment` (Q16.3)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger("graqle.compliance.evidence_state")

#: Feedback-source labels recognised by the ingest layer.
FeedbackSource = Literal["lesson_edges", "explicit_cli", "external_jsonl"]

#: Drift alarm threshold per R25-EU04 § Q16.5. OBSERVATION-only.
DRIFT_ALARM_SIGMA: float = 2.0


# ---------------------------------------------------------------------------
# Welford running statistics — pure, observation-only
# ---------------------------------------------------------------------------


@dataclass
class WelfordAccumulator:
    """Welford's online mean + variance.

    Pure, side-effect-free numerical accumulator. The accumulator state
    is intentionally mutable (this is a streaming reducer); the
    *serialised* :class:`FeedbackTrend` snapshot built from it is frozen.

    Properties:
        n: Number of samples observed.
        mean: Running mean.
        m2: Running second-moment ("S_n" in the spec).
        stdev: Sample standard deviation (sqrt(m2 / (n-1))).
            Returns 0.0 when n < 2.
    """

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, x: float) -> None:
        """Add one observation. Pure numeric; no side effects beyond self."""
        if not isinstance(x, (int, float)):
            raise TypeError(
                f"WelfordAccumulator.add expects real number, got "
                f"{type(x).__name__}"
            )
        xf = float(x)
        if math.isnan(xf) or math.isinf(xf):
            raise ValueError(
                f"WelfordAccumulator.add expects finite number, got {xf!r}"
            )
        self.n += 1
        delta = xf - self.mean
        self.mean += delta / self.n
        delta2 = xf - self.mean
        self.m2 += delta * delta2

    @property
    def stdev(self) -> float:
        """Sample standard deviation. 0.0 when n < 2."""
        if self.n < 2:
            return 0.0
        return math.sqrt(self.m2 / (self.n - 1))


# ---------------------------------------------------------------------------
# Feedback record + trend snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackRecord:
    """A single feedback record from one of the three sources.

    Attributes:
        source: Where the feedback originated.
        rating: Numeric rating (typically 1..5 for CLI; arbitrary float
            for derived sources).
        timestamp_iso: ISO 8601 UTC timestamp.
        session_id: Optional GraQle session ID for cross-linking.
        note: Optional free-text note (max 4096 chars enforced by
            ingest layer).
    """

    source: FeedbackSource
    rating: float
    timestamp_iso: str
    session_id: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class FeedbackTrend:
    """OBSERVATION-only Welford+drift snapshot for one feedback source.

    Per the Q-PATENT 2026-05-22 boundary, the ``drift_indicator`` here
    is *emitted* — never *acted on*. This dataclass has no method that
    invokes recalibration; the audit test
    ``test_q165_no_active_recalibration_path.py`` enforces this.

    Attributes:
        source: One of :data:`FeedbackSource` literals.
        window_days: The rolling-window size (default 30 per spec).
        n_samples: Sample count in the window.
        mean: Running mean over the window.
        stdev: Running stdev over the window.
        baseline_mean: Mean computed at the previous baseline.
        baseline_stdev: Stdev at the previous baseline.
        drift_indicator: ``(M_today - M_baseline) / σ_baseline``;
            ``None`` when ``baseline_stdev`` is 0.0 (degenerate case).
        drift_alert_emitted: True iff ``|drift_indicator| >= 2.0``.
            This is the OBSERVATION — the operator decides what to do
            with it.
        snapshot_at_iso: ISO 8601 UTC timestamp of snapshot construction.
    """

    source: FeedbackSource
    window_days: int
    n_samples: int
    mean: float
    stdev: float
    baseline_mean: float
    baseline_stdev: float
    drift_indicator: float | None
    drift_alert_emitted: bool
    snapshot_at_iso: str
    proof_format_version: str = "R25-EU08-v1.0"

    def to_canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def trend_id(self) -> str:
        """Content-addressed identifier (SHA-256 of canonical JSON)."""
        canonical = json.dumps(
            self.to_canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_drift_indicator(
    *,
    current_mean: float,
    baseline_mean: float,
    baseline_stdev: float,
) -> float | None:
    """Return ``(M_today - M_baseline) / σ_baseline`` or ``None``.

    Per R25-EU04 § Q16.5. Returns ``None`` when ``baseline_stdev`` is
    0.0 (the degenerate case where the baseline window had zero or one
    sample) — callers must handle the ``None`` rather than producing a
    division-by-zero error.

    This function is OBSERVATION-ONLY. It performs arithmetic on three
    floats. There is no code path here that invokes a calibration call
    or mutates any pipeline state. The Q-PATENT 2026-05-22 boundary is
    enforced by the audit test.
    """
    if not isinstance(current_mean, (int, float)) or not isinstance(
        baseline_mean, (int, float)
    ) or not isinstance(baseline_stdev, (int, float)):
        raise TypeError("drift_indicator inputs must be real numbers")
    if math.isnan(current_mean) or math.isinf(current_mean):
        raise ValueError("current_mean must be finite")
    if math.isnan(baseline_mean) or math.isinf(baseline_mean):
        raise ValueError("baseline_mean must be finite")
    if math.isnan(baseline_stdev) or math.isinf(baseline_stdev):
        raise ValueError("baseline_stdev must be finite")
    if baseline_stdev <= 0.0:
        return None
    return (float(current_mean) - float(baseline_mean)) / float(baseline_stdev)


def build_feedback_trend(
    *,
    source: FeedbackSource,
    records: Iterable[FeedbackRecord],
    baseline_mean: float = 0.0,
    baseline_stdev: float = 0.0,
    window_days: int = 30,
) -> FeedbackTrend:
    """Build a :class:`FeedbackTrend` snapshot.

    Computes Welford mean + stdev over ``records`` and the drift
    indicator against the supplied baseline. The function does NOT
    decide what to do with the drift — that's the operator's call.

    Args:
        source: Feedback-source label.
        records: Iterable of :class:`FeedbackRecord` for the current
            window.
        baseline_mean: Mean from the previous baseline window.
        baseline_stdev: Stdev from the previous baseline window. ``0.0``
            means "no usable baseline yet"; the resulting
            ``drift_indicator`` will be ``None`` and
            ``drift_alert_emitted`` will be ``False``.
        window_days: Window size in days (default 30 per spec).

    Returns:
        FeedbackTrend: Frozen snapshot.
    """
    acc = WelfordAccumulator()
    for r in records:
        acc.add(float(r.rating))
    drift = compute_drift_indicator(
        current_mean=acc.mean,
        baseline_mean=baseline_mean,
        baseline_stdev=baseline_stdev,
    )
    alert = drift is not None and abs(drift) >= DRIFT_ALARM_SIGMA
    return FeedbackTrend(
        source=source,
        window_days=window_days,
        n_samples=acc.n,
        mean=acc.mean,
        stdev=acc.stdev,
        baseline_mean=baseline_mean,
        baseline_stdev=baseline_stdev,
        drift_indicator=drift,
        drift_alert_emitted=alert,
        snapshot_at_iso=_iso_now(),
    )


# ---------------------------------------------------------------------------
# Feedback record I/O (AC-Q165-1 + AC-Q165-2)
# ---------------------------------------------------------------------------

_MAX_NOTE_LEN: int = 4096


def _validate_record(rec: FeedbackRecord) -> None:
    """Defensive validation on a FeedbackRecord before persistence."""
    if not isinstance(rec.rating, (int, float)):
        raise TypeError(
            f"FeedbackRecord.rating must be real number, got "
            f"{type(rec.rating).__name__}"
        )
    if math.isnan(rec.rating) or math.isinf(rec.rating):
        raise ValueError("FeedbackRecord.rating must be finite")
    if rec.note is not None and len(rec.note) > _MAX_NOTE_LEN:
        raise ValueError(
            f"FeedbackRecord.note exceeds maximum length {_MAX_NOTE_LEN}"
        )


def append_feedback_record(
    rec: FeedbackRecord,
    output_path: Path,
) -> Path:
    """Append a single :class:`FeedbackRecord` to a JSONL log.

    SECURITY POSTURE (sentinel pass 2):
    The ``output_path`` is operator-supplied at CLI invocation. By
    design, the operator chooses where to persist the audit log; this
    function does NOT validate the path against a directory allow-list
    because that would force a centralised feedback directory and
    break the deployer's freedom to integrate with their own audit-log
    infrastructure (e.g. mounted S3, NFS, deployer-controlled storage).
    The trust boundary is the CLI permission model: anyone who can run
    ``graq compliance feedback record --output X`` already has write
    access to ``X`` via the OS layer.

    User-supplied CONTENT (``rec.note``, ``rec.session_id``) NEVER
    flows into a filesystem path — it lives only inside the JSON body.
    """
    _validate_record(rec)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        asdict(rec), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    with output_path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.write("\n")
    return output_path


def ingest_feedback_jsonl(
    input_path: Path,
    output_path: Path | None = None,
) -> list[FeedbackRecord]:
    """Parse an external feedback JSONL file into :class:`FeedbackRecord` objects.

    Per AC-Q165-2: external JSONL ingest. The shape is the same one
    :func:`append_feedback_record` emits — fields ``source``, ``rating``,
    ``timestamp_iso``, optional ``session_id``, optional ``note``.

    Args:
        input_path: Path to the JSONL input.
        output_path: If supplied, append the parsed records to this
            JSONL log (typical: the operator's persistent feedback
            archive). When None, just parse + return.

    Returns:
        list[FeedbackRecord]: Parsed records (in input order).

    Raises:
        FileNotFoundError: If ``input_path`` does not exist.
        ValueError: If any line fails validation.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"feedback JSONL not found: {input_path}")
    records: list[FeedbackRecord] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"feedback JSONL line {line_no} is not valid JSON: {exc}"
                ) from exc
            try:
                rec = FeedbackRecord(
                    source=obj["source"],
                    rating=float(obj["rating"]),
                    timestamp_iso=obj["timestamp_iso"],
                    session_id=obj.get("session_id"),
                    note=obj.get("note"),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"feedback JSONL line {line_no} missing/invalid fields: {exc}"
                ) from exc
            _validate_record(rec)
            records.append(rec)
            if output_path is not None:
                append_feedback_record(rec, output_path)
    return records
