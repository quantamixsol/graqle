"""Regression tests for the v0.51.2 hotfix.

Covers:
  CG-08 Part 1 — `import os` present at module scope of mcp_dev_server.py
  CG-08 Part 2 — _handle_gate_install rolls back orphaned .tmp on failure
  CG-08 Part 3 — _handle_gate_status rejects .tmp (strict settings.json check)
  H-5 — hook template has {{GRAQLE_VERSION}} marker, install stamps it,
        status exposes hook_version + upgrade_available
  H-6 — doctor._check_claude_gate_drift() PASS/WARN/INFO semantics
  H-7 — _post_install_notice sentinel + env suppression
  CG-09 — claude_code_approved detection in status + install responses
  CG-10 — graq_edit strategy tiers: literal / anchored / auto / explicit failure

These tests hit the MCP server handlers directly via KogniDevServer() so no
stdio dance is required. Filesystem work is done under pytest tmp_path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.__version__ import __version__ as SDK_VERSION


# ──────────────────────────────────────────────────────────────────────────
# CG-08 Part 1 — import os at module scope
# ──────────────────────────────────────────────────────────────────────────


def test_cg08_part1_os_imported_at_module_scope():
    """_safe_replace calls os.replace — `os` MUST be importable at module scope.

    v0.51.1 shipped without `import os`, so every MCP gate install raised
    NameError, orphaned a .tmp, and lied via gate_status. This regression test
    pins the import so it cannot regress silently.
    """
    import graqle.plugins.mcp_dev_server as mod
    assert hasattr(mod, "os"), "mcp_dev_server must import `os` at module scope (CG-08 Part 1)"
    # Prove the reference actually works
    assert mod.os.path.sep in ("/", "\\")


# ──────────────────────────────────────────────────────────────────────────
# CG-08 Part 2 — orphaned .tmp rollback on _safe_replace failure
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cg08_part2_rollback_on_safe_replace_failure(tmp_path, monkeypatch):
    """If _safe_replace raises, _handle_gate_install must unlink .tmp and
    return success:False. No orphaned .tmp allowed."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")

    # Force _safe_replace to raise so we hit the rollback branch
    def _boom(src, dst):  # noqa: ARG001
        raise OSError("simulated replace failure")

    monkeypatch.setattr(KogniDevServer, "_safe_replace", staticmethod(_boom))

    result = json.loads(await srv._handle_gate_install({"force": False, "dry_run": False}))

    assert result.get("success") is False, f"expected success:False on rollback, got {result}"
    assert "atomic rename failed" in (result.get("error") or ""), result
    # CG-08 Part 2 invariant: no orphaned .tmp on disk after rollback
    tmp = tmp_path / ".claude" / "settings.json.tmp"
    assert not tmp.exists(), "rollback must delete the orphaned .tmp file"


# ──────────────────────────────────────────────────────────────────────────
# CG-08 Part 3 — strict installed check
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cg08_part3_status_rejects_tmp_without_settings_json(tmp_path):
    """Hook present but settings.json missing (only .tmp) MUST report
    installed:False. Claude Code does not read .tmp files."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")

    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "hooks" / "graqle-gate.py").write_text(
        "#!/usr/bin/env python3\n# graqle-gate version: test\n", encoding="utf-8"
    )
    # Intentionally ONLY create .tmp, not the real settings.json
    (claude / "settings.json.tmp").write_text("{}", encoding="utf-8")

    result = json.loads(await srv._handle_gate_status({"self_test": False}))
    assert result["installed"] is False, \
        f"hook+{'.tmp'}-only must NOT report installed (CG-08 Part 3): {result}"


# ──────────────────────────────────────────────────────────────────────────
# H-5 — version marker + status fields
# ──────────────────────────────────────────────────────────────────────────


def test_h5_gate_template_has_version_placeholder():
    """The shipped hook template MUST contain {{GRAQLE_VERSION}} on line 2."""
    template = (
        Path(__file__).resolve().parents[2]
        / "graqle" / "data" / "claude_gate" / "graqle-gate.py"
    )
    first_lines = template.read_text(encoding="utf-8").splitlines()[:5]
    assert any("{{GRAQLE_VERSION}}" in ln for ln in first_lines), (
        f"template missing {{{{GRAQLE_VERSION}}}} marker in first 5 lines: {first_lines}"
    )


@pytest.mark.asyncio
async def test_h5_status_returns_hook_version_and_upgrade_available(tmp_path):
    """When a stamped hook is installed, status must surface hook_version and
    upgrade_available. Fresh stamped install with matching SDK version means
    upgrade_available is False."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")

    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "hooks" / "graqle-gate.py").write_text(
        f"#!/usr/bin/env python3\n# graqle-gate version: {SDK_VERSION}\n"
        "import sys; sys.exit(0)\n",
        encoding="utf-8",
    )
    (claude / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": f"{sys.executable} .claude/hooks/graqle-gate.py"}
            ]}
        ]}}),
        encoding="utf-8",
    )

    result = json.loads(await srv._handle_gate_status({"self_test": False}))
    assert "hook_version" in result, f"missing hook_version: {result}"
    assert "upgrade_available" in result, f"missing upgrade_available: {result}"
    assert result["hook_version"] == SDK_VERSION
    assert result["upgrade_available"] is False


