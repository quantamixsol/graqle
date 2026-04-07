"""Tests for ReasoningTaskQueue — S3-11, S3-15, S3-16, S3-17, S3-19, S3-20.

Covers cascade failure isolation, cycle detection, wave ordering,
governance yield, governance gate creation, and progress tracking.
"""
from __future__ import annotations

import pytest

from graqle.core.exceptions import GovernanceViolation
from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel
from graqle.reasoning.governance_tasks import create_governance_gates
from graqle.reasoning.task_queue import (
    GateFailureType,
    ReasoningTask,
    ReasoningTaskQueue,
    TaskStatus,
)


def _make_task(
    task_id: str,
    *,
    node_id: str = "n0",
    depends_on: list[str] | None = None,
    task_type: str = "reasoning",
    weight: float = 1.0,
) -> ReasoningTask:
    return ReasoningTask(
        id=task_id, node_id=node_id,
        depends_on=depends_on or [], task_type=task_type, weight=weight,
    )


def _make_gate(task_id: str, *, depends_on: list[str] | None = None) -> ReasoningTask:
    return _make_task(task_id, depends_on=depends_on, task_type="governance_gate")


def _ok() -> ToolResult:
    return ToolResult.success(data="ok", clearance=ClearanceLevel.PUBLIC)


# ===================================================================
# S3-16 — TestCascadeFailure
# ===================================================================


class TestCascadeFailure:

    def test_gate_fail_isolates_dependents(self):
        gate = _make_gate("gate")
        child = _make_task("child", depends_on=["gate"])
        grandchild = _make_task("grandchild", depends_on=["child"])

        q = ReasoningTaskQueue()
        q.add_batch([gate, child, grandchild])
        q.validate()

        isolated = q.fail("gate", error="policy breach", failure_type=GateFailureType.POLICY_VIOLATION)
        assert "child" in isolated
        assert "grandchild" in isolated

    def test_isolation_reason_set(self):
        gate = _make_gate("g1")
        dep = _make_task("d1", depends_on=["g1"])

        q = ReasoningTaskQueue()
        q.add_batch([gate, dep])
        q.validate()

        q.fail("g1", error="blocked", failure_type=GateFailureType.POLICY_VIOLATION)
        assert dep.status == TaskStatus.ISOLATED
        assert isinstance(dep.isolation_reason, str)
        assert len(dep.isolation_reason) > 0


# ===================================================================
# S3-17 — TestCycleDetection
# ===================================================================


class TestCycleDetection:

    def test_cycle_raises_governance_violation(self):
        a = _make_task("a", depends_on=["b"])
        b = _make_task("b", depends_on=["a"])

        q = ReasoningTaskQueue()
        q.add_batch([a, b])

        with pytest.raises(GovernanceViolation):
            q.validate()

    def test_no_cycle_returns_empty(self):
        a = _make_task("a")
        b = _make_task("b", depends_on=["a"])

        q = ReasoningTaskQueue()
        q.add_batch([a, b])

        errors = q.validate()
        assert errors == []


# ===================================================================
# S3-19 — TestWaveOrdering
# ===================================================================


class TestWaveOrdering:

    def test_gates_in_wave_zero(self):
        gates = create_governance_gates()
        q = ReasoningTaskQueue()
        q.add_batch(gates)
        q.validate()

        waves = q.get_waves()
        assert len(waves) >= 1
        wave0_ids = {t.id for t in waves[0]}
        for g in gates:
            assert g.id in wave0_ids

    def test_reasoning_after_gates(self):
        gates = create_governance_gates()
        gate_ids = [g.id for g in gates]
        reasoning = _make_task("r1", depends_on=gate_ids)

        q = ReasoningTaskQueue()
        q.add_batch(gates + [reasoning])
        q.validate()

        waves = q.get_waves()
        assert len(waves) >= 2
        wave0_ids = {t.id for t in waves[0]}
        assert "r1" not in wave0_ids
        later_ids = {t.id for w in waves[1:] for t in w}
        assert "r1" in later_ids

    def test_three_wave_dag(self):
        gate = _make_gate("gate")
        t1 = _make_task("t1", depends_on=["gate"])
        t2 = _make_task("t2", depends_on=["t1"])

        q = ReasoningTaskQueue()
        q.add_batch([gate, t1, t2])
        q.validate()

        waves = q.get_waves()
        assert len(waves) == 3
        assert "gate" in {t.id for t in waves[0]}
        assert "t1" in {t.id for t in waves[1]}
        assert "t2" in {t.id for t in waves[2]}


# ===================================================================
# S3-20 — TestGovernanceYield
# ===================================================================


class TestGovernanceYield:

    def test_all_completed(self):
        t1 = _make_task("t1")
        t2 = _make_task("t2", depends_on=["t1"])

        q = ReasoningTaskQueue()
        q.add_batch([t1, t2])
        q.validate()

        q.complete("t1", _ok())
        q.complete("t2", _ok())
        assert q.governance_yield() > 0

    def test_with_isolation(self):
        gate = _make_gate("gate")
        child = _make_task("child", depends_on=["gate"])

        q = ReasoningTaskQueue()
        q.add_batch([gate, child])
        q.validate()

        q.fail("gate", error="denied", failure_type=GateFailureType.POLICY_VIOLATION)
        assert q.governance_yield() < 1.0

    def test_empty_queue(self):
        q = ReasoningTaskQueue()
        assert q.governance_yield() == 0.0

    def test_weight_affects_yield(self):
        gate = _make_gate("gate")
        heavy = _make_task("heavy", weight=10.0)
        light = _make_task("light", depends_on=["gate"], weight=0.1)

        q = ReasoningTaskQueue()
        q.add_batch([gate, heavy, light])
        q.validate()

        q.complete("heavy", _ok())
        q.fail("gate", error="denied", failure_type=GateFailureType.POLICY_VIOLATION)
        assert q.governance_yield() > 0.5


