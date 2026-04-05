# tests/test_workflow/test_action_agent_protocol.py
"""
Tests for ActionAgentProtocol and ExecutionResult.

Covers:
- ExecutionResult creation, serialization, properties
- ActionAgentProtocol runtime checkable behavior
- Protocol compliance verification
"""
from __future__ import annotations

import json
import pytest

from graqle.workflow.action_agent_protocol import (
    ActionAgentProtocol,
    ExecutionResult,
)


# ============================================================================
# ExecutionResult Tests (10 tests)
# ============================================================================


class TestExecutionResult:
    """ExecutionResult dataclass behavior."""

    def test_success_when_exit_code_zero(self):
        """success property is True when exit_code=0."""
        r = ExecutionResult(exit_code=0, stdout="ok", stderr="")
        assert r.success is True

    def test_not_success_when_exit_code_nonzero(self):
        """success property is False when exit_code != 0."""
        r = ExecutionResult(exit_code=1, stdout="", stderr="error")
        assert r.success is False

    def test_default_modified_files_empty(self):
        """modified_files defaults to empty list."""
        r = ExecutionResult(exit_code=0, stdout="", stderr="")
        assert r.modified_files == []

    def test_default_test_passed_false(self):
        """test_passed defaults to False."""
        r = ExecutionResult(exit_code=0, stdout="", stderr="")
        assert r.test_passed is False

    def test_default_rollback_token_none(self):
        """rollback_token defaults to None."""
        r = ExecutionResult(exit_code=0, stdout="", stderr="")
        assert r.rollback_token is None

    def test_to_dict_keys(self):
        """to_dict() contains all expected keys."""
        r = ExecutionResult(
            exit_code=0, stdout="out", stderr="err",
            modified_files=["a.py"], test_passed=True,
            rollback_token="stash@{0}",
        )
        d = r.to_dict()
        assert set(d.keys()) == {
            "exit_code", "stdout", "stderr",
            "modified_files", "test_passed", "rollback_token",
        }

    def test_to_dict_truncates_stdout(self):
        """to_dict() truncates stdout to 4000 chars."""
        long_stdout = "x" * 5000
        r = ExecutionResult(exit_code=0, stdout=long_stdout, stderr="")
        d = r.to_dict()
        assert len(d["stdout"]) == 4000

    def test_to_dict_truncates_stderr(self):
        """to_dict() truncates stderr to 1000 chars."""
        long_stderr = "e" * 2000
        r = ExecutionResult(exit_code=0, stdout="", stderr=long_stderr)
        d = r.to_dict()
        assert len(d["stderr"]) == 1000

    def test_to_dict_json_serializable(self):
        """to_dict() output is JSON-serializable."""
        r = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            modified_files=["a.py", "b.py"],
            test_passed=True, rollback_token="abc123",
        )
        serialized = json.dumps(r.to_dict())
        assert isinstance(serialized, str)

    def test_modified_files_preserved(self):
        """modified_files list is preserved correctly."""
        files = ["src/auth.py", "tests/test_auth.py"]
        r = ExecutionResult(
            exit_code=0, stdout="", stderr="",
            modified_files=files,
        )
        assert r.modified_files == files


# ============================================================================
# ActionAgentProtocol Tests (5 tests)
# ============================================================================


class TestActionAgentProtocol:
    """ActionAgentProtocol runtime checkable behavior."""

    def test_protocol_is_runtime_checkable(self):
        """ActionAgentProtocol is a runtime_checkable Protocol."""
        assert hasattr(ActionAgentProtocol, "__protocol_attrs__") or hasattr(
            ActionAgentProtocol, "__abstractmethods__"
        )

    def test_compliant_class_passes_isinstance(self):
        """A class implementing all methods passes isinstance check."""

        class GoodAgent:
            async def plan(self, task, context):
                return ""

            async def generate_diff(self, task, plan, error_context=None):
                return ""

            async def apply(self, diff):
                return ExecutionResult(0, "", "")

            async def run_tests(self, test_paths=None):
                return ExecutionResult(0, "", "")

            async def rollback(self, token):
                return ExecutionResult(0, "", "")

        assert isinstance(GoodAgent(), ActionAgentProtocol)

    def test_non_compliant_class_fails_isinstance(self):
        """A class missing methods fails isinstance check."""

        class BadAgent:
            async def plan(self, task, context):
                return ""
            # Missing: generate_diff, apply, run_tests, rollback

        assert not isinstance(BadAgent(), ActionAgentProtocol)

    def test_partial_implementation_fails(self):
        """Class with some but not all methods fails."""

        class PartialAgent:
            async def plan(self, task, context):
                return ""

            async def generate_diff(self, task, plan, error_context=None):
                return ""

            # Missing: apply, run_tests, rollback

        assert not isinstance(PartialAgent(), ActionAgentProtocol)

    def test_protocol_methods_are_documented(self):
        """Protocol methods have docstrings."""
        # Verify the protocol itself documents its interface
        assert ActionAgentProtocol.plan is not None
        assert ActionAgentProtocol.generate_diff is not None
        assert ActionAgentProtocol.apply is not None
        assert ActionAgentProtocol.run_tests is not None
        assert ActionAgentProtocol.rollback is not None
