# tests/test_workflow/test_autonomous_executor.py
"""
Tests for AutonomousExecutor — the composition root.

Covers:
- Happy path: plan->generate->write->test(pass)->done
- Retry loop: test(fail)->fix->retry->pass
- Max retries exhaustion
- Dry run mode
- Error propagation
- Memory integration
- Config validation
- Edge cases predicted by graq_reason
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from graqle.workflow.action_agent_protocol import ActionAgentProtocol, ExecutionResult
from graqle.workflow.autonomous_executor import (
    AutonomousExecutor,
    ExecutorConfig,
    ExecutorResult,
)
from graqle.workflow.loop_controller import LoopState
from graqle.workflow.test_result_parser import ParsedTestResult


class MockAgent:
    """Mock agent implementing ActionAgentProtocol."""

    def __init__(
        self,
        plan_result: str = "Test plan",
        diff_result: str = "--- a/f.py\n+++ b/f.py",
        apply_success: bool = True,
        test_results: list[bool] | None = None,
    ):
        self._plan_result = plan_result
        self._diff_result = diff_result
        self._apply_success = apply_success
        self._test_results = test_results or [True]
        self._test_call = 0
        self.plan_calls = 0
        self.generate_calls = 0
        self.apply_calls = 0
        self.test_calls = 0
        self.rollback_calls = 0

    async def plan(self, task: str, context: dict) -> str:
        self.plan_calls += 1
        return self._plan_result

    async def generate_diff(self, task: str, plan: str, error_context: str | None = None) -> str:
        self.generate_calls += 1
        return self._diff_result

    async def apply(self, diff: str) -> ExecutionResult:
        self.apply_calls += 1
        if self._apply_success:
            return ExecutionResult(
                exit_code=0, stdout="Applied", stderr="",
                modified_files=["test_file.py"],
                rollback_token="backup-123",
            )
        return ExecutionResult(exit_code=1, stdout="", stderr="Apply failed")

    async def run_tests(self, test_paths: list[str] | None = None) -> ExecutionResult:
        self.test_calls += 1
        idx = min(self._test_call, len(self._test_results) - 1)
        passed = self._test_results[idx]
        self._test_call += 1
        return ExecutionResult(
            exit_code=0 if passed else 1,
            stdout="passed" if passed else "failed",
            stderr="",
            test_passed=passed,
        )

    async def rollback(self, token: str) -> ExecutionResult:
        self.rollback_calls += 1
        return ExecutionResult(exit_code=0, stdout="rolled back", stderr="")


# Verify MockAgent satisfies protocol
assert isinstance(MockAgent(), ActionAgentProtocol)


@pytest.fixture
def config(tmp_path):
    return ExecutorConfig(
        max_retries=3,
        test_command=["python", "-m", "pytest", "-x"],
        working_dir=str(tmp_path),
    )


# ============================================================================
# Happy Path (3 tests)
# ============================================================================


class TestHappyPath:
    """Execute successfully on first attempt."""

    @pytest.mark.asyncio
    async def test_execute_success(self, config):
        """Task succeeds on first pass — GREEN:DONE."""
        agent = MockAgent(test_results=[True])
        executor = AutonomousExecutor(agent, config)

        # Patch subprocess.run to simulate test execution
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed in 0.1s", stderr="", returncode=0
            )
            result = await executor.execute("write auth tests")

        assert result.success is True
        assert result.state == "GREEN:DONE"
        assert result.attempts == 0
        assert agent.plan_calls == 1

    @pytest.mark.asyncio
    async def test_execute_records_memory(self, config):
        """Memory is populated after execution."""
        agent = MockAgent(test_results=[True])
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed", stderr="", returncode=0
            )
            await executor.execute("task")

        summary = executor.memory.summary()
        assert summary["total_attempts"] >= 1

    @pytest.mark.asyncio
    async def test_execute_result_to_dict(self, config):
        """ExecutorResult.to_dict() is JSON-serializable."""
        agent = MockAgent(test_results=[True])
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed", stderr="", returncode=0
            )
            result = await executor.execute("task")

        d = result.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        assert d["success"] is True


# ============================================================================
# Retry Loop (3 tests)
# ============================================================================


class TestRetryLoop:
    """Test RED:FIX retry behavior."""

    @pytest.mark.asyncio
    async def test_single_retry_then_success(self, config):
        """Fails once, retries, succeeds."""
        agent = MockAgent(test_results=[False, True])
        executor = AutonomousExecutor(agent, config)

        test_call_count = {"n": 0}

        with patch("subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                # Only count test invocations (pytest), not git commands
                if any("pytest" in str(c) for c in cmd):
                    test_call_count["n"] += 1
                    if test_call_count["n"] == 1:
                        return MagicMock(
                            stdout="1 failed in 0.1s\nFAILED test.py::test_a",
                            stderr="", returncode=1,
                        )
                    return MagicMock(
                        stdout="1 passed in 0.1s", stderr="", returncode=0
                    )
                # Git commands (stash etc)
                return MagicMock(stdout="", stderr="", returncode=1)

            mock_run.side_effect = side_effect
            result = await executor.execute("fix bug")

        assert result.success is True
        assert result.state == "GREEN:DONE"
        # attempt increments when RED:FIX -> GENERATE transition happens
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, config):
        """All retries fail — FAILED state."""
        config.max_retries = 2
        agent = MockAgent(test_results=[False, False, False, False])
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 failed\nFAILED test::a", stderr="", returncode=1
            )
            result = await executor.execute("impossible task")

        assert result.success is False
        assert result.state == "FAILED"

    @pytest.mark.asyncio
    async def test_retry_receives_error_context(self, config):
        """Second generate_diff call receives error_context from memory."""
        agent = MockAgent(test_results=[False, True])
        received_error_context = []

        original_generate = agent.generate_diff

        async def tracking_generate(task, plan, error_context=None):
            received_error_context.append(error_context)
            return await original_generate(task, plan, error_context)

        agent.generate_diff = tracking_generate
        executor = AutonomousExecutor(agent, config)

        test_call = {"n": 0}
        with patch("subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                if any("pytest" in str(c) for c in cmd):
                    test_call["n"] += 1
                    if test_call["n"] == 1:
                        return MagicMock(
                            stdout="FAILED test::a\nE AssertionError: x!=y",
                            stderr="", returncode=1,
                        )
                    return MagicMock(stdout="1 passed", stderr="", returncode=0)
                return MagicMock(stdout="", stderr="", returncode=1)

            mock_run.side_effect = side_effect
            await executor.execute("fix it")

        # First call has no error context, second should have error context
        assert len(received_error_context) >= 2
        assert received_error_context[0] is None  # first attempt
        assert received_error_context[1] is not None  # retry has context


# ============================================================================
# Dry Run Mode (2 tests)
# ============================================================================


class TestDryRunMode:
    """dry_run=True skips file writes."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_write(self, config):
        """In dry_run mode, no files are written."""
        config.dry_run = True
        agent = MockAgent()
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed", stderr="", returncode=0
            )
            result = await executor.execute("dry run task")

        assert result.modified_files == []

    @pytest.mark.asyncio
    async def test_dry_run_still_tests(self, config):
        """dry_run still runs tests (on existing code)."""
        config.dry_run = True
        agent = MockAgent()
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="5 passed", stderr="", returncode=0
            )
            result = await executor.execute("verify tests pass")

        # Tests should still have been called
        assert result.success is True


