"""pre-reason-activation design — Default (fake/stub) providers for tests and fallback.

These providers are deterministic, fast, and never call an LLM. They are
the injection targets when a test or embedded use-case does not want
real DRACE/TAMR+/PSE wiring.

In production, the factory selects real providers; tests construct
ActivationLayer directly with these fakes.
"""
from __future__ import annotations

from graqle.activation.providers import (
    ActivatedSubgraph,
    ChunkScoreResult,
    ChunkScoringProvider,
    SafetyGateProvider,
    SafetyVerdict,
    SubgraphActivationProvider,
)


class NoopChunkScoringProvider:
    """Returns no scored chunks. Use when TAMR+ retrieval isn't available."""

    async def score(self, user_message, activation_hints):
        return ChunkScoreResult(
            chunks=(),
            scores=(),
            summary="no-op chunk scorer",
        )


class NoopSafetyGateProvider:
    """Returns a neutral (non-blocking) verdict. Use when DRACE isn't wired."""

    async def evaluate(self, user_message, scored_chunks, activation_hints):
        return SafetyVerdict(
            score=1.0,
            should_block=False,
            reason="no-op safety gate (neutral verdict)",
            details={},
        )


class NoopSubgraphActivationProvider:
    """Returns an empty activated subgraph. Use when PSE isn't wired."""

    async def predict(self, scored_chunks, safety):
        return ActivatedSubgraph(
            nodes=(),
            edges=(),
            confidence=0.0,
            summary="no-op subgraph activator",
        )


# Typed helpers for tests that want a specific verdict ------------------


class FakeChunkScoringProvider:
    """Test helper: returns caller-supplied ChunkScoreResult."""

    def __init__(self, result: ChunkScoreResult | None = None):
        self._result = result or ChunkScoreResult()

    async def score(self, user_message, activation_hints):
        return self._result


class FakeSafetyGateProvider:
    """Test helper: returns caller-supplied SafetyVerdict."""

    def __init__(self, verdict: SafetyVerdict | None = None):
        self._verdict = verdict or SafetyVerdict(score=1.0, should_block=False)

    async def evaluate(self, user_message, scored_chunks, activation_hints):
        return self._verdict


class FakeSubgraphActivationProvider:
    """Test helper: returns caller-supplied ActivatedSubgraph."""

    def __init__(self, subgraph: ActivatedSubgraph | None = None):
        self._subgraph = subgraph or ActivatedSubgraph()

    async def predict(self, scored_chunks, safety):
        return self._subgraph
