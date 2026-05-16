"""R25-EU04 Q16.1 — Baseline document at deployment (CG-MKT-02).

VERITAS Pillar 16 Part 1 (Andrii Matiash, published 2026-05-12) defines
Q16.1 as: "Quality baseline documentation at deployment with quantitative
performance metrics, test archives, version records, formal stakeholder
sign-off". This module ships the *generator* for that artefact.

The maths (per R25-EU04 § "Q16.1"):

    B(v, t)  =  (
      sdk_version              : str = v,
      generated_at_iso         : str = t,
      quantitative_metrics     : dict[str, float],
      test_archive_ref         : str  (SHA-256 of CI test-run record),
      version_records          : dict[str, str]
                                  (git_sha, pypi_version, sigstore_digest),
      stakeholder_signoff      : str | None,
      articles_covered         : list[str],
      iso_42001_clauses        : list[str],
      proof_format_version     : str  (per R25-EU08)
    )

    baseline_id = SHA-256(canonicalize_json(B))   # content-addressed

Identical baselines (same SDK version + same metrics) produce the same
``baseline_id`` — i.e. the document deduplicates over time.

Canonicalisation note: this module uses ``json.dumps(sort_keys=True,
separators=(",", ":")).encode("utf-8")`` as the canonical form. This is
the same approach the PCT issuer uses (see ``graqle.pct.issuer``) and
is interoperable with the OPSF v0.1 token spec. A fully RFC 8785 JCS
implementation is not required for v1.0; if Q16.1 audits ever need
strict RFC 8785, the upgrade is local to one helper (`_canonicalize`).

This module ships **Task 1.1 + Task 1.2 + Task 1.3** of the R25-EU04
M1 phase. The Q16.3 periodic-assessment module (Task 1.4–1.6) ships
in PR-010e.

The schema below maps to:

    - **EU AI Act Article 11**: technical documentation at deployment.
    - **ISO 42001 Cl. 6.2**: AI management system planning, baseline
      establishment.
    - **VERITAS Q16.1**: quality baseline at deployment.

Public-comms framing: this module is **"EU AI Act–aligned"**, never
"compliant" / "certified" / "guaranteed".

References:
    - R25-EU04 § "Q16.1" (Research repo, R25-EU04-operational-discipline-veritas-q16.md)
    - VERITAS Pillar 16 Part 1 (Andrii Matiash, 2026-05-12)
    - ADR-MARKETING-002 §5 (binding mapping)
    - CG-MKT-02 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - docs/compliance/eu-ai-act/baseline-document-schema.md (public doc)
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.compliance.baseline_doc")


# ---------------------------------------------------------------------------
# Constants — public mapping to EU AI Act + ISO 42001
# ---------------------------------------------------------------------------

#: The proof-format version this module emits. Bumping requires a
#: separate ADR; readers should refuse to consume a baseline document
#: whose ``proof_format_version`` is unknown.
PROOF_FORMAT_VERSION: str = "R25-EU08-v1.0"

#: EU AI Act articles whose technical-documentation surface this
#: baseline document attests to. Re-uses the list shipped in v0.56.0.
DEFAULT_ARTICLES_COVERED: tuple[str, ...] = (
    "4",   # AI literacy
    "11",  # Technical documentation (the central anchor for Q16.1)
    "12",  # Record keeping
    "13",  # Transparency to deployers
    "14",  # Human oversight
    "15",  # Accuracy + robustness + cybersecurity
    "25",  # Value-chain obligations
    "50",  # Transparency obligations (user-facing AI disclosure)
)

#: ISO 42001 clauses the baseline document supports.
DEFAULT_ISO_42001_CLAUSES: tuple[str, ...] = (
    "6.2",  # AI management system planning + objectives
    "9.1",  # Monitoring, measurement, analysis, evaluation
)

#: Sentinel value emitted when the corresponding upstream record is not
#: yet wired. Auditors should treat this as "operator must supply"
#: rather than "operator has supplied an empty value".
NOT_YET_AVAILABLE: str = "NOT_YET_AVAILABLE"


# ---------------------------------------------------------------------------
# BaselineDocument dataclass — Q16.1 math formulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineDocument:
    """A dated, version-pinned baseline document per VERITAS Q16.1.

    All fields are required (no Optional[]) except ``stakeholder_signoff``,
    which is None until a human operator countersigns the artefact.

    Attributes:
        sdk_version: SDK semver (e.g. ``"0.56.0"``).
        generated_at_iso: ISO 8601 UTC timestamp (``...Z`` suffix).
        quantitative_metrics: Numeric performance metrics. Required keys:
            ``test_count``, ``pass_rate``, ``p95_latency_ms``,
            ``p95_envelope_size_bytes``, ``n_governance_gates_active``,
            ``n_defences_active``. Values may be ``NOT_YET_AVAILABLE``
            when a metric source is not wired (e.g. p95_latency_ms before
            R18 trace corpus aggregation lands).
        test_archive_ref: SHA-256 of the canonical CI test-run record
            for this SDK version. ``NOT_YET_AVAILABLE`` is acceptable
            during early adoption.
        version_records: Mapping with ``git_sha``, ``pypi_version``,
            ``sigstore_digest``. ``sigstore_digest`` is
            ``NOT_YET_AVAILABLE`` until R25-EU01 v2 ships.
        stakeholder_signoff: Email or identity string of the human
            operator who countersigns the artefact. ``None`` until
            signed; an unsigned baseline is still valid for auditors as
            a "draft for sign-off" artefact.
        articles_covered: Tuple of EU AI Act article numbers (strings)
            that the baseline document attests to.
        iso_42001_clauses: Tuple of ISO 42001 clause identifiers.
        proof_format_version: Always
            :data:`PROOF_FORMAT_VERSION` for this writer; readers may
            refuse unknown versions.
    """

    sdk_version: str
    generated_at_iso: str
    quantitative_metrics: dict[str, Any]
    test_archive_ref: str
    version_records: dict[str, str]
    articles_covered: tuple[str, ...]
    iso_42001_clauses: tuple[str, ...]
    proof_format_version: str = PROOF_FORMAT_VERSION
    stakeholder_signoff: str | None = None

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return a deterministic dict shape for canonicalisation.

        Tuples are converted to lists (JSON has no tuple); the field
        ordering is alphabetical (json.dumps sort_keys handles this).
        """
        d = asdict(self)
        # tuples -> lists for JSON compat
        d["articles_covered"] = list(self.articles_covered)
        d["iso_42001_clauses"] = list(self.iso_42001_clauses)
        return d

    @property
    def baseline_id(self) -> str:
        """Content-addressed identifier: ``SHA-256(canonicalize(B))``.

        Identical baselines (same SDK version + same metrics + same
        signoff + same articles + same clauses) produce the same
        ``baseline_id``. Recomputed on demand (no cache) so the value
        always reflects the current dataclass state.
        """
        canonical = _canonicalize(self.to_canonical_dict())
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------


