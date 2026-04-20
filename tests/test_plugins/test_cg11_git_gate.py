"""CG-11 — MCP-side git gate tests (dispatcher-level)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


@pytest.fixture
def server():
    """Bare KogniDevServer with all gate-bypasses set for dispatcher testing."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._session_started = True
    srv._plan_active = True
    srv._cg01_bypass = True
    srv._cg02_bypass = True
    srv._cg03_bypass = True
    srv.read_only = False
    srv._config = type("Cfg", (), {"governance": None})()
    return srv


def _call(server, tool_name, args):
    return asyncio.run(server.handle_tool(tool_name, args))


# ═══════════════════════════════════════════════════════════════════════
# CG-11 blocks git subcommands with graq_git_* equivalents
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("subcmd,expected_tool", [
    ("status",  "graq_git_status"),
    ("commit",  "graq_git_commit"),
    ("branch",  "graq_git_branch"),
    ("diff",    "graq_git_diff"),
    ("log",     "graq_git_log"),
])
def test_cg11_blocks_mapped_git_subcommands(server, subcmd, expected_tool):
    result = _call(server, "graq_bash", {"command": f"git {subcmd}"})
    assert "CG-11_GIT_GATE" in result
    assert expected_tool in result


# Post-impl review MAJOR 1 fix: wrapper forms still route.
def test_cg11_blocks_sudo_git_status(server):
    result = _call(server, "graq_bash", {"command": "sudo git status"})
    assert "CG-11_GIT_GATE" in result
    assert "graq_git_status" in result


def test_cg11_blocks_env_prefixed_git(server):
    result = _call(server, "graq_bash", {"command": "env GIT_PAGER=cat git diff"})
    assert "CG-11_GIT_GATE" in result
    assert "graq_git_diff" in result


# Post-impl review MAJOR 2 fix: option-first git forms still route.
def test_cg11_blocks_git_dash_C_status(server):
    result = _call(server, "graq_bash", {"command": "git -C /path/to/repo status"})
    assert "CG-11_GIT_GATE" in result
    assert "graq_git_status" in result


def test_cg11_blocks_git_dash_dash_git_dir_log(server):
    result = _call(server, "graq_bash", {"command": "git --git-dir /foo log"})
    assert "CG-11_GIT_GATE" in result
    assert "graq_git_log" in result


def test_cg11_blocks_git_commit_with_args(server):
    result = _call(server, "graq_bash", {"command": "git commit -m 'fix: bug'"})
    assert "CG-11_GIT_GATE" in result
    assert "graq_git_commit" in result


def test_cg11_blocks_git_with_leading_whitespace(server):
    result = _call(server, "graq_bash", {"command": "   git status"})
    assert "CG-11_GIT_GATE" in result


def test_cg11_blocks_kogni_bash_too(server):
    result = _call(server, "kogni_bash", {"command": "git status"})
    assert "CG-11_GIT_GATE" in result


# ═══════════════════════════════════════════════════════════════════════
# CG-11 passes through git subcommands WITHOUT graq_ equivalents
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("subcmd", [
    "push", "pull", "fetch", "clone", "checkout", "switch",
    "merge", "rebase", "reset", "stash", "tag", "remote",
])
def test_cg11_passes_through_unmapped_git_subcommands(server, subcmd):
    """git subcommands without a graq_ equivalent must pass through CG-11.

    They may still fail at the handler level (e.g. `graq_bash` allowlist),
    but CG-11 itself is about DX routing — not our gate to enforce full
    git policy here.
    """
    # Replace the handler with a stub so the call completes deterministically
    # even when no graph/backend is loaded.
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    result = _call(server, "graq_bash", {"command": f"git {subcmd}"})
    assert "CG-11_GIT_GATE" not in result


# ═══════════════════════════════════════════════════════════════════════
# CG-11 passes through non-git commands
# ═══════════════════════════════════════════════════════════════════════

def test_cg11_passes_through_non_git_command(server):
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    result = _call(server, "graq_bash", {"command": "ls -la"})
    assert "CG-11_GIT_GATE" not in result


def test_cg11_passes_through_git_in_middle_of_command(server):
    """`echo git` or `mygit status` must NOT trip CG-11 — only leading `git`."""
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    # 'echo git' — token 0 is 'echo', not 'git'
    result = _call(server, "graq_bash", {"command": "echo git status"})
    assert "CG-11_GIT_GATE" not in result


# ═══════════════════════════════════════════════════════════════════════
# CG-11 defensive parsing (malformed inputs)
# ═══════════════════════════════════════════════════════════════════════

def test_cg11_handles_none_command(server):
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    # command=None: CG-11 skips; handler's own validation kicks in.
    result = _call(server, "graq_bash", {"command": None})
    assert "CG-11_GIT_GATE" not in result


def test_cg11_handles_missing_command(server):
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    result = _call(server, "graq_bash", {})
    assert "CG-11_GIT_GATE" not in result


def test_cg11_handles_non_string_command(server):
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    result = _call(server, "graq_bash", {"command": 42})
    assert "CG-11_GIT_GATE" not in result


def test_cg11_handles_whitespace_only_command(server):
    async def _stub(args):
        return json.dumps({"ok": True, "stub": True})
    server._handle_bash = _stub

    result = _call(server, "graq_bash", {"command": "   "})
    assert "CG-11_GIT_GATE" not in result


# ═══════════════════════════════════════════════════════════════════════
# Error envelope shape
# ═══════════════════════════════════════════════════════════════════════

def test_cg11_error_envelope_contains_all_expected_fields(server):
    result = _call(server, "graq_bash", {"command": "git status --porcelain"})
    # strip MCP envelope — result is JSON with "content" key wrapping inner.
    # The error JSON is in the string; parse what we can.
    data = json.loads(result) if result.lstrip().startswith("{") else None
    # Some MCP dispatchers wrap in {"content":[{"type":"text","text":"..."}]}
    # or return the inner json directly. Handle both.
    if isinstance(data, dict) and "content" in data and isinstance(data["content"], list):
        inner = data["content"][0].get("text", "{}")
        inner_data = json.loads(inner) if inner.lstrip().startswith("{") else {}
    else:
        inner_data = data or {}

    # Required fields: error, tool, command, subcommand, message, remediation
    for field in ("error", "tool", "command", "subcommand", "message", "remediation"):
        assert field in inner_data, f"CG-11 error envelope missing field: {field}"
    assert inner_data["error"] == "CG-11_GIT_GATE"
    assert inner_data["subcommand"] == "status"
    assert inner_data["remediation"] == "graq_git_status"
