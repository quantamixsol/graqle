"""R22 SGCV — SHACL Governance Completeness Verification package."""

from graqle.governance.shacl.output_gate import ShaclGateResult, check_output_gate
from graqle.governance.shacl.proof_report import generate_proof_report, save_proof_report
from graqle.governance.shacl.validator import (
    ShaclValidationResult,
    ShaclValidator,
    ViolationDetail,
)

__all__ = [
    "ShaclValidator",
    "ShaclValidationResult",
    "ShaclGateResult",
    "ViolationDetail",
    "check_output_gate",
    "generate_proof_report",
    "save_proof_report",
]
