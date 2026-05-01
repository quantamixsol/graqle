"""Backward-compatibility shim — graqle.api.GraqleClient is deprecated.

Use graqle.core.Graqle instead.
Removal target: v0.55.0. See MIGRATION-0.46-to-0.52.md.
"""
import warnings

warnings.warn(
    "graqle.api.GraqleClient is deprecated — use graqle.core.Graqle instead. "
    "Removed in v0.55.0. See MIGRATION-0.46-to-0.52.md.",
    DeprecationWarning,
    stacklevel=2,
)

from graqle.core.graph import Graqle  # noqa: F401, E402

# Legacy alias
GraqleClient = Graqle

__all__ = ["Graqle", "GraqleClient"]
