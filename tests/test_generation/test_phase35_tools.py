"""
tests/test_generation/test_phase35_tools.py
Phase 3.5 — Tests for graq_read, graq_write, graq_grep, graq_glob, graq_bash,
graq_git_status/diff/log/commit/branch + P0 routing/safety fixes.
30 tests. No API key required.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_server():
    from graqle.plugins.mcp_dev_server import KogniDevServer
    server = KogniDevServer.__new__(KogniDevServer)
    server.config_path = "graqle.yaml"
    server.read_only = False
    server._config = None
    server._graph = None
    server._graph_file = None
    server._graph_mtime = 0.0
    return server


@pytest.fixture
def server():
    return _build_server()


# ---------------------------------------------------------------------------
# P0: _WRITE_TOOLS safety gate
# ---------------------------------------------------------------------------

class TestWriteToolsSafetyGate:
    def test_generate_in_write_tools(self):
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_generate" in _WRITE_TOOLS
        assert "kogni_generate" in _WRITE_TOOLS

    def test_edit_in_write_tools(self):
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_edit" in _WRITE_TOOLS
        assert "kogni_edit" in _WRITE_TOOLS

    def test_write_in_write_tools(self):
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_write" in _WRITE_TOOLS
        assert "kogni_write" in _WRITE_TOOLS

    def test_bash_in_write_tools(self):
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_bash" in _WRITE_TOOLS

    def test_git_commit_in_write_tools(self):
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_git_commit" in _WRITE_TOOLS


# ---------------------------------------------------------------------------
# P0: MCP_TOOL_TO_TASK routing
# ---------------------------------------------------------------------------

class TestMcpToolToTaskRouting:
    def test_generate_routes_to_generate_task(self):
        from graqle.routing import MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK["graq_generate"] == "generate"
        assert MCP_TOOL_TO_TASK["kogni_generate"] == "generate"

    def test_edit_routes_to_edit_task(self):
        from graqle.routing import MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK["graq_edit"] == "edit"

    def test_bash_routes_to_bash_task(self):
        from graqle.routing import MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK["graq_bash"] == "bash"

    def test_git_tools_route_to_git_task(self):
        from graqle.routing import MCP_TOOL_TO_TASK
        for tool in ["graq_git_status", "graq_git_diff", "graq_git_log", "graq_git_commit", "graq_git_branch"]:
            assert MCP_TOOL_TO_TASK[tool] == "git", f"{tool} should route to 'git'"

    def test_task_recommendations_has_generate(self):
        from graqle.routing import TASK_RECOMMENDATIONS
        assert "generate" in TASK_RECOMMENDATIONS
        assert "edit" in TASK_RECOMMENDATIONS
        assert "bash" in TASK_RECOMMENDATIONS
        assert "git" in TASK_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# graq_read
# ---------------------------------------------------------------------------

class TestGraqRead:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, server, tmp_path):
        fp = tmp_path / "hello.py"
        fp.write_text("line one\nline two\nline three\n")
        raw = await server._handle_read({"file_path": str(fp)})
        data = json.loads(raw)
        assert "content" in data
        assert "line one" in data["content"]
        assert data["total_lines"] == 3

    @pytest.mark.asyncio
    async def test_read_missing_file_returns_error(self, server, tmp_path):
        raw = await server._handle_read({"file_path": str(tmp_path / "no_such_file.py")})
        data = json.loads(raw)
        assert "error" in data
        assert data["exists"] is False

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, server, tmp_path):
        fp = tmp_path / "big.txt"
        fp.write_text("\n".join(f"line {i}" for i in range(1, 21)))
        raw = await server._handle_read({"file_path": str(fp), "offset": 5, "limit": 3})
        data = json.loads(raw)
        assert data["lines_returned"] == 3
        assert data["offset"] == 5

    @pytest.mark.asyncio
    async def test_read_missing_param_returns_error(self, server):
        raw = await server._handle_read({})
        data = json.loads(raw)
        assert "error" in data


# ---------------------------------------------------------------------------
# graq_write
# ---------------------------------------------------------------------------

class TestGraqWrite:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_write(self, server, tmp_path):
        fp = tmp_path / "out.py"
        raw = await server._handle_write({"file_path": str(fp), "content": "hello", "dry_run": True})
        data = json.loads(raw)
        assert data["dry_run"] is True
        assert not fp.exists()

    @pytest.mark.asyncio
    async def test_write_creates_file(self, server, tmp_path):
        fp = tmp_path / "new_file.py"
        content = "# generated\nprint('hello')\n"
        raw = await server._handle_write({"file_path": str(fp), "content": content, "dry_run": False})
        data = json.loads(raw)
        assert data["written"] is True
        assert fp.read_text() == content

    @pytest.mark.asyncio
    async def test_patent_gate_blocks_w_J(self, server, tmp_path):
        fp = tmp_path / "secret.py"
        raw = await server._handle_write({"file_path": str(fp), "content": "w_J = 0.7", "dry_run": False})
        data = json.loads(raw)
        assert data["error"] == "PATENT_GATE"
        assert not fp.exists()

    @pytest.mark.asyncio
    async def test_write_default_dry_run_true(self, server, tmp_path):
        fp = tmp_path / "default.py"
        raw = await server._handle_write({"file_path": str(fp), "content": "x = 1"})
        data = json.loads(raw)
        assert data["dry_run"] is True


# ---------------------------------------------------------------------------
# graq_grep
# ---------------------------------------------------------------------------

class TestGraqGrep:
    @pytest.mark.asyncio
    async def test_grep_finds_pattern(self, server, tmp_path):
        (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
        raw = await server._handle_grep({"pattern": "def foo", "path": str(tmp_path)})
        data = json.loads(raw)
        assert data["total_matches"] >= 1
        assert any("def foo" in m["line"] for m in data["matches"])

    @pytest.mark.asyncio
    async def test_grep_no_match_returns_empty(self, server, tmp_path):
        (tmp_path / "b.py").write_text("x = 1\n")
        raw = await server._handle_grep({"pattern": "NONEXISTENT_PATTERN_XYZ", "path": str(tmp_path)})
        data = json.loads(raw)
        assert data["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_grep_missing_pattern_returns_error(self, server):
        raw = await server._handle_grep({})
        data = json.loads(raw)
        assert "error" in data


# ---------------------------------------------------------------------------
# graq_glob
# ---------------------------------------------------------------------------

class TestGraqGlob:
    @pytest.mark.asyncio
    async def test_glob_finds_py_files(self, server, tmp_path):
        (tmp_path / "one.py").write_text("x=1")
        (tmp_path / "two.py").write_text("y=2")
        (tmp_path / "readme.md").write_text("# readme")
        raw = await server._handle_glob({"pattern": "*.py", "path": str(tmp_path)})
        data = json.loads(raw)
        assert data["total"] == 2
        assert all(f.endswith(".py") for f in data["files"])

    @pytest.mark.asyncio
    async def test_glob_missing_pattern_returns_error(self, server):
        raw = await server._handle_glob({})
        data = json.loads(raw)
        assert "error" in data


# ---------------------------------------------------------------------------
# graq_bash
# ---------------------------------------------------------------------------

class TestGraqBash:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_execute(self, server):
        raw = await server._handle_bash({"command": "echo hello", "dry_run": True})
        data = json.loads(raw)
        assert data["dry_run"] is True
        assert "stdout" not in data

    @pytest.mark.asyncio
    async def test_blocklist_rm_rf(self, server):
        raw = await server._handle_bash({"command": "rm -rf /tmp/test", "dry_run": False})
        data = json.loads(raw)
        assert data["error"] == "BLOCKED_COMMAND"

    @pytest.mark.asyncio
    async def test_blocklist_force_push(self, server):
        raw = await server._handle_bash({"command": "git push --force origin main"})
        data = json.loads(raw)
        assert data["error"] == "BLOCKED_COMMAND"

    @pytest.mark.asyncio
    async def test_missing_command_returns_error(self, server):
        raw = await server._handle_bash({})
        data = json.loads(raw)
        assert "error" in data


# ---------------------------------------------------------------------------
# Tool definitions: new tools are registered
# ---------------------------------------------------------------------------

class TestPhase35ToolDefinitions:
    def test_graq_read_in_definitions(self):
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_read" in names
        assert "kogni_read" in names

    def test_graq_bash_in_definitions(self):
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_bash" in names
        assert "kogni_bash" in names

    def test_all_git_tools_in_definitions(self):
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for tool in ["graq_git_status", "graq_git_diff", "graq_git_log", "graq_git_commit", "graq_git_branch"]:
            assert tool in names, f"Missing: {tool}"

    def test_total_tool_count_is_98(self):
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
        # v0.38.0 Phase 7: 57 graq_* + 57 kogni_* = 114
        assert len(TOOL_DEFINITIONS) == 114
