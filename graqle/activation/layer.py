"""ADR-205 — ActivationLayer: orchestrates the 3 providers per chat turn.

Order of operations inside run():
    1. ChunkScoringProvider.score()       — TAMR+ role
    2. SafetyGateProvider.evaluate()      — DRACE role
    3. SubgraphActivationProvider.predict() — PSE role
    4. Compose ActivationVerdict
    5. If tier_mode == ENFORCED and verdict.safety.should_block → raise TurnBlocked

Error handling contract:
    - Provider exceptions are caught inside providers themselves (they
      return neutral fallback results). The layer itself does not catch.
    - TurnBlocked is the only exception this layer raises; callers
      (ChatAgentLoop.run_turn) handle it by transitioning the turn to
      the `blocked` state and emitting a governance_chip event.
"""
from __future__ import annotations

from typing import Any

from graqle.activation.providers import (
    ActivationVerdict,
    ChunkScoringProvider,
    SafetyGateProvider,
    SubgraphActivationProvider,
    TierMode,
    TurnBlocked,
)


class ActivationLayer:
    """Orchestrator for the pre-reason activation flow.

    Parameters
    ----------
    chunk_scorer:
        ChunkScoringProvider — runs first.
    safety_gate:
        SafetyGateProvider — runs on the scored chunks.
    subgraph_activator:
        SubgraphActivationProvider — runs on scored chunks + safety verdict.
    tier_mode:
        TierMode.ADVISORY (Free) or TierMode.ENFORCED (Pro+).
    """

    def __init__(
        self,
        chunk_scorer: ChunkScoringProvider,
        safety_gate: SafetyGateProvider,
        subgraph_activator: SubgraphActivationProvider,
        tier_mode: TierMode = TierMode.ADVISORY,
    ):
        self._chunks = chunk_scorer
        self._safety = safety_gate
        self._subgraph = subgraph_activator
        self._tier = tier_mode

    async def run(
        self,
        user_message: str,
        activation_hints: dict[str, Any] | None = None,
    ) -> ActivationVerdict:
        """Run the full activation flow. Raises TurnBlocked when ENFORCED + blocked."""
        hints = activation_hints or {}

        # 1. Relevance scoring
        chunk_result = await self._chunks.score(user_message, hints)

        # 2. Safety evaluation
        safety = await self._safety.evaluate(user_message, chunk_result, hints)

        # 3. Subgraph pre-activation
        subgraph = await self._subgraph.predict(chunk_result, safety)

        # 4. Compose verdict
        block_reason = ""
        if safety.should_block and self._tier == TierMode.ENFORCED:
            block_reason = safety.reason or "turn blocked by safety gate"

        verdict = ActivationVerdict(
            tier_mode=self._tier,
            chunk_result=chunk_result,
            safety=safety,
            subgraph=subgraph,
            block_reason=block_reason,
        )

        # 5. Enforce (only in ENFORCED mode + blocked)
        if verdict.is_blocked:
            raise TurnBlocked(verdict)

        return verdict
