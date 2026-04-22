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

__all__ = [
    "BaselineCorruptedError",
    "ConfigDriftAuditor",
    "DriftRecord",
    "FileReadError",
]
