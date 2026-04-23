"""CG-15 KG-Write Gate tests (Wave 2 Phase 4).

Hard block on writes to graqle.json and its backup/corrupt variants.
Zero bypass — approved_by does NOT unblock CG-15.
Only graq_learn and graq_grow (separate handlers) legitimately write these.

Covers:
  - _is_kg_file matcher (7)
  - check_kg_block helper (5)
  - Path normalization edge cases (5)
  - _handle_write handler integration (3)
  - _handle_edit handler integration (2)
  - _handle_edit_literal handler integration (2)
  - No-bypass proof (2)
  - Sanitization (2)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from graqle.governance import check_kg_block
from graqle.governance.kg_write_gate import _is_kg_file, _normalize_basename


# ─────────────────────────────────────────────────────────────────────────
# Matcher (7)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "graqle.json",
    "graqle.json.pre-wave2.bak",
    "graqle.json.backup-2026-04-22.bak",
    "graqle_CORRUPT_20260415_2nodes.json",
    "graqle_snapshot_v1.json",
    "GRAQLE.JSON",  # case-insensitive
])
def test_is_kg_file_matches_kg_variants(name):
    assert _is_kg_file(name) is True


@pytest.mark.parametrize("name", [
    "mygraqle.json",
    "graqle.yaml",
    "graqle.json.keep",
    "graqlejson",
    "somedir/graqle.notkg.json",  # wait — this would match graqle_ prefix? no, "graqle.notkg.json" starts with "graqle." not "graqle_"
    "README.md",
    "requirements.txt",
])
def test_is_kg_file_rejects_non_kg_files(name):
    assert _is_kg_file(name) is False


def test_is_kg_file_windows_path():
    assert _is_kg_file("C:\\Users\\alice\\graqle.json") is True


def test_is_kg_file_posix_absolute():
    assert _is_kg_file("/home/alice/graqle.json") is True


def test_is_kg_file_mixed_separators():
    assert _is_kg_file("foo/bar\\graqle.json") is True


def test_is_kg_file_path_object():
    assert _is_kg_file(Path("graqle.json")) is True


def test_is_kg_file_empty_returns_false():
    assert _is_kg_file("") is False
    assert _is_kg_file("   ") is False


# ─────────────────────────────────────────────────────────────────────────
# check_kg_block (5)
# ─────────────────────────────────────────────────────────────────────────


def test_check_kg_block_blocks_kg_file():
    allowed, env = check_kg_block("graqle.json")
    assert allowed is False
    assert env["error"] == "CG-15_KG_WRITE_BLOCKED"
    assert "graq_learn" in env["suggestion"]


def test_check_kg_block_allows_non_kg_file():
    allowed, env = check_kg_block("src/foo.py")
    assert allowed is True
    assert env is None


def test_check_kg_block_absolute_path_sanitized():
    allowed, env = check_kg_block("C:\\Users\\alice\\graqle.json")
    assert allowed is False
    # Sanitization strips Windows drive path from file_path field
    assert "C:\\Users" not in env["file_path"]


def test_check_kg_block_posix_abs_path_sanitized():
    allowed, env = check_kg_block("/home/alice/graqle.json")
    assert allowed is False
    assert "/home/alice" not in env["file_path"]


def test_check_kg_block_backup_variant():
    allowed, env = check_kg_block("graqle.json.pre-wave2-teach-20260421-235449.bak")
    assert allowed is False
    assert env["error"] == "CG-15_KG_WRITE_BLOCKED"


# ─────────────────────────────────────────────────────────────────────────
# Path normalization edge cases (5)
# ─────────────────────────────────────────────────────────────────────────


def test_normalize_basename_posix():
    assert _normalize_basename("/a/b/c.txt") == "c.txt"


def test_normalize_basename_windows():
    assert _normalize_basename("C:\\a\\b\\c.txt") == "c.txt"


def test_normalize_basename_empty_raises():
    with pytest.raises(ValueError):
        _normalize_basename("")


def test_normalize_basename_none_raises():
    with pytest.raises(TypeError):
        _normalize_basename(None)


def test_normalize_basename_path_object():
    assert _normalize_basename(Path("foo/bar.py")) == "bar.py"


# ─────────────────────────────────────────────────────────────────────────
# Handler integration: _handle_write (3)
# ─────────────────────────────────────────────────────────────────────────


class _FakeConfig:
    protected_paths: list[str] = []


class _FakeServer:
    _config = _FakeConfig()
    _graph_file = None


@pytest.mark.asyncio
async def test_handle_write_blocks_graqle_json():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_write(
        server, {"file_path": "graqle.json", "content": "x", "dry_run": False},
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_handle_write_blocks_backup():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_write(
        server,
        {"file_path": "graqle.json.pre-wave2.bak", "content": "x", "dry_run": True},
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_handle_write_approved_by_does_not_bypass_cg15():
    """Critical no-bypass proof: approved_by is ignored by CG-15."""
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_write(
        server,
        {
            "file_path": "graqle.json",
            "content": "x",
            "approved_by": "reviewer-alice",
            "dry_run": True,
        },
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


# ─────────────────────────────────────────────────────────────────────────
# Handler integration: _handle_edit (2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_edit_blocks_kg_file_diff_mode():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_edit(
        server,
        {"file_path": "graqle.json", "description": "tweak it", "dry_run": True},
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_handle_edit_allows_regular_file_passes_cg15():
    """Regular files pass CG-15. Downstream failure is expected with a stub
    server (no _resolve_file_path etc.) — key assertion is that the CG-15
    fail-fast branch did NOT fire."""
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    try:
        result = json.loads(await m.KogniDevServer._handle_edit(
            server,
            {"file_path": "README.md", "description": "x", "dry_run": True},
        ))
        # If we got a JSON result, it must not be a CG-15 block
        assert result.get("error") != "CG-15_KG_WRITE_BLOCKED"
    except AttributeError as exc:
        # Expected: stub server lacks downstream helpers. CG-15 passed through
        # because the crash happened at a later stage (not in the gate).
        assert "_resolve_file_path" in str(exc) or "resolve" in str(exc), (
            f"Unexpected AttributeError after CG-15: {exc}"
        )


# ─────────────────────────────────────────────────────────────────────────
# Handler integration: _handle_edit_literal (2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_edit_literal_blocks_kg_file():
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_edit_literal(
        server,
        file_path="graqle.json",
        old_content="x",
        new_content="y",
        dry_run=True,
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_handle_edit_literal_via_strategy_blocks_kg():
    """Full flow: _handle_edit dispatches to _handle_edit_literal based on strategy."""
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    result = json.loads(await m.KogniDevServer._handle_edit(
        server,
        {
            "file_path": "graqle.json",
            "strategy": "literal",
            "old_content": "x",
            "new_content": "y",
            "dry_run": True,
        },
    ))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


# ─────────────────────────────────────────────────────────────────────────
# No-bypass proof (2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bypass_attempt", [
    {"approved_by": "alice"},
    {"approved_by": "admin"},
    {"override": True},
    {"force": True},
    {"bypass_cg15": True},
])
async def test_handle_write_no_bypass_field_accepted(bypass_attempt):
    """No field name can bypass CG-15 on KG files."""
    import graqle.plugins.mcp_dev_server as m

    server = _FakeServer()
    args = {"file_path": "graqle.json", "content": "x", "dry_run": True}
    args.update(bypass_attempt)
    result = json.loads(await m.KogniDevServer._handle_write(server, args))
    assert result["error"] == "CG-15_KG_WRITE_BLOCKED"


def test_check_kg_block_is_pure_function_takes_only_path():
    """Signature proof: check_kg_block takes ONLY file_path (no kwargs accepted)."""
    import inspect

    sig = inspect.signature(check_kg_block)
    params = list(sig.parameters.keys())
    assert params == ["file_path"], (
        f"check_kg_block must not accept auth context; params={params}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Sanitization (2)
# ─────────────────────────────────────────────────────────────────────────


def test_sanitization_strips_windows_path_from_envelope():
    allowed, env = check_kg_block("C:\\Users\\alice\\secret\\graqle.json")
    assert allowed is False
    assert "C:\\Users" not in env["file_path"]
    assert "C:\\Users" not in env["message"]


def test_sanitization_strips_unc_path():
    allowed, env = check_kg_block("\\\\fileserver\\share\\graqle.json")
    assert allowed is False
    assert "fileserver" not in env["file_path"] or "<path>" in env["file_path"]


# ─────────────────────────────────────────────────────────────────────────
# Batch-mode transitivity (review MAJOR 2 regression)
# ─────────────────────────────────────────────────────────────────────────


def test_handle_edit_batch_mode_transitivity_by_code_inspection():
    """Post-review MAJOR 2 proof: batch mode in _handle_edit calls
    self._handle_edit({"file_path": _path, ...}) RECURSIVELY per entry.
    Each recursive call is a single-file invocation, which hits the
    CG-15 + G4 gate at the top of _handle_edit. Therefore batch mode
    does NOT bypass the gates — the gate runs per entry, not only on
    the outer batch request.

    This is verified by code inspection because constructing a running
    MCP server for a full batch integration test requires the full
    governance + credential chain (out of scope for a unit test)."""
    import inspect
    import graqle.plugins.mcp_dev_server as m

    src = inspect.getsource(m.KogniDevServer._handle_edit)
    # The gate block must exist
    assert "check_kg_block(_single_path)" in src
    # Batch dispatch recursively invokes self._handle_edit with file_path
    assert "await self._handle_edit({" in src
    assert '"file_path": _path' in src
    # Recursive entries have no "files" key, so they hit the gate
    # (because the gate guard is: if _single_path and not args.get("files"))
    assert 'if _single_path and not args.get("files"):' in src
