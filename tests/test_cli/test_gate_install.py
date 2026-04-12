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
    """Hook command must invoke a Python interpreter, not bash.

    After v0.50.1 CG-GATE-01, the installer probes for a working Python 3
    interpreter and substitutes its path into the hook command. The command
    may therefore start with ``python``, ``python3``, ``py``, or a full
    absolute path (e.g. the Windows Store launcher). In all cases it must
    still reference the graqle-gate.py script and NOT be a shell command.
    """
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    settings_text = (tmp_path / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    settings_data = json.loads(settings_text)
    for entry in settings_data.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            assert "graqle-gate.py" in cmd, (
                f"Hook command should reference graqle-gate.py, got: {cmd}"
            )
            # Must not be a shell-only command
            assert not cmd.startswith("bash "), (
                f"Hook command should use Python, not bash, got: {cmd}"
            )
            # Must look like a python interpreter invocation
            lower_cmd = cmd.lower()
            assert (
                "python" in lower_cmd or lower_cmd.startswith("py ")
            ), f"Hook command should invoke a Python interpreter, got: {cmd}"
            # Placeholder must have been substituted
            assert "{{python_interpreter}}" not in lower_cmd, (
                f"Template placeholder not substituted: {cmd}"
            )


def test_gate_install_corrupt_settings_backed_up(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{not valid json!!!", encoding="utf-8")
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    backups = list(claude_dir.glob("settings.json.bak*"))
    assert len(backups) >= 1, "Corrupt settings.json should be backed up"


# ---------------------------------------------------------------------------
# CG-GATE-01 / CG-GATE-05: _probe_python_interpreter + gate self-test (v0.50.1)
# ---------------------------------------------------------------------------


def test_probe_python_interpreter_returns_working_python() -> None:
    """_probe_python_interpreter must return a command that runs Python 3."""
    from graqle.cli.main import _probe_python_interpreter

    cmd = _probe_python_interpreter()
    assert isinstance(cmd, str)
    assert cmd, "probe must not return empty string"

    # Verify the returned command actually runs Python 3
    result = subprocess.run(
        cmd.split() + ["-c", "import sys; print(sys.version_info[0])"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, f"probed interpreter failed: {result.stderr}"
    assert result.stdout.strip() == "3"


def test_gate_install_substitutes_placeholder(tmp_path: Path) -> None:
    """After gate-install, settings.json must not contain {{PYTHON_INTERPRETER}}."""
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0
    settings_text = (tmp_path / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    assert "{{PYTHON_INTERPRETER}}" not in settings_text


def test_gate_install_self_test_runs_and_passes(tmp_path: Path) -> None:
    """gate-install must run a hook self-test that fail-closes on Bash payload.

    The installer output should reference the self-test result. Running
    the installed hook directly with a Bash payload must return exit 2
    with "GATE BLOCKED" on stderr.
    """
    result = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert result.exit_code == 0, f"install failed: {result.output}"
    assert "self-test" in result.output.lower() or "GATE BLOCKED" in result.output

    # Run the installed hook directly with a Bash payload
    gate_path = tmp_path / ".claude" / "hooks" / "graqle-gate.py"
    assert gate_path.exists()

    # Read interpreter from installed settings
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    cmd_str = (
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    )
    # Replace the hook path component with our absolute tmp path
    interpreter = cmd_str.split()[0]

    hook_result = subprocess.run(
        [interpreter, str(gate_path)],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "echo test"}}
        ),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert hook_result.returncode == 2
    assert "GATE BLOCKED" in (hook_result.stderr or "")


# ---------------------------------------------------------------------------
# CG-GATE-04: unknown write-class tools must fail-closed (v0.50.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [
        "WriteNewThing",
        "EditConfigInPlace",
        "DeleteDatabase",
        "ExecRemoteCommand",
        "RunShell",
        "CreateResource",
        "UpdateEverything",
        "PutObject",
        "PostEndpoint",
    ],
)
def test_unknown_write_class_tool_fails_closed(tool_name: str) -> None:
    """Unknown tools whose name starts with a write-class verb must block."""
    result = _run_gate(json.dumps({"tool_name": tool_name}))
    assert result.returncode == 2, (
        f"Expected exit=2 for {tool_name}, got {result.returncode}"
    )
    assert "GATE BLOCKED" in result.stderr
    assert "fail-closed" in result.stderr


@pytest.mark.parametrize(
    "tool_name",
    [
        "SomeUnknownReader",
        "InspectOnly",
        "ViewThing",
        "ListStuff",
        "QueryOnly",
    ],
)
def test_unknown_read_class_tool_allowed(tool_name: str) -> None:
    """Unknown tools whose name does NOT start with a write verb must pass."""
    result = _run_gate(json.dumps({"tool_name": tool_name}))
    assert result.returncode == 0


def test_gate_install_fix_interpreter_rewrites_only_command(tmp_path: Path) -> None:
    """--fix-interpreter must rewrite the command but leave other settings intact."""
    # First install normally
    first = runner.invoke(app, ["gate-install", str(tmp_path)])
    assert first.exit_code == 0

    # Corrupt the command to simulate an old broken install
    settings_path = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
        "python .claude/hooks/graqle-gate.py"
    )
    # Preserve a sentinel so we can verify it was not touched
    data.setdefault("_sentinel", "preserve-me")
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Run --fix-interpreter
    fix = runner.invoke(app, ["gate-install", str(tmp_path), "--fix-interpreter"])
    assert fix.exit_code == 0, f"fix-interpreter failed: {fix.output}"

    # Verify the command was rewritten
    after = json.loads(settings_path.read_text(encoding="utf-8"))
    new_cmd = after["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "graqle-gate.py" in new_cmd
    # Verify the sentinel is preserved (no full settings overwrite)
    assert after.get("_sentinel") == "preserve-me"
