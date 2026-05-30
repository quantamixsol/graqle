# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""Factory helpers + minor activator classes for ActivatorRegistry (v0.62.3).

This module:
  1. Defines DegreeRanker (extracted from the old `strategy=="top_k"` branch
     of Graqle._activate_subgraph). Returns top-N nodes by graph degree.
  2. Defines FullActivator (extracted from the old `strategy=="full"` branch).
     Returns all node ids.
  3. Provides factory callables for each built-in (backend, ranking) pair.
     Factories are bound to a Graqle instance and return an activator object
     with a ``.activate(graph, query) -> list[str]`` method.

V-MARKER: V-CR-WRITE-NATIVE-001 — same workaround as registry.py.
"""

# ── graqle:intelligence ──
# module: graqle.activation.factory_helpers
# risk: LOW (new module, simple wrappers + factories)
# consumers: graqle.activation.__init__ (calls register_defaults)
# dependencies: __future__, logging, typing
# constraints: factories MUST NOT raise at registration time; only at activate() time
# ── /graqle:activation ──

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.activation.factory_helpers")


# ─── Minor activators (extracted from old _activate_subgraph branches) ─────


class DegreeRanker:
    """Return top-N nodes by graph degree (was old strategy=="top_k").

    Pure graph topology — ignores query content and any vector embeddings.
    Useful for "give me the most-connected nodes" queries; usually wrong when
    a semantic vector index is available on the backend.
    """

    def __init__(self, max_nodes: int = 50, warn_on_neo4j: bool = False) -> None:
        self.max_nodes = max_nodes
        self.warn_on_neo4j = warn_on_neo4j
        self.last_relevance: dict[str, float] = {}

    def activate(self, graph: Any, query: str) -> list[str]:  # noqa: ARG002
        """Return top-N nodes by degree. ``query`` is ignored (by design)."""
        if self.warn_on_neo4j:
            logger.warning(
                "DegreeRanker on Neo4j backend: ranking=degree ignores your "
                "vector index. Set activation.ranking='semantic' to use "
                "CypherActivation. (Backend=neo4j detected.)"
            )
        sorted_nodes = sorted(graph.nodes.values(), key=lambda n: n.degree, reverse=True)
        k = min(self.max_nodes, len(sorted_nodes))
        result = [n.id for n in sorted_nodes[:k]]
        self.last_relevance = {nid: 1.0 for nid in result}
        return result


class FullActivator:
    """Return all node ids (was old strategy=="full").

    Used for exhaustive queries. ``max_nodes`` is ignored — caller asked for
    everything. Useful only on small graphs; on a 64k-node graph this returns
    64k ids which downstream agents cannot all process.
    """

    def __init__(self) -> None:
        self.last_relevance: dict[str, float] = {}

    def activate(self, graph: Any, query: str) -> list[str]:  # noqa: ARG002
        result = list(graph.nodes.keys())
        self.last_relevance = {nid: 1.0 for nid in result}
        return result


# ─── Factory functions ─────────────────────────────────────────────────────
# Each factory takes a Graqle instance and returns an activator. Factories are
# THIN: they pull config + build the activator. No graph access at factory
# time — that happens in activator.activate() which the dispatcher calls
# immediately after.


def _make_chunk_scorer(graph: Any) -> Any:
    """(local, semantic) -> ChunkScorer.

    Lazy import to keep registry.py import-cost low.
    """
    from graqle.activation.chunk_scorer import ChunkScorer
    from graqle.activation.embeddings import create_embedding_engine

    cfg = graph.config
    try:
        emb_engine = create_embedding_engine(cfg)
    except Exception as exc:
        logger.warning(
            "ChunkScorer: embedding engine init failed (%s); proceeding with "
            "default engine",
            type(exc).__name__,
        )
        emb_engine = None

    domain_reg = None
    if cfg and cfg.activation.skill_aware:
        try:
            from graqle.ontology.domain_registry import DomainRegistry
            from graqle.ontology.domains import register_all_domains
            domain_reg = DomainRegistry()
            register_all_domains(domain_reg)
        except Exception:
            domain_reg = None

    return ChunkScorer(
        embedding_engine=emb_engine,
        max_nodes=cfg.activation.max_nodes,
        domain_registry=domain_reg,
    )


def _make_degree_ranker_local(graph: Any) -> DegreeRanker:
    """(local, degree) -> DegreeRanker (no warning — degree is a valid choice on local)."""
    return DegreeRanker(max_nodes=graph.config.activation.max_nodes, warn_on_neo4j=False)


def _make_degree_ranker_remote(graph: Any) -> DegreeRanker:
    """(neo4j|neptune, degree) -> DegreeRanker + WARNING (ignores vector index)."""
    return DegreeRanker(max_nodes=graph.config.activation.max_nodes, warn_on_neo4j=True)


def _make_full_activator(graph: Any) -> FullActivator:  # noqa: ARG001
    """(local|neo4j|neptune, none) -> FullActivator."""
    return FullActivator()


def _make_cypher_activation(graph: Any) -> Any:
    """(neo4j, semantic) -> CypherActivation."""
    from graqle.activation.cypher_activation import CypherActivation
    from graqle.activation.embeddings import EmbeddingEngine

    return CypherActivation(
        connector=graph._neo4j_connector,
        embedding_engine=EmbeddingEngine(),
        max_nodes=graph.config.activation.max_nodes,
    )


def _make_neptune_activation(graph: Any) -> Any:
    """(neptune, semantic) -> NeptuneActivator (stub for now).

    Neptune backend is forward-looking. When NeptuneConnector ships with a
    vector_search() method matching the Neo4jConnector signature, this factory
    will dispatch to it. Until then, raise a clear NotImplementedError at
    activate() time (not at factory time, so registration stays clean).
    """
    class _NeptuneStub:
        last_relevance: dict[str, float] = {}

        def activate(self, graph: Any, query: str) -> list[str]:  # noqa: ARG002
            raise NotImplementedError(
                "(neptune, semantic) activator is not yet implemented. "
                "NeptuneConnector with vector_search() is required. "
                "Set graph.connector to 'neo4j' or 'networkx' for now."
            )

    return _NeptuneStub()


# Aliases used by graqle.activation.__init__.register_defaults():
_chunk_scorer_factory = _make_chunk_scorer
_degree_factory = _make_degree_ranker_local
_degree_with_warning_factory = _make_degree_ranker_remote
_full_factory = _make_full_activator
_neo4j_full_factory = _make_full_activator   # same impl; warns on neo4j only if needed
_cypher_factory = _make_cypher_activation
_neptune_factory = _make_neptune_activation
_neptune_full_factory = _make_full_activator
