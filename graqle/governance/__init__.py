"""Governance primitives for graqle.

Exposes the CG-14 config-drift auditor and its typed errors. Shared
primitive consumed by CG-15 (KG-write gate) and G4 (protected_paths)
in Wave 2 Phase 4.
"""

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

__all__ = [
    "BaselineCorruptedError",
    "ConfigDriftAuditor",
    "DriftRecord",
    "FileReadError",
    "check_kg_block",
    "check_protected_path",
]
