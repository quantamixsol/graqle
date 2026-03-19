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
# ──────────────────────────────────────────────────────────────────

"""DebateProtocol — adversarial reasoning through structured debate.

Nodes challenge each other's claims in structured rounds:
1. Opening: each node states its position
2. Challenge: nodes critique each other's arguments
3. Rebuttal: nodes respond to critiques
4. Judge: aggregator synthesizes the strongest arguments

This produces higher-quality reasoning than simple consensus because
it stress-tests claims through adversarial pressure.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.debate
# risk: LOW (impact radius: 1 modules)
# consumers: test_debate
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

logger = logging.getLogger("graqle.orchestration.debate")

CHALLENGE_PROMPT = """You received this claim from {source_node}:
"{claim}"

As {node_label}, critically evaluate this claim. Do you agree or disagree?
What evidence supports or contradicts it? Be specific and concise."""

REBUTTAL_PROMPT = """Your original position:
"{original_claim}"

Challenge from {challenger}:
"{challenge}"

Respond to this challenge. Strengthen your argument if you're right,
or adjust your position if the challenge has merit."""


class DebateProtocol:
    """Adversarial debate protocol for higher-quality reasoning.

    Protocol:
    1. Opening round: each node reasons independently
    2. Challenge rounds: nodes critique neighbors' claims
    3. Rebuttal round: nodes respond to critiques
    4. Final: collect all positions for judge aggregation

    .. note:: Requires Graqle Pro license (``debate_protocol`` feature).
    """

    def __init__(
        self,
        challenge_rounds: int = 1,
        parallel: bool = True,
    ) -> None:
        self.challenge_rounds = challenge_rounds
        self.parallel = parallel

    async def run(
        self,
        graph: Graqle,
        query: str,
        active_node_ids: list[str],
    ) -> dict[str, list[Message]]:
        """Execute the full debate protocol.

        Returns: dict of node_id -> [opening, challenges_received, rebuttal]
        """
        all_messages: dict[str, list[Message]] = {nid: [] for nid in active_node_ids}

        # Phase 1: Opening statements
        openings = await self._opening_round(graph, query, active_node_ids)
        for nid, msg in openings.items():
            all_messages[nid].append(msg)

        # Phase 2: Challenge rounds
        challenges: dict[str, list[Message]] = {nid: [] for nid in active_node_ids}
        for round_num in range(self.challenge_rounds):
            round_challenges = await self._challenge_round(
                graph, query, active_node_ids, openings, round_num + 1
            )
            for nid, msgs in round_challenges.items():
                challenges[nid].extend(msgs)
                all_messages[nid].extend(msgs)

        # Phase 3: Rebuttals
        rebuttals = await self._rebuttal_round(
            graph, query, active_node_ids, openings, challenges
        )
        for nid, msg in rebuttals.items():
            all_messages[nid].append(msg)

        return all_messages

    async def _opening_round(
        self, graph: Graqle, query: str, node_ids: list[str]
    ) -> dict[str, Message]:
        """Each node states its initial position."""
        async def _reason(nid: str) -> tuple[str, Message]:
            node = graph.nodes[nid]
            query_msg = Message.create_query_broadcast(query, nid)
            result = await node.reason(query, [query_msg])
            result.source_node_id = nid
            result.round = 0
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

    async def _challenge_round(
        self,
        graph: Graqle,
        query: str,
        node_ids: list[str],
        openings: dict[str, Message],
        round_num: int,
    ) -> dict[str, list[Message]]:
        """Nodes challenge their neighbors' claims."""
        challenges: dict[str, list[Message]] = {nid: [] for nid in node_ids}

        async def _challenge(
            challenger_id: str, target_id: str
        ) -> tuple[str, str, Message] | None:
            if target_id not in openings:
                return None

            challenger = graph.nodes[challenger_id]
            target_claim = openings[target_id].content

            prompt = CHALLENGE_PROMPT.format(
                source_node=target_id,
                claim=target_claim[:300],
                node_label=challenger.label,
            )

            challenge_msg = Message.create_query_broadcast(
                f"{query}\n\n{prompt}", challenger_id
            )
            result = await challenger.reason(query, [challenge_msg])
            result.source_node_id = challenger_id
            result.target_node_id = target_id
            result.round = round_num
            result.reasoning_type = ReasoningType.CONTRADICTION
            return challenger_id, target_id, result

        # Each node challenges its neighbors
        tasks = []
        for nid in node_ids:
            neighbors = graph.get_neighbors(nid)
            for neighbor_id in neighbors:
                if neighbor_id in node_ids:
                    tasks.append(_challenge(nid, neighbor_id))

        if self.parallel:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for t in tasks:
                results.append(await t)

        for r in results:
            if r is not None and not isinstance(r, Exception):
                _, target_id, msg = r
                challenges[target_id].append(msg)

        return challenges

    async def _rebuttal_round(
        self,
        graph: Graqle,
        query: str,
        node_ids: list[str],
        openings: dict[str, Message],
        challenges: dict[str, list[Message]],
    ) -> dict[str, Message]:
        """Nodes respond to challenges."""
        async def _rebut(nid: str) -> tuple[str, Message]:
            node = graph.nodes[nid]
            original = openings.get(nid)
            node_challenges = challenges.get(nid, [])

            if not node_challenges or not original:
                # No challenges — reaffirm position
                return nid, original or Message.create_query_broadcast(query, nid)

            # Build rebuttal context
            challenge_texts = [
                f"[{c.source_node_id}]: {c.content[:200]}"
                for c in node_challenges
            ]
            context_msgs = [original] + node_challenges
            result = await node.reason(query, context_msgs)
            result.source_node_id = nid
            result.round = self.challenge_rounds + 1
            result.reasoning_type = ReasoningType.SYNTHESIS
            return nid, result

        if self.parallel:
            results = await asyncio.gather(
                *[_rebut(nid) for nid in node_ids],
                return_exceptions=True,
            )
        else:
            results = [await _rebut(nid) for nid in node_ids]

        output = {}
        for r in results:
            if not isinstance(r, Exception):
                output[r[0]] = r[1]
        return output
