"""S4-12, S4-13, S4-15: BudgetAwareSemaphore + ClearanceAwareEventStream tests."""

from __future__ import annotations

import asyncio
import time

import pytest

from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel
from graqle.reasoning.events import (
    ClearanceAwareEventStream,
    StreamEvent,
    StreamEventType,
)
from graqle.reasoning.semaphore import FAULT_BUDGET, BudgetAwareSemaphore, _TRANSIENT_FAULTS
from graqle.core.results import FAULT_NETWORK, FAULT_TIMEOUT


_BASE_CONFIG: dict = {
    "CONCURRENCY_LIMIT": 4,
    "PER_TASK_BUDGET_CEILING": 0.05,
    "BUDGET_PER_QUERY": 0.15,
    "BACKOFF_BASE_SECONDS": 0.001,  # fast for tests
    "BACKOFF_MAX_SECONDS": 0.01,
    "MAX_RETRIES": 2,
}


# ===========================================================================
# S4-12: TestBudgetAwareSemaphore
# ===========================================================================


class TestTransientFaultConstants:
    """AP-14 fix: verify FAULT_NETWORK is imported constant, not string literal."""

    def test_fault_network_in_transient_faults(self):
        assert FAULT_NETWORK in _TRANSIENT_FAULTS

    def test_fault_timeout_in_transient_faults(self):
        assert FAULT_TIMEOUT in _TRANSIENT_FAULTS


class TestBudgetAwareSemaphore:

    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)
        gate = asyncio.Event()
        entered_count = [0]

        async def _task() -> ToolResult:
            entered_count[0] += 1
            if entered_count[0] >= 4:
                gate.set()
            await gate.wait()
            return ToolResult.success(data="ok")

        tasks = [
            asyncio.create_task(
                sem.run(fn=_task, estimated_cost=0.01, task_id=f"t-{i}")
            )
            for i in range(4)
        ]

        await asyncio.wait_for(gate.wait(), timeout=5.0)
        results = await asyncio.gather(*tasks)

        assert all(isinstance(r, ToolResult) for r in results)
        assert sem.stats["tasks_completed"] == 4

    def test_ts2_config_required(self):
        with pytest.raises(ValueError, match="missing required keys"):
            BudgetAwareSemaphore(config={})

        with pytest.raises(ValueError):
            BudgetAwareSemaphore(config={"CONCURRENCY_LIMIT": 4})


# ===========================================================================
# S4-13: TestBudgetExhaustion
# ===========================================================================


class TestBudgetExhaustion:

    @pytest.mark.asyncio
    async def test_per_task_ceiling_rejection(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)

        async def _noop() -> ToolResult:
            return ToolResult.success(data="should not run")

        result = await sem.run(fn=_noop, estimated_cost=0.10, task_id="expensive")
        assert result.is_error is True
        assert result.fault_code == FAULT_BUDGET

    @pytest.mark.asyncio
    async def test_budget_depletion(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)

        async def _cheap() -> ToolResult:
            return ToolResult.success(data="done")

        for i in range(3):
            await sem.run(fn=_cheap, estimated_cost=0.05, task_id=f"spend-{i}")

        result = await sem.run(fn=_cheap, estimated_cost=0.05, task_id="over-budget")
        assert result.fault_code == FAULT_BUDGET

    @pytest.mark.asyncio
    async def test_gbs_metric(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)

        async def _work() -> ToolResult:
            return ToolResult.success(data="ok")

        await sem.run(fn=_work, estimated_cost=0.04, task_id="ok-1")
        await sem.run(fn=_work, estimated_cost=0.04, task_id="ok-2")
        await sem.run(fn=_work, estimated_cost=0.10, task_id="reject-ceiling")

        stats = sem.stats
        assert stats["tasks_completed"] >= 2
        assert stats["tasks_budget_rejected"] >= 1
        gbs = stats["governance_bounded_speedup"]
        assert 0.0 < gbs < 1.0


# ===========================================================================
# S4-15: TestClearanceEventStream
# ===========================================================================


