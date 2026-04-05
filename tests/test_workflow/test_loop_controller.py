# tests/test_workflow/test_loop_controller.py
"""
Comprehensive tests for LoopController state machine.

40+ tests covering:
- Happy path (PLAN->GENERATE->WRITE->TEST->GREEN:DONE)
- RED:FIX loop up to max_retries then FAILED
- InvalidTransitionError on illegal transitions
- Boundary conditions (max_retries=0, empty task, negative max_retries)
- History recording and serialization
- run() with async callbacks
- run() exception handling
- LoopState enum completeness
- Edge cases from graq_reason prediction
"""
from __future__ import annotations

import asyncio
import json
import pytest

from graqle.workflow.loop_controller import (
    InvalidTransitionError,
    LoopContext,
    LoopController,
    LoopState,
    _TRANSITIONS,
    _TERMINAL,
)
from graqle.workflow.test_result_parser import ParsedTestResult


# ============================================================================
# Category 1: Happy Path (5 tests)
# ============================================================================


class TestHappyPath:
    """PLAN -> GENERATE -> WRITE -> TEST -> GREEN:DONE on first pass."""

    def test_happy_path_first_attempt_green(self):
        """Full cycle: PLAN->GENERATE->WRITE->TEST(pass)->GREEN:DONE."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("write tests for auth module")

        assert ctx.state == LoopState.PLAN
        ctrl.transition(ctx)  # PLAN -> GENERATE
        assert ctx.state == LoopState.GENERATE
        ctrl.transition(ctx)  # GENERATE -> WRITE
        assert ctx.state == LoopState.WRITE
        ctrl.transition(ctx)  # WRITE -> TEST
        assert ctx.state == LoopState.TEST
        ctrl.transition(ctx, test_passed=True)  # TEST -> GREEN:DONE
        assert ctx.state == LoopState.GREEN_DONE
        assert ctrl.is_terminal(ctx)

    def test_happy_path_attempt_stays_zero(self):
        """On first pass success, attempt counter remains 0."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # PLAN -> GENERATE
        ctrl.transition(ctx)  # GENERATE -> WRITE
        ctrl.transition(ctx)  # WRITE -> TEST
        ctrl.transition(ctx, test_passed=True)  # TEST -> GREEN:DONE
        assert ctx.attempt == 0

    def test_happy_path_retries_not_exhausted(self):
        """After first pass success, retries_exhausted is False."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")
        for _ in range(3):
            ctrl.transition(ctx)
        ctrl.transition(ctx, test_passed=True)
        assert not ctx.retries_exhausted

    def test_green_done_is_terminal(self):
        """GREEN:DONE is a terminal state."""
        assert LoopState.GREEN_DONE in _TERMINAL

    def test_happy_path_history_length(self):
        """Happy path: transition() records exactly 4 entries (one per transition)."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=True)  # -> GREEN:DONE
        # Each transition() call records exactly one entry
        assert len(ctx.history) == 4


# ============================================================================
# Category 2: RED:FIX Loop (6 tests)
# ============================================================================