def _canonicalize(obj: Any) -> bytes:
    """Return a deterministic byte string for ``obj``.

    Uses the same approach as :mod:`graqle.pct.issuer`:
    ``json.dumps(sort_keys=True, separators=(",", ":")).encode("utf-8")``.
    Equivalent to RFC 8785 JCS for the shapes this module emits
    (string-keyed dicts, lists, ints/floats, bool, None, str).

    Note: if Q16.1 audits ever need *strict* RFC 8785 (number
    normalisation per ECMA-262, Unicode normalisation), upgrade this
    one helper. Every other call site goes through here.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Live-metric collectors (Task 1.1)
# ---------------------------------------------------------------------------


def _get_sdk_version() -> str:
    """Best-effort lookup of the installed SDK version."""
    try:
        from graqle import __version__ as _v  # type: ignore[attr-defined]
        return str(_v)
    except Exception:  # noqa: BLE001 — version probe must never fail the builder
        return NOT_YET_AVAILABLE


def _iso_now() -> str:
    """Current UTC timestamp as ISO-8601 ``...Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_git_sha(cwd: Path | None = None) -> str:
    """Best-effort lookup of the current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return NOT_YET_AVAILABLE


def _collect_quantitative_metrics() -> dict[str, Any]:
    """Collect the required Q16.1 quantitative metrics.

    Some sources are wired today; others remain ``NOT_YET_AVAILABLE``
    until their feeding infrastructure ships:

      - ``test_count``: ``NOT_YET_AVAILABLE`` (live `pytest --collect-only`
        is too expensive to spawn from the CLI; operator-controlled CI
        run record supplies this via ``test_archive_ref``).
      - ``pass_rate``: ``NOT_YET_AVAILABLE`` (sourced from CI run record).
      - ``p95_latency_ms``: ``NOT_YET_AVAILABLE`` (sourced from R18 trace
        corpus aggregation — ships with Q16.3).
      - ``p95_envelope_size_bytes``: ``NOT_YET_AVAILABLE`` (same).
      - ``n_governance_gates_active``: integer count of active gates
        (CG-01..CG-08 etc.). Wired today via static enumeration.
      - ``n_defences_active``: integer count of robustness defences.
        Wired today via :mod:`graqle.compliance.robustness`.

    The sentinel values are still serialisable — they appear in the
    output JSONL as plain strings. An auditor reads them as
    "operator must supply via the CI integration".
    """
    metrics: dict[str, Any] = {
        "test_count": NOT_YET_AVAILABLE,
        "pass_rate": NOT_YET_AVAILABLE,
        "p95_latency_ms": NOT_YET_AVAILABLE,
        "p95_envelope_size_bytes": NOT_YET_AVAILABLE,
        "n_governance_gates_active": NOT_YET_AVAILABLE,
        "n_defences_active": NOT_YET_AVAILABLE,
    }

    # n_governance_gates_active — static enumeration of CG-01..CG-08 +
    # CG-MKT-01 (Article 14 gate) and CG-MKT-10 (claim-limits gate).
    # When new gates ship, this count is the source of truth for the
    # baseline doc; downstream auditors read it for "how many guards
    # protect this build?".
    try:
        from graqle.config.settings import GovernancePolicyConfig
        cfg = GovernancePolicyConfig()
        active_gates = sum(
            1 for attr in (
                "session_gate_enabled",
                "plan_mandatory",
                "edit_enforcement",
            ) if getattr(cfg, attr, False)
        )
        # Add 2 for the always-active Article 14 + claim-limits gates
        active_gates += 2
        metrics["n_governance_gates_active"] = active_gates
    except Exception as exc:  # noqa: BLE001
        logger.debug("baseline_doc: governance gate count unavailable: %s", exc)

    # n_defences_active — via robustness attestation if available.
    try:
        from graqle.compliance.robustness import build_robustness_attestation
        att = build_robustness_attestation()
        metrics["n_defences_active"] = int(getattr(att, "n_defences", 0))
    except Exception as exc:  # noqa: BLE001
        logger.debug("baseline_doc: defence count unavailable: %s", exc)

    return metrics


def _collect_version_records(cwd: Path | None = None) -> dict[str, str]:
    """Collect the required Q16.1 version-record fields."""
    return {
        "git_sha": _get_git_sha(cwd),
        "pypi_version": _get_sdk_version(),
        # Sigstore digest ships with R25-EU01 v2. Placeholder for now —
        # explicit, surfaced as sentinel rather than empty string.
        "sigstore_digest": NOT_YET_AVAILABLE,
    }


# ---------------------------------------------------------------------------
# Builder (Task 1.1)
# ---------------------------------------------------------------------------


#: Maximum length for free-text identity fields (signoff, test_archive_ref).
#: Sentinel pass 2 MINOR: prevents oversized JSON records when an operator
#: paste-bombs a multi-MB string into --signoff. 1024 is well above any
#: realistic email + role description.
_MAX_FREE_TEXT_LEN: int = 1024


def _validate_free_text(value: str | None, *, field_name: str) -> str | None:
    """Validate a free-text field for shape + length.

    Per sentinel pass 2 MINOR finding: length-cap user-supplied strings
    that flow into the JSON envelope so a misbehaving operator cannot
    bloat the audit-log file. Non-string non-None types raise TypeError.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be str or None, got {type(value).__name__}"
        )
    if len(value) > _MAX_FREE_TEXT_LEN:
        raise ValueError(
            f"{field_name} exceeds maximum length of {_MAX_FREE_TEXT_LEN} "
            f"characters (got {len(value)})"
        )
    return value


