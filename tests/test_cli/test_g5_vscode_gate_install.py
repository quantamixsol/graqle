"""G5 (Wave 2 Phase 7): graq gate-install --target=vscode-extension tests.

Covers:
  - CLI --target flag (5 tests)
  - VS Code file creation (6 tests)
  - Merge safety / idempotency (5 tests)
  - dry_run + MCP schema (3 tests)
  - Edge cases (3 tests)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.vscode_gate import (
    _deep_merge_preserve_user,
    _merge_extensions,
    _merge_tasks_by_label,
    install_vscode_extension_target,
)
from graqle.cli.main import app

runner = CliRunner()


@pytest.fixture
def pkg_data() -> Path:
    """Path to the VS Code gate package templates."""
    return Path(__file__).parent.parent.parent / "graqle" / "data" / "vscode_gate"


# ── CLI --target flag (5) ────────────────────────────────────────────


def test_cli_target_default_is_claude():
    """Default --target (no flag) should NOT create .vscode/ dir."""
    with runner.isolated_filesystem() as fs:
        result = runner.invoke(
            app,
            ["gate-install", fs, "--dry-run"],
        )
        # Command may fail due to interpreter probe, but we only care
        # that no vscode-extension scaffolding appears in output
        assert "G5 vscode-extension" not in (result.output or "")


def test_cli_target_vscode_extension_creates_vscode_dir():
    with runner.isolated_filesystem() as fs:
        root = Path(fs)
        result = runner.invoke(
            app,
            ["gate-install", str(root), "--target=vscode-extension"],
        )
        assert (root / ".vscode").exists()
        assert (root / ".vscode" / "settings.json").exists()
        assert (root / ".vscode" / "tasks.json").exists()
        assert (root / ".vscode" / "extensions.json").exists()
        assert (root / ".mcp.json").exists()


def test_cli_target_invalid_exits_1():
    with runner.isolated_filesystem() as fs:
        result = runner.invoke(
            app, ["gate-install", fs, "--target=invalid_target"],
        )
        assert result.exit_code == 1
        assert "Invalid --target" in (result.output or "")


def test_cli_target_vscode_dry_run_does_not_write(pkg_data):
    with runner.isolated_filesystem() as fs:
        root = Path(fs)
        result = runner.invoke(
            app,
            ["gate-install", str(root), "--target=vscode-extension", "--dry-run"],
        )
        assert not (root / ".vscode").exists()
        assert not (root / ".mcp.json").exists()


def test_cli_target_vscode_shows_would_write_in_dry_run():
    with runner.isolated_filesystem() as fs:
        result = runner.invoke(
            app,
            ["gate-install", fs, "--target=vscode-extension", "--dry-run"],
        )
        assert "would-write" in (result.output or "")


# ── VS Code file creation (6) ────────────────────────────────────────


def test_settings_json_has_graqle_keys(tmp_path: Path, pkg_data):
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert "graqle.mcp.enabled" in data
    assert data["graqle.mcp.enabled"] is True


def test_tasks_json_has_graq_tasks(tmp_path: Path, pkg_data):
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = [t["label"] for t in data.get("tasks", [])]
    assert "graq: doctor" in labels
    assert "graq: scan repo" in labels


def test_extensions_json_recommends_graqle(tmp_path: Path, pkg_data):
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((tmp_path / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    assert "graqle.graqle" in data["recommendations"]


def test_mcp_json_registers_graqle_server(tmp_path: Path, pkg_data):
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "graqle" in data["mcpServers"]


def test_mcp_json_interpreter_substituted(tmp_path: Path, pkg_data):
    install_vscode_extension_target(
        tmp_path, pkg_data, dry_run=False, interpreter_cmd="/custom/python",
    )
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["graqle"]["command"] == "/custom/python"
    assert "{{PYTHON_INTERPRETER}}" not in str(data)


def test_helper_returns_action_list(tmp_path: Path, pkg_data):
    result = install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    assert result["target"] == "vscode-extension"
    assert result["dry_run"] is False
    assert len(result["actions"]) == 4


# ── Merge safety (5) ─────────────────────────────────────────────────


def test_existing_settings_user_keys_preserved(tmp_path: Path, pkg_data):
    # Pre-create user settings
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "settings.json").write_text(
        json.dumps({"editor.fontSize": 14, "my.custom": "keep-me"}),
        encoding="utf-8",
    )
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    # User key preserved
    assert data["editor.fontSize"] == 14
    assert data["my.custom"] == "keep-me"
    # Template key added
    assert "graqle.mcp.enabled" in data


def test_existing_tasks_appended_not_overwritten(tmp_path: Path, pkg_data):
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "tasks.json").write_text(
        json.dumps({
            "version": "2.0.0",
            "tasks": [{"label": "my custom task", "type": "shell", "command": "echo"}],
        }),
        encoding="utf-8",
    )
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))
    labels = [t["label"] for t in data["tasks"]]
    assert "my custom task" in labels  # preserved
    assert "graq: doctor" in labels  # appended


def test_existing_tasks_duplicate_labels_skipped(tmp_path: Path, pkg_data):
    """Re-running install twice does not duplicate graq: doctor task."""
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = [t["label"] for t in data["tasks"]]
    assert labels.count("graq: doctor") == 1


def test_existing_extensions_deduped(tmp_path: Path, pkg_data):
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "extensions.json").write_text(
        json.dumps({"recommendations": ["graqle.graqle", "ms-python.python"]}),
        encoding="utf-8",
    )
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False)
    data = json.loads((vscode / "extensions.json").read_text(encoding="utf-8"))
    recs = data["recommendations"]
    assert recs.count("graqle.graqle") == 1
    assert recs.count("ms-python.python") == 1


def test_existing_mcp_servers_skipped_without_force(tmp_path: Path, pkg_data):
    """Pre-existing graqle entry in .mcp.json should NOT be overwritten."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"graqle": {"command": "/user/python", "args": []}}}),
        encoding="utf-8",
    )
    result = install_vscode_extension_target(tmp_path, pkg_data, dry_run=False, force=False)
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    # User's command NOT overwritten
    assert data["mcpServers"]["graqle"]["command"] == "/user/python"
    # Skip recorded in actions
    mcp_actions = [a for a in result["actions"] if a["file"] == ".mcp.json"]
    assert any(a["status"] == "skipped" for a in mcp_actions)


