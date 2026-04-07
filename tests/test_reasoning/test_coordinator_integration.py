"""S8: Cross-component integration tests for MAG coordinator.

Tests wiring between ReasoningCoordinator, ReasoningMemory,
BudgetAwareSemaphore, and DebateCostBudget.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from graqle.reasoning.coordinator import CoordinatorConfig, ReasoningCoordinator, Specialist
from graqle.reasoning.memory import ReasoningMemory
from graqle.reasoning.semaphore import BudgetAwareSemaphore
from graqle.core.types import DebateCostBudget, ClearanceLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MEMORY_CONFIG = {
    "MEMORY_SUMMARY_MAX_CHARS": 2000,
    "MEMORY_MIN_CONFIDENCE": 0.1,
    "EPISTEMIC_DECAY_LAMBDA": 0.1,
    "CONTRADICTION_PENALTY": 0.2,
    "REVERIFICATION_THRESHOLD": 0.3,
}


def _make_config(max_specialists=3):
    return CoordinatorConfig(
        COORDINATOR_DECOMPOSITION_PROMPT="Decompose the query.",
        COORDINATOR_SYNTHESIS_PROMPT="Synthesize the results.",
        max_specialists=max_specialists,
        specialist_timeout_seconds=5.0,
    )


def _make_agent(name="agent-0"):
    agent = MagicMock()
    agent.name = name
    agent.model_id = "mock"
    agent.generate = AsyncMock(return_value=f"response from {name}")
    return agent


def _make_backend():
    backend = AsyncMock()
    backend.generate = AsyncMock(return_value="llm response")
    backend.name = "mock-backend"
    backend.cost_per_1k_tokens = 0.003
    return backend


# ---------------------------------------------------------------------------
# Class 1: ReasoningMemory integration
# ---------------------------------------------------------------------------

class TestMemoryIntegration:
    """Verify ReasoningMemory can be instantiated and used."""

    def test_memory_requires_config(self):
        """ReasoningMemory needs the 5 required config keys."""
        with pytest.raises(ValueError, match="requires config keys"):
            ReasoningMemory({})

    def test_memory_construction_with_valid_config(self):
        """ReasoningMemory constructs with all required keys."""
        memory = ReasoningMemory(_MEMORY_CONFIG)
        assert memory.entry_count == 0

    def test_memory_store_increments_count(self):
        """store() adds an entry to the memory."""
        memory = ReasoningMemory(_MEMORY_CONFIG)
        result = MagicMock()
        result.clearance = ClearanceLevel.PUBLIC
        memory.store(
            round_num=1,
            node_id="node-1",
            result=result,
            confidence=0.8,
            source_agent_id="agent-1",
        )
        assert memory.entry_count == 1

    def test_memory_decay_all(self):
        """decay_all processes without error."""
        memory = ReasoningMemory(_MEMORY_CONFIG)
        result = MagicMock()
        result.clearance = ClearanceLevel.PUBLIC
        memory.store(
            round_num=1, node_id="n1", result=result,
            confidence=0.9, source_agent_id="a1",
        )
        needs_reverify = memory.decay_all(current_round=5)
        assert isinstance(needs_reverify, list)


# ---------------------------------------------------------------------------
# Class 2: BudgetAwareSemaphore integration
# ---------------------------------------------------------------------------

_SEMAPHORE_CONFIG = {
    "CONCURRENCY_LIMIT": 3,
    "PER_TASK_BUDGET_CEILING": 10.0,
    "BUDGET_PER_QUERY": 100.0,
    "BACKOFF_BASE_SECONDS": 0.1,
    "BACKOFF_MAX_SECONDS": 1.0,
    "MAX_RETRIES": 2,
}


class TestSemaphoreIntegration:
    """Verify BudgetAwareSemaphore construction and budget tracking."""

    def test_semaphore_construction_with_valid_config(self):
        """BudgetAwareSemaphore constructs with required config keys."""
        sem = BudgetAwareSemaphore(_SEMAPHORE_CONFIG)
        assert sem is not None

    def test_semaphore_rejects_missing_keys(self):
        """BudgetAwareSemaphore raises on missing config keys."""
        with pytest.raises(ValueError, match="missing required keys"):
            BudgetAwareSemaphore({})


# ---------------------------------------------------------------------------
# Class 3: Fault isolation — coordinator lifecycle
# ---------------------------------------------------------------------------

class TestFaultIsolation:
    """Verify coordinator handles faults gracefully."""

    @pytest.mark.asyncio
    async def test_coordinator_survives_bad_agent_in_roster(self):
        """Coordinator lifecycle works even with an agent that would fail."""
        failing_agent = _make_agent("failing")
        failing_agent.generate = AsyncMock(side_effect=RuntimeError("boom"))
        good_agent = _make_agent("good")

        async with ReasoningCoordinator(
            llm_backend=_make_backend(),
            agent_roster=[failing_agent, good_agent],
            config=_make_config(),
        ) as coordinator:
            assert coordinator._active is True

        assert coordinator._active is False

    @pytest.mark.asyncio
    async def test_coordinator_cleans_up_on_exception(self):
        """Specialists cleared even if exception raised inside context."""
        coordinator = ReasoningCoordinator(
            llm_backend=_make_backend(),
            agent_roster=[_make_agent()],
            config=_make_config(),
        )

        with pytest.raises(ValueError, match="deliberate"):
            async with coordinator:
                coordinator.register_specialist(Specialist(name="s1", model_id="m1"))
                raise ValueError("deliberate")

        assert len(coordinator._specialists) == 0


# ---------------------------------------------------------------------------
# Class 4: DebateCostBudget decay
# ---------------------------------------------------------------------------

class TestBudgetDecayMultiRound:
    """Budget decay interacts correctly with multi-round dispatch."""

    def test_budget_decreases_monotonically(self):
        budget = DebateCostBudget(initial_budget=100.0, decay_factor=0.8)
        remainders = []
        for _ in range(5):
            r = budget.record_spend(5.0)
            remainders.append(r)
        for i in range(1, len(remainders)):
            assert remainders[i] < remainders[i - 1]

    def test_exhausted_budget_blocks_authorize(self):
        budget = DebateCostBudget(initial_budget=10.0, decay_factor=0.5)
        budget.record_spend(10.0)
        assert budget.exhausted
        assert budget.authorize_round(0.01) is False

    def test_decay_factor_affects_lifetime(self):
        fast = DebateCostBudget(initial_budget=100.0, decay_factor=0.5)
        slow = DebateCostBudget(initial_budget=100.0, decay_factor=0.9)
        for _ in range(3):
            fast.record_spend(10.0)
            slow.record_spend(10.0)
        assert slow._remaining > fast._remaining


# ---------------------------------------------------------------------------
# Class 5: Full stack — coordinator + memory + budget
# ---------------------------------------------------------------------------

class TestFullStack:
    """All components coexist without conflicts."""

    @pytest.mark.asyncio
    async def test_all_components_together(self):
        memory = ReasoningMemory(_MEMORY_CONFIG)
        budget = DebateCostBudget(initial_budget=50.0, decay_factor=0.8)

        async with ReasoningCoordinator(
            llm_backend=_make_backend(),
            agent_roster=[_make_agent("a1"), _make_agent("a2")],
            config=_make_config(),
        ) as coordinator:
            # Memory works
            result_mock = MagicMock()
            result_mock.clearance = ClearanceLevel.PUBLIC
            memory.store(round_num=1, node_id="n1", result=result_mock,
                         confidence=0.85, source_agent_id="a1")

            # Budget works
            assert budget.authorize_round(10.0) is True

            # Coordinator works
            coordinator.register_specialist(Specialist(name="s1", model_id="m1"))

        assert memory.entry_count == 1
        assert not budget.exhausted
        assert coordinator._active is False