@pytest.mark.asyncio
async def test_h5_upgrade_available_true_on_stale_stamp(tmp_path):
    """Older hook_version relative to SDK version must flip upgrade_available:true."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")

    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "hooks" / "graqle-gate.py").write_text(
        "#!/usr/bin/env python3\n# graqle-gate version: 0.0.1-ancient\n",
        encoding="utf-8",
    )
    (claude / "settings.json").write_text("{}", encoding="utf-8")

    result = json.loads(await srv._handle_gate_status({"self_test": False}))
    assert result["hook_version"] == "0.0.1-ancient"
    assert result["upgrade_available"] is True


# ──────────────────────────────────────────────────────────────────────────
# H-6 — doctor._check_claude_gate_drift()
# ──────────────────────────────────────────────────────────────────────────


def test_h6_doctor_drift_pass_when_versions_match(tmp_path, monkeypatch):
    """PASS outcome when hook_version == SDK version."""
    from graqle.cli.commands.doctor import _check_claude_gate_drift, PASS

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks" / "graqle-gate.py").write_text(
        f"#!/usr/bin/env python3\n# graqle-gate version: {SDK_VERSION}\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    results = _check_claude_gate_drift()
    statuses = [r[0] for r in results]
    assert PASS in statuses, f"expected PASS when versions match: {results}"


def test_h6_doctor_drift_info_when_no_hook(tmp_path, monkeypatch):
    """INFO outcome when .claude/hooks/graqle-gate.py is absent."""
    from graqle.cli.commands.doctor import _check_claude_gate_drift, INFO

    monkeypatch.chdir(tmp_path)
    results = _check_claude_gate_drift()
    statuses = [r[0] for r in results]
    assert INFO in statuses, f"expected INFO when no hook: {results}"


def test_h6_doctor_drift_warn_when_stale(tmp_path, monkeypatch):
    """WARN outcome when hook_version != SDK version."""
    from graqle.cli.commands.doctor import _check_claude_gate_drift, WARN

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks" / "graqle-gate.py").write_text(
        "#!/usr/bin/env python3\n# graqle-gate version: 0.0.1-stale\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    results = _check_claude_gate_drift()
    statuses = [r[0] for r in results]
    assert WARN in statuses, f"expected WARN on stale: {results}"


# ──────────────────────────────────────────────────────────────────────────
# H-7 — post-install discoverability notice
# ──────────────────────────────────────────────────────────────────────────


def test_h7_notice_suppressed_by_env(tmp_path, monkeypatch):
    """GRAQLE_SKIP_FIRST_RUN_NOTICE env var silences the notice."""
    from graqle._post_install_notice import maybe_show_first_run_notice, SENTINEL_ENV_VAR

    monkeypatch.setenv(SENTINEL_ENV_VAR, "1")
    (tmp_path / ".claude").mkdir()  # Claude Code detected but gate missing
    shown = maybe_show_first_run_notice(cwd=tmp_path)
    assert shown is False, "env var must suppress notice"


def test_h7_notice_suppressed_when_no_claude_dir(tmp_path, monkeypatch):
    """If .claude/ is absent, notice must stay silent."""
    from graqle._post_install_notice import maybe_show_first_run_notice, SENTINEL_ENV_VAR
    monkeypatch.delenv(SENTINEL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "graqle._post_install_notice._sentinel_path",
        lambda: tmp_path / ".graqle" / ".first_run_shown",
    )
    shown = maybe_show_first_run_notice(cwd=tmp_path)
    assert shown is False


def test_h7_notice_fires_once_then_silent(tmp_path, monkeypatch, capsys):
    """Notice fires on first call, sentinel file is written, second call is silent."""
    from graqle._post_install_notice import maybe_show_first_run_notice, SENTINEL_ENV_VAR
    monkeypatch.delenv(SENTINEL_ENV_VAR, raising=False)
    sentinel = tmp_path / ".graqle" / ".first_run_shown"
    monkeypatch.setattr(
        "graqle._post_install_notice._sentinel_path",
        lambda: sentinel,
    )
    (tmp_path / ".claude").mkdir()

    first = maybe_show_first_run_notice(cwd=tmp_path)
    assert first is True
    assert sentinel.exists(), "sentinel must be written after first notice"

    second = maybe_show_first_run_notice(cwd=tmp_path)
    assert second is False, "notice must be silent on subsequent runs"


# ──────────────────────────────────────────────────────────────────────────
# CG-09 — claude_code_approved detection
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cg09_status_approved_unknown_when_no_local_settings(tmp_path):
    """Fresh install with no settings.local.json → claude_code_approved
    MUST be 'unknown' (never silently True)."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")

    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "hooks" / "graqle-gate.py").write_text(
        f"#!/usr/bin/env python3\n# graqle-gate version: {SDK_VERSION}\n",
        encoding="utf-8",
    )
    (claude / "settings.json").write_text("{}", encoding="utf-8")
    # Deliberately NO settings.local.json

    result = json.loads(await srv._handle_gate_status({"self_test": False}))
    assert "claude_code_approved" in result, f"missing field: {result}"
    assert result["claude_code_approved"] in (False, "unknown"), (
        f"must never claim approved True without evidence: {result}"
    )


