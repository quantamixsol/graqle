"""CypherActivation — Neo4j vector search activation strategy.

Replaces PCST entirely for Neo4j mode. Uses Cypher vector search on
chunk embeddings to directly find content-bearing nodes via their chunks.
No tree algorithm needed — the vector index handles relevance scoring.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.activation.cypher")


class CypherActivation:
    """Activate subgraph nodes via Neo4j chunk-level vector search.

    Instead of PCST (embed query → cosine similarity on node descriptions →
    prize assignment → Steiner tree), CypherActivation:

    1. Embeds the query
    2. Calls ``db.index.vector.queryNodes()`` on chunk embeddings
    3. Maps chunks back to parent GraqleNode IDs
    4. Returns (node_ids, relevance_scores) — same interface as PCSTActivation

    This is faster, more accurate (searches chunk-level content), and
    eliminates PCST's structural bias toward directory/parent nodes.
    """

    def __init__(
        self,
        connector: Any,
        embedding_engine: Any,
        max_nodes: int = 50,
        k_chunks: int = 100,
    ) -> None:
        """
        Args:
            connector: Neo4jConnector with vector_search method.
            embedding_engine: Object with an ``embed(text) -> list[float]`` method.
            max_nodes: Maximum number of nodes to activate.
            k_chunks: Number of chunks to retrieve from vector index (more chunks
                      means better coverage but slower).
        """
        self._connector = connector
        self._embedding_engine = embedding_engine
        self._max_nodes = max_nodes
        self._k_chunks = k_chunks
        self.last_relevance: dict[str, float] = {}

    def activate(
        self,
        graph: Any,
        query: str,
    ) -> list[str]:
        """Activate nodes by vector search on chunk embeddings.

        Side effect: stores relevance scores in ``self.last_relevance``
        for use in confidence calibration (Bug 18 fix).

        Returns:
            List of activated node IDs present in the graph.
        """
        # 1. Embed the query
        try:
            query_embedding = self._embedding_engine.embed(query)
        except Exception as exc:
            logger.warning("CypherActivation: embedding failed (%s), falling back to full", exc)
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        # 2. Vector search → (node_id, relevance) pairs
        try:
            hits = self._connector.vector_search(
                query_embedding=query_embedding,
                k=self._k_chunks,
                max_nodes=self._max_nodes,
            )
        except Exception as exc:
            logger.warning("CypherActivation: vector search failed (%s), falling back to full", exc)
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        if not hits:
            logger.warning("CypherActivation: vector search returned 0 hits, using full graph")
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        # 3. Filter to nodes that exist in the in-memory graph
        activated = []
        relevance: dict[str, float] = {}
        for node_id, score in hits:
            if node_id in graph.nodes:
                activated.append(node_id)
                relevance[node_id] = score

        self.last_relevance = relevance

        logger.info(
            "CypherActivation: %d nodes activated (top relevance: %.3f)",
            len(activated),
            hits[0][1] if hits else 0.0,
        )
        return activated