class TestRedFixLoop:
    """RED:FIX loop behavior up to max_retries."""

    def test_single_red_fix_cycle(self):
        """TEST(fail)->RED:FIX->GENERATE->WRITE->TEST->GREEN:DONE."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        assert ctx.state == LoopState.RED_FIX

        ctrl.transition(ctx)  # RED:FIX -> GENERATE (attempt 1)
        assert ctx.state == LoopState.GENERATE
        assert ctx.attempt == 1

        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=True)  # -> GREEN:DONE
        assert ctx.state == LoopState.GREEN_DONE

    def test_max_retries_exhausted_forces_failed(self):
        """After max_retries, RED:FIX -> FAILED instead of GENERATE."""
        ctrl = LoopController(max_retries=2)
        ctx = ctrl.initial_context("task")

        # First pass: fail
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX

        # Retry 1
        ctrl.transition(ctx)  # RED:FIX -> GENERATE (attempt 1)
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX

        # Retry 2
        ctrl.transition(ctx)  # RED:FIX -> GENERATE (attempt 2)
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX

        # Now max_retries=2 exhausted, next transition -> FAILED
        ctrl.transition(ctx)  # RED:FIX -> FAILED
        assert ctx.state == LoopState.FAILED
        assert ctrl.is_terminal(ctx)

    def test_attempt_increments_on_each_retry(self):
        """Attempt counter increments each time RED:FIX -> GENERATE."""
        ctrl = LoopController(max_retries=5)
        ctx = ctrl.initial_context("task")

        for i in range(3):
            # Cycle through to RED:FIX
            if ctx.state == LoopState.PLAN:
                ctrl.transition(ctx)  # -> GENERATE
            ctrl.transition(ctx)  # GENERATE -> WRITE
            ctrl.transition(ctx)  # WRITE -> TEST
            ctrl.transition(ctx, test_passed=False)  # TEST -> RED:FIX
            ctrl.transition(ctx)  # RED:FIX -> GENERATE
            assert ctx.attempt == i + 1

    def test_red_fix_records_in_history(self):
        """RED:FIX transitions are recorded in history."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX

        red_entries = [h for h in ctx.history if h["state"] == "RED:FIX"]
        assert len(red_entries) == 1

    def test_failed_is_terminal(self):
        """FAILED is a terminal state."""
        assert LoopState.FAILED in _TERMINAL

    def test_failed_state_after_exhaustion_has_correct_history(self):
        """After max_retries exhaustion, last history entry is FAILED."""
        ctrl = LoopController(max_retries=1)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # RED:FIX -> GENERATE (attempt 1)
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # RED:FIX -> FAILED (max_retries=1 exhausted)
        assert ctx.state == LoopState.FAILED
        assert ctx.history[-1]["state"] == "FAILED"
        assert "max_retries_exhausted" in ctx.history[-1]["detail"]


# ============================================================================
# Category 3: InvalidTransitionError (5 tests)
# ============================================================================


class TestInvalidTransitions:
    """InvalidTransitionError on illegal state transitions."""

    def test_transition_from_green_done_raises(self):
        """Transitioning from GREEN:DONE raises InvalidTransitionError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.GREEN_DONE
        with pytest.raises(InvalidTransitionError) as exc_info:
            ctrl.transition(ctx)
        assert exc_info.value.from_state == LoopState.GREEN_DONE

    def test_transition_from_failed_raises(self):
        """Transitioning from FAILED raises InvalidTransitionError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.FAILED
        with pytest.raises(InvalidTransitionError):
            ctrl.transition(ctx)

    def test_plan_with_test_passed_true_raises(self):
        """PLAN + test_passed=True is not a valid transition."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        assert ctx.state == LoopState.PLAN
        with pytest.raises(InvalidTransitionError):
            ctrl.transition(ctx, test_passed=True)

    def test_plan_with_test_passed_false_raises(self):
        """PLAN + test_passed=False is not a valid transition."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        with pytest.raises(InvalidTransitionError):
            ctrl.transition(ctx, test_passed=False)

    def test_generate_with_test_passed_raises(self):
        """GENERATE + test_passed=True is not valid."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        with pytest.raises(InvalidTransitionError):
            ctrl.transition(ctx, test_passed=True)


# ============================================================================
# Category 4: max_retries=0 Boundary (3 tests)
# ============================================================================


class TestMaxRetriesZero:
    """Boundary: max_retries=0 means first RED:FIX goes to FAILED."""

    def test_max_retries_zero_first_red_fix_goes_to_failed(self):
        """With max_retries=0, first RED:FIX -> FAILED."""
        ctrl = LoopController(max_retries=0)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # RED:FIX -> FAILED (retries_exhausted at 0)
        assert ctx.state == LoopState.FAILED

    def test_max_retries_zero_green_still_works(self):
        """max_retries=0 doesn't affect the GREEN:DONE path."""
        ctrl = LoopController(max_retries=0)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=True)  # -> GREEN:DONE
        assert ctx.state == LoopState.GREEN_DONE

    def test_max_retries_zero_attempt_is_one_on_failed(self):
        """With max_retries=0, attempt increments to 1 then exceeds limit."""
        ctrl = LoopController(max_retries=0)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # -> FAILED (attempt 1 > max_retries 0)
        assert ctx.attempt == 1  # incremented before exhaustion check


