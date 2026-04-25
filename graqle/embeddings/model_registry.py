"""R23 GSEFT: model registry for fine-tuned governance embedding models (ADR-206).

Tracks base model, fine-tune checkpoint path, and evaluation metrics.
Fine-tuned model loading deferred until R24 dataset is ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EmbeddingModelEntry:
    model_id: str
    base_model: str
    checkpoint_path: Path | None = None
    eval_metrics: dict = field(default_factory=dict)
    is_fine_tuned: bool = False


class EmbeddingModelRegistry:
    """Registry for governance embedding models."""

    def __init__(self) -> None:
        self._models: dict[str, EmbeddingModelEntry] = {}

    def register(self, entry: EmbeddingModelEntry) -> None:
        self._models[entry.model_id] = entry

    def get(self, model_id: str) -> EmbeddingModelEntry | None:
        return self._models.get(model_id)

    def list_models(self) -> list[str]:
        return list(self._models.keys())

    def best_fine_tuned(self) -> EmbeddingModelEntry | None:
        """Return highest-scoring fine-tuned model by f1 (mrr as tie-break), or None."""
        candidates = [e for e in self._models.values() if e.is_fine_tuned]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda e: (e.eval_metrics.get("f1", 0.0), e.eval_metrics.get("mrr", 0.0)),
        )
