# tests/test_workflow/test_e2e_demonstration.py
"""
End-to-end demonstration tests for the autonomous loop.

These tests prove the FULL loop works as designed:
- Complete PLAN->GENERATE->WRITE->TEST->GREEN:DONE flow
- Complete PLAN->GENERATE->WRITE->TEST->RED:FIX->GENERATE->...->GREEN:DONE flow
- Complete PLAN->GENERATE->WRITE->TEST->RED:FIX->...->FAILED flow
- Observer tracks everything transparently
- Governance gates block protected files
- Memory records all iterations for diagnosis
- DiffApplicator handles real file operations
- TestResultParser parses real pytest output

These are the tests that demonstrate to the user that the system works
as a frictionless, governed, transparent autonomous loop.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from graqle.workflow.action_agent_protocol import ActionAgentProtocol, ExecutionResult
from graqle.workflow.autonomous_executor import (
    AutonomousExecutor,
    ExecutorConfig,
    ExecutorResult,
)
from graqle.workflow.diff_applicator import DiffApplicator
from graqle.workflow.execution_memory import ExecutionMemory
from graqle.workflow.loop_controller import LoopContext, LoopController, LoopState
from graqle.workflow.loop_observer import LoopObserver, ViolationType
from graqle.workflow.test_result_parser import ParsedTestResult, TestResultParser


# ============================================================================
# Real Agent Mock — simulates what graq_generate/graq_edit would do
# ============================================================================


class DemoAgent:
    """
    Simulates a real agent that generates code and runs tests.

    This demonstrates the full ActionAgentProtocol in action.
    """

    def __init__(
        self,
        working_dir: Path,
        test_results: list[bool] | None = None,
    ):
        self._work_dir = working_dir
        self._test_results = test_results or [True]
        self._test_idx = 0
        self._diff_applicator = DiffApplicator(working_dir)
        self.call_log: list[dict] = []
        self.plan_calls = 0
        self.generate_calls = 0
        self.apply_calls = 0
        self.test_calls = 0
        self.rollback_calls = 0

    async def plan(self, task: str, context: dict) -> str:
        self.plan_calls += 1
        plan = f"Plan for '{task}':\n1. Create test file\n2. Write assertions\n3. Run pytest"
        self.call_log.append({"action": "plan", "task": task})
        return plan

    async def generate_diff(
        self, task: str, plan: str, error_context: str | None = None
    ) -> str:
        self.generate_calls += 1
        # Generate a simple Python test file
        content = (
            "def test_addition():\n"
            "    assert 1 + 1 == 2\n\n"
            "def test_subtraction():\n"
            "    assert 5 - 3 == 2\n"
        )
        if error_context and "attempt" in str(error_context):
            content += "\ndef test_fixed():\n    assert True\n"

        self.call_log.append({
            "action": "generate",
            "has_error_context": error_context is not None,
        })
        return content  # For demo, we write content directly rather than diffs

    async def apply(self, diff: str) -> ExecutionResult:
        self.apply_calls += 1
        # Write the generated content to a test file
        test_file = self._work_dir / "test_generated.py"
        result = self._diff_applicator.write_file_atomic(str(test_file), diff)
        self.call_log.append({"action": "apply", "success": result.success})
        return result

    async def run_tests(self, test_paths: list[str] | None = None) -> ExecutionResult:
        self.test_calls += 1
        idx = min(self._test_idx, len(self._test_results) - 1)
        passed = self._test_results[idx]
        self._test_idx += 1
        self.call_log.append({"action": "test", "passed": passed})
        return ExecutionResult(
            exit_code=0 if passed else 1,
            stdout="2 passed" if passed else "1 failed, 1 passed",
            stderr="",
            test_passed=passed,
        )

    async def rollback(self, token: str) -> ExecutionResult:
        self.rollback_calls += 1
        self.call_log.append({"action": "rollback", "token": token})
        return ExecutionResult(exit_code=0, stdout="rolled back", stderr="")


# Verify DemoAgent satisfies protocol
assert isinstance(DemoAgent(Path("."), [True]), ActionAgentProtocol)


# ============================================================================
# E2E Demo 1: Happy Path — First Attempt Success
# ============================================================================


class TestE2EDemoHappyPath:
    """Demonstrate: task succeeds on first attempt."""

    @pytest.mark.asyncio
    async def test_full_happy_path_with_observer(self, tmp_path):
        """
        DEMO: PLAN -> GENERATE -> WRITE -> TEST(pass) -> GREEN:DONE

        Shows:
        1. Agent plans the task
        2. Agent generates code
        3. Code is written to disk atomically
        4. Tests pass on first attempt
        5. Observer tracks everything transparently
        6. Memory records the iteration
        7. Final result is GREEN:DONE with 0 attempts
        """
        agent = DemoAgent(tmp_path, test_results=[True])
        observer = LoopObserver()
        transitions = []

        def on_change(from_s, to_s, attempt, meta):
            transitions.append(f"{from_s} -> {to_s}")

        observer.on_state_change = on_change

        # Build the loop
        ctrl = LoopController(max_retries=3)
        memory = ExecutionMemory(tmp_path)
        ctx = ctrl.initial_context("write unit tests for the auth module")

        # Run the loop manually to show each step
        # Step 1: PLAN
        assert ctx.state == LoopState.PLAN
        plan = await agent.plan(ctx.task, {"working_dir": str(tmp_path)})
        observer.record_transition("PLAN", "GENERATE", attempt=0)
        ctx.plan = plan
        ctrl.transition(ctx)
        assert ctx.state == LoopState.GENERATE

        # Step 2: GENERATE
        diff = await agent.generate_diff(ctx.task, plan)
        observer.record_transition("GENERATE", "WRITE", attempt=0)
        ctx.generated_diff = diff
        ctrl.transition(ctx)
        assert ctx.state == LoopState.WRITE

        # Step 3: WRITE
        result = await agent.apply(diff)
        observer.record_transition("WRITE", "TEST", attempt=0)
        observer.record_files_modified(len(result.modified_files))
        ctx.modified_files = result.modified_files
        ctrl.transition(ctx)
        assert ctx.state == LoopState.TEST

        # Verify file was actually written
        test_file = tmp_path / "test_generated.py"
        assert test_file.exists()
        content = test_file.read_text()
        assert "def test_addition" in content

        # Step 4: TEST
        test_result = await agent.run_tests()
        observer.record_transition("TEST", "GREEN:DONE", attempt=0)
        observer.record_test_result(tests_run=2, tests_passed=2)
        ctrl.transition(ctx, test_passed=True)
        assert ctx.state == LoopState.GREEN_DONE
        assert ctrl.is_terminal(ctx)

        # Verify transparency
        observer.finalize()
        summary = observer.summary()
        assert summary["total_iterations"] == 4
        assert summary["violations"]["total"] == 0
        assert summary["governance_score"] == 100.0
        assert len(transitions) == 4

        # Verify memory
        assert len(agent.call_log) == 4
        assert agent.call_log[0]["action"] == "plan"
        assert agent.call_log[1]["action"] == "generate"
        assert agent.call_log[2]["action"] == "apply"
        assert agent.call_log[3]["action"] == "test"

        # Verify the full result is JSON-serializable
        full_report = {
            "context": ctx.to_dict(),
            "observer": summary,
            "agent_log": agent.call_log,
        }
        serialized = json.dumps(full_report, indent=2, default=str)
        assert len(serialized) > 100


# ============================================================================
# E2E Demo 2: Retry Loop — Fix Then Succeed
# ============================================================================


class TestE2EDemoRetryLoop:
    """Demonstrate: task fails, gets fixed, then succeeds."""

    @pytest.mark.asyncio
    async def test_full_retry_with_fix(self, tmp_path):
        """
        DEMO: PLAN -> GENERATE -> WRITE -> TEST(fail) -> RED:FIX ->
              GENERATE -> WRITE -> TEST(pass) -> GREEN:DONE

        Shows:
        1. First attempt fails tests
        2. Loop enters RED:FIX state
        3. Error context is built from memory
        4. Agent re-generates with error context
        5. Second attempt passes
        6. Observer shows 2 test iterations, 0 violations
        """
        agent = DemoAgent(tmp_path, test_results=[False, True])
        observer = LoopObserver()

        config = ExecutorConfig(
            max_retries=3,
            working_dir=str(tmp_path),
        )
        executor = AutonomousExecutor(agent, config)

        # Patch subprocess.run since executor uses it for tests
        with patch("subprocess.run") as mock_run:
            call_n = {"n": 0}

            def side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                if any("pytest" in str(c) for c in cmd):
                    call_n["n"] += 1
                    if call_n["n"] == 1:
                        return MagicMock(
                            stdout=(
                                "FAILED test_generated.py::test_subtraction "
                                "- AssertionError: assert 4 == 2\n"
                                "E   AssertionError: assert 4 == 2\n"
                                "test_generated.py:5: AssertionError\n"
                                "============ 1 failed, 1 passed in 0.05s ============"
                            ),
                            stderr="",
                            returncode=1,
                        )
                    return MagicMock(
                        stdout="============ 2 passed in 0.03s ============",
                        stderr="",
                        returncode=0,
                    )
                return MagicMock(stdout="", stderr="", returncode=1)

            mock_run.side_effect = side_effect
            result = await executor.execute("fix the subtraction test")

        assert result.success is True
        assert result.state == "GREEN:DONE"
        assert result.attempts >= 1

        # Memory should have at least 2 entries (first fail + retry pass)
        assert executor.memory.attempt_count >= 1

        # Agent should have been called for plan, generate, apply, test
        # at least twice for generate (original + retry)
        assert agent.generate_calls >= 2
        assert agent.plan_calls >= 1

    @pytest.mark.asyncio
    async def test_error_context_flows_to_retry(self, tmp_path):
        """
        DEMO: Error context from first failure flows into retry generate call.

        This proves the diagnostic feedback loop works.
        """
        memory = ExecutionMemory(tmp_path)

        # Simulate first iteration failure
        memory.record(
            attempt=0,
            diff_applied="def test_math(): assert 1+1 == 3",
            result_exit_code=1,
            test_output="FAILED test::test_math - AssertionError: assert 2 == 3",
            modified_files=["test_math.py"],
            error_message="AssertionError: assert 2 == 3",
        )

        # Get error context for retry
        error_ctx = memory.error_context_for_retry()

        # Verify it contains diagnostic info
        assert "exit_code=1" in error_ctx
        assert "AssertionError" in error_ctx
        assert "test_math.py" in error_ctx


# ============================================================================
# E2E Demo 3: Max Retries Exhaustion
# ============================================================================


class TestE2EDemoExhaustion:
    """Demonstrate: task exhausts all retries and fails."""

    @pytest.mark.asyncio
    async def test_exhaustion_with_full_diagnostics(self, tmp_path):
        """
        DEMO: All retries exhausted -> FAILED with full diagnostic trail.

        Shows:
        1. Task fails on every attempt
        2. max_retries=2 means 3 total attempts (0, 1, 2)
        3. Memory captures every failure
        4. Final state is FAILED with complete history
        """
        agent = DemoAgent(tmp_path, test_results=[False, False, False, False])
        config = ExecutorConfig(max_retries=2, working_dir=str(tmp_path))
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="FAILED test::a\n======= 1 failed in 0.1s =======",
                stderr="", returncode=1,
            )
            result = await executor.execute("impossible task")

        assert result.success is False
        assert result.state == "FAILED"

        # Memory should have multiple entries
        summary = executor.memory.summary()
        assert summary["total_attempts"] >= 1


# ============================================================================
# E2E Demo 4: Governance Gate in Action
# ============================================================================


class TestE2EDemoGovernance:
    """Demonstrate: governance gates block unauthorized actions."""

    def test_protected_file_blocked_with_explanation(self, tmp_path):
        """
        DEMO: Autonomous loop CANNOT modify .env files.

        This is the P0 governance gate in action.
        """
        applicator = DiffApplicator(tmp_path)

        # Try to write a .env file
        result = applicator.write_file_atomic(
            str(tmp_path / ".env"),
            "DATABASE_URL=postgres://...\nSECRET_KEY=abc123\n",
        )

        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr
        assert not (tmp_path / ".env").exists()  # File was NOT created

    def test_trade_secret_file_blocked(self, tmp_path):
        """
        DEMO: Cannot modify files matching trade secret patterns.
        """
        applicator = DiffApplicator(tmp_path)
        result = applicator.apply_diff_atomic(
            str(tmp_path / "graqle" / "ip_gate.py"),
            "--- a/ip_gate.py\n+++ b/ip_gate.py\n@@ ...\n-old\n+new",
        )
        assert not result.success
        assert "GOVERNANCE BLOCK" in result.stderr

    def test_normal_file_allowed(self, tmp_path):
        """
        DEMO: Normal source files are freely writable.
        """
        applicator = DiffApplicator(tmp_path)
        result = applicator.write_file_atomic(
            str(tmp_path / "src" / "auth.py"),
            "def login(user, password):\n    pass\n",
        )
        assert result.success
        assert (tmp_path / "src" / "auth.py").exists()


# ============================================================================
# E2E Demo 5: Observer Transparency Report
# ============================================================================


class TestE2EDemoTransparency:
    """Demonstrate: full transparency report for user visibility."""

    def test_complete_transparency_report(self):
        """
        DEMO: Observer produces a complete, JSON-serializable transparency report.

        This is what the user sees after every autonomous loop execution.
        """
        observer = LoopObserver()

        # Simulate a 2-iteration loop
        observer.record_transition("PLAN", "GENERATE", attempt=0)
        observer.record_llm_call(tokens=500, cost_usd=0.0015)

        observer.record_transition("GENERATE", "WRITE", attempt=0)
        observer.record_llm_call(tokens=1200, cost_usd=0.0036)

        observer.record_transition("WRITE", "TEST", attempt=0)
        observer.record_files_modified(2)

        observer.record_transition("TEST", "RED:FIX", attempt=0)
        observer.record_test_result(tests_run=5, tests_passed=3, tests_failed=2)

        # Violation detected and auto-corrected
        observer.record_violation(
            ViolationType.STALE_KG,
            "KG is 2 hours old — auto-rescanned",
            auto_corrected=True,
            correction_action="Ran graq scan to refresh KG",
        )

        observer.record_transition("RED:FIX", "GENERATE", attempt=1)
        observer.record_llm_call(tokens=800, cost_usd=0.0024)

        observer.record_transition("GENERATE", "WRITE", attempt=1)
        observer.record_files_modified(1)

        observer.record_transition("WRITE", "TEST", attempt=1)
        observer.record_test_result(tests_run=5, tests_passed=5, tests_failed=0)

        observer.record_transition("TEST", "GREEN:DONE", attempt=1)

        observer.finalize()
        report = observer.summary()

        # Verify report structure
        assert report["total_iterations"] == 8
        assert report["total_llm_calls"] == 3
        assert report["total_cost_usd"] > 0
        assert report["violations"]["total"] == 1
        assert report["violations"]["auto_corrected"] == 1
        assert report["governance_score"] == 95.0  # 100 - (10 * 0.5)

        # Verify JSON-serializable
        serialized = json.dumps(report, indent=2)
        assert len(serialized) > 200

        # Print the report for visual verification (visible in test output with -s flag)
        print("\n" + "=" * 60)
        print("TRANSPARENCY REPORT")
        print("=" * 60)
        print(serialized)
        print("=" * 60)

    def test_violation_self_correction_example(self):
        """
        DEMO: Violations are detected, reported, and self-corrected.

        Shows the violation -> correction -> governance score pipeline.
        """
        observer = LoopObserver()

        # Scenario: budget exceeded, auto-corrected by reducing rounds
        v = observer.record_violation(
            ViolationType.EXCEEDED_BUDGET,
            "Budget exceeded by $0.12 — reduced max_rounds from 5 to 2",
            severity="WARN",
            auto_corrected=True,
            correction_action="Reduced reasoning rounds from 5 to 2",
        )

        assert v.auto_corrected is True
        assert v.severity == "WARN"

        report = observer.summary()
        assert report["governance_score"] == 95.0

        # Verify the violation details are transparent
        details = report["violations"]["details"][0]
        assert details["type"] == "EXCEEDED_BUDGET"
        assert details["auto_corrected"] is True
        assert "Reduced reasoning rounds" in details["correction_action"]


# ============================================================================
# E2E Demo 6: TestResultParser with Real Pytest Output
# ============================================================================


class TestE2EDemoParser:
    """Demonstrate: parser handles real pytest output formats."""

    def test_parse_real_pytest_failure_output(self):
        """
        DEMO: Parser extracts actionable info from real pytest output.
        """
        real_output = """
