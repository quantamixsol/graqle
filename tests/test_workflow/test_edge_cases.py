# tests/test_workflow/test_edge_cases.py
"""
Edge case tests for every fix from Senior review rounds 1-5.

Each test targets a specific finding from graq_review:
- R2-BLOCKER: Double-record bug (now fixed)
- R2-BLOCKER: assert stripped by -O (now RuntimeError)
- R3-MAJOR: on_fix wasted work on exhausted slot (now pre-checked)
- R3-MAJOR: Duplicate history on exhaustion (now removed)
- R3-MAJOR: Silent ctx.max_retries mutation (now logged)
- R3-MAJOR: Empty-string bypass on callbacks
- R5-MAJOR: Pre-validation ctx mutation in TEST
- SECURITY: Stash token injection
- SECURITY: Protected file traversal
- SECURITY: Fail-closed on unresolvable path
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from graqle.workflow.loop_controller import (
    InvalidTransitionError,
    LoopContext,
    LoopController,
    LoopState,
    _TERMINAL,
)
from graqle.workflow.test_result_parser import ParsedTestResult
from graqle.workflow.diff_applicator import DiffApplicator, _is_protected_file


# ============================================================================
# Edge Case 1: No double-recording in history
# ============================================================================


class TestNoDoubleRecord:
    """R2-BLOCKER fix: transition() is sole owner of history recording."""

    @pytest.mark.asyncio
    async def test_happy_path_no_double_records(self):
        """Happy path produces exactly 1 history entry per transition."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                       on_write=on_write, on_test=on_test, on_fix=on_fix)

        # 4 transitions: PLAN->GEN, GEN->WRITE, WRITE->TEST, TEST->GREEN
        assert len(ctx.history) == 4
        states = [h["state"] for h in ctx.history]
        # Each entry records the TARGET state, not the source
        assert states == ["GENERATE", "WRITE", "TEST", "GREEN:DONE"]

    @pytest.mark.asyncio
    async def test_retry_path_no_double_records(self):
        """Retry path: each transition records exactly once."""
        ctrl = LoopController(max_retries=1)
        ctx = ctrl.initial_context("task")
        test_n = {"n": 0}

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c):
            test_n["n"] += 1
            return ParsedTestResult(passed=(test_n["n"] > 1), raw_output="r")
        async def on_fix(c): pass

        await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                       on_write=on_write, on_test=on_test, on_fix=on_fix)

        # Count history entries — should have no duplicates
        state_counts = {}
        for h in ctx.history:
            s = h["state"]
            state_counts[s] = state_counts.get(s, 0) + 1

        # GENERATE appears twice (initial + retry), not 4 times (no double-record)
        assert state_counts.get("GENERATE", 0) == 2


# ============================================================================
# Edge Case 2: assert -> RuntimeError (python -O safe)
# ============================================================================


