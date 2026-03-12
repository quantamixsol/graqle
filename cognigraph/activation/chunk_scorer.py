"""ChunkScorer — chunk-level relevance scoring for subgraph activation.

Replaces PCST's node-level embedding approach with chunk-level search.
Each chunk gets its own embedding and is scored independently against
the query. Parent nodes inherit the best chunk score.

This eliminates PCST's fundamental flaw: a single 384/1024-dim vector
cannot represent an entire file's content. By scoring at chunk level,
a query about "ProductList function" directly matches the chunk
containing that function, regardless of what else the file contains.

Works with any backend (JSON/NetworkX or Neo4j). No external dependencies
beyond the embedding engine already used by CogniGraph.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import numpy as np

from cognigraph.activation.embeddings import EmbeddingEngine, cosine_similarity

if TYPE_CHECKING:
    from cognigraph.core.graph import CogniGraph

logger = logging.getLogger("cognigraph.activation.chunk_scorer")


class ChunkScorer:
    """Score nodes by chunk-level embedding similarity.

    For each node, every chunk is embedded separately and compared
    to the query embedding. The node's score is the MAX chunk score
    (best-matching chunk wins), not an average.

    This is the in-memory equivalent of Neo4j's vector index search
    on :Chunk nodes — same accuracy, no database required.
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine | None = None,
        max_nodes: int = 50,
        min_score: float = 0.15,
    ) -> None:
        """
        Args:
            embedding_engine: Embedding model for query + chunks.
            max_nodes: Maximum nodes to activate.
            min_score: Minimum chunk similarity to include a node.
                       Below this threshold the node is noise.
        """
        self.embedding_engine = embedding_engine or EmbeddingEngine()
        self.max_nodes = max_nodes
        self.min_score = min_score
        self.last_relevance: dict[str, float] = {}

    def score(
        self, graph: CogniGraph, query: str
    ) -> dict[str, float]:
        """Score all nodes by chunk-level similarity.

        Returns dict mapping node_id -> best_chunk_score.
        """
        query_embedding = self.embedding_engine.embed(query)
        query_lower = query.lower()
        scores: dict[str, float] = {}

        for node_id, node in graph.nodes.items():
            chunks = node.properties.get("chunks", [])

            if not chunks:
                # No chunks: fall back to description-only scoring
                desc_text = f"{node.label} {node.entity_type} {node.description}"
                desc_emb = self.embedding_engine.embed(desc_text)
                sim = float(cosine_similarity(query_embedding, desc_emb))
                scores[node_id] = max(sim * 0.5, 0.0)  # penalize: no evidence
                continue

            # Score each chunk independently
            best_chunk_score = 0.0
            for chunk in chunks:
                if isinstance(chunk, dict):
                    text = chunk.get("text", "")
                    chunk_type = chunk.get("type", "")
                elif isinstance(chunk, str):
                    text = chunk
                    chunk_type = ""
                else:
                    continue

                if not text or len(text.strip()) < 10:
                    continue

                # Embed chunk with node context (label + type prefix)
                chunk_text = f"{node.label} {chunk_type}: {text}"
                chunk_emb = self.embedding_engine.embed(chunk_text)
                sim = float(cosine_similarity(query_embedding, chunk_emb))

                if sim > best_chunk_score:
                    best_chunk_score = sim

            scores[node_id] = max(best_chunk_score, 0.0)

            # Filename boost: if query mentions this file, guarantee selection
            label_lower = (node.label or "").lower()
            if label_lower and len(label_lower) >= 3:
                bare = label_lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                bare_no_ext = bare.rsplit(".", 1)[0] if "." in bare else bare
                if len(bare_no_ext) >= 3 and (bare in query_lower or bare_no_ext in query_lower):
                    scores[node_id] = max(scores[node_id], 2.0)

        return scores

    def activate(
        self, graph: CogniGraph, query: str
    ) -> list[str]:
        """Activate the top-N nodes by chunk-level scoring.

        Side effect: stores relevance scores in ``self.last_relevance``.

        Returns:
            List of activated node IDs, sorted by relevance descending.
        """
        scores = self.score(graph, query)

        # Filter by minimum score
        candidates = [
            (nid, score) for nid, score in scores.items()
            if score >= self.min_score
        ]

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Take top N
        activated = candidates[:self.max_nodes]

        self.last_relevance = {nid: score for nid, score in activated}

        if activated:
            logger.info(
                "ChunkScorer activated %d nodes (top: %s=%.3f, cutoff: %.3f)",
                len(activated),
                activated[0][0],
                activated[0][1],
                self.min_score,
            )
        else:
            logger.warning("ChunkScorer: no nodes above min_score=%.3f", self.min_score)

        return [nid for nid, _ in activated]
