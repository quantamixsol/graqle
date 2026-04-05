# graqle/workflow/loop_controller.py
"""
LoopController: PLAN->GENERATE->WRITE->TEST->(RED:FIX loop | GREEN:DONE | FAILED)

CREATE NEW FILE — does NOT import or modify workflow_orchestrator.py (1238 deps).
Composes alongside WorkflowOrchestrator via AutonomousExecutor.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.workflow.test_result_parser import ParsedTestResult

logger = logging.getLogger("graqle.workflow.loop_controller")


class LoopState(str, Enum):
    PLAN = "PLAN"
    GENERATE = "GENERATE"
    WRITE = "WRITE"
    TEST = "TEST"
    RED_FIX = "RED:FIX"
    GREEN_DONE = "GREEN:DONE"
    FAILED = "FAILED"  # terminal: max_retries exceeded or unrecoverable error


# Explicit transition table — (current_state, test_passed | None) -> next_state
_TRANSITIONS: dict[tuple[LoopState, bool | None], LoopState] = {
    (LoopState.PLAN, None): LoopState.GENERATE,
    (LoopState.GENERATE, None): LoopState.WRITE,
    (LoopState.WRITE, None): LoopState.TEST,
    (LoopState.TEST, True): LoopState.GREEN_DONE,
    (LoopState.TEST, False): LoopState.RED_FIX,
    (LoopState.RED_FIX, None): LoopState.GENERATE,  # re-enter with error context
}

_TERMINAL: frozenset[LoopState] = frozenset({LoopState.GREEN_DONE, LoopState.FAILED})


@dataclass
class LoopContext:
    task: str
    attempt: int = 0
    max_retries: int = 3
    state: LoopState = LoopState.PLAN
    plan: str = ""
    generated_diff: str = ""
    modified_files: list[str] = field(default_factory=list)
    test_output: str = ""
    failed_tests: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
    rollback_token: str | None = None

    @property
    def retries_exhausted(self) -> bool:
        """True when no more RED_FIX->GENERATE re-entries are allowed.

        Semantics: attempt is incremented from 0 on each RED_FIX->GENERATE
        transition. max_retries=N allows re-entries for attempts 1..N;
        attempt N+1 is blocked. max_retries=0 means zero retries: first
        test failure immediately forces FAILED.
        """
        return self.attempt > self.max_retries

    def record(self, state: LoopState, detail: str = "") -> None:
        self.history.append(
            {
                "state": state.value,
                "attempt": self.attempt,
                "detail": detail,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "state": self.state.value,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "modified_files": self.modified_files,
            "failed_tests": self.failed_tests,
            "error_messages": self.error_messages,
            "last_error": self.last_error,
            "history": self.history,
        }


class InvalidTransitionError(ValueError):
    def __init__(self, from_state: LoopState, test_passed: bool | None = None) -> None:
        super().__init__(
            f"No transition from {from_state!r} with test_passed={test_passed!r}"
        )
        self.from_state = from_state
        self.test_passed = test_passed


class LoopController:
    """
    Finite state machine: PLAN->GENERATE->WRITE->TEST->RED:FIX (loop) | GREEN:DONE.

    Governance
    ----------
    * max_retries hard cap prevents infinite loops.
    * Exceeding retries forces FAILED terminal state.
    * Does NOT import or modify WorkflowOrchestrator (1238-dep constraint).
    * Composed alongside WorkflowOrchestrator inside AutonomousExecutor.
    """

    def __init__(self, max_retries: int = 3) -> None:
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        self.max_retries = max_retries

    def initial_context(self, task: str) -> LoopContext:
        if not task or not task.strip():
            raise ValueError("task must be a non-empty string")
        return LoopContext(task=task.strip(), max_retries=self.max_retries)

    def transition(
        self,
        ctx: LoopContext,
        test_passed: bool | None = None,
    ) -> LoopContext:
        """
        Validate and apply a state transition.

        Raises InvalidTransitionError on illegal moves.
        Enforces max_retries governance: RED:FIX->GENERATE is blocked
        when retries are exhausted, forcing FAILED instead.
        """
        if ctx.state in _TERMINAL:
            raise InvalidTransitionError(ctx.state, test_passed)

        key = (ctx.state, test_passed)
        next_state = _TRANSITIONS.get(key)

        if next_state is None:
            raise InvalidTransitionError(ctx.state, test_passed)

        # Governance gate: abort before re-entering GENERATE from RED:FIX
        # Increment attempt BEFORE check for consistent history recording.
        # max_retries=N allows exactly N RED_FIX->GENERATE re-entries.
        if ctx.state == LoopState.RED_FIX and next_state == LoopState.GENERATE:
            ctx.attempt += 1
            if ctx.retries_exhausted:
                # _force_failed is sole recorder — no duplicate history entry
                self._force_failed(ctx, f"max_retries_exhausted at attempt={ctx.attempt}")
                return ctx

        ctx.record(next_state, f"attempt={ctx.attempt}")
        logger.info(
            "Loop: %s -> %s (attempt=%d)", ctx.state, next_state, ctx.attempt
        )
        ctx.state = next_state
        return ctx

    def is_terminal(self, ctx: LoopContext) -> bool:
        return ctx.state in _TERMINAL

    def _force_failed(self, ctx: LoopContext, reason: str) -> None:
        """Force FAILED state consistently from any code path.

        Guards against double-call: if already terminal, does nothing.
        """
        if ctx.state in _TERMINAL:
            return
        ctx.last_error = reason
        ctx.record(LoopState.FAILED, reason)
        ctx.state = LoopState.FAILED
        logger.warning("LoopController: forced FAILED — %s", reason[:100])

    async def run(
        self,
        ctx: LoopContext,
        *,
        on_plan: Callable[[LoopContext], Awaitable[str]],
        on_generate: Callable[[LoopContext], Awaitable[str]],
        on_write: Callable[[LoopContext], Awaitable[list[str]]],
        on_test: Callable[[LoopContext], Awaitable[ParsedTestResult]],
        on_fix: Callable[[LoopContext], Awaitable[None]],
    ) -> LoopContext:
        """Drive the full loop until GREEN:DONE or FAILED.

        Note: ctx.max_retries is clamped to self.max_retries at entry.
        ctx must be fresh from initial_context() (attempt == 0, state == PLAN).
        """
        # Validate fresh context
        if ctx.state != LoopState.PLAN or ctx.attempt != 0:
            raise ValueError(
                f"run() requires a fresh context from initial_context(); "
                f"got attempt={ctx.attempt}, state={ctx.state}"
            )
        if not ctx.task or not ctx.task.strip():
            raise ValueError("ctx.task must be a non-empty string")
        if ctx.max_retries < 0:
            raise ValueError(f"ctx.max_retries must be >= 0, got {ctx.max_retries}")
        # Enforce controller's governance cap — intentional mutation, logged if clamped
        if ctx.max_retries > self.max_retries:
            logger.warning(
                "ctx.max_retries clamped %d -> %d by controller governance cap",
                ctx.max_retries,
                self.max_retries,
            )
            ctx.max_retries = self.max_retries
        # 4 initial states (PLAN+GEN+WRITE+TEST) + 4 per retry cycle (FIX+GEN+WRITE+TEST) + 4 buffer
        _absolute_max = 4 + (ctx.max_retries * 4) + 4
        _iteration_count = 0

        while not self.is_terminal(ctx):
            _iteration_count += 1
            if _iteration_count > _absolute_max:
                self._force_failed(
                    ctx,
                    f"Absolute iteration limit ({_absolute_max}) exceeded (safety guard)",
                )
                break
            try:
                if ctx.state == LoopState.PLAN:
                    plan = await on_plan(ctx)
                    if not isinstance(plan, str) or not plan.strip():
                        raise ValueError(
                            f"on_plan must return a non-empty str, got {type(plan).__name__}"
                        )
                    ctx.plan = plan
                    self.transition(ctx)  # PLAN -> GENERATE

                elif ctx.state == LoopState.GENERATE:
                    diff = await on_generate(ctx)
                    if not isinstance(diff, str) or not diff.strip():
                        raise ValueError(
                            "on_generate returned empty/None; expected non-empty str"
                        )
                    ctx.generated_diff = diff
                    self.transition(ctx)  # GENERATE -> WRITE

                elif ctx.state == LoopState.WRITE:
                    files = await on_write(ctx)
                    if not isinstance(files, list):
                        raise ValueError(
                            f"on_write must return list[str], got {type(files).__name__}"
                        )
                    if not all(isinstance(f, str) for f in files):
                        bad = [type(f).__name__ for f in files if not isinstance(f, str)]
                        raise ValueError(
                            f"on_write must return list[str], got non-str elements: {bad}"
                        )
                    ctx.modified_files = files
                    self.transition(ctx)  # WRITE -> TEST

                elif ctx.state == LoopState.TEST:
                    result = await on_test(ctx)
                    if result is None:
                        raise ValueError("on_test returned None; expected ParsedTestResult")
                    # Validate BEFORE mutating ctx to prevent inconsistent state
                    passed = result.passed
                    if not isinstance(passed, bool):
                        raise ValueError(
                            f"on_test must return ParsedTestResult with passed as bool, got {type(passed)}"
                        )
                    # Now safe to mutate ctx
                    ctx.test_output = result.raw_output if result.raw_output is not None else ""
                    ctx.failed_tests = result.failed_tests if result.failed_tests is not None else []
                    ctx.error_messages = result.error_messages if result.error_messages is not None else []
                    self.transition(ctx, test_passed=passed)  # TEST -> GREEN:DONE | RED:FIX

                elif ctx.state == LoopState.RED_FIX:
                    # transition() is the SOLE authority on retry exhaustion.
                    # No pre-check here — single responsibility, no dual-gate.
                    await on_fix(ctx)
                    # on_fix returns None by contract; no return-value check needed
                    self.transition(ctx)  # RED:FIX -> GENERATE | FAILED
                    if self.is_terminal(ctx):
                        break

                else:
                    self._force_failed(ctx, f"unhandled state: {ctx.state}")
                    break

            except InvalidTransitionError:
                # Must re-raise: InvalidTransitionError(ValueError) would
                # otherwise be swallowed by the broad handler below,
                # silently masking FSM contract violations as FAILED states.
                raise
            except ValueError:
                # Callback contract violations (wrong return type, empty string, etc.)
                # must propagate — they are programming errors, not runtime failures.
                raise
            except asyncio.CancelledError:
                raise  # never swallow cooperative cancellation
            except Exception as exc:
                logger.exception(
                    "LoopController error in state %s: %s", ctx.state, exc
                )
                self._force_failed(ctx, f"exception: {repr(exc)[:200]}")
                break

        return ctx