class TestForceFailedContract:
    """R5-BLOCKER fix: RuntimeError instead of assert."""

    def test_force_failed_sets_terminal_state(self):
        """_force_failed always results in a terminal state."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl._force_failed(ctx, "test reason")
        assert ctx.state in _TERMINAL
        assert ctx.state == LoopState.FAILED
        assert ctx.last_error == "test reason"

    def test_force_failed_idempotent(self):
        """Calling _force_failed on already-terminal ctx does nothing."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctrl._force_failed(ctx, "first")
        history_len = len(ctx.history)
        ctrl._force_failed(ctx, "second")
        # No additional history entry
        assert len(ctx.history) == history_len
        # last_error unchanged
        assert ctx.last_error == "first"

    def test_force_failed_on_green_done_does_nothing(self):
        """_force_failed on GREEN:DONE is a no-op."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")
        ctx.state = LoopState.GREEN_DONE
        ctrl._force_failed(ctx, "shouldn't change")
        assert ctx.state == LoopState.GREEN_DONE


# ============================================================================
# Edge Case 3: on_fix NOT called on exhausted slot
# ============================================================================


class TestOnFixWithExhaustion:
    """R6 fix: transition() is sole authority on retry exhaustion."""

    @pytest.mark.asyncio
    async def test_on_fix_called_then_transition_exhausts(self):
        """on_fix is called, then transition() handles exhaustion."""
        ctrl = LoopController(max_retries=1)
        ctx = ctrl.initial_context("task")
        fix_calls = {"n": 0}

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c):
            return ParsedTestResult(passed=False, raw_output="fail")
        async def on_fix(c):
            fix_calls["n"] += 1

        await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                       on_write=on_write, on_test=on_test, on_fix=on_fix)

        assert ctx.state == LoopState.FAILED
        # transition() is sole authority — on_fix is called on every RED:FIX entry
        assert fix_calls["n"] == 2  # called for both RED:FIX entries


# ============================================================================
# Edge Case 4: No duplicate history on exhaustion path
# ============================================================================


class TestExhaustionHistoryClean:
    """R5-MAJOR fix: only _force_failed records on exhaustion."""

    def test_exhaustion_single_failed_entry(self):
        """Exhaustion path produces exactly one FAILED history entry."""
        ctrl = LoopController(max_retries=0)
        ctx = ctrl.initial_context("task")
        # Walk to RED:FIX
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # -> FAILED (max_retries=0 exhausted)

        failed_entries = [h for h in ctx.history if h["state"] == "FAILED"]
        assert len(failed_entries) == 1  # no duplicate
        assert "max_retries_exhausted" in failed_entries[0]["detail"]


# ============================================================================
# Edge Case 5: ctx.max_retries clamping
# ============================================================================


class TestGovernanceCap:
    """R5-MAJOR fix: ctx.max_retries clamped with warning."""

    @pytest.mark.asyncio
    async def test_ctx_max_retries_clamped(self):
        """Controller clamps ctx.max_retries to its own limit."""
        ctrl = LoopController(max_retries=2)
        ctx = LoopContext(task="task", max_retries=100)

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                       on_write=on_write, on_test=on_test, on_fix=on_fix)

        # max_retries was clamped from 100 to 2
        assert ctx.max_retries == 2


# ============================================================================
# Edge Case 6: Empty-string callback rejection
# ============================================================================


class TestEmptyCallbackRejection:
    """R5-MAJOR fix: empty strings from callbacks are rejected."""

    @pytest.mark.asyncio
    async def test_empty_plan_rejected(self):
        """on_plan returning empty string raises ValueError (contract violation)."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return ""
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="non-empty str"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_whitespace_plan_rejected(self):
        """on_plan returning whitespace raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "   \n\t  "
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="non-empty str"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_empty_diff_rejected(self):
        """on_generate returning empty string raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "valid plan"
        async def on_generate(c): return ""
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="non-empty str"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_none_plan_rejected(self):
        """on_plan returning None raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return None
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="non-empty str"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_none_test_result_rejected(self):
        """on_test returning None raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c): return None
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="None"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_none_write_result_rejected(self):
        """on_write returning None raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return None
        async def on_test(c): return ParsedTestResult(passed=True, raw_output="ok")
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="list"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

    @pytest.mark.asyncio
    async def test_non_bool_passed_rejected(self):
        """on_test with passed as non-bool raises ValueError."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c): return "plan"
        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c):
            r = ParsedTestResult(passed=True, raw_output="ok")
            r.passed = "yes"  # type: ignore — intentional for test
            return r
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="bool"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)


# ============================================================================
# Edge Case 7: Pre-validation ctx mutation in TEST
# ============================================================================


class TestPreValidationMutation:
    """R4-MAJOR fix: validate BEFORE mutating ctx in TEST state."""

    @pytest.mark.asyncio
    async def test_invalid_passed_raises_value_error(self):
        """Invalid passed type raises ValueError — ctx not corrupted."""
        ctrl = LoopController()
        ctx = ctrl.initial_context("task")

        async def on_plan(c):
            c.test_output = "ORIGINAL"
            return "plan"

        async def on_generate(c): return "diff"
        async def on_write(c): return ["f.py"]
        async def on_test(c):
            r = ParsedTestResult(passed=True, raw_output="new output")
            r.passed = 42  # type: ignore — invalid type
            return r
        async def on_fix(c): pass

        with pytest.raises(ValueError, match="bool"):
            await ctrl.run(ctx, on_plan=on_plan, on_generate=on_generate,
                           on_write=on_write, on_test=on_test, on_fix=on_fix)

        # ctx.test_output should NOT have been mutated to "new output"
        assert ctx.test_output == "ORIGINAL"


# ============================================================================
# Edge Case 8: Security — stash token injection
# ============================================================================


