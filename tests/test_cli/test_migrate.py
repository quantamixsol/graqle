"""Tests for graq migrate command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.migrate import (
    _rename_file,
    _update_claude_md,
    _update_mcp_json,
    migrate_command,
)
from graqle.cli.main import app

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temp workspace with legacy files."""
    return tmp_path


class TestRenamesCognigraphYaml:
    def test_renames_cognigraph_yaml(self, workspace: Path):
        (workspace / "cognigraph.yaml").write_text("graph: true\n")
        result = _rename_file(workspace, "cognigraph.yaml", "graqle.yaml", dry_run=False)
        assert result is not None
        assert "RENAMED" in result
        assert (workspace / "graqle.yaml").exists()
        assert not (workspace / "cognigraph.yaml").exists()


class TestRenamesCognigraphJson:
    def test_renames_cognigraph_json(self, workspace: Path):
        (workspace / "cognigraph.json").write_text('{"nodes": []}\n')
        result = _rename_file(workspace, "cognigraph.json", "graqle.json", dry_run=False)
        assert result is not None
        assert "RENAMED" in result
        assert (workspace / "graqle.json").exists()
        assert not (workspace / "cognigraph.json").exists()


class TestUpdatesClaudeMd:
    def test_updates_kogni_refs(self, workspace: Path):
        content = "Use `kogni_reason` for questions.\nTry `kogni_impact` for deps.\n"
        (workspace / "CLAUDE.md").write_text(content)
        result = _update_claude_md(workspace, dry_run=False)
        assert result is not None
        assert "2 kogni_*" in result
        updated = (workspace / "CLAUDE.md").read_text()
        assert "graq_reason" in updated
        assert "graq_impact" in updated
        assert "kogni_reason" not in updated


class TestUpdatesMcpJson:
    def test_updates_mcp_json_server_name(self, workspace: Path):
        data = {"mcpServers": {"cognigraph": {"command": "graq", "args": ["mcp", "serve"]}}}
        (workspace / ".mcp.json").write_text(json.dumps(data))
        result = _update_mcp_json(workspace, dry_run=False)
        assert result is not None
        assert "UPDATED" in result
        updated = json.loads((workspace / ".mcp.json").read_text())
        assert "graqle" in updated["mcpServers"]
        assert "cognigraph" not in updated["mcpServers"]


class TestDryRun:
    def test_dry_run_no_changes(self, workspace: Path):
        (workspace / "cognigraph.yaml").write_text("graph: true\n")
        result = _rename_file(workspace, "cognigraph.yaml", "graqle.yaml", dry_run=True)
        assert result is not None
        assert "WOULD" in result
        # File should NOT have been renamed
        assert (workspace / "cognigraph.yaml").exists()
        assert not (workspace / "graqle.yaml").exists()


class TestAlreadyMigrated:
    def test_no_changes_when_already_migrated(self, workspace: Path):
        # Only graqle.yaml exists (already migrated)
        (workspace / "graqle.yaml").write_text("graph: true\n")
        result = _rename_file(workspace, "cognigraph.yaml", "graqle.yaml", dry_run=False)
        assert result is None  # Nothing to do


class TestSkipsIfTargetExists:
    def test_skips_rename_if_target_exists(self, workspace: Path):
        (workspace / "cognigraph.yaml").write_text("old\n")
        (workspace / "graqle.yaml").write_text("new\n")
        result = _rename_file(workspace, "cognigraph.yaml", "graqle.yaml", dry_run=False)
        assert result is not None
        assert "SKIP" in result
        # Both files still exist — no overwrite
        assert (workspace / "cognigraph.yaml").exists()
        assert (workspace / "graqle.yaml").read_text() == "new\n"


class TestCliIntegration:
    def test_migrate_cli_runs(self, workspace: Path):
        (workspace / "cognigraph.yaml").write_text("graph: true\n")
        result = runner.invoke(app, ["migrate", "--cwd", str(workspace)])
        assert result.exit_code == 0
        assert (workspace / "graqle.yaml").exists()
