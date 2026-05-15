"""EU AI Act compliance runtime surfaces.

Modules:
  * :mod:`graqle.compliance.disclosure` — Article 50(1) AI-disclosure
    banner + machine-readable ``ai_disclosure`` field for MCP envelopes.
  * :mod:`graqle.compliance.robustness` — Article 15 machine-readable
    robustness attestation for deployer compliance pipelines.

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
    "MeasurableClaim",
    "RobustnessAttestation",
    "build_ai_disclosure",
    "build_compliance_envelope",
    "build_robustness_attestation",
    "is_eu_ai_act_mode_on",
    "is_ai_disclosure_suppressed",
    "maybe_emit_session_banner",
    "reset_session_banner_state",
]
