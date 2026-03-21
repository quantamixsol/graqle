# ── graqle:intelligence ──
# module: graqle.activation.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: pcst, relevance, embeddings, adaptive, chunk_scorer +3 more
# constraints: none
# ── /graqle:intelligence ──

from graqle.activation.adaptive import (
    AdaptiveActivation,
    AdaptiveConfig,
    ComplexityProfile,
    QueryComplexityScorer,
)
from graqle.activation.chunk_scorer import ChunkScorer
from graqle.activation.cypher_activation import CypherActivation
from graqle.activation.embeddings import EmbeddingEngine, cosine_similarity
from graqle.activation.multi_signal import MultiSignalActivation

try:
    from graqle.activation.pcst import PCSTActivation
except ImportError:
    PCSTActivation = None  # type: ignore[assignment,misc]

from graqle.activation.reformulator import (
    Attachment,
    QueryReformulator,
    ReformulationContext,
    ReformulationResult,
)
try:
    from graqle.activation.relevance import RelevanceScorer
except ImportError:
    RelevanceScorer = None  # type: ignore[assignment,misc]

__all__ = [
    "PCSTActivation",
    "RelevanceScorer",
    "EmbeddingEngine",
    "cosine_similarity",
    "AdaptiveActivation",
    "AdaptiveConfig",
    "ComplexityProfile",
    "QueryComplexityScorer",
    "ChunkScorer",
    "CypherActivation",
    "MultiSignalActivation",
    "Attachment",
    "QueryReformulator",
    "ReformulationContext",
    "ReformulationResult",
]