# ──────────────────────────────────────────────────────────────────────────
# CG-10 — graq_edit strategy tiers
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cg10_literal_strategy_no_match_fails_fast(tmp_path, monkeypatch):
    """strategy='literal' with nonexistent old_content MUST fail fast — no
    LLM fallback, no disk write. This is the contract that saved us during
    this very hotfix."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")
    srv._graph = None
    srv._kg_load_state = "IDLE"

    target = tmp_path / "sample.py"
    target.write_text("def hello():\n    return 42\n", encoding="utf-8")

    # Make plan gate permissive for the test
    class _FakeCreds:
        plan = "enterprise"

    monkeypatch.setattr(
        "graqle.cloud.credentials.load_credentials",
        lambda: _FakeCreds(),
    )

    result = json.loads(await srv._handle_edit({
        "file_path": str(target),
        "old_content": "THIS_LINE_DOES_NOT_EXIST",
        "new_content": "replacement",
        "strategy": "literal",
        "dry_run": True,
    }))

    assert "error" in result, f"literal strategy must error on miss: {result}"
    assert "strategy=" in result.get("error", "")
    # File must be unchanged (no LLM fallback, no disk write)
    assert target.read_text(encoding="utf-8") == "def hello():\n    return 42\n"


@pytest.mark.asyncio
async def test_cg10_literal_strategy_ambiguous_fails_fast(tmp_path, monkeypatch):
    """strategy='literal' with old_content appearing ≥2 times MUST fail fast."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")
    srv._graph = None
    srv._kg_load_state = "IDLE"

    target = tmp_path / "sample.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")

    class _FakeCreds:
        plan = "enterprise"

    monkeypatch.setattr(
        "graqle.cloud.credentials.load_credentials",
        lambda: _FakeCreds(),
    )

    result = json.loads(await srv._handle_edit({
        "file_path": str(target),
        "old_content": "x = 1\n",  # appears twice
        "new_content": "x = 2\n",
        "strategy": "literal",
        "dry_run": True,
    }))
    assert "error" in result
    assert "literal" in result["error"].lower() or "strategy=" in result["error"]


def test_cg10_tool_schema_advertises_new_params():
    """The graq_edit tool definition must document old_content, new_content,
    and strategy params so MCP clients can discover them."""
    from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
    edit_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
    props = edit_tool["inputSchema"]["properties"]
    assert "old_content" in props, "graq_edit schema missing old_content (CG-10)"
    assert "new_content" in props, "graq_edit schema missing new_content (CG-10)"
    assert "strategy" in props, "graq_edit schema missing strategy (CG-10)"
    strategy_enum = props["strategy"].get("enum", [])
    for required_tier in ("auto", "literal", "anchored", "llm", "regenerate", "race"):
        assert required_tier in strategy_enum, (
            f"strategy enum missing {required_tier}: {strategy_enum}"
        )


@pytest.mark.asyncio
async def test_cg10_invalid_strategy_rejected(tmp_path, monkeypatch):
    """Unknown strategy value MUST be rejected with a clear error, not
    silently coerced to default."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph_file = str(tmp_path / "graqle.json")
    srv._graph = None
    srv._kg_load_state = "IDLE"

    target = tmp_path / "sample.py"
    target.write_text("pass\n", encoding="utf-8")

    class _FakeCreds:
        plan = "enterprise"

    monkeypatch.setattr(
        "graqle.cloud.credentials.load_credentials",
        lambda: _FakeCreds(),
    )

    result = json.loads(await srv._handle_edit({
        "file_path": str(target),
        "old_content": "pass",
        "new_content": "return None",
        "strategy": "nonsense_strategy",
        "dry_run": True,
    }))
    assert "error" in result
    assert "Invalid strategy" in result["error"]