def build_baseline_document(
    *,
    signoff: str | None = None,
    cwd: Path | None = None,
    articles_covered: tuple[str, ...] | None = None,
    iso_42001_clauses: tuple[str, ...] | None = None,
    test_archive_ref: str | None = None,
) -> BaselineDocument:
    """Build a fresh :class:`BaselineDocument` from live SDK state.

    Args:
        signoff: Optional email / identity string of the human operator
            countersigning the artefact. Max 1024 chars.
        cwd: Working directory for git-sha lookup. Defaults to the
            current process CWD.
        articles_covered: Override for the default article list (rare —
            the default is the canonical v1.0 set).
        iso_42001_clauses: Override for the default ISO 42001 clause list.
        test_archive_ref: SHA-256 of the CI test-run record (supplied by
            CI). When None, the field is set to :data:`NOT_YET_AVAILABLE`
            so the auditor sees the gap explicitly. Max 1024 chars.

    Returns:
        BaselineDocument: A frozen, content-addressable artefact ready
        for emission (`to_jsonl`, `to_pdf`).

    Raises:
        ValueError: If ``signoff`` or ``test_archive_ref`` exceed
            1024 characters.
        TypeError: If ``signoff`` or ``test_archive_ref`` are not str
            or None.
    """
    signoff = _validate_free_text(signoff, field_name="signoff")
    test_archive_ref = _validate_free_text(
        test_archive_ref, field_name="test_archive_ref"
    )
    return BaselineDocument(
        sdk_version=_get_sdk_version(),
        generated_at_iso=_iso_now(),
        quantitative_metrics=_collect_quantitative_metrics(),
        test_archive_ref=test_archive_ref or NOT_YET_AVAILABLE,
        version_records=_collect_version_records(cwd),
        articles_covered=tuple(articles_covered) if articles_covered else DEFAULT_ARTICLES_COVERED,
        iso_42001_clauses=tuple(iso_42001_clauses) if iso_42001_clauses else DEFAULT_ISO_42001_CLAUSES,
        proof_format_version=PROOF_FORMAT_VERSION,
        stakeholder_signoff=signoff,
    )


