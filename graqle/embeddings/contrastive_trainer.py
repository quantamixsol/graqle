"""R23 GSEFT: contrastive fine-tuning trainer stub (ADR-206).

Implements the GSEFT training loop interface. Actual training deferred until
R24 dataset is ready and compute budget is approved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from graqle.embeddings.governance_dataset import GSEFT_TRAINING_DEFERRED, GovernanceDataset

if TYPE_CHECKING:
    from graqle.embeddings.model_registry import EmbeddingModelRegistry


@dataclass
class TrainerConfig:
    base_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    output_dir: str = ".graqle/gseft-checkpoints"
    epochs: int = 3
    # B1 (TS-2): training hyperparameters externalized — no hardcoded defaults.
    # Set via GRAQLE_GSEFT_BATCH_SIZE / GRAQLE_GSEFT_LEARNING_RATE env vars,
    # or pass explicitly when constructing TrainerConfig.
    batch_size: int = field(
        default_factory=lambda: int(os.environ.get("GRAQLE_GSEFT_BATCH_SIZE", "0") or "0")
    )
    learning_rate: float = field(
        default_factory=lambda: float(os.environ.get("GRAQLE_GSEFT_LEARNING_RATE", "0") or "0")
    )
    warmup_steps: int = 100
    eval_steps: int = 200
    extra: dict = field(default_factory=dict)


@dataclass
class TrainResult:
    trained: bool
    skipped_reason: str = ""
    checkpoint_path: str = ""
    eval_metrics: dict = field(default_factory=dict)


class ContrastiveTrainer:
    """GSEFT contrastive fine-tuning trainer.

    Training is gated by ``GSEFT_TRAINING_DEFERRED``. When R24 dataset
    curation is complete, set that flag to False and implement ``_run_training``.
    """

    def __init__(
        self,
        config: TrainerConfig | None = None,
        registry: EmbeddingModelRegistry | None = None,
    ) -> None:
        self.config = config or TrainerConfig()
        self.registry = registry

    def train(self, dataset: GovernanceDataset) -> TrainResult:
        if GSEFT_TRAINING_DEFERRED:
            return TrainResult(
                trained=False,
                skipped_reason="GSEFT_TRAINING_DEFERRED — R24 dataset not yet curated",
            )
        # B4: guard against silent degenerate training run when env vars are unset.
        # batch_size=0 or learning_rate=0.0 would produce a nonsensical training run.
        if self.config.batch_size <= 0:
            raise ValueError(
                "TrainerConfig.batch_size must be > 0. "
                "Set GRAQLE_GSEFT_BATCH_SIZE env var or pass batch_size explicitly."
            )
        if self.config.learning_rate <= 0.0:
            raise ValueError(
                "TrainerConfig.learning_rate must be > 0. "
                "Set GRAQLE_GSEFT_LEARNING_RATE env var or pass learning_rate explicitly."
            )
        if len(dataset) == 0:
            return TrainResult(trained=False, skipped_reason="empty dataset")
        return self._run_training(dataset)

    def _run_training(self, dataset: GovernanceDataset) -> TrainResult:
        # R24 implementation placeholder
        raise NotImplementedError("ContrastiveTrainer._run_training not yet implemented (R24)")