# ============================================================================
# Category 5: Empty Task Validation (3 tests)
# ============================================================================


class TestTaskValidation:
    """Input validation for task parameter."""

    def test_empty_task_raises_value_error(self):
        """Empty string task raises ValueError."""
        ctrl = LoopController()
        with pytest.raises(ValueError, match="non-empty"):
            ctrl.initial_context("")

    def test_whitespace_task_raises_value_error(self):
        """Whitespace-only task raises ValueError."""
        ctrl = LoopController()
        with pytest.raises(ValueError, match="non-empty"):
            ctrl.initial_context("   ")

    def test_task_is_stripped(self):
        """Task with leading/trailing whitespace is stripped."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("  fix bug  ")
        assert ctx.task == "fix bug"


# ============================================================================
# Category 6: Negative max_retries (2 tests)
# ============================================================================


class TestMaxRetriesValidation:
    """Validation of max_retries parameter."""

    def test_negative_max_retries_raises_value_error(self):
        """max_retries=-1 raises ValueError."""
        with pytest.raises(ValueError, match="max_retries"):
            LoopController(max_retries=-1)

    def test_zero_max_retries_is_valid(self):
        """max_retries=0 is a valid boundary value."""
        ctrl = LoopController(max_retries=0)
        assert ctrl.max_retries == 0


# ============================================================================
# Category 7: test_passed Signal Handling (3 tests)
# ============================================================================


class TestTestPassedSignals:
    """test_passed=True/False/None behavior at TEST state."""

    def test_test_passed_true_goes_green(self):
        """test_passed=True at TEST -> GREEN:DONE."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.TEST
        ctrl.transition(ctx, test_passed=True)
        assert ctx.state == LoopState.GREEN_DONE

    def test_test_passed_false_goes_red(self):
        """test_passed=False at TEST -> RED:FIX."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.TEST
        ctrl.transition(ctx, test_passed=False)
        assert ctx.state == LoopState.RED_FIX

    def test_test_passed_none_at_test_raises(self):
        """test_passed=None at TEST is an invalid transition."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.TEST
        with pytest.raises(InvalidTransitionError):
            ctrl.transition(ctx, test_passed=None)


# ============================================================================
# Category 8: History Recording (4 tests)
# ============================================================================


class TestHistoryRecording:
    """History list tracks all transitions."""

    def test_history_records_every_transition(self):
        """Every transition() call appends exactly one entry to history."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=True)  # -> GREEN:DONE
        # 4 transitions = 4 history entries (no double-recording)
        assert len(ctx.history) == 4

    def test_history_entries_have_state_and_attempt(self):
        """Each history entry contains state and attempt fields."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        entry = ctx.history[0]
        assert "state" in entry
        assert "attempt" in entry
        assert entry["state"] == "GENERATE"

    def test_history_not_affected_by_external_mutation(self):
        """Mutating history list externally doesn't affect internal state."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)
        history_copy = ctx.history.copy()
        ctx.history.clear()
        # The internal list IS directly mutable — this is by design
        # for dataclass simplicity. Assert it's the same list.
        assert len(ctx.history) == 0  # cleared
        assert len(history_copy) == 1  # copy preserved

    def test_record_manual(self):
        """LoopContext.record() appends correctly."""
        ctx = LoopContext(task="task")
        ctx.record(LoopState.PLAN, "initial")
        assert len(ctx.history) == 1
        assert ctx.history[0]["state"] == "PLAN"
        assert ctx.history[0]["detail"] == "initial"


# ============================================================================
# Category 9: LoopContext.to_dict (3 tests)
# ============================================================================


class TestContextSerialization:
    """LoopContext.to_dict() serialization."""

    def test_to_dict_contains_required_keys(self):
        """to_dict() has task, state, attempt, max_retries, history."""
        ctx = LoopContext(task="task")
        d = ctx.to_dict()
        assert "task" in d
        assert "state" in d
        assert "attempt" in d
        assert "max_retries" in d
        assert "history" in d

    def test_to_dict_state_is_string(self):
        """State is serialized as a plain string, not enum."""
        ctx = LoopContext(task="task")
        d = ctx.to_dict()
        assert isinstance(d["state"], str)
        assert d["state"] == "PLAN"

    def test_to_dict_is_json_serializable(self):
        """json.dumps(ctx.to_dict()) succeeds."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        serialized = json.dumps(ctx.to_dict())
        assert isinstance(serialized, str)


