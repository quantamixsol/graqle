"""R10 Embedding Space Alignment — embedding store adapter.

Thin adapter wrapping node.properties["_embedding_cache"] to provide
a uniform get/update interface for alignment operations.
"""

# ── graqle:intelligence ──
# module: graqle.alignment.embedding_store
# risk: LOW (impact radius: 2 modules)
# consumers: alignment.measurement, alignment.procrustes, alignment.augmentation
# dependencies: __future__, logging, typing, numpy
# constraints: "aligned:r10" hash prefix for corrected embeddings
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger("graqle.alignment.embedding_store")


class EmbeddingStore:
    """Adapter over ``node.properties['_embedding_cache']`` for alignment.

    Provides a uniform ``get``/``update`` interface so alignment modules
    don't need to know the underlying storage format.

    Parameters
    ----------
    graph:
        A :class:`~graqle.core.graph.Graqle` instance whose nodes
        contain ``_embedding_cache`` properties.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def get(self, node_id: str) -> Optional[np.ndarray]:
        """Retrieve the embedding vector for *node_id*.

        Checks ``_aligned_embedding`` first (post-correction), then
        ``_embedding_cache`` (raw model output). Returns ``None`` if
        neither exists or the node is missing.
        """
        node = self._graph.nodes.get(node_id)
        if node is None:
            return None

        # Prefer aligned embedding if it exists
        aligned = node.properties.get("_aligned_embedding")
        if aligned and "vector" in aligned:
            return np.array(aligned["vector"], dtype=np.float32)

        # Fall back to raw embedding cache
        cached = node.properties.get("_embedding_cache")
        if cached and "vector" in cached:
            return np.array(cached["vector"], dtype=np.float32)

        return None

    def update(self, node_id: str, embedding: np.ndarray) -> None:
        """Store an aligned embedding for *node_id*.

        Writes to ``_aligned_embedding`` with an ``aligned:r10`` hash
        prefix to distinguish from raw model embeddings. The raw
        ``_embedding_cache`` is never overwritten.
        """
        node = self._graph.nodes.get(node_id)
        if node is None:
            logger.warning("Cannot update embedding: node %s not found", node_id)
            return

        node.properties["_aligned_embedding"] = {
            "hash": "aligned:r10",
            "vector": embedding.tolist(),
        }

    def bulk_get(self, node_ids: list[str]) -> Dict[str, np.ndarray]:
        """Retrieve embeddings for multiple nodes, skipping missing ones."""
        result: Dict[str, np.ndarray] = {}
        for nid in node_ids:
            vec = self.get(nid)
            if vec is not None:
                result[nid] = vec
        return result

    def has_embedding(self, node_id: str) -> bool:
        """Return ``True`` if *node_id* has any embedding (aligned or raw)."""
        return self.get(node_id) is not None

    def items(self) -> list[tuple[str, np.ndarray]]:
        """Iterate over all (node_id, embedding) pairs in the graph."""
        result: list[tuple[str, np.ndarray]] = []
        for nid in self._graph.nodes:
            vec = self.get(nid)
            if vec is not None:
                result.append((nid, vec))
        return result
