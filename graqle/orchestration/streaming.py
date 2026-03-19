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

"""StreamingOrchestrator — yield partial results as nodes complete.

Wraps the orchestration pipeline to emit StreamChunk objects as
reasoning progresses, enabling real-time UIs and `async for` usage.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.streaming
# risk: LOW (impact radius: 1 modules)
# consumers: test_streaming
# dependencies: __future__, time, dataclasses, typing, message +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from graqle.core.message import Message

if TYPE_CHECKING:
    from graqle.core.graph import Graqle


@dataclass
class StreamChunk:
    """A partial result emitted during streaming reasoning."""

    chunk_type: str  # "node_result", "round_complete", "observer_finding", "final_answer"
    node_id: str | None = None
    round_num: int = 0
    content: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
    timestamp_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.chunk_type,
            "node_id": self.node_id,
            "round": self.round_num,
            "content": self.content,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "timestamp_ms": self.timestamp_ms,
        }


class StreamingOrchestrator:
    """Orchestrator that yields StreamChunk objects during reasoning.

    Usage:
        async for chunk in StreamingOrchestrator(graph).stream(query):
            print(f"[{chunk.chunk_type}] {chunk.content[:100]}")
    """

    def __init__(
        self,
        graph: Graqle,
        max_rounds: int = 5,
        strategy: str = "pcst",
    ) -> None:
        self.graph = graph
        self.max_rounds = max_rounds
        self.strategy = strategy

    async def stream(
        self,
        query: str,
        active_node_ids: list[str] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream reasoning results as they become available."""
        from graqle.orchestration.convergence import ConvergenceDetector
        from graqle.orchestration.message_passing import MessagePassingProtocol

        start = time.perf_counter()
        protocol = MessagePassingProtocol(parallel=True)
        convergence = ConvergenceDetector(max_rounds=self.max_rounds)

        # Activate subgraph if needed
        if active_node_ids is None:
            active_node_ids = list(self.graph.nodes.keys())

        previous_messages: dict[str, Message] | None = None

        for round_num in range(self.max_rounds):
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Run round
            messages = await protocol.run_round(
                self.graph, query, active_node_ids, round_num, previous_messages
            )

            # Yield per-node results
            for node_id, msg in messages.items():
                yield StreamChunk(
                    chunk_type="node_result",
                    node_id=node_id,
                    round_num=round_num,
                    content=msg.content,
                    confidence=msg.confidence,
                    timestamp_ms=(time.perf_counter() - start) * 1000,
                )

            # Yield round summary
            avg_conf = (
                sum(m.confidence for m in messages.values()) / len(messages)
                if messages
                else 0.0
            )
            yield StreamChunk(
                chunk_type="round_complete",
                round_num=round_num,
                content=f"Round {round_num}: {len(messages)} nodes, avg confidence {avg_conf:.0%}",
                confidence=avg_conf,
                timestamp_ms=(time.perf_counter() - start) * 1000,
                metadata={"node_count": len(messages)},
            )

            # Check convergence
            current_list = list(messages.values())
            prev_list = list(previous_messages.values()) if previous_messages else None
            if convergence.check(round_num, current_list, prev_list):
                break

            previous_messages = messages

        # Yield final answer
        if previous_messages or messages:
            final_msgs = messages if messages else previous_messages
            # Simple confidence-weighted synthesis for streaming
            best = max(final_msgs.values(), key=lambda m: m.confidence)
            yield StreamChunk(
                chunk_type="final_answer",
                content=best.content,
                confidence=best.confidence,
                timestamp_ms=(time.perf_counter() - start) * 1000,
                metadata={
                    "total_rounds": round_num + 1,
                    "total_nodes": len(active_node_ids),
                },
            )