class TestClearanceEventStream:

    def _make_event(self, clearance: ClearanceLevel) -> StreamEvent:
        return StreamEvent(
            event=StreamEventType.NODE_ACTIVATED,
            data={"info": "test"},
            clearance=clearance,
        )

    def test_public_event_visible_to_public(self):
        evt = self._make_event(ClearanceLevel.PUBLIC)
        assert evt.visible_to(ClearanceLevel.PUBLIC) is True

    def test_confidential_event_suppressed_for_public(self):
        stream = ClearanceAwareEventStream(viewer_clearance=ClearanceLevel.PUBLIC)
        evt = self._make_event(ClearanceLevel.CONFIDENTIAL)
        assert evt.visible_to(ClearanceLevel.PUBLIC) is False
        assert stream.emit(evt) is False

    def test_suppressed_count_increments(self):
        stream = ClearanceAwareEventStream(viewer_clearance=ClearanceLevel.PUBLIC)
        conf_evt = self._make_event(ClearanceLevel.CONFIDENTIAL)

        assert stream.suppressed_count == 0
        stream.emit(conf_evt)
        assert stream.suppressed_count == 1
        stream.emit(conf_evt)
        assert stream.suppressed_count == 2

    def test_to_dict_serializable(self):
        evt = self._make_event(ClearanceLevel.PUBLIC)
        d = evt.to_dict()
        assert isinstance(d, dict)
        assert "event" in d
        assert "data" in d
        assert "clearance" in d
        assert "timestamp" in d
        assert d["event"] == "node_activated"
        # D4: 4 new metadata fields
        assert "round_num" in d
        assert "wave_num" in d
        assert "task_id" in d
        assert "agent_id" in d


# ===========================================================================
# D1/D2/D3/D4/D5 Fix Verification Tests
# ===========================================================================


class TestD1Reconcile:

    @pytest.mark.asyncio
    async def test_reconcile_refunds_surplus(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)

        async def _cheap() -> ToolResult:
            return ToolResult.success(data="done")

        await sem.run(fn=_cheap, estimated_cost=0.05, task_id="t1")
        # Estimated 0.05, actual 0.02 → refund 0.03
        refund = await sem.reconcile(estimated_cost=0.05, actual_cost=0.02)
        assert refund == pytest.approx(0.03)
        assert sem.budget_remaining > 0.10  # refund restored some budget


class TestD2RedactedEvent:

    def test_redacted_for_returns_event_not_none(self):
        evt = StreamEvent(
            event=StreamEventType.NODE_COMPLETED,
            data={"secret": "classified"},
            clearance=ClearanceLevel.CONFIDENTIAL,
            task_id="t1",
            wave_num=0,
        )
        redacted = evt.redacted_for(ClearanceLevel.PUBLIC)
        assert redacted is not None
        assert isinstance(redacted, StreamEvent)
        assert redacted.data == {"redacted": True}
        assert redacted.task_id == "t1"
        assert redacted.wave_num == 0


class TestD5BudgetUtilization:

    @pytest.mark.asyncio
    async def test_budget_utilization_tracks_spend(self):
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)

        async def _work() -> ToolResult:
            return ToolResult.success(data="ok")

        await sem.run(fn=_work, estimated_cost=0.05, task_id="t1")
        util = sem.budget_utilization
        assert util > 0.0
        assert util <= 1.0
        assert "budget_utilization" in sem.stats


# ===========================================================================
# IR-S4-001 Finding 1+3: Budget resilience under transient failures
# ===========================================================================


class TestTransientFailureResilience:
    """Verify budget is NOT starved by transient failures (Finding 1)
    and that backoff is invoked on retry (Finding 3)."""

    @pytest.mark.asyncio
    async def test_budget_survives_transient_failures(self):
        """10 consecutive timeouts should NOT exhaust the budget permanently."""
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)
        initial_budget = sem.budget_remaining

        call_count = [0]

        async def _timeout_fn() -> ToolResult:
            call_count[0] += 1
            raise asyncio.TimeoutError("simulated timeout")

        # Run 3 tasks that all timeout — each gets MAX_RETRIES attempts
        for i in range(3):
            await sem.run(fn=_timeout_fn, estimated_cost=0.03, task_id=f"timeout-{i}")

        # Budget should be REFUNDED for transient failures
        assert sem.budget_remaining == pytest.approx(initial_budget, abs=0.01), (
            f"Budget should be refunded for transient failures. "
            f"Initial={initial_budget}, remaining={sem.budget_remaining}"
        )

    @pytest.mark.asyncio
    async def test_permanent_failure_not_refunded(self):
        """Permission errors (non-transient) should NOT be refunded."""
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)
        initial_budget = sem.budget_remaining

        async def _perm_fail() -> ToolResult:
            raise PermissionError("access denied")

        await sem.run(fn=_perm_fail, estimated_cost=0.04, task_id="perm-fail")

        # Budget should be permanently deducted (no refund)
        assert sem.budget_remaining < initial_budget

    @pytest.mark.asyncio
    async def test_retry_invokes_backoff(self):
        """Transient failure triggers retry (call count > 1)."""
        sem = BudgetAwareSemaphore(config=_BASE_CONFIG)
        call_count = [0]

        async def _flaky_fn() -> ToolResult:
            call_count[0] += 1
            if call_count[0] <= 2:
                raise asyncio.TimeoutError("flaky")
            return ToolResult.success(data="recovered")

        result = await sem.run(fn=_flaky_fn, estimated_cost=0.03, task_id="flaky")
        assert result.is_error is False  # should succeed on 3rd attempt
        assert call_count[0] == 3  # 2 retries + 1 success
