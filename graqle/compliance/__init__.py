"""EU AI Act compliance runtime surfaces.

Modules:
  * :mod:`graqle.compliance.disclosure` — Article 50(1) AI-disclosure
    banner + machine-readable ``ai_disclosure`` field for MCP envelopes.
  * :mod:`graqle.compliance.robustness` — Article 15 machine-readable
    robustness attestation for deployer compliance pipelines.
  * :mod:`graqle.compliance.management_review_gate` — SOX/COSO
    management-review-control gate (CR-010.R3). The financial-controls
    counterpart of the Article 14 human-oversight gate: same mechanics,
    different vocabulary and a distinct error code.
  * :mod:`graqle.compliance.packs` — compliance frameworks expressed as
    data (``pack.yaml`` + ``schema.json``), so a new framework needs no
    Python and no engine change.

All modules in this package are READ-ONLY and SIDE-EFFECT-FREE except
for the banner emit (which writes to stderr exactly once per session).
"""

from graqle.compliance.disclosure import (
    AIDisclosure,
    ComplianceEnvelope,
    build_ai_disclosure,
    build_compliance_envelope,
    is_eu_ai_act_mode_on,
    is_ai_disclosure_suppressed,
    maybe_emit_session_banner,
    reset_session_banner_state,
)
from graqle.compliance.management_review_gate import (
    MANAGEMENT_REVIEW_ERROR_CODE,
    ManagementReviewGateResult,
    check_management_review,
)
from graqle.compliance.robustness import (
    Defence,
    MeasurableClaim,
    RobustnessAttestation,
    build_robustness_attestation,
)

__all__ = [
    "AIDisclosure",
    "ComplianceEnvelope",
    "Defence",
    "MANAGEMENT_REVIEW_ERROR_CODE",
    "ManagementReviewGateResult",
    "MeasurableClaim",
    "RobustnessAttestation",
    "build_ai_disclosure",
    "build_compliance_envelope",
    "build_robustness_attestation",
    "check_management_review",
    "is_eu_ai_act_mode_on",
    "is_ai_disclosure_suppressed",
    "maybe_emit_session_banner",
    "reset_session_banner_state",
]
