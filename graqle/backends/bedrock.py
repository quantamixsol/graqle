"""Backward-compatibility shim — graqle.backends.bedrock is deprecated.

Use graqle.backends.api instead.
Removal target: v0.55.0. See MIGRATION-0.46-to-0.52.md.
"""
import warnings

warnings.warn(
    "graqle.backends.bedrock is deprecated — use graqle.backends.api. "
    "Removed in v0.55.0. See MIGRATION-0.46-to-0.52.md.",
    DeprecationWarning,
    stacklevel=2,
)

from graqle.backends.api import BedrockBackend  # noqa: F401, E402

__all__ = ["BedrockBackend"]