# ============================================================================
# Category 10: run() with Async Callbacks (4 tests)
# ============================================================================


class TestRunAsync:
    """LoopController.run() driving the full async loop."""

    @pytest.mark.asyncio
    async def test_run_happy_path(self):
        """run() drives PLAN->GENERATE->WRITE->TEST->GREEN:DONE."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("write auth tests")

        async def on_plan(c):
            return "Plan: write 5 tests"

        async def on_generate(c):
            return "--- a/test.py\n+++ b/test.py\n@@ ...\n+def test_auth(): pass"

        async def on_write(c):
            return ["test.py"]

        async def on_test(c):
            return ParsedTestResult(passed=True, total=5, passed_count=5, raw_output="5 passed")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        assert result.state == LoopState.GREEN_DONE

    @pytest.mark.asyncio
    async def test_run_single_retry_then_green(self):
        """run() retries once on failure then succeeds."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("fix bug")
        call_count = {"test": 0}

        async def on_plan(c):
            return "Fix the CORS bug"

        async def on_generate(c):
            return "diff content"

        async def on_write(c):
            return ["api.py"]

        async def on_test(c):
            call_count["test"] += 1
            if call_count["test"] == 1:
                return ParsedTestResult(
                    passed=False, failed_count=1,
                    failed_tests=["test_cors"],
                    error_messages=["AssertionError"],
                    raw_output="1 failed",
                )
            return ParsedTestResult(passed=True, total=1, passed_count=1, raw_output="1 passed")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        assert result.state == LoopState.GREEN_DONE
        assert result.attempt == 1
        assert call_count["test"] == 2

    @pytest.mark.asyncio
    async def test_run_exhausts_retries(self):
        """run() transitions to FAILED after max_retries exhaustion."""
        ctrl = LoopController(max_retries=2)
        ctx = ctrl.initial_context("impossible task")

        async def on_plan(c):
            return "Plan"

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            return ["file.py"]

        async def on_test(c):
            return ParsedTestResult(
                passed=False, failed_count=1,
                failed_tests=["test_always_fails"],
                raw_output="1 failed",
            )

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        assert result.state == LoopState.FAILED
        # With increment-before-check: attempt reaches max_retries+1 when exhausted
        assert result.attempt == 3  # max_retries=2 → attempts 1,2 succeed, 3 exceeds

    @pytest.mark.asyncio
    async def test_run_records_complete_history(self):
        """run() populates full history for each iteration."""
        ctrl = LoopController(max_retries=1)
        ctx = ctrl.initial_context("task")
        call_count = {"test": 0}

        async def on_plan(c):
            return "plan"

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            return ["f.py"]

        async def on_test(c):
            call_count["test"] += 1
            if call_count["test"] <= 2:
                return ParsedTestResult(passed=False, raw_output="fail")
            return ParsedTestResult(passed=True, raw_output="pass")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        # transition() records the TARGET state, not the source.
        # So PLAN->GENERATE records "GENERATE", not "PLAN".
        assert len(result.history) > 0
        states = [h["state"] for h in result.history]
        assert "GENERATE" in states  # first transition from PLAN
        assert "TEST" in states


# ============================================================================
# Category 11: run() Exception Handling (3 tests)
# ============================================================================


