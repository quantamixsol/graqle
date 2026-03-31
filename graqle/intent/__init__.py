"""R6 Learned Intent Classification — adaptive routing from corrections."""

from graqle.intent.types import (
    CorrectionRecord,
    EvaluationMetrics,
    LearnerCheckpoint,
    ToolPrediction,
)

__all__ = [
    "CorrectionRecord",
    "LearnerCheckpoint",
    "ToolPrediction",
    "EvaluationMetrics",
    "OnlineLearner",
    "CorrectionStore",
    "RingBuffer",
    "ClassifierEvaluator",
]


def __getattr__(name: str):  # noqa: ANN001
    """Lazy imports for heavy modules — avoid loading at package import time."""
    if name == "OnlineLearner":
        from graqle.intent.online_learner import OnlineLearner
        return OnlineLearner
    if name == "CorrectionStore":
        from graqle.intent.correction_store import CorrectionStore
        return CorrectionStore
    if name == "RingBuffer":
        from graqle.intent.correction_store import RingBuffer
        return RingBuffer
    if name == "ClassifierEvaluator":
        from graqle.intent.evaluator import ClassifierEvaluator
        return ClassifierEvaluator
    raise AttributeError(f"module 'graqle.intent' has no attribute {name!r}")