# ---------------------------------------------------------------------------
# Emitters (Task 1.2)
# ---------------------------------------------------------------------------


def to_jsonl(doc: BaselineDocument, output_path: Path) -> Path:
    """Append-only JSONL emitter.

    Writes one JSON line containing the canonical dict + a top-level
    ``baseline_id`` field. The file is opened in append mode so a
    deployer can accumulate baselines over many releases in a single
    log file for audit-trail use.

    Args:
        doc: The baseline document to emit.
        output_path: Target file path. Parent directory is created if
            needed.

    Returns:
        Path: The output path (for convenience).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = doc.to_canonical_dict()
    record["baseline_id"] = doc.baseline_id
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.write("\n")
    return output_path


def to_pdf(doc: BaselineDocument, output_path: Path) -> Path:
    """Human-readable PDF emitter.

    Uses ``reportlab`` when available (optional dependency, not in the
    default install). When ``reportlab`` is not installed, raises a
    :class:`RuntimeError` with a helpful message rather than silently
    degrading — PDFs are a regulatory artefact, and a silent fallback
    would defeat the audit-trail purpose.

    Args:
        doc: The baseline document to emit.
        output_path: Target file path. Parent directory is created if
            needed.

    Returns:
        Path: The output path (for convenience).

    Raises:
        RuntimeError: If ``reportlab`` is not installed.
    """
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:
        raise RuntimeError(
            "to_pdf requires the optional `reportlab` dependency. "
            "Install with: pip install reportlab>=4.0. "
            "Or emit JSONL via to_jsonl() for an audit-friendly format."
        ) from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = SimpleDocTemplate(str(output_path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"GraQle SDK Baseline Document", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"<b>baseline_id:</b> {doc.baseline_id}", styles["Normal"]),
        Paragraph(f"<b>sdk_version:</b> {doc.sdk_version}", styles["Normal"]),
        Paragraph(f"<b>generated_at:</b> {doc.generated_at_iso}", styles["Normal"]),
        Paragraph(
            f"<b>stakeholder_signoff:</b> {doc.stakeholder_signoff or '(unsigned)'}",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("<b>Articles covered:</b>", styles["Heading2"]),
        Paragraph(", ".join(doc.articles_covered), styles["Normal"]),
        Spacer(1, 6),
        Paragraph("<b>ISO 42001 clauses:</b>", styles["Heading2"]),
        Paragraph(", ".join(doc.iso_42001_clauses), styles["Normal"]),
        Spacer(1, 12),
        Paragraph("<b>Quantitative metrics:</b>", styles["Heading2"]),
    ]
    for k, v in sorted(doc.quantitative_metrics.items()):
        story.append(Paragraph(f"<b>{k}:</b> {v}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Version records:</b>", styles["Heading2"]))
    for k, v in sorted(doc.version_records.items()):
        story.append(Paragraph(f"<b>{k}:</b> {v}", styles["Normal"]))
    pdf.build(story)
    return output_path
