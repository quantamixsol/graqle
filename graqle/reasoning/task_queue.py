"""Reasoning task queue with governance-aware wave scheduling.

Implements topological wave decomposition (Kahn's algorithm), cascade
isolation on gate failures (AND-semantics), and governance yield tracking.

Reference: ADR-147 — Governed Reasoning Pipeline Architecture.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from graqle.core.exceptions import GovernanceViolation
from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel
from graqle.reasoning.memory import ReasoningMemory

logger = logging.getLogger(__name__)

_GOVERNANCE_TASK_TYPES: frozenset[str] = frozenset(
    {"governance_gate", "ip_check", "clearance_check"},
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Lifecycle status of a reasoning task."""

    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ISOLATED = "ISOLATED"


class GateFailureType(str, Enum):
    """Classification of governance-gate failures."""

    SCHEMA_INCOMPLETE = "SCHEMA_INCOMPLETE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TEMPORAL_CONSTRAINT = "TEMPORAL_CONSTRAINT"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# ReasoningTask dataclass (NOT frozen — status changes during execution)
# ---------------------------------------------------------------------------


@dataclass
class ReasoningTask:
    """A single unit of work in the governed reasoning pipeline."""

    id: str
    node_id: str
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: ToolResult | None = None
    assigned_to: str | None = None
    task_type: str = "reasoning"
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC
    wave: int = -1
    isolation_reason: str | None = None
    gate_failure_type: GateFailureType | None = None
    weight: float = 1.0

    @property
    def is_governance_gate(self) -> bool:
        """Return ``True`` if this task is a governance gate."""
        return self.task_type in _GOVERNANCE_TASK_TYPES


# ---------------------------------------------------------------------------
# ReasoningTaskQueue
# ---------------------------------------------------------------------------