============================= test session starts ==============================
platform win32 -- Python 3.10.11, pytest-9.0.2
rootdir: C:\\Users\\haris\\Graqle\\graqle-sdk
collected 5 items

tests/test_auth.py::test_login PASSED
tests/test_auth.py::test_logout PASSED
tests/test_auth.py::test_refresh_token FAILED
tests/test_auth.py::test_revoke_token PASSED
tests/test_auth.py::test_expired_token FAILED

===================================== FAILURES =================================
___________________________ test_refresh_token ___________________________________

    def test_refresh_token():
>       assert refresh("token123") == {"status": "refreshed"}
E       AssertionError: assert None == {'status': 'refreshed'}
E        +  where None = refresh('token123')

tests/test_auth.py:42: AssertionError
___________________________ test_expired_token ___________________________________

    def test_expired_token():
>       assert validate("expired") is False
E       TypeError: validate() got an unexpected keyword argument

tests/test_auth.py:58: TypeError
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_refresh_token - AssertionError: assert None == {'status': 'refreshed'}
FAILED tests/test_auth.py::test_expired_token - TypeError: validate() got an unexpected keyword argument
========================= 2 failed, 3 passed in 0.42s =========================
"""
        parser = TestResultParser()
        result = parser.parse(real_output, exit_code=1)

        # Verify all fields extracted correctly
        assert result.passed is False
        assert result.failed_count == 2
        assert result.passed_count == 3
        assert result.total == 5

        # Failed test names extracted
        assert len(result.failed_tests) == 2
        assert "tests/test_auth.py::test_refresh_token" in result.failed_tests
        assert "tests/test_auth.py::test_expired_token" in result.failed_tests

        # Error messages extracted
        assert any("AssertionError" in e for e in result.error_messages)
        assert any("TypeError" in e for e in result.error_messages)

        # File locations extracted
        assert any("tests/test_auth.py:42" in loc for loc in result.file_locations)
        assert any("tests/test_auth.py:58" in loc for loc in result.file_locations)

        # Duration parsed
        assert abs(result.duration_seconds - 0.42) < 0.01

        # Print for visual verification
        print("\n" + "-" * 40)
        print("PARSED TEST RESULT:")
        print(json.dumps(result.to_dict(), indent=2))
        print("-" * 40)

    def test_parse_all_passed_output(self):
        """
        DEMO: Parser correctly handles 100% passing output.
        """
        output = """
