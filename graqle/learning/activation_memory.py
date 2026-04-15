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
# Contact: support@quantamixsolutions.com
"""Activation memory — cross-query learning store (v0.12+).

Records which subgraph nodes were activated for each query so that
future queries can receive small activation boosts on nodes that
have proven relevant for similar queries. v0.51.4 stub: in-memory
only, no persistence, to unblock ontology_refiner imports.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger("graqle.learning.activation_memory")


class ActivationMemory:
    """In-memory activation pattern store.

    Stub implementation (v0.51.4) — provides the API surface expected
    by graqle.core.graph and graqle.learning.ontology_refiner. No disk
    persistence yet; state resets on process restart.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._node_hits: dict[str, int] = defaultdict(int)
        self._query_nodes: dict[str, list[str]] = {}

    def load(self) -> None:
        """Load persisted activations. No-op in the stub."""
        return None

    def save(self) -> None:
        """Persist activations to disk. No-op in the stub."""
        return None

    def record(
        self,
        query: str,
        node_ids: list[str] | None = None,
        result: Any = None,
    ) -> None:
        """Record that ``node_ids`` were activated for ``query``."""
        if not query:
            return
        ids = list(node_ids or [])
        self._records.append({"query": query, "node_ids": ids, "result": result})
        self._query_nodes[query] = ids
        for nid in ids:
            if nid:
                self._node_hits[nid] += 1

    def get_boosts(self, query: str) -> dict[str, float]:
        """Return a ``{node_id: boost}`` map for a query.

        Stub heuristic: if this exact query has been seen before, return
        a small constant boost for each previously-activated node.
        """
        prior = self._query_nodes.get(query)
        if not prior:
            return {}
        return {nid: 0.1 for nid in prior if nid}

    def recent(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the most recent ``n`` activation records."""
        return self._records[-n:]