class ReasoningTaskQueue:
    """DAG-based task queue with wave scheduling and failure cascade.

    Tasks are validated for cycles (DFS), sorted into waves (Kahn's
    algorithm), and executed with AND-semantics failure cascading.
    Gate results and failures are persisted to GEM when a
    :class:`ReasoningMemory` is provided.
    """

    def __init__(self, memory: ReasoningMemory | None = None) -> None:
        self._tasks: dict[str, ReasoningTask] = {}
        self._memory: ReasoningMemory | None = memory

    def add_batch(self, tasks: list[ReasoningTask]) -> None:
        """Add a batch of tasks to the queue."""
        for task in tasks:
            self._tasks[task.id] = task

    # -- validation ---------------------------------------------------------

    def validate(self) -> list[str]:
        """Run DFS cycle detection on the task dependency graph.

        Returns a list of human-readable error messages (empty when valid).

        Raises
        ------
        GovernanceViolation
            If any dependency cycle is detected (Tarjan deferred).
        """
        errors: list[str] = []
        WHITE, GRAY, BLACK = 0, 1, 2  # noqa: N806
        colour: dict[str, int] = {tid: WHITE for tid in self._tasks}

        def _dfs(tid: str, path: list[str]) -> None:
            colour[tid] = GRAY
            path.append(tid)
            task = self._tasks[tid]
            for dep_id in task.depends_on:
                if dep_id not in self._tasks:
                    errors.append(
                        f"Task '{tid}' depends on unknown task '{dep_id}'"
                    )
                    continue
                if colour[dep_id] == GRAY:
                    cycle_start = path.index(dep_id)
                    cycle = path[cycle_start:] + [dep_id]
                    errors.append(f"Cycle detected: {' -> '.join(cycle)}")
                elif colour[dep_id] == WHITE:
                    _dfs(dep_id, path)
            path.pop()
            colour[tid] = BLACK

        for tid in self._tasks:
            if colour[tid] == WHITE:
                _dfs(tid, [])

        if errors:
            msg = "; ".join(errors)
            raise GovernanceViolation(f"Task graph validation failed: {msg}")

        return errors

    # -- wave scheduling (Kahn's algorithm) ---------------------------------

    def get_waves(self) -> list[list[ReasoningTask]]:
        """Topological sort into execution waves using Kahn's algorithm.

        Wave 0 contains tasks with no dependencies (typically governance
        gates).  Never silently drops tasks — logs with root cause.
        """
        in_degree: dict[str, int] = {tid: 0 for tid in self._tasks}
        dependents: dict[str, list[str]] = {tid: [] for tid in self._tasks}

        for tid, task in self._tasks.items():
            for dep_id in task.depends_on:
                if dep_id in self._tasks:
                    in_degree[tid] += 1
                    dependents[dep_id].append(tid)

        queue: deque[str] = deque(
            tid for tid, deg in in_degree.items() if deg == 0
        )

        waves: list[list[ReasoningTask]] = []
        scheduled: set[str] = set()

        while queue:
            wave_ids = list(queue)
            queue.clear()
            wave_tasks: list[ReasoningTask] = []
            for tid in wave_ids:
                task = self._tasks[tid]
                task.wave = len(waves)
                wave_tasks.append(task)
                scheduled.add(tid)
                for dep_tid in dependents[tid]:
                    in_degree[dep_tid] -= 1
                    if in_degree[dep_tid] == 0:
                        queue.append(dep_tid)
            waves.append(wave_tasks)

        unscheduled = set(self._tasks) - scheduled
        if unscheduled:
            for tid in unscheduled:
                task = self._tasks[tid]
                missing_deps = [
                    d for d in task.depends_on if d not in scheduled
                ]
                logger.error(
                    "Task '%s' unscheduled; unresolved dependencies: %s",
                    tid,
                    missing_deps,
                )

        return waves

    # -- completion / failure -----------------------------------------------

    def complete(self, task_id: str, result: ToolResult) -> list[str]:
        """Mark *task_id* completed, unblock dependents where ALL deps done.

        Stores gate results in GEM when memory is available.
        Returns list of newly-unblocked task IDs.
        """
        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result

        if self._memory is not None and task.is_governance_gate:
            self._memory.store(
                round_num=task.wave,
                node_id=task.node_id,
                result=result,
                confidence=1.0,
                source_agent_id=f"gate:{task.task_type}",
            )

        unblocked: list[str] = []
        for tid, t in self._tasks.items():
            if t.status != TaskStatus.PENDING:
                continue
            if task_id not in t.depends_on:
                continue
            if all(
                self._tasks[d].status == TaskStatus.COMPLETED
                for d in t.depends_on
                if d in self._tasks
            ):
                unblocked.append(tid)

        return unblocked

    # -- SIG read path (S3-14) ---------------------------------------------

    def check_gem_for_gate(
        self, task: ReasoningTask, current_round: int,
    ) -> ToolResult | None:
        """S3-14: Check GEM for recent gate result — SIG read path.

        Returns cached ToolResult if a recent PASS exists for this gate's
        node_id, or None if the gate should be re-evaluated.

        This completes the SIG feedback loop:
        write (complete/fail) + read (this method).
        """
        if self._memory is None:
            return None

        entries = self._memory.get_weighted()
        for entry in entries:
            if entry.node_id != task.node_id:
                continue
            if not entry.source_agent_id.startswith("gate:"):
                continue
            if entry.confidence <= 0.0:
                continue
            rounds_since = current_round - entry.round_stored
            if rounds_since < 0:
                continue
            return ToolResult.success(
                data=f"GEM short-circuit: gate {task.node_id} passed in round {entry.round_stored}",
                clearance=task.clearance,
                source_node_id=task.node_id,
            )

        return None

    def fail(
        self,
        task_id: str,
        error: str,
        failure_type: GateFailureType = GateFailureType.UNKNOWN,
    ) -> list[str]:
        """Mark *task_id* failed and cascade-isolate all transitive dependents.

        Uses AND-semantics: any failed dependency isolates the dependent.
        Stores failure in GEM when memory is available.
        Returns list of isolated task IDs.
        """
        task = self._tasks[task_id]
        task.status = TaskStatus.FAILED
        task.gate_failure_type = failure_type

        if self._memory is not None and task.is_governance_gate:
            failure_result = ToolResult.failure(
                data=error,
                clearance=task.clearance,
                source_node_id=task.node_id,
            )
            self._memory.store(
                round_num=task.wave,
                node_id=task.node_id,
                result=failure_result,
                confidence=0.0,
                source_agent_id=f"gate:{task.task_type}",
            )

        isolated: list[str] = []
        reason = f"Dependency '{task_id}' failed: {error}"
        self._cascade_isolate(task_id, reason, isolated)

        logger.warning(
            "Task '%s' failed (%s); isolated %d dependents: %s",
            task_id,
            failure_type.value,
            len(isolated),
            isolated,
        )

        return isolated

    def _cascade_isolate(
        self, failed_id: str, reason: str, isolated: list[str],
    ) -> None:
        """Recursively isolate all transitive dependents of *failed_id*."""
        for tid, task in self._tasks.items():
            if failed_id in task.depends_on and task.status not in (
                TaskStatus.FAILED,
                TaskStatus.ISOLATED,
                TaskStatus.COMPLETED,
            ):
                task.status = TaskStatus.ISOLATED
                task.isolation_reason = reason
                isolated.append(tid)
                self._cascade_isolate(tid, reason, isolated)

    # -- metrics ------------------------------------------------------------

    def governance_yield(self) -> float:
        """Compute governance yield (GY).

        GY = sum(weight for COMPLETED) / sum(weight for COMPLETED +
        ISOLATED + governance_gates).  Returns 0.0 if denominator is zero.
        """
        completed_weight = sum(
            t.weight
            for t in self._tasks.values()
            if t.status == TaskStatus.COMPLETED
        )
        denominator_weight = sum(
            t.weight
            for t in self._tasks.values()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.ISOLATED)
            or t.is_governance_gate
        )
        if denominator_weight == 0.0:
            return 0.0
        return completed_weight / denominator_weight

    @property
    def progress(self) -> dict[str, int]:
        """Return counts of all six statuses plus total."""
        counts: dict[str, int] = {s.value: 0 for s in TaskStatus}
        for task in self._tasks.values():
            counts[task.status.value] += 1
        counts["total"] = len(self._tasks)
        return counts
