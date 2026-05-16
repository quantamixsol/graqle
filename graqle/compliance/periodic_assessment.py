"""R25-EU04 Q16.3 — Periodic assessment over window (CG-MKT-03).

VERITAS Pillar 16 Part 1 Q16.3: "Periodic-assessment artefact produces
dated written outputs with tracked remediation actions; cadence
configurable per deployer."

This module ships the *runtime* for that artefact. Q16.3 is independent
of the Q16.1 baseline-doc generator (which ships in PR-010d /
:mod:`graqle.compliance.baseline_doc`) but every periodic-assessment
record references the most recent ``baseline_id`` per AC-Q163-6 — so the
Cl. 9.1 monitoring chain (ISO 42001) traces back to the Cl. 6.2 planning
baseline.

The maths (per R25-EU04 § Q16.3):

    A(W)  =  (
      period_start            : t_start,
      period_end              : t_end,
      cadence                 : "monthly" | "quarterly" | "annual",
      n_calls                 : |S_W|,
      quality_metrics         : Q(S_W),
      remediation_actions     : R(S_W),
      drift_indicators        : D(S_W, baseline)
    )

    Q(S_W) = (
      mean_confidence,
      p95_confidence,
      n_degraded                   = |{R : R.graph_health.degraded}|,
      n_outcome_not_ok             = |{R : R.outcome != "OK"}|,
      n_governance_refusals        = |{R : R.governance.refused}|
    )

    Threshold breaches (default):
      n_outcome_not_ok / n_calls > 0.02   → severity=high
      n_degraded / n_calls > 0.05         → severity=warn
      mean_confidence < 0.6                → severity=warn

This module ships **Task 1.4 + 1.5** of R25-EU04 M1. APScheduler
integration (Task 1.6) + sidecar integration (Task 1.7) are deferred to
PR-010e-1 fast-follow-on.

Regulatory anchors:
    - **EU AI Act Article 9** (risk management) — periodic assessment is
      the *evidence-producing* arm of the risk-management file.
    - **EU AI Act Article 11** (technical documentation) — the assessment
      artefact is part of the deployer's Annex IV file.
    - **ISO 42001 Cl. 9.1** (monitoring, measurement, analysis,
      evaluation) — Cl. 9.1 evidence directly.

Public-comms framing: this module is **"EU AI Act–aligned"**, never
"compliant" / "certified" / "guaranteed".

References:
    - R25-EU04 § "Q16.3" (Research repo)
    - VERITAS Pillar 16 Part 1 Q16.3 (Andrii Matiash, 2026-05-12)
    - ADR-MARKETING-002 §5 (binding mapping)
    - CG-MKT-03 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - Sibling: :mod:`graqle.compliance.baseline_doc` (Q16.1, PR-010d)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger("graqle.compliance.periodic_assessment")

# ---------------------------------------------------------------------------
# Constants — Q16.3 threshold defaults
# ---------------------------------------------------------------------------

#: Cadence literals — accepted via CLI + config.
Cadence = Literal["monthly", "quarterly", "annual"]

#: Default threshold for the "outcome-not-ok rate is alarming" trigger.
#: Per R25-EU04 § Q16.3. Operators may override per-deployer via config
#: in a future PR; today the value is hard-coded.
THRESHOLD_OUTCOME_NOT_OK_RATE: float = 0.02

#: Default threshold for the "degraded-graph rate is alarming" trigger.
THRESHOLD_DEGRADED_RATE: float = 0.05

#: Default threshold for the "mean confidence too low" trigger.
THRESHOLD_LOW_MEAN_CONFIDENCE: float = 0.6

#: Severity literals on remediation actions.
Severity = Literal["high", "warn", "info"]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityMetrics:
    """Q(S_W) — quality metrics computed over the window.

    All values are non-negative; when the window has zero records, the
    confidence stats are 0.0 and the count stats are 0 (callers should
    check ``n_calls`` first to disambiguate "empty window" from "bad
    window").
    """

    mean_confidence: float
    p95_confidence: float
    n_degraded: int
    n_outcome_not_ok: int
    n_governance_refusals: int


@dataclass(frozen=True)
class RemediationAction:
    """A remediation candidate triggered by a threshold breach.

    Per AC-Q163-3: remediation candidates are auto-created when
    threshold breaches are detected. The action is a *recommendation* —
    operators decide whether to act on it.
    """

    trigger: str
    severity: Severity
    observed_value: float
    threshold: float
    recommendation: str


@dataclass(frozen=True)
class PeriodicAssessment:
    """A dated periodic-assessment record per R25-EU04 Q16.3.

    Attributes:
        period_start_iso: ISO 8601 UTC timestamp (window start, inclusive).
        period_end_iso: ISO 8601 UTC timestamp (window end, exclusive).
        cadence: One of :data:`Cadence` literals.
        n_calls: Number of ResponseSnapshots in the window.
        quality_metrics: Computed quality stats.
        remediation_actions: List of triggered remediation candidates.
        baseline_id: Reference to the most recent
            :class:`~graqle.compliance.baseline_doc.BaselineDocument`
            ``baseline_id`` at the time the assessment was run (AC-Q163-6).
            ``""`` when no baseline has been generated yet.
        proof_format_version: Always
            :data:`PROOF_FORMAT_VERSION` for this writer.
    """

    period_start_iso: str
    period_end_iso: str
    cadence: Cadence
    n_calls: int
    quality_metrics: QualityMetrics
    remediation_actions: tuple[RemediationAction, ...] = field(default_factory=tuple)
    baseline_id: str = ""
    proof_format_version: str = "R25-EU08-v1.0"

    def to_canonical_dict(self) -> dict[str, Any]:
        """Deterministic dict for canonicalisation + JSON emission."""
        d = asdict(self)
        # asdict converts dataclasses recursively — tuples become lists
        return d

    @property
    def assessment_id(self) -> str:
        """Content-addressed identifier per AC-Q163-7 (idempotency).

        Re-running ``assess_window`` for the same ``(period, cadence,
        baseline_id)`` over the same input corpus produces byte-identical
        canonical JSON — hence the same ``assessment_id``.
        """
        canonical = json.dumps(
            self.to_canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Response-snapshot trace reader (minimal protocol)
# ---------------------------------------------------------------------------


def _iter_traces_in_window(
    traces: Iterable[dict[str, Any]],
    period_start_iso: str,
    period_end_iso: str,
) -> list[dict[str, Any]]:
    """Filter trace records to those whose timestamp lies in [start, end).

    Args:
        traces: Iterable of trace dicts (file-based or in-memory). Each
            dict must have a ``timestamp_iso`` (or ``generated_at_iso``)
            key. Other shape variations are tolerated and skipped.
        period_start_iso: Inclusive lower bound (ISO 8601).
        period_end_iso: Exclusive upper bound (ISO 8601).

    Returns:
        list[dict[str, Any]]: Filtered traces.
    """
    result = []
    for t in traces:
        ts = t.get("timestamp_iso") or t.get("generated_at_iso")
        if not isinstance(ts, str):
            continue
        if period_start_iso <= ts < period_end_iso:
            result.append(t)
    return result


def _percentile(values: list[float], p: float) -> float:
    """Compute the ``p``-th percentile (0..1) of ``values``.

    Uses linear interpolation between closest ranks. Returns 0.0 on
    empty input. Pure-Python; no numpy dep.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


# ---------------------------------------------------------------------------
# Quality metrics + remediation
# ---------------------------------------------------------------------------


def compute_quality_metrics(traces: list[dict[str, Any]]) -> QualityMetrics:
    """Compute Q(S_W) over the trace records.

    Traces missing fields are skipped for the relevant aggregator (e.g.
    a trace without a ``confidence`` field doesn't contribute to the
    mean, but still counts in ``n_calls`` for the caller).

    Per sentinel pass 1 MAJOR-2: non-dict entries in the input list
    are skipped defensively (a malformed external feed shouldn't break
    the aggregation).
    """
    confidences: list[float] = []
    n_degraded = 0
    n_outcome_not_ok = 0
    n_governance_refusals = 0
    for t in traces:
        if not isinstance(t, dict):
            # Defensive: skip non-dict entries from malformed feeds.
            continue
        if "confidence" in t and isinstance(t["confidence"], (int, float)):
            c = float(t["confidence"])
            # Skip NaN/inf — would corrupt mean + percentile
            if not (c != c or c in (float("inf"), float("-inf"))):
                confidences.append(c)
        gh = t.get("graph_health") or {}
        if isinstance(gh, dict) and gh.get("degraded"):
            n_degraded += 1
        outcome = t.get("outcome")
        if isinstance(outcome, str) and outcome != "OK":
            n_outcome_not_ok += 1
        gov = t.get("governance") or {}
        if isinstance(gov, dict) and gov.get("refused"):
            n_governance_refusals += 1
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    p95_conf = _percentile(confidences, 0.95)
    return QualityMetrics(
        mean_confidence=mean_conf,
        p95_confidence=p95_conf,
        n_degraded=n_degraded,
        n_outcome_not_ok=n_outcome_not_ok,
        n_governance_refusals=n_governance_refusals,
    )


def compute_remediation_actions(
    n_calls: int,
    quality_metrics: QualityMetrics,
) -> tuple[RemediationAction, ...]:
    """Build the remediation-action list from threshold breaches.

    Per R25-EU04 § Q16.3 default thresholds:

      - ``n_outcome_not_ok / n_calls > 0.02`` → severity=high
      - ``n_degraded / n_calls > 0.05`` → severity=warn
      - ``mean_confidence < 0.6`` → severity=warn

    Args:
        n_calls: Total trace records in the window.
        quality_metrics: Q(S_W).

    Returns:
        tuple[RemediationAction, ...]: Triggered actions in stable order
        (high-severity first, then warn).
    """
    actions: list[RemediationAction] = []
    if n_calls > 0:
        outcome_rate = quality_metrics.n_outcome_not_ok / n_calls
        if outcome_rate > THRESHOLD_OUTCOME_NOT_OK_RATE:
            actions.append(RemediationAction(
                trigger="outcome_not_ok_rate_exceeded",
                severity="high",
                observed_value=outcome_rate,
                threshold=THRESHOLD_OUTCOME_NOT_OK_RATE,
                recommendation=(
                    f"Outcome-not-OK rate ({outcome_rate:.2%}) exceeds "
                    f"threshold ({THRESHOLD_OUTCOME_NOT_OK_RATE:.2%}). "
                    f"Investigate recent ResponseSnapshots with non-OK "
                    f"outcomes; consider rolling back the most recent "
                    f"deployment if the breach correlates with a release."
                ),
            ))
        degraded_rate = quality_metrics.n_degraded / n_calls
        if degraded_rate > THRESHOLD_DEGRADED_RATE:
            actions.append(RemediationAction(
                trigger="degraded_graph_rate_exceeded",
                severity="warn",
                observed_value=degraded_rate,
                threshold=THRESHOLD_DEGRADED_RATE,
                recommendation=(
                    f"Degraded-graph rate ({degraded_rate:.2%}) exceeds "
                    f"threshold ({THRESHOLD_DEGRADED_RATE:.2%}). Run "
                    f"`graq doctor` on the affected workspace and check "
                    f"KG health metrics."
                ),
            ))
    # mean_confidence threshold applies even when n_calls is 0 (will be
    # 0.0 which is below 0.6) — but only emit when there were actual
    # records to assess.
    if n_calls > 0 and quality_metrics.mean_confidence < THRESHOLD_LOW_MEAN_CONFIDENCE:
        actions.append(RemediationAction(
            trigger="mean_confidence_below_threshold",
            severity="warn",
            observed_value=quality_metrics.mean_confidence,
            threshold=THRESHOLD_LOW_MEAN_CONFIDENCE,
            recommendation=(
                f"Mean confidence ({quality_metrics.mean_confidence:.3f}) "
                f"below threshold ({THRESHOLD_LOW_MEAN_CONFIDENCE}). "
                f"Consider running calibration spike R25-EU-CALIB-01 "
                f"or reviewing prompt-quality regressions."
            ),
        ))
    return tuple(actions)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def assess_window(
    *,
    traces: Iterable[dict[str, Any]],
    period_start_iso: str,
    period_end_iso: str,
    cadence: Cadence = "monthly",
    baseline_id: str = "",
) -> PeriodicAssessment:
    """Build a :class:`PeriodicAssessment` for the given window.

    Args:
        traces: Iterable of ResponseSnapshot-shaped trace records (from
            R18 trace corpus or operator-supplied JSONL).
        period_start_iso: Inclusive lower bound of the assessment
            window (ISO 8601 UTC).
        period_end_iso: Exclusive upper bound.
        cadence: ``"monthly"`` | ``"quarterly"`` | ``"annual"``.
        baseline_id: SHA-256 of the most recent Q16.1 baseline document
            (AC-Q163-6). Pass ``""`` if no baseline has been generated
            yet — this is surfaced explicitly in the output for the
            auditor.

    Returns:
        PeriodicAssessment: Content-addressable artefact.
    """
    filtered = _iter_traces_in_window(traces, period_start_iso, period_end_iso)
    quality = compute_quality_metrics(filtered)
    remediation = compute_remediation_actions(len(filtered), quality)
    return PeriodicAssessment(
        period_start_iso=period_start_iso,
        period_end_iso=period_end_iso,
        cadence=cadence,
        n_calls=len(filtered),
        quality_metrics=quality,
        remediation_actions=remediation,
        baseline_id=baseline_id,
    )


# ---------------------------------------------------------------------------
# JSONL emitter
# ---------------------------------------------------------------------------


def to_jsonl(assessment: PeriodicAssessment, output_path: Path) -> Path:
    """Append-only JSONL emitter for periodic assessments."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = assessment.to_canonical_dict()
    record["assessment_id"] = assessment.assessment_id
    line = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    with output_path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.write("\n")
    return output_path