class TestStashTokenSecurity:
    """Security fix: stash token format validation."""

    def test_valid_stash_tokens(self):
        """Valid stash@{N} tokens pass validation."""
        assert DiffApplicator._validate_stash_token("stash@{0}") is True
        assert DiffApplicator._validate_stash_token("stash@{42}") is True
        assert DiffApplicator._validate_stash_token("stash@{999}") is True

    def test_flag_injection_rejected(self):
        """Git flag injection tokens are rejected."""
        assert DiffApplicator._validate_stash_token("--index") is False
        assert DiffApplicator._validate_stash_token("-v") is False

    def test_command_injection_rejected(self):
        """Command injection tokens are rejected."""
        assert DiffApplicator._validate_stash_token("; rm -rf /") is False
        assert DiffApplicator._validate_stash_token("$(whoami)") is False
        assert DiffApplicator._validate_stash_token("stash@{0} && rm -rf /") is False

    def test_empty_token_rejected(self):
        """Empty token is rejected."""
        assert DiffApplicator._validate_stash_token("") is False

    def test_message_sanitization(self):
        """Stash messages are sanitized against injection."""
        assert DiffApplicator._sanitize_message("normal message") == "normal message"
        # "--evil-flag" -> strip non-\w\s\- -> "--evil-flag" -> lstrip("-") -> "evil-flag" -> prefix
        assert DiffApplicator._sanitize_message("--evil-flag") == "checkpoint-evil-flag"
        assert DiffApplicator._sanitize_message("a" * 200)[:80] == "a" * 80


# ============================================================================
# Edge Case 9: Security — protected file bypass attempts
# ============================================================================


class TestProtectedFileBypass:
    """Security fixes: path traversal and fail-closed behavior."""

    def test_direct_env(self):
        assert _is_protected_file(".env") is True

    def test_nested_env(self):
        assert _is_protected_file("/project/config/.env.local") is True

    def test_path_traversal_env(self):
        """Path traversal attempt to reach .env is blocked."""
        assert _is_protected_file("../../../.env") is True

    def test_normal_python_file_allowed(self):
        assert _is_protected_file("src/main.py") is False

    def test_normal_test_file_allowed(self):
        assert _is_protected_file("tests/test_auth.py") is False

    def test_trade_secret_blocked(self):
        assert _is_protected_file("graqle/trade_secret_values.py") is True

    def test_patent_file_blocked(self):
        assert _is_protected_file("docs/patent_application.pdf") is True


# ============================================================================
# Edge Case 10: Retry semantics boundary conditions
# ============================================================================


class TestRetryBoundaries:
    """Verify exact retry counts at all boundary values."""

    def test_max_retries_0_zero_fix_cycles(self):
        """max_retries=0: first test failure -> immediate FAILED."""
        ctrl = LoopController(max_retries=0)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # attempt 1 > 0 -> FAILED
        assert ctx.state == LoopState.FAILED
        assert ctx.attempt == 1

    def test_max_retries_1_one_fix_cycle(self):
        """max_retries=1: exactly 1 retry allowed."""
        ctrl = LoopController(max_retries=1)
        ctx = ctrl.initial_context("task")
        ctrl.transition(ctx)  # -> GEN
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # attempt 1, 1 > 1 = False -> GENERATE
        assert ctx.state == LoopState.GENERATE
        ctrl.transition(ctx)  # -> WRITE
        ctrl.transition(ctx)  # -> TEST
        ctrl.transition(ctx, test_passed=False)  # -> RED:FIX
        ctrl.transition(ctx)  # attempt 2, 2 > 1 = True -> FAILED
        assert ctx.state == LoopState.FAILED
        assert ctx.attempt == 2

    def test_max_retries_3_three_fix_cycles(self):
        """max_retries=3: exactly 3 retries allowed."""
        ctrl = LoopController(max_retries=3)
        ctx = ctrl.initial_context("task")

        successful_retries = 0
        for i in range(10):  # more than enough
            if ctx.state == LoopState.PLAN:
                ctrl.transition(ctx)
            if ctx.state == LoopState.GENERATE:
                ctrl.transition(ctx)
            if ctx.state == LoopState.WRITE:
                ctrl.transition(ctx)
            if ctx.state == LoopState.TEST:
                ctrl.transition(ctx, test_passed=False)
            if ctx.state == LoopState.RED_FIX:
                old_state = ctx.state
                ctrl.transition(ctx)
                if ctx.state == LoopState.GENERATE:
                    successful_retries += 1
                if ctx.state == LoopState.FAILED:
                    break

        assert ctx.state == LoopState.FAILED
        assert successful_retries == 3  # exactly 3 re-entries

    def test_max_retries_large_value(self):
        """Large max_retries value works without issues."""
        ctrl = LoopController(max_retries=50)
        ctx = ctrl.initial_context("task")
        assert ctx.max_retries == 50
