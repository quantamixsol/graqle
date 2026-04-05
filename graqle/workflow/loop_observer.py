# graqle/workflow/loop_observer.py
"""
LoopObserver: transparency and observability for the autonomous loop.

Provides:
- Real-time state change callbacks for UI/logging
- Cost and latency tracking per iteration
- Violation detection and self-correction reporting
- Governance compliance auditing

This module ensures users always know what the loop is doing,
how much it costs, and whether governance was respected.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("graqle.workflow.loop_observer")


class ViolationType(str, Enum):
    """Types of governance violations detected during execution."""
    SKIPPED_PREFLIGHT = "SKIPPED_PREFLIGHT"
    SKIPPED_REVIEW = "SKIPPED_REVIEW"
    EXCEEDED_BUDGET = "EXCEEDED_BUDGET"
    EXCEEDED_TIMEOUT = "EXCEEDED_TIMEOUT"
    MODIFIED_PROTECTED_FILE = "MODIFIED_PROTECTED_FILE"
    BYPASSED_GATE = "BYPASSED_GATE"
    STALE_KG = "STALE_KG"


@dataclass
class Violation:
    """A recorded governance violation with self-correction info."""
    violation_type: ViolationType
    description: str
    timestamp: float = field(default_factory=time.time)
    auto_corrected: bool = False
    correction_action: str = ""
    severity: str = "WARN"  # WARN | ERROR | CRITICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.violation_type.value,
            "description": self.description,
            "timestamp": self.timestamp,
            "auto_corrected": self.auto_corrected,
            "correction_action": self.correction_action,
            "severity": self.severity,
        }


@dataclass
class IterationMetrics:
    """Cost, latency, and quality metrics for a single iteration."""
    attempt: int
    state_from: str
    state_to: str
    duration_seconds: float = 0.0
    llm_calls: int = 0
    tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    files_modified: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "transition": f"{self.state_from} -> {self.state_to}",
            "duration_seconds": round(self.duration_seconds, 2),
            "llm_calls": self.llm_calls,
            "tokens_used": self.tokens_used,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "files_modified": self.files_modified,
        }


# Type for state change callback
StateChangeCallback = Callable[[str, str, int, dict[str, Any]], Awaitable[None] | None]


class LoopObserver:
    """
    Observes and reports on autonomous loop execution.

    Provides transparent reporting to users:
    - State changes with timestamps
    - Cost and latency per iteration
    - Violation detection with self-correction
    - Cumulative session summary

    Usage:
        observer = LoopObserver()
        observer.on_state_change = my_callback  # optional real-time hook

        # During loop execution:
        observer.record_transition("PLAN", "GENERATE", attempt=0)
        observer.record_llm_call(tokens=500, cost=0.001)
        observer.record_violation(ViolationType.SKIPPED_PREFLIGHT, "...")

        # After loop:
        print(observer.summary())
    """

    # Hard caps to prevent unbounded memory growth in long sessions
    MAX_ITERATIONS = 500
    MAX_VIOLATIONS = 200

    def __init__(self) -> None:
        self._iterations: list[IterationMetrics] = []
        self._violations: list[Violation] = []
        self._current: IterationMetrics | None = None
        self._start_time: float = 0.0
        self._session_start: float = time.time()
        self._state_change_callback: StateChangeCallback | None = None
        self._log_transitions: bool = True

    @property
    def on_state_change(self) -> StateChangeCallback | None:
        return self._state_change_callback

    @on_state_change.setter
    def on_state_change(self, callback: StateChangeCallback | None) -> None:
        self._state_change_callback = callback

    @property
    def violations(self) -> list[Violation]:
        return list(self._violations)

    @property
    def total_cost_usd(self) -> float:
        return sum(m.estimated_cost_usd for m in self._iterations)

    @property
    def total_duration_seconds(self) -> float:
        return sum(m.duration_seconds for m in self._iterations)

    @property
    def total_llm_calls(self) -> int:
        return sum(m.llm_calls for m in self._iterations)

    # -- Recording methods -----------------------------------------------

    def record_transition(
        self,
        from_state: str,
        to_state: str,
        attempt: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a state transition with timing."""
        # Finalize previous iteration
        if self._current is not None:
            self._current.duration_seconds = time.time() - self._start_time
            if len(self._iterations) < self.MAX_ITERATIONS:
                self._iterations.append(self._current)
            else:
                logger.warning(
                    "LoopObserver: MAX_ITERATIONS=%d reached, dropping oldest",
                    self.MAX_ITERATIONS,
                )
                self._iterations.pop(0)
                self._iterations.append(self._current)

        # Start new iteration
        self._start_time = time.time()
        self._current = IterationMetrics(
            attempt=attempt,
            state_from=from_state,
            state_to=to_state,
        )

        # Log for transparency
        if self._log_transitions:
            logger.info(
                "[LOOP] %s -> %s (attempt=%d)",
                from_state, to_state, attempt,
            )

        # Fire callback if registered
        if self._state_change_callback is not None:
            try:
                result = self._state_change_callback(
                    from_state, to_state, attempt, metadata or {}
                )
                # Handle both sync and async callbacks
                if hasattr(result, "__await__"):
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(result)
            except Exception as exc:
                logger.warning("State change callback error: %s", exc)

    def record_llm_call(
        self,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record an LLM call within the current iteration."""
        if self._current is not None:
            self._current.llm_calls += 1
            self._current.tokens_used += tokens
            self._current.estimated_cost_usd += cost_usd

    def record_test_result(
        self,
        tests_run: int = 0,
        tests_passed: int = 0,
        tests_failed: int = 0,
    ) -> None:
        """Record test execution results."""
        if self._current is not None:
            self._current.tests_run = tests_run
            self._current.tests_passed = tests_passed
            self._current.tests_failed = tests_failed

    def record_files_modified(self, count: int) -> None:
        """Record number of files modified."""
        if self._current is not None:
            self._current.files_modified = count

    def record_violation(
        self,
        violation_type: ViolationType,
        description: str,
        *,
        severity: str = "WARN",
        auto_corrected: bool = False,
        correction_action: str = "",
    ) -> Violation:
        """
        Record a governance violation.

        If auto_corrected=True, the violation was detected and fixed automatically.
        """
        violation = Violation(
            violation_type=violation_type,
            description=description,
            severity=severity,
            auto_corrected=auto_corrected,
            correction_action=correction_action,
        )
        if len(self._violations) < self.MAX_VIOLATIONS:
            self._violations.append(violation)
        else:
            logger.warning(
                "LoopObserver: MAX_VIOLATIONS=%d reached, dropping oldest",
                self.MAX_VIOLATIONS,
            )
            self._violations.pop(0)
            self._violations.append(violation)

        level = logging.WARNING if severity == "WARN" else logging.ERROR
        logger.log(
            level,
            "[VIOLATION] %s: %s (auto_corrected=%s)",
            violation_type.value,
            description,
            auto_corrected,
        )
        return violation

    def finalize(self) -> None:
        """Finalize the last iteration (call at end of loop)."""
        if self._current is not None:
            self._current.duration_seconds = time.time() - self._start_time
            self._iterations.append(self._current)
            self._current = None

    # -- Summary and reporting -------------------------------------------

    def summary(self) -> dict[str, Any]:
        """
        Generate a complete session summary.

        This is the transparency report the user sees.
        """
        self.finalize()

        return {
            "session_duration_seconds": round(
                time.time() - self._session_start, 2
            ),
            "total_iterations": len(self._iterations),
            "total_llm_calls": self.total_llm_calls,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "violations": {
                "total": len(self._violations),
                "auto_corrected": sum(
                    1 for v in self._violations if v.auto_corrected
                ),
                "uncorrected": sum(
                    1 for v in self._violations if not v.auto_corrected
                ),
                "details": [v.to_dict() for v in self._violations],
            },
            "iterations": [m.to_dict() for m in self._iterations],
            "governance_score": self._compute_governance_score(),
        }

    def format_progress(self, state: str, attempt: int) -> str:
        """
        Format a human-readable progress line for CLI output.

        Example: "[2/3] TEST -> checking 5 tests..."
        """
        total_iterations = len(self._iterations) + (1 if self._current else 0)
        cost_str = f"${self.total_cost_usd:.4f}" if self.total_cost_usd > 0 else ""
        parts = [f"[{attempt}/{attempt}]", state]
        if cost_str:
            parts.append(f"(cost: {cost_str})")
        return " ".join(parts)

    def _compute_governance_score(self) -> float:
        """
        Compute a 0-100 governance compliance score.

        100 = no violations
        Deductions: -10 per WARN, -25 per ERROR, -50 per CRITICAL
        Auto-corrected violations get 50% deduction reduction.
        """
        if not self._violations:
            return 100.0

        deductions = {
            "WARN": 10,
            "ERROR": 25,
            "CRITICAL": 50,
        }

        total_deduction = 0.0
        for v in self._violations:
            base = deductions.get(v.severity, 10)
            if v.auto_corrected:
                base *= 0.5
            total_deduction += base

        return max(0.0, 100.0 - total_deduction)
