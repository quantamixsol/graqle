"""Governance primitives for graqle.

Wave 2 (0.52.0b1): CG-14 config-drift auditor, CG-15 KG-write gate,
G4 protected_paths, CG-12 web gate, CG-13 deps gate.

R18 (ADR-201): Governed Execution Trace Capture — append-only trace schema,
foundation for R19 (Failure Chain Prediction), R20 (Calibration),
R21 (Cross-Org Transfer), R23 (Embedding Fine-Tuning).
"""

# Wave 2 — config-drift, KG-write, web, deps gates
from graqle.governance.config_drift import (
    BaselineCorruptedError,
    ConfigDriftAuditor,
    DriftRecord,
    FileReadError,
)
from graqle.governance.kg_write_gate import (
    check_kg_block,
    check_protected_path,
)
from graqle.governance.allowlist import _validate_allowlist
from graqle.governance.web_gate import (
    RedirectBlocked,
    check_web_url,
    sanitize_response_content,
    _sanitize_record,
)
from graqle.governance.deps_gate import check_deps_install

# R18 — governed trace schema (public surface only; GovernanceDecision is TS-2 internal)
from graqle.governance.trace_schema import (
    ClearanceLevel,
    Decision,
    GateType,
    GovernedTrace,
    Outcome,
    ToolCall,
)

__all__ = [
    # Wave 2 gates
    "BaselineCorruptedError",
    "ConfigDriftAuditor",
    "DriftRecord",
    "FileReadError",
    "check_kg_block",
    "check_protected_path",
    "check_web_url",
    "check_deps_install",
    "sanitize_response_content",
    "RedirectBlocked",
    # R18 trace schema
    "ClearanceLevel",
    "Decision",
    "GateType",
    "GovernedTrace",
    "Outcome",
    "ToolCall",
]
