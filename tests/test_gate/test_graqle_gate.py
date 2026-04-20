"""CG-09 + CG-10 regression tests on the Claude Code gate template.

These tests are the codified invariant guards for CG-09 (Bash blocked)
and CG-10 (Read blocked globally). If any future PR removes one of
these mappings, these tests fail loudly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "graqle"
    / "data"
    / "claude_gate"
    / "graqle-gate.py"
)


def _run_gate(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the gate template as a subprocess with stdin JSON payload."""
    return subprocess.run(
        [sys.executable, str(GATE_TEMPLATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# CG-09 / CG-10 invariant regression guards
# ═══════════════════════════════════════════════════════════════════════

REQUIRED_BLOCKED_TOOLS = {
    "Bash":       "graq_bash",
    "Read":       "graq_read",
    "Write":      "graq_write",
    "Edit":       "graq_edit",
    "Grep":       "graq_grep",
    "Glob":       "graq_glob",
    "WebSearch":  "graq_web_search",
    "Agent":      "graq_reason",
    "TodoWrite":  "graq_todo",
}


def test_gate_template_file_exists():
    assert GATE_TEMPLATE.is_file(), (
        f"Claude Code gate template missing at {GATE_TEMPLATE}. "
        "CG-09/CG-10/CG-11 enforcement depends on this template "
        "being shipped in the graqle wheel."
    )


def test_blocked_tools_contains_all_required_mappings():
    """CG-09 (Bash) + CG-10 (Read/Grep/Glob/Edit/Write) + all natives blocked."""
    src = GATE_TEMPLATE.read_text(encoding="utf-8")
    # Grep-style check on the template source — it's a small file.
    for native, governed in REQUIRED_BLOCKED_TOOLS.items():
        assert f'"{native}": "{governed}"' in src, (
            f"CG-09/CG-10 regression: BLOCKED_TOOLS is missing "
            f"{native} → {governed} mapping in gate template."
        )


# ═══════════════════════════════════════════════════════════════════════
# CG-09 — native Bash is blocked at the hook
# ═══════════════════════════════════════════════════════════════════════

def test_native_bash_is_blocked():
    result = _run_gate({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert result.returncode == 2, (
        f"Native Bash must be blocked (exit 2). Got exit {result.returncode}. "
        f"stderr={result.stderr!r}"
    )
    assert "graq_bash" in result.stderr


# ═══════════════════════════════════════════════════════════════════════
# CG-10 — native Read is blocked globally (including ~/.claude/**)
# ═══════════════════════════════════════════════════════════════════════

def test_native_read_is_blocked_globally():
    # Even on a path outside the project (~/.claude/...), the hook blocks.
    result = _run_gate({"tool_name": "Read", "tool_input": {"file_path": "~/.claude/x.md"}})
    assert result.returncode == 2
    assert "graq_read" in result.stderr


def test_native_read_is_blocked_on_project_path():
    result = _run_gate({"tool_name": "Read", "tool_input": {"file_path": "src/foo.py"}})
    assert result.returncode == 2


# ═══════════════════════════════════════════════════════════════════════
# MCP tools always pass through
# ═══════════════════════════════════════════════════════════════════════

def test_mcp_graqle_tools_pass_through():
    result = _run_gate({"tool_name": "mcp__graqle__graq_bash", "tool_input": {"command": "ls"}})
    assert result.returncode == 0, (
        f"MCP graq_bash must pass through. Got exit {result.returncode}. "
        f"stderr={result.stderr!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
# VS Code bypass
# ═══════════════════════════════════════════════════════════════════════

def test_vscode_client_mode_bypass():
    import os
    env = os.environ.copy()
    env["GRAQLE_CLIENT_MODE"] = "vscode"
    result = _run_gate(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        env=env,
    )
    assert result.returncode == 0, (
        f"VS Code bypass must pass through. Got exit {result.returncode}."
    )


# ═══════════════════════════════════════════════════════════════════════
# Malformed / defensive inputs
# ═══════════════════════════════════════════════════════════════════════

def test_malformed_json_fails_closed():
    result = subprocess.run(
        [sys.executable, str(GATE_TEMPLATE)],
        input="not-json-at-all",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_non_dict_payload_fails_closed():
    result = subprocess.run(
        [sys.executable, str(GATE_TEMPLATE)],
        input='["not", "a", "dict"]',
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_missing_tool_name_fails_closed():
    result = _run_gate({"tool_input": {}})
    assert result.returncode == 2


# ═══════════════════════════════════════════════════════════════════════
# Unknown write-class tools: fail-closed
# ═══════════════════════════════════════════════════════════════════════

def test_unknown_write_class_tool_fails_closed():
    # Any tool whose name looks write-ish gets blocked by the fallback.
    result = _run_gate({"tool_name": "PutFile", "tool_input": {"path": "x"}})
    assert result.returncode == 2


def test_unknown_read_class_tool_passes_through():
    # Non-write-ish unknown tools pass (conservative allow).
    result = _run_gate({"tool_name": "Peek", "tool_input": {}})
    assert result.returncode == 0