# ===================================================================
# S3-11 — TestGovernanceGates
# ===================================================================


class TestGovernanceGates:

    def test_creates_three_gates(self):
        gates = create_governance_gates()
        assert len(gates) == 3

    def test_all_are_gates(self):
        gates = create_governance_gates()
        for g in gates:
            assert g.is_governance_gate is True

    def test_no_dependencies(self):
        gates = create_governance_gates()
        for g in gates:
            assert g.depends_on == []


# ===================================================================
# S3-15 — TestProgress
# ===================================================================


class TestProgress:

    def test_progress_counts(self):
        gate = _make_gate("gate")
        t1 = _make_task("t1", depends_on=["gate"])
        t2 = _make_task("t2", depends_on=["gate"])
        t3 = _make_task("t3")

        q = ReasoningTaskQueue()
        q.add_batch([gate, t1, t2, t3])
        q.validate()

        q.complete("t3", _ok())
        q.complete("gate", _ok())

        progress = q.progress
        assert progress["total"] == 4
        assert progress["COMPLETED"] >= 2


# ===================================================================
# S3-21 — TestGEMGateShortCircuit
# ===================================================================

_MEM_CONFIG: dict = {
    "MEMORY_SUMMARY_MAX_CHARS": 100,
    "MEMORY_MIN_CONFIDENCE": 0.1,
    "EPISTEMIC_DECAY_LAMBDA": 0.9,
    "CONTRADICTION_PENALTY": 0.9,
    "REVERIFICATION_THRESHOLD": 0.5,
}


class TestGEMGateShortCircuit:

    def test_short_circuit_on_recent_pass(self):
        from graqle.reasoning.memory import ReasoningMemory
        memory = ReasoningMemory(config=_MEM_CONFIG)
        q = ReasoningTaskQueue(memory=memory)

        passed = ToolResult.success(data="gate passed", clearance=ClearanceLevel.PUBLIC)
        memory.store(
            round_num=1, node_id="governance:git", result=passed,
            confidence=0.95, source_agent_id="gate:governance_gate",
        )

        task = _make_gate("g1")
        task.node_id = "governance:git"
        result = q.check_gem_for_gate(task, current_round=2)
        assert result is not None
        assert isinstance(result, ToolResult)
        assert "short-circuit" in result.data.lower()

    def test_no_memory_returns_none(self):
        q = ReasoningTaskQueue(memory=None)
        task = _make_gate("g1")
        assert q.check_gem_for_gate(task, current_round=1) is None

    def test_no_matching_gate_returns_none(self):
        from graqle.reasoning.memory import ReasoningMemory
        memory = ReasoningMemory(config=_MEM_CONFIG)
        q = ReasoningTaskQueue(memory=memory)

        passed = ToolResult.success(data="other gate", clearance=ClearanceLevel.PUBLIC)
        memory.store(
            round_num=1, node_id="governance:OTHER", result=passed,
            confidence=0.9, source_agent_id="gate:governance_gate",
        )

        task = _make_gate("g1")
        task.node_id = "governance:git"
        assert q.check_gem_for_gate(task, current_round=2) is None

    def test_failed_gate_not_short_circuited(self):
        from graqle.reasoning.memory import ReasoningMemory
        memory = ReasoningMemory(config=_MEM_CONFIG)
        q = ReasoningTaskQueue(memory=memory)

        failed = ToolResult.failure(data="gate failed", clearance=ClearanceLevel.PUBLIC)
        memory.store(
            round_num=1, node_id="governance:git", result=failed,
            confidence=0.0, source_agent_id="gate:governance_gate",
        )

        task = _make_gate("g1")
        task.node_id = "governance:git"
        assert q.check_gem_for_gate(task, current_round=2) is None


# ===================================================================
# S3-22 — TestFailureTypeDecay
# ===================================================================


class TestFailureTypeDecay:

    def test_schema_incomplete_decays_fast(self):
        from graqle.reasoning.memory import ReasoningMemory
        memory = ReasoningMemory(config=_MEM_CONFIG)

        result = ToolResult.failure(data="schema incomplete", clearance=ClearanceLevel.PUBLIC)
        memory.store(
            round_num=0, node_id="node-z", result=result,
            confidence=0.8, source_agent_id="gate:governance_gate",
        )

        memory.decay_all(current_round=20)
        entries = memory.get_weighted()
        node_z = [e for e in entries if e.node_id == "node-z"]
        assert len(node_z) > 0
        assert node_z[0].confidence < 0.4

    def test_decay_increases_dlt(self):
        from graqle.reasoning.memory import ReasoningMemory
        memory = ReasoningMemory(config=_MEM_CONFIG)

        result = ToolResult.success(data="gate ok", clearance=ClearanceLevel.PUBLIC)
        memory.store(
            round_num=0, node_id="node-w", result=result,
            confidence=0.9, source_agent_id="gate:governance_gate",
        )

        memory.decay_all(current_round=10)
        entries = memory.get_weighted()
        node_w = [e for e in entries if e.node_id == "node-w"]
        assert len(node_w) > 0
        assert node_w[0].trace_scores.dlt > 0.0
