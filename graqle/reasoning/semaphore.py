"""Budget-aware concurrency semaphore for governed parallel reasoning.

Implements governance-bounded parallelism with per-task and
per-query budget ceilings enforced *before* concurrency acquisition.

All thresholds are injected via ``config`` — zero hardcoded defaults (internal-pattern-B/V9).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from graqle.core.results import FAULT_NETWORK, FAULT_TIMEOUT, FAULT_UNKNOWN, ToolResult
from graqle.core.types import ClearanceLevel  # noqa: F401 — available for consumers
from graqle.intelligence.governance.debate_cost_gate import (
    BudgetExhaustedError as BudgetExhaustedError,  # re-export
)

__all__ = [
    "BudgetAwareSemaphore",
    "BudgetExhaustedError",
]

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = [
    "CONCURRENCY_LIMIT", "PER_TASK_BUDGET_CEILING", "BUDGET_PER_QUERY",
    "BACKOFF_BASE_SECONDS", "BACKOFF_MAX_SECONDS", "MAX_RETRIES",
]

# Transient fault codes eligible for retry + refund
_TRANSIENT_FAULTS = frozenset({FAULT_TIMEOUT, FAULT_NETWORK})

FAULT_BUDGET = "FAULT_BUDGET"


class BudgetAwareSemaphore:
    """Concurrency limiter with per-task and per-query budget gates.

    Budget checks run **before** the concurrency gate so that over-budget
    tasks never occupy a semaphore slot.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        missing = [k for k in _REQUIRED_KEYS if k not in config]
        if missing:
            raise ValueError(
                f"BudgetAwareSemaphore config missing required keys: {missing}. "
                f"internal-pattern-B: these must come from graqle_secrets.yaml, not defaults."
            )

        self._semaphore = asyncio.Semaphore(int(config["CONCURRENCY_LIMIT"]))
        self._budget: float = float(config["BUDGET_PER_QUERY"])
        self._per_task: float = float(config["PER_TASK_BUDGET_CEILING"])

        self._initial_budget: float = self._budget
        self._backoff = ExponentialBackoff(config)
        self._max_retries: int = int(config["MAX_RETRIES"])
        self._lock = asyncio.Lock()
        self._active_count: int = 0
        self._reserved: float = 0.0   # Budget reserved for in-flight tasks
        self._committed: float = 0.0  # Budget actually consumed (success + permanent failure)
        self._tasks_completed: int = 0
        self._tasks_budget_rejected: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        fn: Callable[[], Awaitable[ToolResult]],
        estimated_cost: float,
        task_id: str = "",
    ) -> ToolResult:
        """Execute *fn* under budget + concurrency governance."""
        # — Budget gate (before concurrency gate) —
        async with self._lock:
            if estimated_cost > self._per_task:
                self._tasks_budget_rejected += 1
                logger.warning(
                    "Task %s rejected: estimated_cost=%.4f exceeds per-task ceiling=%.4f",
                    task_id, estimated_cost, self._per_task,
                )
                return ToolResult.failure(
                    data=f"Task {task_id} rejected: estimated cost {estimated_cost:.4f} exceeds per-task ceiling",
                    fault_code=FAULT_BUDGET,
                )

            remaining = self._budget - self._committed - self._reserved
            if estimated_cost > remaining:
                self._tasks_budget_rejected += 1
                logger.warning(
                    "Task %s rejected: estimated_cost=%.4f exceeds remaining budget=%.4f",
                    task_id, estimated_cost, remaining,
                )
                return ToolResult.failure(
                    data=f"Task {task_id} rejected: estimated cost {estimated_cost:.4f} exceeds remaining budget {remaining:.4f}",
                    fault_code=FAULT_BUDGET,
                )

            # Reserve budget (not committed until task completes)
            self._reserved += estimated_cost

        # — Concurrency gate with retry for transient failures —
        last_fault_code = FAULT_UNKNOWN
        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                async with self._lock:
                    self._active_count += 1
                try:
                    result = await fn()
                    async with self._lock:
                        self._tasks_completed += 1
                        self._committed += estimated_cost
                        self._reserved -= estimated_cost
                    return result
                except (asyncio.TimeoutError, TimeoutError):
                    last_fault_code = FAULT_TIMEOUT
                    if attempt < self._max_retries:
                        logger.warning(
                            "Task %s timeout (attempt %d/%d), backing off",
                            task_id, attempt + 1, self._max_retries,
                        )
                        await self._backoff.wait(attempt)
                        continue
                except ConnectionError:
                    last_fault_code = FAULT_NETWORK
                    if attempt < self._max_retries:
                        logger.warning(
                            "Task %s network error (attempt %d/%d), backing off",
                            task_id, attempt + 1, self._max_retries,
                        )
                        await self._backoff.wait(attempt)
                        continue
                except Exception as exc:  # noqa: BLE001
                    # Non-retryable — commit cost, NO refund
                    async with self._lock:
                        self._committed += estimated_cost
                        self._reserved -= estimated_cost
                    logger.exception("Task %s failed: %s", task_id, exc)
                    return ToolResult.failure(
                        data=f"Task {task_id} failed: {exc}",
                        fault_code=FAULT_UNKNOWN,
                    )
                finally:
                    async with self._lock:
                        self._active_count -= 1

        # Retries exhausted — classify and handle budget
        if last_fault_code in _TRANSIENT_FAULTS:
            # Transient failure: release reservation without committing (refund)
            async with self._lock:
                self._reserved -= estimated_cost
                logger.info(
                    "Auto-refund %.4f for task %s (transient %s after %d retries)",
                    estimated_cost, task_id, last_fault_code, self._max_retries,
                )
        else:
            # Permanent failure: commit the cost (no refund)
            async with self._lock:
                self._committed += estimated_cost
                self._reserved -= estimated_cost

        return ToolResult.failure(
            data=f"Task {task_id} failed after {self._max_retries} retries",
            fault_code=last_fault_code,
        )

    async def reconcile(self, estimated_cost: float, actual_cost: float) -> float:
        """Refund surplus budget after task execution (D1 fix).

        Returns the amount refunded. Prevents budget leak on failed/cheap tasks.
        """
        async with self._lock:
            refund = max(estimated_cost - actual_cost, 0.0)
            self._committed -= refund
            return refund

    async def run_wave(
        self,
        tasks: list[tuple[Callable[[], Awaitable[ToolResult]], float, str]],
    ) -> list[ToolResult]:
        """Run a wave of tasks concurrently through :meth:`run`."""
        coros = [self.run(fn, cost, tid) for fn, cost, tid in tasks]
        return list(await asyncio.gather(*coros))

    # ------------------------------------------------------------------
    # Properties / stats
    # ------------------------------------------------------------------

    @property
    def active(self) -> int:
        """Number of tasks currently executing inside the semaphore."""
        return self._active_count

    @property
    def budget_remaining(self) -> float:
        """Remaining query-level budget (excludes both committed and reserved)."""
        return self._budget - self._committed - self._reserved

    @property
    def budget_utilization(self) -> float:
        """Fraction of initial budget actually committed (0.0 to 1.0+)."""
        if self._initial_budget == 0.0:
            return 0.0
        return self._committed / self._initial_budget

    @property
    def stats(self) -> dict[str, Any]:
        """Snapshot of governance metrics."""
        return {
            "active": self._active_count,
            "budget_remaining": self.budget_remaining,
            "total_spent": self._committed + self._reserved,
            "committed": self._committed,
            "reserved": self._reserved,
            "tasks_completed": self._tasks_completed,
            "tasks_budget_rejected": self._tasks_budget_rejected,
            "governance_bounded_speedup": self._compute_gbs(),
            "budget_utilization": self.budget_utilization,
        }

    def _compute_gbs(self) -> float:
        """Governance-Bounded Speedup: completed / (completed + rejected)."""
        total = self._tasks_completed + self._tasks_budget_rejected
        if total == 0:
            return 1.0
        return self._tasks_completed / total


# ---------------------------------------------------------------------------
# ExponentialBackoff — rate-limit retry with jitter
# ---------------------------------------------------------------------------


class ExponentialBackoff:
    """Exponential backoff with jitter for rate-limited API calls.

    Config keys BACKOFF_BASE_SECONDS and BACKOFF_MAX_SECONDS are required
    in the semaphore config (internal-pattern-B — no hardcoded defaults).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._base = float(config["BACKOFF_BASE_SECONDS"])
        self._max = float(config["BACKOFF_MAX_SECONDS"])

    async def wait(self, attempt: int) -> float:
        """Wait for 2^attempt * base seconds (capped at max). Returns actual wait."""
        import random

        delay = min(self._base * (2 ** attempt), self._max)
        jitter = random.uniform(0, delay * 0.1)
        actual = delay + jitter
        await asyncio.sleep(actual)
        return actual
