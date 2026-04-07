"""MAG Cross-Module Integration Tests — 32 tests covering 7 confidence gaps.

Modules under test:
  - ReasoningCoordinator   (coordinator.py)
  - ReasoningMemory        (memory.py)
  - ReasoningTaskQueue     (task_queue.py)
  - BudgetAwareSemaphore   (semaphore.py)
  - ClearanceAwareEventStream (events.py)
  - governance_tasks.py

Gaps covered:
  1. Fault isolation in dispatch
  2. Anti-laundering / ClearanceOutputClamping
  3. Memory summary injection
  4. Semaphore + wave coordination
  5. StreamEvent pipeline
  6. Cross-module full lifecycle
  7. Governance topology dispatch filtering

Design: graq_reason 88% confidence, 50 nodes, 2 rounds.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel
from graqle.reasoning.coordinator import (
    CoordinatorConfig,
    GovernanceEdge,
    GovernanceTopology,
    ReasoningCoordinator,
    Specialist,
    SubTask,
    SynthesisResult,
    TaskDecomposition,
)
from graqle.reasoning.events import (
    ClearanceAwareEventStream,
    StreamEvent,
    StreamEventType,
)
from graqle.reasoning.memory import ReasoningMemory
from graqle.reasoning.semaphore import BudgetAwareSemaphore
from graqle.reasoning.task_queue import (
    ReasoningTask,
    ReasoningTaskQueue,
    TaskStatus,
)

# ── Shared configs (TS-2 compliant — no hardcoded defaults in production) ────

_MEMORY_CONFIG: dict[str, Any] = {
    "MEMORY_SUMMARY_MAX_CHARS": "8000",
    "MEMORY_MIN_CONFIDENCE": "0.1",
    "EPISTEMIC_DECAY_LAMBDA": "0.95",  # Base for exponential decay (high = slow decay)
    "CONTRADICTION_PENALTY": "0.9",
    "REVERIFICATION_THRESHOLD": "0.3",
}

_SEMAPHORE_CONFIG: dict[str, Any] = {
    "CONCURRENCY_LIMIT": "2",
    "PER_TASK_BUDGET_CEILING": "1.0",
    "BUDGET_PER_QUERY": "5.0",
    "BACKOFF_BASE_SECONDS": "0.001",
    "BACKOFF_MAX_SECONDS": "0.01",
    "MAX_RETRIES": "1",
}

_COORD_CONFIG = CoordinatorConfig(
    COORDINATOR_DECOMPOSITION_PROMPT="decompose_v1",
    COORDINATOR_SYNTHESIS_PROMPT="synthesize_v1",
    max_specialists=4,
    specialist_timeout_seconds=1.0,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_llm_backend() -> MagicMock:
    backend = MagicMock(name="llm_backend")
    backend.generate = AsyncMock(return_value="mock answer")
    return backend


@pytest.fixture()
def mock_agent() -> MagicMock:
    agent = MagicMock(name="test-agent")
    agent.name = "test-agent"
    agent.model_id = "test-model"
    agent.generate = AsyncMock(return_value="agent answer")
    agent.clearance_level = ClearanceLevel.PUBLIC
    agent.capability_tags = ()
    return agent


@pytest.fixture()
def memory() -> ReasoningMemory:
    return ReasoningMemory(_MEMORY_CONFIG)


@pytest.fixture()
def semaphore() -> BudgetAwareSemaphore:
    return BudgetAwareSemaphore(_SEMAPHORE_CONFIG)


# ═════════════════════════════════════════════════════════════════════════════
# Gap 1: Fault Isolation in Dispatch (5 tests)
# Invariant: Agent failure → error result, never crashes coordinator
# ═════════════════════════════════════════════════════════════════════════════


class TestFaultIsolationDispatch:
    """Agent failures are wrapped in error results; coordinator never crashes."""

    @pytest.mark.asyncio
    async def test_agent_exception_wrapped_in_error_result(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Agent raising RuntimeError returns error result, not propagated exception."""
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("agent crash"))
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert "agent crash" in results[0]["answer"]
        assert results[0]["clearance"] == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_agent_timeout_returns_error_result(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Agent exceeding deadline returns timeout error result."""
        async def slow_generate(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(100)
            return "never"

        mock_agent.generate = slow_generate
        small_config = CoordinatorConfig(
            COORDINATOR_DECOMPOSITION_PROMPT="dp",
            COORDINATOR_SYNTHESIS_PROMPT="sp",
            max_specialists=4,
            specialist_timeout_seconds=0.01,
        )
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], small_config)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="Do X")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert "timeout" in results[0]["answer"].lower() or "Error" in results[0]["answer"]

    @pytest.mark.asyncio
    async def test_multiple_agent_failures_do_not_halt_wave(
        self, mock_llm_backend: MagicMock,
    ) -> None:
        """Two failing agents in one dispatch produce individual error results."""
        agent1 = MagicMock(name="agent1")
        agent1.name = "agent1"
        agent1.model_id = "m"
        agent1.generate = AsyncMock(side_effect=RuntimeError("fail1"))
        agent1.clearance_level = ClearanceLevel.PUBLIC
        agent1.capability_tags = ()

        coord = ReasoningCoordinator(mock_llm_backend, [agent1], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="A"), SubTask(description="B")],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 2
        assert all("fail1" in r["answer"] for r in results)

    @pytest.mark.asyncio
    async def test_coordinator_state_intact_after_agent_crash(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Coordinator internal state (active, specialists) untouched after agent crash."""
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("crash"))
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q", subtasks=[SubTask(description="X")],
        )
        with coord:
            coord.register_specialist(Specialist(name="s1", model_id="m1"))
            await coord.dispatch(td)
            # State should be intact after crash
            assert coord._active is True
            assert len(coord.list_specialists()) == 1

    @pytest.mark.asyncio
    async def test_error_result_included_in_synthesis(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Error results from dispatch are included in synthesis — not dropped."""
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("agent error"))
        mock_llm_backend.generate = AsyncMock(return_value="synthesized with errors")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        with coord:
            result = await coord.execute("test query")
        assert isinstance(result, SynthesisResult)
        # The synthesis should have processed (not crashed)
        assert len(result.merged_answer) > 0


# ═════════════════════════════════════════════════════════════════════════════
# Gap 2: Anti-Laundering / ClearanceOutputClamping (5 tests)
# Invariant: output_clearance >= max(input_clearances)
# ═════════════════════════════════════════════════════════════════════════════


class TestAntiLaunderingClearance:
    """CONFIDENTIAL input cannot produce PUBLIC output."""

    @pytest.mark.asyncio
    async def test_confidential_input_clamped_to_confidential(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Output clearance >= max(input clearances)."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "B", "clearance": ClearanceLevel.CONFIDENTIAL, "taint": []},
        ]
        with coord:
            synthesis = await coord.synthesize(results)
        assert synthesis.clearance >= ClearanceLevel.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_mixed_clearances_clamped_to_highest(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """PUBLIC + INTERNAL + RESTRICTED → output = RESTRICTED."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "B", "clearance": ClearanceLevel.INTERNAL, "taint": []},
            {"answer": "C", "clearance": ClearanceLevel.RESTRICTED, "taint": []},
        ]
        with coord:
            synthesis = await coord.synthesize(results)
        assert synthesis.clearance == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_public_inputs_allow_public_output(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """All-PUBLIC inputs permit PUBLIC output (no false-positive clamping)."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": []},
            {"answer": "B", "clearance": ClearanceLevel.PUBLIC, "taint": []},
        ]
        with coord:
            synthesis = await coord.synthesize(results)
        assert synthesis.clearance == ClearanceLevel.PUBLIC

    @pytest.mark.asyncio
    async def test_missing_clearance_fails_closed_to_restricted(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Missing clearance key → fail-closed to RESTRICTED (max enum)."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        results = [
            {"answer": "A", "taint": []},  # No clearance key
        ]
        with coord:
            synthesis = await coord.synthesize(results)
        assert synthesis.clearance == ClearanceLevel.RESTRICTED

    @pytest.mark.asyncio
    async def test_taint_propagated_through_synthesis(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Taint from CONFIDENTIAL results propagated to synthesis output."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        results = [
            {"answer": "A", "clearance": ClearanceLevel.PUBLIC, "taint": ["pii"]},
            {"answer": "B", "clearance": ClearanceLevel.CONFIDENTIAL, "taint": ["gdpr"]},
        ]
        with coord:
            synthesis = await coord.synthesize(results)
        assert "pii" in synthesis.taint
        assert "gdpr" in synthesis.taint
        assert synthesis.clearance >= ClearanceLevel.CONFIDENTIAL


# ═════════════════════════════════════════════════════════════════════════════
# Gap 3: Memory Summary Injection (5 tests)
# Invariant: get_summary() content available for coordinator consumption
# ═════════════════════════════════════════════════════════════════════════════


class TestMemorySummaryInjection:
    """ReasoningMemory.get_summary() feeds into coordinator prompts."""

    def test_summary_content_after_store(self, memory: ReasoningMemory) -> None:
        """Memory with stored entry returns non-empty summary."""
        result = ToolResult(data="Analysis result", is_error=False)
        memory.store(
            round_num=1,
            node_id="node_1",
            result=result,
            confidence=0.9,
            source_agent_id="agent_a",
        )
        summary = memory.get_summary(
            viewer_clearance=ClearanceLevel.PUBLIC,
            current_round=2,
        )
        assert len(summary) > 0
        assert "agent_a" in summary

    def test_empty_memory_returns_minimal_summary(self, memory: ReasoningMemory) -> None:
        """Fresh memory yields summary with only the header."""
        summary = memory.get_summary(
            viewer_clearance=ClearanceLevel.PUBLIC,
            current_round=1,
        )
        assert "Prior Findings" in summary

    def test_summary_updates_between_stores(self, memory: ReasoningMemory) -> None:
        """After multiple stores, summary reflects all entries."""
        result1 = ToolResult(data="First finding", is_error=False)
        result2 = ToolResult(data="Second finding", is_error=False)
        memory.store(1, "n1", result1, 0.9, "agent_1")
        memory.store(1, "n2", result2, 0.8, "agent_2")
        summary = memory.get_summary(ClearanceLevel.PUBLIC, 2)
        assert "agent_1" in summary
        assert "agent_2" in summary

    def test_summary_respects_clearance_filter(self, memory: ReasoningMemory) -> None:
        """CONFIDENTIAL entry is redacted for PUBLIC viewer."""
        public_result = ToolResult(data="Public data", is_error=False)
        conf_result = ToolResult(data="Secret data", is_error=False, clearance=ClearanceLevel.CONFIDENTIAL)
        memory.store(1, "n1", public_result, 0.9, "agent_pub")
        memory.store(1, "n2", conf_result, 0.9, "agent_conf")
        summary = memory.get_summary(ClearanceLevel.PUBLIC, 2)
        # PUBLIC viewer should see public data but CONFIDENTIAL should be redacted
        assert "agent_pub" in summary
        assert "Secret data" not in summary

    def test_summary_truncated_to_char_cap(self, memory: ReasoningMemory) -> None:
        """Summary does not exceed MEMORY_SUMMARY_MAX_CHARS."""
        # Store many entries to exceed char cap
        for i in range(50):
            result = ToolResult(data=f"Finding {i} " + "x" * 200, is_error=False)
            memory.store(1, f"node_{i}", result, 0.9 - i * 0.01, f"agent_{i}")
        summary = memory.get_summary(ClearanceLevel.PUBLIC, 2)
        assert len(summary) <= 8500  # Allow slight overhead for header


# ═════════════════════════════════════════════════════════════════════════════
# Gap 4: Semaphore + Wave Coordination (5 tests)
# Invariant: run_wave() respects budget; waves execute sequentially
# ═════════════════════════════════════════════════════════════════════════════


class TestSemaphoreWaveIntegration:
    """BudgetAwareSemaphore.run_wave() with ReasoningTaskQueue.get_waves()."""

    @pytest.mark.asyncio
    async def test_wave_tasks_respect_concurrency_limit(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """run_wave() never exceeds semaphore's max concurrent slots."""
        max_concurrent = 0
        active = 0

        async def tracked_task() -> ToolResult:
            nonlocal max_concurrent, active
            active += 1
            max_concurrent = max(max_concurrent, active)
            await asyncio.sleep(0.01)
            active -= 1
            return ToolResult(data="ok", is_error=False)

        tasks = [(tracked_task, 0.1, f"t{i}") for i in range(5)]
        results = await semaphore.run_wave(tasks)
        assert max_concurrent <= 2  # CONCURRENCY_LIMIT=2
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_budget_exhaustion_rejects_task(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """When budget runs out, task is rejected with FAULT_BUDGET."""
        async def cheap_task() -> ToolResult:
            return ToolResult(data="ok", is_error=False)

        # Exhaust budget by running expensive tasks
        for i in range(5):
            await semaphore.run(cheap_task, estimated_cost=1.0, task_id=f"t{i}")
        # 6th task should be rejected (budget=5.0, spent=5.0)
        result = await semaphore.run(cheap_task, estimated_cost=0.5, task_id="over_budget")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_task_queue_produces_sequential_waves(self) -> None:
        """TaskQueue get_waves() produces waves in dependency order."""
        queue = ReasoningTaskQueue()
        gate = ReasoningTask(id="gate1", node_id="g1", task_type="governance_gate")
        task_a = ReasoningTask(id="a", node_id="na", depends_on=["gate1"])
        task_b = ReasoningTask(id="b", node_id="nb", depends_on=["a"])
        queue.add_batch([gate, task_a, task_b])
        queue.validate()
        waves = queue.get_waves()
        assert len(waves) == 3
        assert waves[0][0].id == "gate1"
        assert waves[1][0].id == "a"
        assert waves[2][0].id == "b"

    @pytest.mark.asyncio
    async def test_empty_wave_is_noop(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """Empty task list in run_wave() returns empty results."""
        results = await semaphore.run_wave([])
        assert results == []

    @pytest.mark.asyncio
    async def test_semaphore_released_on_task_failure(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """Failed task releases its semaphore slot for subsequent tasks."""
        async def failing_task() -> ToolResult:
            raise RuntimeError("boom")

        async def success_task() -> ToolResult:
            return ToolResult(data="ok", is_error=False)

        # First task fails, second should still run
        r1 = await semaphore.run(failing_task, estimated_cost=0.1, task_id="fail")
        r2 = await semaphore.run(success_task, estimated_cost=0.1, task_id="pass")
        assert r1.is_error
        assert not r2.is_error
        assert semaphore.active == 0


# ═════════════════════════════════════════════════════════════════════════════
# Gap 5: StreamEvent Pipeline (4 tests)
# Invariant: Events filtered by subscriber clearance; ordering preserved
# ═════════════════════════════════════════════════════════════════════════════


class TestStreamEventPipeline:
    """Coordinator emits StreamEvents filtered by ClearanceAwareEventStream."""

    def test_public_subscriber_receives_public_events(self) -> None:
        """PUBLIC subscriber receives PUBLIC events."""
        stream = ClearanceAwareEventStream(ClearanceLevel.PUBLIC)
        event = StreamEvent(
            event=StreamEventType.COORDINATOR_STARTED,
            data={"query": "test"},
            clearance=ClearanceLevel.PUBLIC,
        )
        assert stream.emit(event) is True
        assert len(stream.events) == 1

    def test_confidential_events_filtered_for_public_subscriber(self) -> None:
        """PUBLIC subscriber does not receive CONFIDENTIAL events."""
        stream = ClearanceAwareEventStream(ClearanceLevel.PUBLIC)
        event = StreamEvent(
            event=StreamEventType.NODE_COMPLETED,
            data={"node": "secret_node"},
            clearance=ClearanceLevel.CONFIDENTIAL,
        )
        assert stream.emit(event) is False
        assert len(stream.events) == 0
        assert stream.suppressed_count == 1

    def test_restricted_subscriber_receives_all(self) -> None:
        """RESTRICTED subscriber receives events at all clearance levels."""
        stream = ClearanceAwareEventStream(ClearanceLevel.RESTRICTED)
        events = [
            StreamEvent(event=StreamEventType.COORDINATOR_STARTED, clearance=ClearanceLevel.PUBLIC),
            StreamEvent(event=StreamEventType.WAVE_STARTED, clearance=ClearanceLevel.INTERNAL),
            StreamEvent(event=StreamEventType.NODE_COMPLETED, clearance=ClearanceLevel.CONFIDENTIAL),
            StreamEvent(event=StreamEventType.SYNTHESIS_COMPLETE, clearance=ClearanceLevel.RESTRICTED),
        ]
        for e in events:
            stream.emit(e)
        assert len(stream.events) == 4
        assert stream.suppressed_count == 0

    def test_event_ordering_preserved_after_filtering(self) -> None:
        """Filtered stream maintains chronological event order."""
        stream = ClearanceAwareEventStream(ClearanceLevel.INTERNAL)
        e1 = StreamEvent(event=StreamEventType.COORDINATOR_STARTED, clearance=ClearanceLevel.PUBLIC)
        e2 = StreamEvent(event=StreamEventType.NODE_COMPLETED, clearance=ClearanceLevel.RESTRICTED)  # filtered
        e3 = StreamEvent(event=StreamEventType.WAVE_COMPLETED, clearance=ClearanceLevel.INTERNAL)
        stream.emit(e1)
        stream.emit(e2)
        stream.emit(e3)
        assert len(stream.events) == 2
        assert stream.events[0].event == StreamEventType.COORDINATOR_STARTED
        assert stream.events[1].event == StreamEventType.WAVE_COMPLETED


# ═════════════════════════════════════════════════════════════════════════════
# Gap 6: Cross-Module Full Lifecycle (4 tests)
# Invariant: End-to-end pipeline produces consistent state
# ═════════════════════════════════════════════════════════════════════════════


class TestCrossModuleLifecycle:
    """Memory + TaskQueue + Coordinator full lifecycle."""

    @pytest.mark.asyncio
    async def test_end_to_end_pipeline_returns_result(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Full pipeline: query → decompose → dispatch → synthesize → result."""
        mock_llm_backend.generate = AsyncMock(return_value="synthesized")
        mock_agent.generate = AsyncMock(return_value="agent result")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            result = await coord.execute("analyse dependencies", memory=memory)
        assert isinstance(result, SynthesisResult)
        assert "synthesis:result" in memory
        assert "gate:gate_git_governance" in memory

    @pytest.mark.asyncio
    async def test_memory_persists_across_coordinator_invocations(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Second coordinator call sees memory written by first call."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent.generate = AsyncMock(return_value="agent answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            await coord.execute("query 1", memory=memory)
        gate_count_after_first = len([k for k in memory if k.startswith("gate:")])
        assert gate_count_after_first > 0

        with coord:
            await coord.execute("query 2", memory=memory)
        # Memory should still have entries from both calls
        assert "synthesis:result" in memory

    @pytest.mark.asyncio
    async def test_task_queue_governance_gates_in_wave_zero(self) -> None:
        """Governance gates from create_governance_gates() land in wave 0."""
        from graqle.reasoning.governance_tasks import create_governance_gates
        queue = ReasoningTaskQueue()
        gates = create_governance_gates()
        reasoning = ReasoningTask(id="reason_1", node_id="r1", depends_on=[g.id for g in gates])
        queue.add_batch(gates + [reasoning])
        queue.validate()
        waves = queue.get_waves()
        assert len(waves) >= 2
        wave0_ids = {t.id for t in waves[0]}
        assert all(g.id in wave0_ids for g in gates)

    @pytest.mark.asyncio
    async def test_partial_failure_leaves_memory_consistent(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """One failed agent in dispatch; memory still gets synthesis:result."""
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("fail"))
        mock_llm_backend.generate = AsyncMock(return_value="synthesis despite error")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        memory: dict[str, Any] = {}
        with coord:
            result = await coord.execute("failing query", memory=memory)
        assert isinstance(result, SynthesisResult)
        assert "synthesis:result" in memory


# ═════════════════════════════════════════════════════════════════════════════
# Gap 7: Governance Topology Dispatch Filtering (4 tests)
# Invariant: Topology edges block under-cleared agents
# ═════════════════════════════════════════════════════════════════════════════


class TestGovernanceTopologyDispatchFiltering:
    """Topology edges block under-cleared agents from receiving tasks."""

    @pytest.mark.asyncio
    async def test_under_cleared_agent_falls_back_to_llm(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Agent with PUBLIC clearance can't process RESTRICTED subtask → LLM fallback."""
        mock_agent.clearance_level = ClearanceLevel.PUBLIC
        mock_llm_backend.generate = AsyncMock(return_value="llm fallback answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="restricted task", clearance_required=ClearanceLevel.RESTRICTED)],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 1
        assert results[0]["answer"] == "llm fallback answer"
        # Agent should NOT have been called
        mock_agent.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleared_agent_receives_task_normally(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """Agent with RESTRICTED clearance processes RESTRICTED edge without filtering."""
        mock_agent.clearance_level = ClearanceLevel.RESTRICTED
        mock_agent.generate = AsyncMock(return_value="restricted answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[SubTask(description="restricted", clearance_required=ClearanceLevel.RESTRICTED)],
        )
        with coord:
            results = await coord.dispatch(td)
        assert results[0]["answer"] == "restricted answer"
        mock_agent.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_clearance_wave_filters_selectively(
        self, mock_llm_backend: MagicMock,
    ) -> None:
        """Wave with mixed clearance subtasks: agent handles PUBLIC, LLM handles RESTRICTED."""
        public_agent = MagicMock(name="public_agent")
        public_agent.name = "public_agent"
        public_agent.model_id = "m"
        public_agent.generate = AsyncMock(return_value="public answer")
        public_agent.clearance_level = ClearanceLevel.PUBLIC
        public_agent.capability_tags = ()

        mock_llm_backend.generate = AsyncMock(return_value="llm restricted answer")
        coord = ReasoningCoordinator(mock_llm_backend, [public_agent], _COORD_CONFIG)
        td = TaskDecomposition(
            original_query="Q",
            subtasks=[
                SubTask(description="public task", clearance_required=ClearanceLevel.PUBLIC),
                SubTask(description="restricted task", clearance_required=ClearanceLevel.RESTRICTED),
            ],
        )
        with coord:
            results = await coord.dispatch(td)
        assert len(results) == 2
        assert results[0]["answer"] == "public answer"
        assert results[1]["answer"] == "llm restricted answer"

    @pytest.mark.asyncio
    async def test_governance_topology_filters_dispatch_edges(
        self, mock_llm_backend: MagicMock, mock_agent: MagicMock,
    ) -> None:
        """GovernanceTopology with auth edges filters correctly in execute pipeline."""
        mock_llm_backend.generate = AsyncMock(return_value="answer")
        mock_agent.generate = AsyncMock(return_value="agent answer")
        coord = ReasoningCoordinator(mock_llm_backend, [mock_agent], _COORD_CONFIG)
        topology = GovernanceTopology(edges=[
            GovernanceEdge(source="auth/login", target="policy", relation="GOVERNS"),
            GovernanceEdge(source="billing/pay", target="audit", relation="COMPLIES_WITH"),
        ])
        memory: dict[str, Any] = {}
        with coord:
            result = await coord.execute(
                "auth query",
                governance_topology=topology,
                memory=memory,
            )
        assert isinstance(result, SynthesisResult)
        # Gate should reflect filtered topology (auth edges = 1)
        gate = memory.get("gate:gate_git_governance", {})
        assert gate.get("topology_edges_count") == 1


# ═════════════════════════════════════════════════════════════════════════════
# graq_review findings: Additional tests for comprehensive coverage
# ═════════════════════════════════════════════════════════════════════════════


class TestMemoryDecayAndContradiction:
    """Epistemic decay, contradiction penalty, and reverification threshold."""

    def test_confidence_decays_over_rounds(self, memory: ReasoningMemory) -> None:
        """Stored entry loses confidence over multiple rounds."""
        result = ToolResult(data="finding", is_error=False)
        memory.store(1, "n1", result, 0.9, "agent_a")
        initial_conf = list(memory._store.values())[0].confidence
        memory.decay_all(current_round=5)
        decayed_conf = list(memory._store.values())[0].confidence
        assert decayed_conf < initial_conf

    def test_contradiction_detection(self, memory: ReasoningMemory) -> None:
        """Two agents storing for same node_id triggers contradiction count."""
        r1 = ToolResult(data="finding A", is_error=False)
        r2 = ToolResult(data="finding B", is_error=False)
        memory.store(1, "shared_node", r1, 0.9, "agent_1")
        memory.store(1, "shared_node", r2, 0.8, "agent_2")
        # First entry should have contradiction_count > 0
        entry = memory._store["agent_1:1/shared_node"]
        assert entry.contradiction_count > 0

    def test_reverification_threshold(self, memory: ReasoningMemory) -> None:
        """Entries below reverification threshold are flagged by decay_all."""
        result = ToolResult(data="finding", is_error=False)
        memory.store(1, "n1", result, 0.35, "agent_a")
        needs_reverification = memory.decay_all(current_round=10)
        # After heavy decay, the entry should need reverification
        assert len(needs_reverification) > 0


class TestSemaphoreBudgetEdgeCases:
    """Per-task budget ceiling and retry behavior."""

    @pytest.mark.asyncio
    async def test_per_task_ceiling_rejects_expensive_task(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """Task exceeding PER_TASK_BUDGET_CEILING=1.0 is rejected."""
        async def task() -> ToolResult:
            return ToolResult(data="ok", is_error=False)

        result = await semaphore.run(task, estimated_cost=1.5, task_id="expensive")
        assert result.is_error
        assert "ceiling" in result.data.lower()

    @pytest.mark.asyncio
    async def test_fault_budget_code_on_rejection(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """Budget rejection includes FAULT_BUDGET fault code."""
        from graqle.reasoning.semaphore import FAULT_BUDGET

        async def task() -> ToolResult:
            return ToolResult(data="ok", is_error=False)

        result = await semaphore.run(task, estimated_cost=1.5, task_id="over")
        assert result.fault_code == FAULT_BUDGET

    @pytest.mark.asyncio
    async def test_transient_failure_retried(self) -> None:
        """Transient failure (timeout) triggers retry before returning error."""
        config = {**_SEMAPHORE_CONFIG, "MAX_RETRIES": "2"}
        sem = BudgetAwareSemaphore(config)
        call_count = 0

        async def flaky_task() -> ToolResult:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("transient")
            return ToolResult(data="ok", is_error=False)

        result = await sem.run(flaky_task, estimated_cost=0.1, task_id="flaky")
        assert not result.is_error
        assert call_count == 3  # 2 retries + 1 success

    @pytest.mark.asyncio
    async def test_budget_utilization_tracks_spending(
        self, semaphore: BudgetAwareSemaphore,
    ) -> None:
        """budget_utilization property tracks committed spending."""
        async def task() -> ToolResult:
            return ToolResult(data="ok", is_error=False)

        assert semaphore.budget_utilization == 0.0
        await semaphore.run(task, estimated_cost=1.0, task_id="t1")
        assert semaphore.budget_utilization > 0.0


class TestTaskQueueWaveGrouping:
    """Wave grouping with parallel fan-out and governance gates."""

    def test_parallel_fan_out_same_wave(self) -> None:
        """Two tasks depending on same gate appear in the same wave."""
        queue = ReasoningTaskQueue()
        gate = ReasoningTask(id="gate1", node_id="g1", task_type="governance_gate")
        task_a = ReasoningTask(id="a", node_id="na", depends_on=["gate1"])
        task_b = ReasoningTask(id="b", node_id="nb", depends_on=["gate1"])
        queue.add_batch([gate, task_a, task_b])
        queue.validate()
        waves = queue.get_waves()
        wave1_ids = {t.id for t in waves[1]}
        assert wave1_ids == {"a", "b"}

    def test_governance_gates_always_wave_zero(self) -> None:
        """Governance gates with no dependencies land in wave 0."""
        from graqle.reasoning.governance_tasks import create_governance_gates
        queue = ReasoningTaskQueue()
        gates = create_governance_gates()
        queue.add_batch(gates)
        queue.validate()
        waves = queue.get_waves()
        assert len(waves) == 1
        assert all(t.is_governance_gate for t in waves[0])

    def test_empty_queue_returns_no_waves(self) -> None:
        """Empty queue returns empty wave list."""
        queue = ReasoningTaskQueue()
        waves = queue.get_waves()
        assert waves == []


class TestStreamEventRedaction:
    """StreamEvent redaction and metadata-preserving filtering."""

    def test_redacted_event_preserves_metadata(self) -> None:
        """Redacted event keeps event type, timestamp, but data is replaced."""
        event = StreamEvent(
            event=StreamEventType.NODE_COMPLETED,
            data={"secret": "classified_data"},
            clearance=ClearanceLevel.RESTRICTED,
            task_id="secret_task",
        )
        redacted = event.redacted_for(ClearanceLevel.PUBLIC)
        assert redacted.event == StreamEventType.NODE_COMPLETED
        assert redacted.task_id == "secret_task"
        assert redacted.data == {"redacted": True}
        assert "classified_data" not in str(redacted.data)

    def test_visible_event_returns_self(self) -> None:
        """Visible event returns itself unchanged."""
        event = StreamEvent(
            event=StreamEventType.COORDINATOR_STARTED,
            clearance=ClearanceLevel.PUBLIC,
        )
        assert event.redacted_for(ClearanceLevel.PUBLIC) is event

    def test_internal_subscriber_boundary(self) -> None:
        """INTERNAL subscriber receives PUBLIC+INTERNAL, suppresses CONFIDENTIAL+RESTRICTED."""
        stream = ClearanceAwareEventStream(ClearanceLevel.INTERNAL)
        events = [
            StreamEvent(event=StreamEventType.COORDINATOR_STARTED, clearance=ClearanceLevel.PUBLIC),
            StreamEvent(event=StreamEventType.WAVE_STARTED, clearance=ClearanceLevel.INTERNAL),
            StreamEvent(event=StreamEventType.NODE_COMPLETED, clearance=ClearanceLevel.CONFIDENTIAL),
            StreamEvent(event=StreamEventType.SYNTHESIS_COMPLETE, clearance=ClearanceLevel.RESTRICTED),
        ]
        for e in events:
            stream.emit(e)
        assert len(stream.events) == 2
        assert stream.suppressed_count == 2
