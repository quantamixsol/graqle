# ── graqle:intelligence ──
# module: graqle.learning.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: graph_learner, gds_intelligence
# constraints: none
# ── /graqle:intelligence ──

try:
    from graqle.learning.gds_intelligence import (
        Community,
        GDSIntelligence,
        GDSReport,
        LinkPrediction,
        SimilarityPair,
    )
except ImportError:
    Community = GDSIntelligence = GDSReport = LinkPrediction = SimilarityPair = None  # type: ignore[assignment,misc]

from graqle.learning.graph_learner import EdgeUpdate, GraphLearner, LearningConfig

__all__ = [
    "GraphLearner",
    "LearningConfig",
    "EdgeUpdate",
    "GDSIntelligence",
    "GDSReport",
    "LinkPrediction",
    "Community",
    "SimilarityPair",
]