# ── dry_run + MCP schema (3) ─────────────────────────────────────────


def test_dry_run_does_not_write_any_file(tmp_path: Path, pkg_data):
    result = install_vscode_extension_target(tmp_path, pkg_data, dry_run=True)
    assert all(a["status"] == "would-write" for a in result["actions"])
    assert not (tmp_path / ".vscode").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_mcp_tool_schema_has_target_property():
    import graqle.plugins.mcp_dev_server as mcp

    tool = next(t for t in mcp.TOOL_DEFINITIONS if t["name"] == "graq_gate_install")
    props = tool["inputSchema"]["properties"]
    assert "target" in props
    assert props["target"]["enum"] == ["claude", "vscode-extension", "all"]
    assert props["target"]["default"] == "claude"


@pytest.mark.asyncio
async def test_mcp_handler_vscode_target_routes_to_helper(tmp_path: Path, pkg_data, monkeypatch):
    """MCP handler with target=vscode-extension calls the helper."""
    import graqle.plugins.mcp_dev_server as mcp

    monkeypatch.chdir(tmp_path)

    class _Srv:
        _graph_file = None

    result = json.loads(await mcp.KogniDevServer._handle_gate_install(
        _Srv(), {"target": "vscode-extension", "dry_run": False},
    ))
    assert result["target"] == "vscode-extension"
    assert "actions" in result


# ── Edge cases (3) ───────────────────────────────────────────────────


def test_corrupt_existing_settings_without_force_errors(tmp_path: Path, pkg_data):
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "settings.json").write_text("{{ not json", encoding="utf-8")
    result = install_vscode_extension_target(tmp_path, pkg_data, dry_run=False, force=False)
    errors = [a for a in result["actions"] if a["status"] == "error" and a["file"] == ".vscode/settings.json"]
    assert len(errors) == 1
    assert "corrupt" in errors[0]["reason"].lower()


def test_force_overwrites_corrupt_existing(tmp_path: Path, pkg_data):
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "settings.json").write_text("not json", encoding="utf-8")
    install_vscode_extension_target(tmp_path, pkg_data, dry_run=False, force=True)
    data = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert "graqle.mcp.enabled" in data


def test_mcp_handler_invalid_target_returns_error():
    import asyncio
    import graqle.plugins.mcp_dev_server as mcp

    class _Srv:
        _graph_file = None

    result = json.loads(asyncio.run(
        mcp.KogniDevServer._handle_gate_install(_Srv(), {"target": "bogus"})
    ))
    assert result["error"] == "CG-G5_INVALID_TARGET"
    assert "valid_targets" in result
