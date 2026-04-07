"""
Edge case tests for DebateCostBudget and ReasoningCoordinator lifecycle.

Coverage:
  1. authorize_round blocks after exhaustion
  2. record_spend applies decay correctly (with negative-remaining contract)
  3. Pre-exhausted budget blocks from the start
  4. authorize_round rejects over-budget estimates
  5. Decay compounds correctly over multiple rounds
  6. Zero spend still applies decay
  7. register_specialist raises outside context manager
  8. Coordinator is not re-entrant
  9. Specialists cleared on context exit (B2 ephemeral)
  10. Constructor rejects non-async agents

Note: Budget-integrated dispatch loop tests require the LoopController
from graqle.workflow — those tests live in tests/test_workflow/.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

try:
    from graqle.reasoning.coordinator import (
        CoordinatorConfig,
        ReasoningCoordinator,
        Specialist,
    )
    from graqle.core.types import DebateCostBudget
    _IMPORTS_OK = True
except ImportError:  # pragma: no cover
    _IMPORTS_OK = False
    ReasoningCoordinator = None  # type: ignore[assignment,misc]
    DebateCostBudget = None  # type: ignore[assignment,misc]
    CoordinatorConfig = None  # type: ignore[assignment,misc]
    Specialist = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    not _IMPORTS_OK,
    reason="graqle.reasoning package not available in this environment",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_backend() -> AsyncMock:
    """Return an AsyncMock LLM backend satisfying ModelBackend protocol."""
    backend = AsyncMock()
    backend.generate = AsyncMock(return_value="mock-llm-response")
    backend.name = "mock-backend"
    return backend


def _make_agent(name: str = "agent-0") -> MagicMock:
    """Return a mock agent satisfying AgentProtocol."""
    agent = MagicMock()
    agent.name = name
    agent.model_id = "mock-model"
    agent.generate = AsyncMock(return_value="mock-agent-response")
    return agent


def _make_config() -> CoordinatorConfig:
    """Return a minimal CoordinatorConfig for tests."""
    return CoordinatorConfig(
        COORDINATOR_DECOMPOSITION_PROMPT="Decompose the query.",
        COORDINATOR_SYNTHESIS_PROMPT="Synthesize the results.",
        max_specialists=4,
        specialist_timeout_seconds=30.0,
    )


# ---------------------------------------------------------------------------
# DebateCostBudget edge cases
# ---------------------------------------------------------------------------

class TestDebateCostBudgetEdgeCases:
    """Edge cases for DebateCostBudget — decaying cost budget."""

    def test_authorize_round_blocks_after_exhaustion(self):
        """authorize_round() returns False after budget is fully spent."""
        budget = DebateCostBudget(initial_budget=10.0, decay_factor=0.9)

        # authorize_round is read-only; only record_spend deducts budget
        assert budget.authorize_round(5.0) is True
        assert not budget.exhausted

        # Spend everything: (10 - 10) * 0.9 = 0.0
        budget.record_spend(10.0)

        assert budget.exhausted
        assert budget.authorize_round(0.01) is False

    def test_record_spend_applies_decay(self):
        """record_spend deducts cost and applies decay_factor each round.

        Contract: record_spend returns raw remaining (no floor clamping).
        Negative remaining is valid and indicates over-spend.
        """
        budget = DebateCostBudget(initial_budget=100.0, decay_factor=0.5)

        # Round 1: (100 - 10) * 0.5 = 45.0
        remaining = budget.record_spend(10.0)
        assert remaining == pytest.approx(45.0)
        assert not budget.exhausted

        # Round 2: (45 - 40) * 0.5 = 2.5
        remaining = budget.record_spend(40.0)
        assert remaining == pytest.approx(2.5)
        assert not budget.exhausted

        # Round 3: (2.5 - 10) * 0.5 = -3.75 → exhausted
        remaining = budget.record_spend(10.0)
        assert remaining == pytest.approx(-3.75)
        assert budget.exhausted
        assert budget.authorize_round(0.01) is False

    def test_pre_exhausted_budget_blocks_authorize(self):
        """A zero-budget instance is immediately exhausted."""
        budget = DebateCostBudget(initial_budget=0.0, decay_factor=0.5)

        assert budget.exhausted
        assert budget.authorize_round(0.01) is False

    def test_authorize_round_rejects_over_budget_estimate(self):
        """authorize_round rejects when estimated_cost exceeds remaining."""
        # Use separate instances to avoid statefulness concerns
        budget_at_limit = DebateCostBudget(initial_budget=10.0, decay_factor=0.9)
        assert budget_at_limit.authorize_round(10.0) is True

        budget_over = DebateCostBudget(initial_budget=10.0, decay_factor=0.9)
        assert budget_over.authorize_round(10.01) is False

    def test_decay_chain_multiple_rounds(self):
        """Verify decay compounds correctly over multiple rounds."""
        budget = DebateCostBudget(initial_budget=1000.0, decay_factor=0.8)

        # Round 1: (1000 - 100) * 0.8 = 720.0
        r1 = budget.record_spend(100.0)
        assert r1 == pytest.approx(720.0)

        # Round 2: (720 - 100) * 0.8 = 496.0
        r2 = budget.record_spend(100.0)
        assert r2 == pytest.approx(496.0)

        # Round 3: (496 - 100) * 0.8 = 316.8
        r3 = budget.record_spend(100.0)
        assert r3 == pytest.approx(316.8)

        assert not budget.exhausted

    def test_zero_spend_still_applies_decay(self):
        """Even zero spend applies decay — budget shrinks each round."""
        budget = DebateCostBudget(initial_budget=10.0, decay_factor=0.5)

        # Round 1: (10 - 0) * 0.5 = 5.0
        r1 = budget.record_spend(0.0)
        assert r1 == pytest.approx(5.0)

        # Round 2: (5 - 0) * 0.5 = 2.5
        r2 = budget.record_spend(0.0)
        assert r2 == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# ReasoningCoordinator lifecycle edge cases
# ---------------------------------------------------------------------------

class TestCoordinatorLifecycleEdgeCases:
    """Context manager and lifecycle enforcement for ReasoningCoordinator."""

    def test_register_specialist_outside_context_raises(self):
        """register_specialist raises RuntimeError outside context manager."""
        coordinator = ReasoningCoordinator(
            llm_backend=_make_llm_backend(),
            agent_roster=[_make_agent()],
            config=_make_config(),
        )

        with pytest.raises(RuntimeError, match="context manager"):
            coordinator.register_specialist(
                Specialist(name="test", model_id="mock")
            )

    @pytest.mark.asyncio
    async def test_coordinator_not_reentrant(self):
        """Coordinator raises on nested context manager entry."""
        coordinator = ReasoningCoordinator(
            llm_backend=_make_llm_backend(),
            agent_roster=[_make_agent()],
            config=_make_config(),
        )

        async with coordinator:
            with pytest.raises(RuntimeError, match="not re-entrant"):
                async with coordinator:
                    pass  # should not reach here

    @pytest.mark.asyncio
    async def test_specialist_cleared_on_exit(self):
        """Specialists list is cleared when context manager exits (B2 ephemeral)."""
        coordinator = ReasoningCoordinator(
            llm_backend=_make_llm_backend(),
            agent_roster=[_make_agent()],
            config=_make_config(),
        )

        async with coordinator:
            coordinator.register_specialist(
                Specialist(name="s1", model_id="m1")
            )
            # White-box access: no public specialist count API exists
            assert len(coordinator._specialists) == 1

        assert len(coordinator._specialists) == 0

    @pytest.mark.asyncio
    async def test_specialist_cleared_on_exception_exit(self):
        """Specialists are cleared even if exception raised inside context."""
        coordinator = ReasoningCoordinator(
            llm_backend=_make_llm_backend(),
            agent_roster=[_make_agent()],
            config=_make_config(),
        )

        with pytest.raises(ValueError, match="deliberate"):
            async with coordinator:
                coordinator.register_specialist(
                    Specialist(name="s1", model_id="m1")
                )
                raise ValueError("deliberate test exception")

        assert len(coordinator._specialists) == 0

    def test_agent_roster_validates_async_generate(self):
        """Constructor rejects agents with non-coroutine generate."""
        bad_agent = MagicMock()
        bad_agent.name = "bad"
        bad_agent.model_id = "mock"
        bad_agent.generate = lambda prompt: "sync"  # NOT async

        with pytest.raises(TypeError, match="coroutine function"):
            ReasoningCoordinator(
                llm_backend=_make_llm_backend(),
                agent_roster=[bad_agent],
                config=_make_config(),
            )
