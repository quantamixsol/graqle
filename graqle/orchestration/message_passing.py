"""Message passing protocol — the core reasoning loop of Graqle."""

# ── graqle:intelligence ──
# module: graqle.orchestration.message_passing
# risk: MEDIUM (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, orchestrator, __init__, test_message_passing
# dependencies: __future__, asyncio, logging, typing, message
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from graqle.core.message import Message

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.message_passing")


class MessagePassingProtocol:
    """Synchronous round-based message passing between CogniNode agents.

    Protocol:
    Round 0: Query broadcast → each node produces initial reasoning
    Round 1..N: Neighbor exchange → each node re-reasons with neighbor context
    Final: Collect all outputs for aggregation

    This is the mechanism through which emergent reasoning occurs — insights
    that exist in NO single agent emerge from their interactions.
    """

    def __init__(
        self,
        parallel: bool = True,
        ontology_router: Any = None,
        embedding_fn: Any = None,
    ) -> None:
        self.parallel = parallel
        self.ontology_router = ontology_router  # OntologyRouter instance
        self.embedding_fn = embedding_fn  # For evidence filtering in nodes
        self._observer_feedback: dict[str, Message] | None = None

    def inject_observer_feedback(self, feedback: dict[str, Message]) -> None:
        """Inject observer feedback for next round (T4.2)."""
        self._observer_feedback = feedback

    async def run_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
        round_num: int,
        previous_messages: dict[str, Message] | None = None,
    ) -> dict[str, Message]:
        """Execute one round of message passing."""
        # Filter out pruned nodes
        active_ids = [
            nid for nid in active_node_ids
            if not getattr(graph.nodes.get(nid), "pruned", False)
        ]

        logger.debug(f"Round {round_num}: {len(active_ids)} active nodes")

        if round_num == 0:
            return await self._initial_round(graph, query, active_ids)

        return await self._exchange_round(
            graph, query, active_ids, round_num, previous_messages or {}
        )

    async def _initial_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> dict[str, Message]:
        """Round 0: Each node reasons independently about the query."""

        async def _node_reason(node_id: str) -> tuple[str, Message]:
            node = graph.nodes[node_id]
            query_msg = Message.create_query_broadcast(query, node_id)
            result = await node.reason(
                query, [query_msg], embedding_fn=self.embedding_fn
            )
            result.source_node_id = node_id
            result.round = 0
            return node_id, result

        if self.parallel:
            tasks = [_node_reason(nid) for nid in active_node_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for nid in active_node_ids:
                results.append(await _node_reason(nid))

        output: dict[str, Message] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Node reasoning failed: {r}")
                continue
            node_id, message = r
            output[node_id] = message

        logger.debug(f"Round 0 complete: {len(output)} nodes responded")
        return output

    async def _exchange_round(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
        round_num: int,
        previous_messages: dict[str, Message],
    ) -> dict[str, Message]:
        """Round N: Exchange messages with neighbors and re-reason."""

        async def _node_exchange(node_id: str) -> tuple[str, Message]:
            node = graph.nodes[node_id]

            # Use ontology router if available, otherwise fall back to graph neighbors
            if self.ontology_router is not None:
                neighbor_ids = self.ontology_router.get_valid_recipients(
                    graph, node_id, active_node_ids=active_node_ids
                )
            else:
                neighbor_ids = graph.get_neighbors(node_id)

            incoming = [
                previous_messages[nid]
                for nid in neighbor_ids
                if nid in previous_messages
            ]

            # Prepend observer feedback if available (T4.2)
            if self._observer_feedback and node_id in self._observer_feedback:
                incoming.insert(0, self._observer_feedback[node_id])

            # Re-reason with neighbor context + evidence filtering
            result = await node.reason(
                query, incoming, embedding_fn=self.embedding_fn
            )
            result.source_node_id = node_id
            result.round = round_num
            return node_id, result

        if self.parallel:
            tasks = [_node_exchange(nid) for nid in active_node_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for nid in active_node_ids:
                results.append(await _node_exchange(nid))

        output: dict[str, Message] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Node exchange failed: {r}")
                continue
            node_id, message = r
            output[node_id] = message

        # Clear observer feedback after consumption
        self._observer_feedback = None

        logger.debug(
            f"Round {round_num} complete: {len(output)} nodes responded"
        )
        return output
