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
from graqle.governance.allowlist import _validate_allowlist
from graqle.governance.web_gate import (
    RedirectBlocked,
    check_web_url,
    sanitize_response_content,
    _sanitize_record,
)
from graqle.governance.deps_gate import check_deps_install

__all__ = [
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
]