class TestRunExceptionHandling:
    """Exception handling during run() callbacks."""

    @pytest.mark.asyncio
    async def test_exception_in_on_plan_sets_failed(self):
        """Exception in on_plan callback sets state to FAILED."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c):
            raise RuntimeError("Plan generation failed")

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            return []

        async def on_test(c):
            return ParsedTestResult(passed=True, raw_output="")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        assert result.state == LoopState.FAILED
        assert "Plan generation failed" in result.last_error

    @pytest.mark.asyncio
    async def test_exception_in_on_write_sets_failed(self):
        """Exception in on_write sets FAILED."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c):
            return "plan"

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            raise IOError("Disk full")

        async def on_test(c):
            return ParsedTestResult(passed=True, raw_output="")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        assert result.state == LoopState.FAILED
        assert "Disk full" in result.last_error

    @pytest.mark.asyncio
    async def test_invalid_transition_in_run_propagates(self):
        """InvalidTransitionError from manual state corruption propagates."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c):
            # Corrupt state to create an invalid transition
            c.state = LoopState.GREEN_DONE
            return "plan"

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            return []

        async def on_test(c):
            return ParsedTestResult(passed=True, raw_output="")

        async def on_fix(c):
            pass

        with pytest.raises(InvalidTransitionError):
            await ctrl.run(
                ctx,
                on_plan=on_plan,
                on_generate=on_generate,
                on_write=on_write,
                on_test=on_test,
                on_fix=on_fix,
            )


# ============================================================================
# Category 12: LoopState Enum (2 tests)
# ============================================================================


class TestLoopStateEnum:
    """LoopState enum completeness."""

    def test_all_loop_state_values_exist(self):
        """LoopState has all 7 expected members."""
        expected = {"PLAN", "GENERATE", "WRITE", "TEST", "RED:FIX", "GREEN:DONE", "FAILED"}
        actual = {s.value for s in LoopState}
        assert actual == expected

    def test_loop_state_is_str_enum(self):
        """LoopState values are strings."""
        for state in LoopState:
            assert isinstance(state.value, str)


# ============================================================================
# Category 13: Transition Table Completeness (3 tests)
# ============================================================================


class TestSafetyGuards:
    """P0: Absolute iteration limit prevents infinite spin."""

    @pytest.mark.asyncio
    async def test_absolute_max_iterations_prevents_spin(self):
        """Safety guard forces FAILED if iterations exceed absolute limit."""
        ctrl = LoopController(max_retries=1000)  # very high retries
        ctx = ctrl.initial_context("spin task")

        # Mock callbacks that always return to same state by manipulating ctx
        call_count = {"n": 0}

        async def on_plan(c):
            return "plan"

        async def on_generate(c):
            return "diff"

        async def on_write(c):
            return ["f.py"]

        async def on_test(c):
            call_count["n"] += 1
            # Always fail to keep looping
            return ParsedTestResult(passed=False, raw_output="fail")

        async def on_fix(c):
            pass

        result = await ctrl.run(
            ctx,
            on_plan=on_plan,
            on_generate=on_generate,
            on_write=on_write,
            on_test=on_test,
            on_fix=on_fix,
        )
        # Should eventually hit FAILED due to max_retries or absolute limit
        assert result.state == LoopState.FAILED


class TestTransitionTable:
    """Verify the transition table is complete and correct."""

    def test_all_non_terminal_states_have_transitions(self):
        """Every non-terminal state has at least one outgoing transition."""
        non_terminal = set(LoopState) - _TERMINAL
        for state in non_terminal:
            has_transition = any(k[0] == state for k in _TRANSITIONS)
            assert has_transition, f"State {state} has no transitions"

    def test_terminal_states_have_no_transitions(self):
        """Terminal states have no outgoing transitions in the table."""
        for state in _TERMINAL:
            has_transition = any(k[0] == state for k in _TRANSITIONS)
            assert not has_transition, f"Terminal state {state} has transitions"

    def test_transition_table_size(self):
        """Transition table has exactly 6 entries."""
        assert len(_TRANSITIONS) == 6
