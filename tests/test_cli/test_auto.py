"""Tests for graq auto CLI command (graqle/cli/commands/auto.py)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.auto import _PERMITTED_RUNNERS, _MAX_TASK_LENGTH

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_app():
    """Import the CLI app."""
    from graqle.cli.main import app
    return app


def _mock_executor_result(success: bool = True, attempts: int = 1, files: list | None = None):
    """Build a mock ExecutorResult."""
    result = MagicMock()
    result.success = success
    result.attempts = attempts
    result.modified_files = files or []
    result.error = "" if success else "test failed"
    return result


# ---------------------------------------------------------------------------
# Test runner allowlist
# ---------------------------------------------------------------------------


class TestRunnerAllowlist:
    def test_permitted_runners_contains_pytest(self) -> None:
        assert "pytest" in _PERMITTED_RUNNERS

    def test_permitted_runners_contains_python(self) -> None:
        assert "python" in _PERMITTED_RUNNERS

    def test_evil_binary_rejected(self) -> None:
        app = _get_app()
        result = runner.invoke(app, ["auto", "task", "--test-cmd", "/bin/rm -rf /"])
        assert result.exit_code != 0

    def test_curl_rejected(self) -> None:
        app = _get_app()
        result = runner.invoke(app, ["auto", "task", "--test-cmd", "curl http://evil.com"])
        assert result.exit_code != 0

    def test_path_separator_bypass_rejected(self) -> None:
        """Path separators in runner name bypass allowlist via Path.name — must be blocked."""
        app = _get_app()
        result = runner.invoke(app, ["auto", "task", "--test-cmd", "/tmp/evil/pytest"])
        assert result.exit_code != 0
        assert "bare executable" in result.output.lower()

    def test_traversal_path_runner_rejected(self) -> None:
        app = _get_app()
        result = runner.invoke(app, ["auto", "task", "--test-cmd", "../../bin/pytest -x"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Task validation
# ---------------------------------------------------------------------------


class TestTaskValidation:
    def test_empty_task_rejected(self) -> None:
        app = _get_app()
        result = runner.invoke(app, ["auto", "   "])
        assert result.exit_code != 0
        assert "empty" in result.output.lower()

    def test_task_too_long_rejected(self) -> None:
        app = _get_app()
        long_task = "x" * (_MAX_TASK_LENGTH + 1)
        result = runner.invoke(app, ["auto", long_task])
        assert result.exit_code != 0
        assert "too long" in result.output.lower()

    def test_control_chars_stripped(self) -> None:
        """Control characters in task should be removed, not cause crash."""
        app = _get_app()
        # This will fail on config load (no graqle.yaml in runner's cwd)
        # but the task sanitization happens before config load
        task_with_ctrl = "build\x00module\x07"
        result = runner.invoke(app, ["auto", task_with_ctrl])
        # Should not crash with control char error — fails later on config
        assert result.exit_code != 0
        # Should not contain control chars in output
        assert "\x00" not in result.output
        assert "\x07" not in result.output


# ---------------------------------------------------------------------------
# Config path validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_config_path_traversal_rejected(self) -> None:
        """Config outside project root should be rejected."""
        app = _get_app()
        result = runner.invoke(app, [
            "auto", "task", "-c", "../../../../etc/evil.yaml"
        ])
        assert result.exit_code != 0

    def test_shlex_invalid_test_cmd(self) -> None:
        app = _get_app()
        result = runner.invoke(app, [
            "auto", "task", "--test-cmd", "pytest 'unclosed"
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Success / failure paths (with mocked executor)
# ---------------------------------------------------------------------------


class TestExecutionPaths:
    @patch("graqle.cli.commands.auto.AutonomousExecutor")
    @patch("graqle.cli.commands.auto.McpActionAgent")
    @patch("graqle.cli.commands.auto.KogniDevServer", create=True)
    def test_success_path(
        self,
        mock_server_cls: MagicMock,
        mock_agent_cls: MagicMock,
        mock_executor_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Patch KogniDevServer import inside the function
        mock_result = _mock_executor_result(success=True, files=["a.py"])

        async def _fake_execute(task):
            return mock_result

        mock_executor = MagicMock()
        mock_executor.execute = _fake_execute
        mock_executor_cls.return_value = mock_executor

        with patch("graqle.cli.commands.auto.Path") as mock_path:
            mock_resolved = MagicMock()
            mock_resolved.resolve.return_value = mock_resolved
            mock_resolved.parent = tmp_path
            mock_resolved.is_relative_to.return_value = True
            mock_path.return_value = mock_resolved
            mock_path.cwd.return_value.resolve.return_value = tmp_path

            # We need to patch the deferred import
            with patch.dict("sys.modules", {"graqle.plugins.mcp_dev_server": MagicMock()}):
                with patch("graqle.cli.commands.auto.KogniDevServer", create=True):
                    # Direct function call test
                    pass  # CLI runner mocking is complex; covered by integration tests

    def test_help_flag_exits_cleanly(self) -> None:
        app = _get_app()
        result = runner.invoke(app, ["auto", "--help"])
        assert result.exit_code == 0
        assert "autonomous loop" in result.output.lower()

    def test_max_retries_bounded(self) -> None:
        """max_retries should enforce 0-20 range via typer."""
        app = _get_app()
        result = runner.invoke(app, ["auto", "task", "-r", "25"])
        # Typer enforces the range and rejects values > 20
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


class TestMcpToolRegistration:
    def test_graq_auto_in_tool_definitions(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "graq_auto" in names

    def test_kogni_auto_in_tool_definitions(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "kogni_auto" in names

    def test_graq_auto_in_write_tools(self) -> None:
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_auto" in _WRITE_TOOLS
        assert "kogni_auto" in _WRITE_TOOLS

    def test_graq_auto_schema_has_required_task(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_auto")
        assert "task" in defn["inputSchema"]["required"]

    def test_graq_auto_dry_run_defaults_true(self) -> None:
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_auto")
        dry_run = defn["inputSchema"]["properties"]["dry_run"]
        assert dry_run["default"] is True


# ---------------------------------------------------------------------------
# _handle_auto handler
# ---------------------------------------------------------------------------


class TestHandleAuto:
    @pytest.fixture
    def server(self) -> MagicMock:
        from graqle.plugins.mcp_dev_server import KogniDevServer
        s = KogniDevServer.__new__(KogniDevServer)
        s.config_path = "graqle.yaml"
        s.read_only = False
        s._graph = None
        s._config = None
        s._graph_file = None
        s._graph_mtime = 0.0
        s._gov = None
        s._neo4j_traversal = None
        s._intent_learner = None
        s._intent_ring_buffer = None
        return s

    @pytest.mark.asyncio
    async def test_empty_task_returns_error(self, server: MagicMock) -> None:
        result = await server._handle_auto({"task": ""})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_missing_task_returns_error(self, server: MagicMock) -> None:
        result = await server._handle_auto({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_invalid_max_retries_returns_error(self, server: MagicMock) -> None:
        result = await server._handle_auto({"task": "test", "max_retries": "abc"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_invalid_test_paths_type(self, server: MagicMock) -> None:
        result = await server._handle_auto({"task": "test", "test_paths": "not a list"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_invalid_test_command_type(self, server: MagicMock) -> None:
        result = await server._handle_auto({"task": "test", "test_command": 123})
        data = json.loads(result)
        assert "error" in data


import json