# ============================================================================
# Error Propagation (3 tests)
# ============================================================================


class TestErrorPropagation:
    """Error handling in the executor."""

    @pytest.mark.asyncio
    async def test_agent_plan_failure(self, config):
        """Agent plan failure results in FAILED."""
        agent = MockAgent()
        agent.plan = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        executor = AutonomousExecutor(agent, config)

        result = await executor.execute("task")
        assert result.success is False
        assert "LLM timeout" in result.error

    @pytest.mark.asyncio
    async def test_test_timeout(self, config):
        """Test command timeout is handled."""
        config.timeout_seconds = 1
        agent = MockAgent()
        executor = AutonomousExecutor(agent, config)

        with patch("subprocess.run", side_effect=RuntimeError("timeout")):
            # The on_write callback will work but test execution will fail
            result = await executor.execute("slow test task")

        # Should either be FAILED or have error recorded
        assert result.success is False or result.state == "FAILED"

    @pytest.mark.asyncio
    async def test_apply_failure_propagates(self, config):
        """Agent.apply() failure causes FAILED state."""
        agent = MockAgent(apply_success=False)
        executor = AutonomousExecutor(agent, config)

        result = await executor.execute("task with bad diff")
        assert result.success is False


# ============================================================================
# Config Tests (3 tests)
# ============================================================================


class TestExecutorConfig:
    """ExecutorConfig validation and defaults."""

    def test_default_config(self):
        """Default config has reasonable values."""
        cfg = ExecutorConfig()
        assert cfg.max_retries == 3
        assert cfg.timeout_seconds == 300
        assert cfg.dry_run is False
        assert "pytest" in " ".join(cfg.test_command)

    def test_config_to_dict(self):
        """Config serializes correctly."""
        cfg = ExecutorConfig(max_retries=5, working_dir="/tmp")
        d = cfg.to_dict()
        assert d["max_retries"] == 5
        assert d["working_dir"] == "/tmp"

    def test_config_json_serializable(self):
        """Config is JSON-serializable."""
        cfg = ExecutorConfig()
        serialized = json.dumps(cfg.to_dict())
        assert isinstance(serialized, str)


# ============================================================================
# ExecutorResult Tests (2 tests)
# ============================================================================


class TestExecutorResult:
    """ExecutorResult output."""

    def test_result_to_dict_keys(self):
        """to_dict() has expected keys."""
        r = ExecutorResult(
            success=True, state="GREEN:DONE", attempts=0,
            modified_files=["a.py"], test_output="passed",
        )
        d = r.to_dict()
        assert "success" in d
        assert "state" in d
        assert "attempts" in d
        assert "modified_files" in d
        assert "memory" in d

    def test_result_error_field(self):
        """Error field captured on failure."""
        r = ExecutorResult(
            success=False, state="FAILED", attempts=3,
            error="max retries exhausted",
        )
        assert r.error == "max retries exhausted"