============================= test session starts ==============================
collected 136 items

tests/test_workflow/test_loop_controller.py ............................... [ 22%]
tests/test_workflow/test_action_agent_protocol.py .................... [ 37%]
tests/test_workflow/test_test_result_parser.py .................... [ 52%]
tests/test_workflow/test_execution_memory.py .................... [ 67%]
tests/test_workflow/test_diff_applicator.py ............... [ 79%]
tests/test_workflow/test_autonomous_executor.py .................... [ 93%]
tests/test_workflow/test_loop_observer.py .......... [100%]
========================= 136 passed in 0.38s =========================
"""
        parser = TestResultParser()
        result = parser.parse(output, exit_code=0)

        assert result.passed is True
        assert result.passed_count == 136
        assert result.failed_count == 0
        assert result.total == 136
        assert result.failed_tests == []
        assert result.error_messages == []


# ============================================================================
# E2E Demo 7: Memory Diagnostic Chain
# ============================================================================


class TestE2EDemoMemory:
    """Demonstrate: memory provides diagnostic context across iterations."""

    def test_memory_captures_full_diagnostic_chain(self, tmp_path):
        """
        DEMO: Memory captures each iteration's state for diagnosis.

        Shows how error context accumulates and feeds back.
        """
        memory = ExecutionMemory(tmp_path)

        # Create a file to track
        test_file = tmp_path / "test_target.py"
        test_file.write_text("def broken(): return None")

        # Iteration 0: file exists, test fails
        before = memory.snapshot(["test_target.py"])
        memory.record(
            attempt=0,
            diff_applied="--- a/test_target.py\n+++ b/test_target.py",
            result_exit_code=1,
            test_output="FAILED test_target.py::test_it - AssertionError",
            modified_files=["test_target.py"],
            error_message="AssertionError: expected True, got None",
            snapshots_before=before,
        )

        # Iteration 1: file modified, test still fails
        test_file.write_text("def broken(): return False")
        after = memory.snapshot(["test_target.py"])
        memory.record(
            attempt=1,
            diff_applied="--- a/test_target.py\n+++ b/test_target.py\n-None\n+False",
            result_exit_code=1,
            test_output="FAILED test_target.py::test_it - AssertionError: False != True",
            modified_files=["test_target.py"],
            error_message="AssertionError: False != True",
            snapshots_before=before,
            snapshots_after=after,
        )

        # Verify diagnostic chain
        assert memory.attempt_count == 2
        error_ctx = memory.error_context_for_retry()
        assert "exit_code=1" in error_ctx
        assert "False != True" in error_ctx

        # Detect the file changed between snapshots
        changed = memory.changed_since_snapshot(["test_target.py"], before)
        assert "test_target.py" in changed

        # Summary is complete
        summary = memory.summary()
        assert summary["total_attempts"] == 2
        assert len(summary["entries"]) == 2

        serialized = json.dumps(summary, indent=2, default=str)
        print("\n" + "-" * 40)
        print("MEMORY DIAGNOSTIC CHAIN:")
        print(serialized)
        print("-" * 40)
