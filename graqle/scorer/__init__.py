"""Backward-compatibility shim — graqle.scorer is deprecated.

Use graqle.activation.chunk_scorer instead.
Removal target: v0.55.0. See MIGRATION-0.46-to-0.52.md.
"""
import warnings

warnings.warn(
    "graqle.scorer is deprecated — use graqle.activation.chunk_scorer. "
    "Removed in v0.55.0. See MIGRATION-0.46-to-0.52.md.",
    DeprecationWarning,
    stacklevel=2,
)

from graqle.activation.chunk_scorer import ChunkScorer  # noqa: F401, E402

__all__ = ["ChunkScorer"]
