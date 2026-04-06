"""Tests for graqle.workflow.mcp_agent — McpActionAgent."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.workflow.action_agent_protocol import ExecutionResult
from graqle.workflow.mcp_agent import McpActionAgent, _TEST_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_server() -> MagicMock:
    """MCP server mock with async handle_tool."""
    server = MagicMock()
    server.handle_tool = AsyncMock()
    return server


@pytest.fixture
def agent(mock_server: MagicMock, tmp_path: Path) -> McpActionAgent:
    """McpActionAgent with a temp working directory."""
    return McpActionAgent(mock_server, tmp_path)


# ---------------------------------------------------------------------------
# plan() tests
# ---------------------------------------------------------------------------


class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_returns_graq_plan_on_success(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({"steps": ["a", "b"]})
        result = await agent.plan("build X", {})
        data = json.loads(result)
        assert "steps" in data
        mock_server.handle_tool.assert_awaited_once_with(
            "graq_plan",
            {"goal": "build X", "scope": "", "dry_run": True},
        )

    @pytest.mark.asyncio
    async def test_plan_domain_error_propagated_not_downgraded(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        """Domain errors from graq_plan should be returned, NOT fall through to preflight."""
        mock_server.handle_tool.return_value = json.dumps({"error": "bad goal"})
        result = await agent.plan("bad task", {})
        data = json.loads(result)
        assert data["error"] == "bad goal"
        # Should NOT have called graq_preflight
        assert mock_server.handle_tool.await_count == 1

    @pytest.mark.asyncio
    async def test_plan_falls_back_to_preflight_on_exception(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        """Tool-unavailable (exception) triggers preflight fallback."""
        mock_server.handle_tool.side_effect = [
            RuntimeError("graq_plan not found"),
            json.dumps({"risk_level": "low"}),
        ]
        result = await agent.plan("task", {})
        data = json.loads(result)
        assert data["risk_level"] == "low"
        # Called graq_plan then graq_preflight
        assert mock_server.handle_tool.await_count == 2
        second_call = mock_server.handle_tool.call_args_list[1]
        assert second_call.args[0] == "graq_preflight"
        assert second_call.args[1] == {"action": "task"}

    @pytest.mark.asyncio
    async def test_plan_both_unavailable_returns_error(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.side_effect = RuntimeError("unavailable")
        result = await agent.plan("task", {})
        data = json.loads(result)
        assert "error" in data
        assert "unavailable" in data["error"]

    @pytest.mark.asyncio
    async def test_plan_unparseable_response_propagated(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        """Malformed JSON from graq_plan is returned raw, not fallen through."""
        mock_server.handle_tool.return_value = "not json {{"
        result = await agent.plan("task", {})
        assert result == "not json {{"
        assert mock_server.handle_tool.await_count == 1


# ---------------------------------------------------------------------------
# generate_diff() tests
# ---------------------------------------------------------------------------


class TestGenerateDiff:
    @pytest.mark.asyncio
    async def test_passes_description_and_plan(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({"files": []})
        await agent.generate_diff("write tests", "step 1")
        mock_server.handle_tool.assert_awaited_once_with(
            "graq_generate",
            {"description": "write tests", "plan": "step 1"},
        )

    @pytest.mark.asyncio
    async def test_forwards_error_context(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({})
        await agent.generate_diff("fix", "plan", error_context="AssertionError")
        args = mock_server.handle_tool.call_args.args[1]
        assert args["error_context"] == "AssertionError"

    @pytest.mark.asyncio
    async def test_none_error_context_not_sent(
        self, agent: McpActionAgent, mock_server: MagicMock
    ) -> None:
        mock_server.handle_tool.return_value = json.dumps({})
        await agent.generate_diff("fix", "plan", error_context=None)
        args = mock_server.handle_tool.call_args.args[1]
        assert "error_context" not in args


# ---------------------------------------------------------------------------
# apply() tests
# ---------------------------------------------------------------------------


class TestApply:
    @pytest.mark.asyncio
    async def test_apply_writes_files(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({
            "files": [{"path": "hello.py", "content": "print('hi')"}]
        })
        result = await agent.apply(diff)
        assert result.success
        assert result.modified_files == ["hello.py"]
        assert (tmp_path / "hello.py").read_text() == "print('hi')"

    @pytest.mark.asyncio
    async def test_apply_blocks_path_traversal(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({
            "files": [{"path": "../../etc/passwd", "content": "evil"}]
        })
        result = await agent.apply(diff)
        assert not result.success
        assert not (tmp_path / "../../etc/passwd").exists()

    @pytest.mark.asyncio
    async def test_apply_rejects_unparseable_json(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.apply("not json {{")
        assert result.exit_code == 1
        assert "Unparseable" in result.stderr

    @pytest.mark.asyncio
    async def test_apply_rejects_json_array(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.apply("[1, 2, 3]")
        assert result.exit_code == 1
        assert "list" in result.stderr

    @pytest.mark.asyncio
    async def test_apply_propagates_error_key(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"error": "generation failed"})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "generation failed" in result.stderr

    @pytest.mark.asyncio
    async def test_apply_returns_failure_on_empty_files(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"files": []})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "No files extracted" in result.stderr

    @pytest.mark.asyncio
    async def test_apply_handles_files_null(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        """files: null should not crash (TypeError)."""
        diff = json.dumps({"files": None, "path": "x.py", "content": "ok"})
        result = await agent.apply(diff)
        # Should fall through to single-file fallback
        assert result.success
        assert (tmp_path / "x.py").read_text() == "ok"

    @pytest.mark.asyncio
    async def test_apply_rejects_files_non_list(
        self, agent: McpActionAgent
    ) -> None:
        diff = json.dumps({"files": "not a list"})
        result = await agent.apply(diff)
        assert result.exit_code == 1
        assert "must be a list" in result.stderr

    @pytest.mark.asyncio
    async def test_apply_skips_none_content(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({
            "files": [
                {"path": "a.py", "content": "ok"},
                {"path": "b.py"},  # content is missing → None
            ]
        })
        result = await agent.apply(diff)
        assert result.success
        assert "a.py" in result.modified_files
        assert "b.py" not in result.modified_files

    @pytest.mark.asyncio
    async def test_apply_allows_empty_content(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        """Empty string content is valid (e.g. __init__.py)."""
        diff = json.dumps({
            "files": [{"path": "__init__.py", "content": ""}]
        })
        result = await agent.apply(diff)
        assert result.success
        assert (tmp_path / "__init__.py").read_text() == ""

    @pytest.mark.asyncio
    async def test_apply_creates_subdirectories(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({
            "files": [{"path": "sub/dir/file.py", "content": "x = 1"}]
        })
        result = await agent.apply(diff)
        assert result.success
        assert (tmp_path / "sub" / "dir" / "file.py").read_text() == "x = 1"

    @pytest.mark.asyncio
    async def test_apply_single_file_fallback(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        diff = json.dumps({"path": "single.py", "content": "hello"})
        result = await agent.apply(diff)
        assert result.success
        assert (tmp_path / "single.py").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_apply_coerces_non_string_content(
        self, agent: McpActionAgent, tmp_path: Path
    ) -> None:
        """Non-string content (dict) should be JSON-serialized, not crash."""
        diff = json.dumps({
            "files": [{"path": "data.json", "content": {"key": "val"}}]
        })
        result = await agent.apply(diff)
        assert result.success
        written = json.loads((tmp_path / "data.json").read_text())
        assert written == {"key": "val"}


# ---------------------------------------------------------------------------
# run_tests() tests
# ---------------------------------------------------------------------------


class TestRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_blocks_path_traversal(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.run_tests(["../../etc/evil.py"])
        assert result.exit_code == 1
        assert "traversal" in result.stderr

    @pytest.mark.asyncio
    async def test_run_tests_blocks_flag_injection(
        self, agent: McpActionAgent
    ) -> None:
        result = await agent.run_tests(["--collect-only"])
        assert result.exit_code == 1
        assert "flag injection" in result.stderr

    @pytest.mark.asyncio
    async def test_run_tests_timeout_returns_124(
        self, agent: McpActionAgent
    ) -> None:
        with patch.object(agent, "_run_subprocess", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            result = await agent.run_tests()
        assert result.exit_code == 124
        assert "timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_run_tests_os_error(
        self, agent: McpActionAgent
    ) -> None:
        with patch.object(agent, "_run_subprocess", side_effect=OSError("not found")):
            result = await agent.run_tests()
        assert result.exit_code == 1
        assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_run_tests_uses_sys_executable(
        self, agent: McpActionAgent
    ) -> None:
        """Verify the command uses sys.executable, not 'python'."""
        import sys
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch.object(agent, "_run_subprocess", return_value=mock_proc) as mock_run:
            await agent.run_tests()
            cmd = mock_run.call_args.args[0]
            assert cmd[0] == sys.executable


# ---------------------------------------------------------------------------
# rollback() tests
# ---------------------------------------------------------------------------


class TestRollback:
    @pytest.mark.asyncio
    async def test_rollback_failure_returns_execution_result(
        self, agent: McpActionAgent
    ) -> None:
        with patch.object(agent._diff, "rollback", side_effect=RuntimeError("stash gone")):
            result = await agent.rollback("abc123")
        assert result.exit_code == 1
        assert "stash gone" in result.stderr


# ---------------------------------------------------------------------------
# Integration: circular import safety
# ---------------------------------------------------------------------------


class TestImportSafety:
    def test_no_circular_import(self) -> None:
        """Both modules can be imported in the same process."""
        from graqle.workflow.mcp_agent import McpActionAgent
        from graqle.plugins.mcp_dev_server import KogniDevServer
        assert McpActionAgent is not None
        assert KogniDevServer is not None
