"""R23 GSEFT: governance embedding evaluation harness (ADR-206).

Computes retrieval and classification metrics on held-out governance pairs.
Evaluation deferred until fine-tuned checkpoints are available (R24).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graqle.embeddings.governance_dataset import GSEFT_TRAINING_DEFERRED


@dataclass
class EvalResult:
    model_id: str
    precision_at_1: float = 0.0
    recall_at_5: float = 0.0
    f1: float = 0.0
    mrr: float = 0.0
    evaluated: bool = False
    skipped_reason: str = ""


class GovernanceEvaluator:
    """Evaluates embedding models on governance retrieval tasks.

    Full evaluation deferred until R24 fine-tuned checkpoints are ready.
    """

    def __init__(self, model_id: str = "base") -> None:
        self.model_id = model_id

    def evaluate(self, pairs: list[dict[str, Any]]) -> EvalResult:
        if GSEFT_TRAINING_DEFERRED:
            return EvalResult(
                model_id=self.model_id,
                evaluated=False,
                skipped_reason="GSEFT_TRAINING_DEFERRED — no fine-tuned model yet (R24)",
            )
        if not pairs:
            return EvalResult(
                model_id=self.model_id, evaluated=False, skipped_reason="empty eval set"
            )
        return self._run_eval(pairs)

    def _run_eval(self, pairs: list[dict[str, Any]]) -> EvalResult:
        # R24 implementation placeholder
        raise NotImplementedError("GovernanceEvaluator._run_eval not yet implemented (R24)")
