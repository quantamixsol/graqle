"""Async event-driven message passing — true async node processing.

Unlike the round-based MessagePassingProtocol, this protocol processes
messages as they arrive via asyncio.Queue per node. Nodes don't wait
for all peers to finish — they react to incoming messages immediately.

This enables:
- Lower latency (fast nodes don't wait for slow ones)
- Natural backpressure (queue capacity limits)
- Event-driven architecture (nodes are reactive, not polled)
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.async_protocol
# risk: LOW (impact radius: 1 modules)
# consumers: test_async_protocol
# dependencies: __future__, asyncio, logging, time, typing +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from graqle.core.message import Message

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.async_protocol")


class NodeMailbox:
    """Per-node message queue with backpressure."""

    def __init__(self, node_id: str, capacity: int = 100) -> None:
        self.node_id = node_id
        self.queue: asyncio.Queue[Message | None] = asyncio.Queue(maxsize=capacity)
        self.processed: int = 0

    async def send(self, message: Message) -> None:
        """Enqueue a message for this node."""
        await self.queue.put(message)

    async def receive(self) -> Message | None:
        """Dequeue next message. Returns None as sentinel to stop."""
        msg = await self.queue.get()
        if msg is not None:
            self.processed += 1
        return msg

    async def stop(self) -> None:
        """Send stop sentinel."""
        await self.queue.put(None)

    @property
    def pending(self) -> int:
        return self.queue.qsize()


class AsyncMessageProtocol:
    """Event-driven async message passing.

    Each active node gets a mailbox (asyncio.Queue). Messages flow
    through the graph asynchronously — fast nodes produce results
    immediately while slow nodes are still processing.

    Supports:
    - True async (no round synchronization barriers)
    - Configurable waves (max concurrent messages per node)
    - Backpressure via queue capacity
    - Streaming partial results via async iterator
    """

    def __init__(
        self,
        max_waves: int = 5,
        wave_timeout: float = 120.0,
        mailbox_capacity: int = 100,
    ) -> None:
        self.max_waves = max_waves
        self.wave_timeout = wave_timeout
        self.mailbox_capacity = mailbox_capacity

    @staticmethod
    def adaptive_wave_timeout(
        node_count: int,
        activated_nodes: int = 0,
        *,
        floor: float = 120.0,
        scale: float = 0.03,
    ) -> float:
        """Calculate adaptive wave timeout based on graph size.

        Prevents premature wave cancellation on large graphs where
        Sonnet/Opus reasoning takes longer due to more context.

        Formula: max(floor, node_count * scale) seconds
        Default: max(120, nodes * 0.03) → 3,749 nodes = 120s, 10K nodes = 300s

        Parameters
        ----------
        node_count : total nodes in the graph
        activated_nodes : nodes activated for this query (0 = use node_count)
        floor : minimum timeout in seconds (default 120)
        scale : seconds per node (default 0.03)
        """
        basis = activated_nodes if activated_nodes > 0 else node_count
        return max(floor, basis * scale)

    async def run(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> dict[str, list[Message]]:
        """Run async message passing. Returns all messages per node."""
        mailboxes: dict[str, NodeMailbox] = {
            nid: NodeMailbox(nid, self.mailbox_capacity)
            for nid in active_node_ids
        }

        all_messages: dict[str, list[Message]] = {nid: [] for nid in active_node_ids}

        # Wave 0: broadcast query to all nodes
        for nid in active_node_ids:
            query_msg = Message.create_query_broadcast(query, nid)
            await mailboxes[nid].send(query_msg)

        # Process waves
        for wave in range(self.max_waves):
            logger.debug(f"Wave {wave}: processing {len(active_node_ids)} nodes")

            # Each node processes its mailbox and produces a response
            tasks = [
                self._process_node(graph, query, nid, mailboxes, wave)
                for nid in active_node_ids
            ]

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.wave_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Wave {wave} timed out after {self.wave_timeout}s")
                break

            # Collect results and fan out to neighbors
            wave_messages: dict[str, Message] = {}
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"Node processing failed: {r}")
                    continue
                if r is None:
                    continue
                node_id, message = r
                wave_messages[node_id] = message
                all_messages[node_id].append(message)

            # Fan out: send each node's output to its neighbors
            for node_id, msg in wave_messages.items():
                neighbors = graph.get_neighbors(node_id)
                for neighbor_id in neighbors:
                    if neighbor_id in mailboxes:
                        try:
                            mailboxes[neighbor_id].queue.put_nowait(msg)
                        except asyncio.QueueFull:
                            logger.warning(
                                f"Mailbox full for {neighbor_id}, dropping message from {node_id}"
                            )

            if not wave_messages:
                logger.debug(f"No messages produced in wave {wave}, stopping")
                break

        return all_messages

    async def stream(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> AsyncIterator[tuple[int, str, Message]]:
        """Stream results as nodes complete. Yields (wave, node_id, message)."""
        mailboxes: dict[str, NodeMailbox] = {
            nid: NodeMailbox(nid, self.mailbox_capacity)
            for nid in active_node_ids
        }

        # Wave 0: broadcast query
        for nid in active_node_ids:
            query_msg = Message.create_query_broadcast(query, nid)
            await mailboxes[nid].send(query_msg)

        for wave in range(self.max_waves):
            tasks = [
                self._process_node(graph, query, nid, mailboxes, wave)
                for nid in active_node_ids
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            any_produced = False
            for r in results:
                if isinstance(r, Exception) or r is None:
                    continue
                node_id, message = r
                any_produced = True
                yield wave, node_id, message

                # Fan out to neighbors
                for neighbor_id in graph.get_neighbors(node_id):
                    if neighbor_id in mailboxes:
                        try:
                            mailboxes[neighbor_id].queue.put_nowait(message)
                        except asyncio.QueueFull:
                            pass

            if not any_produced:
                break

    async def _process_node(
        self,
        graph: Graqle,
        query: str,
        node_id: str,
        mailboxes: dict[str, NodeMailbox],
        wave: int,
    ) -> tuple[str, Message] | None:
        """Process pending messages for a single node."""
        node = graph.nodes[node_id]
        mailbox = mailboxes[node_id]

        if mailbox.pending == 0:
            return None

        # Drain all pending messages
        incoming: list[Message] = []
        while mailbox.pending > 0:
            msg = mailbox.queue.get_nowait()
            if msg is not None:
                incoming.append(msg)
                mailbox.processed += 1

        if not incoming:
            return None

        # Node reasons with all incoming context
        result = await node.reason(query, incoming)
        result.source_node_id = node_id
        result.round = wave
        return node_id, result
