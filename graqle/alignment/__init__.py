"""R10 Embedding Space Alignment — cross-language embedding correction."""

from graqle.alignment.types import (
    AlignmentPair,
    AlignmentReport,
    DiagnosisResult,
    cosine_similarity,
)
from graqle.alignment.tiers import ALIGNMENT_TIERS, classify_alignment_tier

__all__ = [
    "AlignmentPair",
    "AlignmentReport",
    "DiagnosisResult",
    "cosine_similarity",
    "ALIGNMENT_TIERS",
    "classify_alignment_tier",
    "EmbeddingStore",
    "measure_alignment",
    "diagnose_misalignment",
    "correct_alignment",
    "configure_r9_from_alignment",
    "FederatedActivationConfig",
]


def __getattr__(name: str):  # noqa: ANN001
    """Lazy imports for heavier modules."""
    if name == "EmbeddingStore":
        from graqle.alignment.embedding_store import EmbeddingStore
        return EmbeddingStore
    if name == "measure_alignment":
        from graqle.alignment.measurement import measure_alignment
        return measure_alignment
    if name == "diagnose_misalignment":
        from graqle.alignment.diagnostic import diagnose_misalignment
        return diagnose_misalignment
    if name == "correct_alignment":
        from graqle.alignment.pipeline import correct_alignment
        return correct_alignment
    if name == "configure_r9_from_alignment":
        from graqle.alignment.r9_config import configure_r9_from_alignment
        return configure_r9_from_alignment
    if name == "FederatedActivationConfig":
        from graqle.alignment.r9_config import FederatedActivationConfig
        return FederatedActivationConfig
    raise AttributeError(f"module 'graqle.alignment' has no attribute {name!r}")
