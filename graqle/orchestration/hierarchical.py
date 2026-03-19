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

"""HierarchicalAggregation — topology-aware aggregation.

Aggregates reasoning results following the graph topology:
leaf nodes → hub nodes → root aggregation.

This respects the KG structure: domain-specific leaf nodes inform
hub nodes, which synthesize across domains for the final answer.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.hierarchical
# risk: LOW (impact radius: 1 modules)
# consumers: test_hierarchical
# dependencies: __future__, asyncio, logging, typing, message +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from graqle.core.message import Message
from graqle.core.types import ReasoningType

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.orchestration.hierarchical")


class HierarchicalAggregation:
    """Aggregate results following graph topology.

    Strategy:
    1. Identify leaf nodes (degree ≤ 2) and hub nodes (degree > threshold)
    2. Leaf nodes reason first → send to connected hubs
    3. Hub nodes synthesize leaf inputs → send to root
    4. Root produces final aggregated answer

    This naturally follows KG structure where entities (leaves)
    inform categories (hubs) which inform the overall answer.
    """

    def __init__(
        self,
        hub_degree_threshold: int = 3,
        parallel: bool = True,
    ) -> None:
        self.hub_degree_threshold = hub_degree_threshold
        self.parallel = parallel

    def classify_nodes(
        self, graph: Graqle, active_node_ids: list[str]
    ) -> tuple[list[str], list[str], str | None]:
        """Classify nodes into leaves, hubs, and root.

        Returns: (leaf_ids, hub_ids, root_id)
        """
        degrees = {}
        for nid in active_node_ids:
            neighbors = graph.get_neighbors(nid)
            active_neighbors = [n for n in neighbors if n in active_node_ids]
            degrees[nid] = len(active_neighbors)

        leaves = [nid for nid, d in degrees.items() if d <= 2]
        hubs = [nid for nid, d in degrees.items() if d > self.hub_degree_threshold]

        # Root = highest degree hub (or highest degree node overall)
        root = None
        if hubs:
            root = max(hubs, key=lambda nid: degrees[nid])
        elif active_node_ids:
            root = max(active_node_ids, key=lambda nid: degrees[nid])

        # Nodes that are neither leaf nor hub
        mid_nodes = [
            nid for nid in active_node_ids
            if nid not in leaves and nid not in hubs
        ]
        # Include mid nodes in leaves for processing
        leaves.extend(mid_nodes)

        return leaves, hubs, root

    async def run(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> dict[str, Message]:
        """Run hierarchical aggregation.

        Returns: dict of node_id -> final Message (after hierarchy)
        """
        leaves, hubs, root = self.classify_nodes(graph, active_node_ids)

        all_messages: dict[str, Message] = {}

        # Phase 1: Leaf nodes reason independently
        leaf_messages = await self._run_tier(
            graph, query, leaves, round_num=0, context={}
        )
        all_messages.update(leaf_messages)

        # Phase 2: Hub nodes synthesize leaf inputs
        if hubs:
            hub_context: dict[str, list[Message]] = {}
            for hub_id in hubs:
                neighbors = graph.get_neighbors(hub_id)
                hub_context[hub_id] = [
                    leaf_messages[nid]
                    for nid in neighbors
                    if nid in leaf_messages
                ]

            hub_messages = await self._run_tier(
                graph, query, hubs, round_num=1, context=hub_context
            )
            all_messages.update(hub_messages)

        # Phase 3: Root synthesizes hub inputs (if different from hubs)
        if root and root in hubs and len(hubs) > 1:
            neighbors = graph.get_neighbors(root)
            root_context = [
                all_messages[nid]
                for nid in neighbors
                if nid in all_messages and nid != root
            ]
            if root_context:
                node = graph.nodes[root]
                result = await node.reason(query, root_context)
                result.source_node_id = root
                result.round = 2
                result.reasoning_type = ReasoningType.SYNTHESIS
                all_messages[root] = result

        return all_messages

    async def _run_tier(
        self,
        graph: Graqle,
        query: str,
        node_ids: list[str],
        round_num: int,
        context: dict[str, list[Message]],
    ) -> dict[str, Message]:
        """Run reasoning for a tier of nodes."""
        async def _reason(nid: str) -> tuple[str, Message]:
            node = graph.nodes[nid]
            ctx = context.get(nid, [])
            if not ctx:
                ctx = [Message.create_query_broadcast(query, nid)]
            result = await node.reason(query, ctx)
            result.source_node_id = nid
            result.round = round_num
            return nid, result

        if self.parallel:
            results = await asyncio.gather(
                *[_reason(nid) for nid in node_ids],
                return_exceptions=True,
            )
        else:
            results = [await _reason(nid) for nid in node_ids]

        output = {}
        for r in results:
            if not isinstance(r, Exception):
                output[r[0]] = r[1]
        return output
