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
    # pre-reason-activation design pre-reason activation layer (SDK-B2 + B4 + GOV-01 + GOV-02)
    "ActivationLayer",
    "ActivationVerdict",
    "ChunkScoringProvider",
    "ChunkScoreResult",
    "SafetyGateProvider",
    "SafetyVerdict",
    "SubgraphActivationProvider",
    "ActivatedSubgraph",
    "TierMode",
    "TurnBlocked",
    "resolve_tier_mode",
    "default_activation_layer",
]

# pre-reason-activation design: pre-reason activation layer exports
from graqle.activation.providers import (  # noqa: E402
    ActivationVerdict,
    ActivatedSubgraph,
    ChunkScoreResult,
    ChunkScoringProvider,
    SafetyGateProvider,
    SafetyVerdict,
    SubgraphActivationProvider,
    TierMode,
    TurnBlocked,
)
from graqle.activation.layer import ActivationLayer  # noqa: E402
from graqle.activation.tier_gate import resolve_tier_mode  # noqa: E402
from graqle.activation.factory import default_activation_layer  # noqa: E402

# ─── v0.62.3: ActivatorRegistry eager registration (SPEC-v0623) ──────────
# Builds the (backend, ranking) -> factory registry at module import.
# Thread-safe: Python's import lock guarantees this completes before any
# concurrent resolve() call from another thread can race.
from graqle.activation.registry import ActivatorRegistry  # noqa: E402
from graqle.activation import factory_helpers as _fh  # noqa: E402


def register_defaults() -> None:
    """Populate the ActivatorRegistry with built-in (backend, ranking) pairs.

    Called once at module import. Idempotent: re-calling does not duplicate
    entries (dict assignment overwrites). Safe to call from tests.
    """
    ActivatorRegistry.register("local",   "semantic", _fh._chunk_scorer_factory, _builtin=True)
    ActivatorRegistry.register("local",   "degree",   _fh._degree_factory,        _builtin=True)
    ActivatorRegistry.register("local",   "none",     _fh._full_factory,          _builtin=True)
    ActivatorRegistry.register("neo4j",   "semantic", _fh._cypher_factory,        _builtin=True)
    ActivatorRegistry.register("neo4j",   "degree",   _fh._degree_with_warning_factory, _builtin=True)
    ActivatorRegistry.register("neo4j",   "none",     _fh._neo4j_full_factory,    _builtin=True)
    ActivatorRegistry.register("neptune", "semantic", _fh._neptune_factory,       _builtin=True)
    ActivatorRegistry.register("neptune", "degree",   _fh._degree_with_warning_factory, _builtin=True)
    ActivatorRegistry.register("neptune", "none",     _fh._neptune_full_factory,  _builtin=True)


register_defaults()  # eager, runs at first import of graqle.activation
