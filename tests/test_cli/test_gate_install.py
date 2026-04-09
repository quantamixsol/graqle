"""Comprehensive tests for the GraQle governance gate (graqle-gate.py) and gate-install CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.main import app

GATE_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "graqle"
    / "data"
    / "claude_gate"
    / "graqle-gate.py"
)


def _run_gate(
    payload: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the gate script as a subprocess, simulating Claude Code hook invocation."""
    process_env = os.environ.copy()
    # Remove vscode bypass if present in parent env
    process_env.pop("GRAQLE_CLIENT_MODE", None)
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        env=process_env,
        check=False,
    )


# ── Unit tests: GraQle MCP tools always allowed ─────────────────────


def test_allows_graqle_mcp_tools() -> None:
    result = _run_gate(json.dumps({"tool_name": "mcp__graqle__graq_read"}))
    assert result.returncode == 0


def test_allows_kogni_mcp_tools() -> None:
    result = _run_gate(json.dumps({"tool_name": "mcp__kogni__kogni_read"}))
    assert result.returncode == 0


def test_allows_graqle_mcp_any_suffix() -> None:
    result = _run_gate(json.dumps({"tool_name": "mcp__graqle__graq_anything_new"}))
    assert result.returncode == 0


# ── Unit tests: blocked native tools ────────────────────────────────


@pytest.mark.parametrize(
    "tool_name, expected_graq",
    [
        ("Read", "graq_read"),
        ("Write", "graq_write"),
        ("Edit", "graq_edit"),
        ("Bash", "graq_bash"),
        ("Grep", "graq_grep"),
        ("Glob", "graq_glob"),
        ("WebSearch", "graq_web_search"),
        ("Agent", "graq_reason"),
        ("TodoWrite", "graq_todo"),
    ],
)
def test_blocks_native_tools(tool_name: str, expected_graq: str) -> None:
    result = _run_gate(json.dumps({"tool_name": tool_name}))
    assert result.returncode == 2, f"Expected block for {tool_name}, got exit 0"
    assert expected_graq in result.stderr, f"stderr should mention {expected_graq}"
    assert "GATE BLOCKED" in result.stderr


# ── Unit tests: capability gap tools ────────────────────────────────


@pytest.mark.parametrize("tool_name", ["WebFetch", "NotebookEdit"])
def test_blocks_capability_gap_tools(tool_name: str) -> None:
    result = _run_gate(json.dumps({"tool_name": tool_name}))
    assert result.returncode == 2
    assert "capability gap" in result.stderr.lower()


# ── Unit tests: allowed tools ───────────────────────────────────────


@pytest.mark.parametrize(
    "tool_name",
    ["ToolSearch", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Skill"],
)
def test_allows_allowed_tools(tool_name: str) -> None:
    result = _run_gate(json.dumps({"tool_name": tool_name}))
    assert result.returncode == 0, f"Expected allow for {tool_name}"


def test_allows_unknown_tools() -> None:
    result = _run_gate(json.dumps({"tool_name": "SomeRandomInternalTool"}))
    assert result.returncode == 0


# ── Unit tests: VS Code bypass ──────────────────────────────────────


def test_vscode_bypass_allows_blocked_tools() -> None:
    result = _run_gate(
        json.dumps({"tool_name": "Read"}), env={"GRAQLE_CLIENT_MODE": "vscode"}
    )
    assert result.returncode == 0, "VS Code extension should bypass gate"


def test_no_vscode_bypass_blocks() -> None:
    """Negative control: without GRAQLE_CLIENT_MODE, Read is blocked."""
    result = _run_gate(json.dumps({"tool_name": "Read"}))
    assert result.returncode == 2


# ── Unit tests: fail-closed on malformed input ──────────────────────


def test_fail_closed_malformed_json() -> None:
    result = _run_gate("{invalid json")
    assert result.returncode == 2
    assert "invalid JSON" in result.stderr


def test_fail_closed_empty_stdin() -> None:
    result = _run_gate("")
    assert result.returncode == 2


def test_fail_closed_non_dict_payload() -> None:
    result = _run_gate(json.dumps(["Read"]))
    assert result.returncode == 2
    assert "expected JSON object" in result.stderr


def test_fail_closed_missing_tool_name() -> None:
    result = _run_gate(json.dumps({"not_tool_name": "Read"}))
    assert result.returncode == 2
    assert "expected string" in result.stderr


def test_fail_closed_null_tool_name() -> None:
    result = _run_gate(json.dumps({"tool_name": None}))
    assert result.returncode == 2


def test_fail_closed_numeric_tool_name() -> None:
    result = _run_gate(json.dumps({"tool_name": 42}))
    assert result.returncode == 2


# ── Integration tests: gate-install CLI command ─────────────────────

runner = CliRunner()


def test_gate_install_creates_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".claude" / "hooks" / "graqle-gate.py").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()


def test_gate_install_idempotent(tmp_path: Path) -> None:
    runner.invoke(app, ["gate-install", str(tmp_path)])
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    # Check no duplicate hook entries
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    pre_hooks = settings.get("hooks", {}).get("PreToolUse", [])
    # Only one graqle-gate entry should exist
    gate_entries = [
        h
        for h in pre_hooks
        if any(
            "graqle-gate" in (hook.get("command") or "")
            for hook in h.get("hooks", [])
        )
    ]
    assert len(gate_entries) == 1


def test_gate_install_force_overwrites(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    gate_path = hooks_dir / "graqle-gate.py"
    gate_path.write_text("old content", encoding="utf-8")
    result = runner.invoke(app, ["gate-install", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert gate_path.read_text(encoding="utf-8") != "old content"


def test_gate_install_dry_run_no_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gate-install", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert not (tmp_path / ".claude").exists()


def test_gate_install_preserves_existing_hooks(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "my-custom-hook.sh"}],
                }
            ]
        }
    }
    (claude_dir / "settings.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    settings = json.loads(
        (claude_dir / "settings.json").read_text(encoding="utf-8")
    )
    pre_hooks = settings["hooks"]["PreToolUse"]
    # Original hook still present
    custom_found = any(
        "my-custom-hook.sh" in (h.get("command") or "")
        for entry in pre_hooks
        for h in entry.get("hooks", [])
    )
    assert custom_found, "Existing custom hooks should be preserved"


def test_gate_install_settings_uses_python_not_bash(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    settings_text = (tmp_path / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    assert "python" in settings_text
    settings_data = json.loads(settings_text)
    for entry in settings_data.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            assert cmd.startswith("python"), f"Hook command should use python, got: {cmd}"


def test_gate_install_corrupt_settings_backed_up(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{not valid json!!!", encoding="utf-8")
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    backups = list(claude_dir.glob("settings.json.bak*"))
    assert len(backups) >= 1, "Corrupt settings.json should be backed up"
