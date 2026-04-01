"""Tests for P3 DebateOrchestrator — propose/challenge/synthesize rounds."""
from __future__ import annotations

import pytest

from graqle.config.settings import DebateConfig
from graqle.core.types import DebateCostBudget, DebateTrace
from graqle.intelligence.governance.debate_cost_gate import DebateCostGate
from graqle.intelligence.governance.debate_citation import CitationValidator
from graqle.orchestration.backend_pool import BackendPool
from graqle.orchestration.debate import (
    DebateOrchestrator,
    _parse_confidence,
    _check_consensus,
)
from tests.test_debate.test_backend_pool import MockBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(
    num_panelists: int = 2,
    max_rounds: int = 1,
    budget: float = 10.0,
    response: str = "proposal text. Confidence: 0.85",
) -> DebateOrchestrator:
    panelists = [
        (f"p{i}", MockBackend(response=response))
        for i in range(num_panelists)
    ]
    config = DebateConfig(
        mode="debate",
        panelists=[f"p{i}" for i in range(num_panelists)],
        max_rounds=max_rounds,
    )
    pool = BackendPool(panelists)
    cost_gate = DebateCostGate(DebateCostBudget(initial_budget=budget, decay_factor=0.75))
    return DebateOrchestrator(config, pool, cost_gate)


# ---------------------------------------------------------------------------
# _parse_confidence
# ---------------------------------------------------------------------------


class TestParseConfidence:

    def test_extracts_decimal(self):
        assert _parse_confidence("Confidence: 0.85") == pytest.approx(0.85)

    def test_extracts_percentage(self):
        assert _parse_confidence("Confidence: 85%") == pytest.approx(0.85)

    def test_default_when_missing(self):
        assert _parse_confidence("no confidence here") == pytest.approx(0.5)

    def test_clamps_above_one(self):
        # Value > 1 without % is treated as percentage
        assert _parse_confidence("Confidence: 92") == pytest.approx(0.92)

    def test_clamps_to_bounds(self):
        assert 0.0 <= _parse_confidence("Confidence: 150%") <= 1.0


# ---------------------------------------------------------------------------
# _check_consensus
# ---------------------------------------------------------------------------


class TestCheckConsensus:

    def test_consensus_when_all_agree(self):
        from graqle.orchestration.backend_pool import PanelistResponse
        challenges = [
            PanelistResponse(panelist="p1", response="I concur with this."),
            PanelistResponse(panelist="p2", response="I agree completely."),
        ]
        assert _check_consensus(challenges) is True

    def test_no_consensus_when_objection(self):
        from graqle.orchestration.backend_pool import PanelistResponse
        challenges = [
            PanelistResponse(panelist="p1", response="I concur."),
            PanelistResponse(panelist="p2", response="I disagree strongly."),
        ]
        assert _check_consensus(challenges) is False

    def test_empty_challenges(self):
        assert _check_consensus([]) is False


# ---------------------------------------------------------------------------
# DebateOrchestrator
# ---------------------------------------------------------------------------


class TestDebateOrchestrator:

    @pytest.mark.asyncio
    async def test_run_returns_debate_trace(self):
        orch = _make_orchestrator()
        trace = await orch.run("What is X?")
        assert isinstance(trace, DebateTrace)

    @pytest.mark.asyncio
    async def test_run_populates_fields(self):
        orch = _make_orchestrator()
        trace = await orch.run("What is X?", context="Some context")
        assert trace.query == "What is X?"
        assert trace.rounds_completed >= 1
        assert len(trace.turns) > 0
        assert len(trace.panelist_names) == 2
        assert trace.total_cost_usd >= 0.0
        assert trace.total_latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_turns_have_correct_positions(self):
        orch = _make_orchestrator(max_rounds=1)
        trace = await orch.run("test")
        positions = {t.position for t in trace.turns}
        assert "propose" in positions
        assert "challenge" in positions
        assert "synthesize" in positions

    @pytest.mark.asyncio
    async def test_consensus_stops_early(self):
        orch = _make_orchestrator(
            max_rounds=5,
            response="I concur. Confidence: 0.9",
        )
        trace = await orch.run("test")
        assert trace.consensus_reached is True
        assert trace.rounds_completed <= 5

    @pytest.mark.asyncio
    async def test_budget_exhaustion_stops(self):
        orch = _make_orchestrator(max_rounds=10, budget=0.001)
        trace = await orch.run("test")
        assert trace.rounds_completed < 10

    @pytest.mark.asyncio
    async def test_confidence_parsed_from_responses(self):
        orch = _make_orchestrator(response="Answer here. Confidence: 0.92")
        trace = await orch.run("test")
        assert trace.final_confidence > 0.0

    @pytest.mark.asyncio
    async def test_single_panelist_still_works(self):
        orch = _make_orchestrator(num_panelists=1)
        trace = await orch.run("test")
        assert isinstance(trace, DebateTrace)
        assert trace.rounds_completed >= 1
