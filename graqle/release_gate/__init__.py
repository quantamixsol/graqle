"""GraQle Release Gate (G2) — pre-publish KG-multi-agent governance gate.

Composes `graq_review` (correctness-focused diff review) with `graq_predict`
(risk prediction) into a single structured verdict that gates PyPI or
VS Code Marketplace releases.

Public API:
    ReleaseGateEngine          — main engine (injection pattern)
    ReleaseGateVerdict         — frozen dataclass of the gate outcome
    Verdict                    — enum: CLEAR | WARN | BLOCK
    ReviewSummary              — provider-supplied diff review summary
    PredictionSummary          — provider-supplied risk prediction summary
    ReviewProvider             — Protocol for the review dependency
    PredictionProvider         — Protocol for the prediction dependency
    SUPPORTED_TARGETS          — frozenset of accepted `target` values
"""
from graqle.release_gate.models import (
    PredictionProvider,
    PredictionSummary,
    ReleaseGateVerdict,
    ReviewProvider,
    ReviewSummary,
    SUPPORTED_TARGETS,
    Verdict,
)
from graqle.release_gate.engine import ReleaseGateEngine

__all__ = [
    "ReleaseGateEngine",
    "ReleaseGateVerdict",
    "Verdict",
    "ReviewSummary",
    "PredictionSummary",
    "ReviewProvider",
    "PredictionProvider",
    "SUPPORTED_TARGETS",
]
