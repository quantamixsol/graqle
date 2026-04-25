"""graqle.embeddings — R23 GSEFT scaffold (ADR-206).

Governance-Supervised Embedding Fine-Tuning (GSEFT) infrastructure.
Training pipeline deferred pending dataset curation (R24 milestone).
"""

from graqle.embeddings.model_registry import EmbeddingModelRegistry

__all__ = ["EmbeddingModelRegistry"]
