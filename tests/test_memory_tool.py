"""CG-17 / G1 — tests for graq_memory tool + memory-write gate.

Covers:
  - Happy paths: read, write-new, update-index
  - Gate enforcement: native Write/Edit blocked on memory paths
  - Path validation: traversal, symlink escape, relative, empty, non-string
  - Frontmatter: missing fields on create, canonical overwrite
  - Partial-success contract: forced index-update failure
  - Tool discovery: tools/list includes graq_memory + kogni_memory
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import patch

import pytest

from graqle.plugins.mcp_dev_server import (
    KogniDevServer,
    TOOL_DEFINITIONS,
    _FRONTMATTER_MALFORMED_KEY,
    _MemoryIndexError,
    _escape_md_inline,
    _extract_indexed_filenames,
    _parse_frontmatter,
    _resolve_memory_dir,
    _resolve_memory_path,
    _update_memory_index,
)


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point expanduser('~') at a pytest tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def memory_dir(fake_home):
    """Create ~/.claude/projects/<fake-hash>/memory/ and return the path."""
    mem = fake_home / ".claude" / "projects" / "test-proj-hash" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return mem


@pytest.fixture
def server():
    """Minimal KogniDevServer instance for dispatcher-level tests."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._session_started = True
    srv._plan_active = True
    srv._cg01_bypass = True
    srv._cg02_bypass = True
    srv._cg03_bypass = True
    srv.read_only = False
    srv._config = type("Cfg", (), {"governance": None})()
    return srv


def _call_handler(server, args):
    return asyncio.run(server._handle_memory(args))


def _call_dispatcher(server, tool_name, args):
    return asyncio.run(server.handle_tool(tool_name, args))


# ── 1. Happy path: write new memory file ──────────────────────────────────

def test_memory_write_via_graq_memory_succeeds(memory_dir, server):
    target = memory_dir / "feedback_test.md"
    result = _call_handler(server, {
        "op": "write",
        "file": str(target),
        "content": "This is the memory body.",
        "type": "feedback",
        "name": "Test feedback",
        "description": "A test feedback memory",
    })
    data = json.loads(result)
    assert data["ok"] is True, data
    assert data["is_new_file"] is True
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: Test feedback" in text
    assert "type: feedback" in text
    assert "This is the memory body." in text


# ── 2. MEMORY.md index updated ────────────────────────────────────────────

def test_memory_write_updates_index_atomically(memory_dir, server):
    target = memory_dir / "project_x.md"
    result = _call_handler(server, {
        "op": "write",
        "file": str(target),
        "content": "Body",
        "type": "project",
        "name": "Project X",
        "description": "A project memory",
    })
    data = json.loads(result)
    assert data["ok"] is True
    assert data["index_updated"] is True
    assert "index_error" not in data
    idx = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Project" in idx
    assert "[Project X](project_x.md)" in idx


# ── 3. Native graq_write blocked on memory path ───────────────────────────

def test_native_write_to_memory_path_blocked(memory_dir, server):
    target = memory_dir / "whatever.md"
    result = _call_dispatcher(server, "graq_write", {
        "file_path": str(target),
        "content": "bypass",
    })
    assert "CG-17_MEMORY_GATE" in result
    assert "graq_memory" in result


# ── 4. Native graq_edit blocked on memory path ────────────────────────────

def test_native_edit_to_memory_path_blocked(memory_dir, server):
    target = memory_dir / "whatever.md"
    target.write_text("existing content")
    result = _call_dispatcher(server, "graq_edit", {
        "file_path": str(target),
        "old_content": "existing",
        "new_content": "modified",
    })
    assert "CG-17_MEMORY_GATE" in result


# ── 5. Path traversal blocked ─────────────────────────────────────────────

def test_path_traversal_blocked(memory_dir, server, fake_home):
    target = memory_dir / ".." / ".." / ".." / "escape.md"
    result = _call_handler(server, {
        "op": "write",
        "file": str(target),
        "content": "x",
        "type": "user", "name": "x", "description": "x",
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "PATH_OUTSIDE_MEMORY_ROOT"


# ── 6. Symlink escape blocked ─────────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="symlink privilege differs on Windows")
def test_symlink_escape_blocked(memory_dir, server, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("victim")
    link = memory_dir / "trojan.md"
    os.symlink(outside, link)
    result = _call_handler(server, {
        "op": "write",
        "file": str(link),
        "content": "x",
        "type": "user", "name": "x", "description": "x",
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "PATH_OUTSIDE_MEMORY_ROOT"


# ── 7. Relative path rejected ─────────────────────────────────────────────

def test_relative_path_rejected(server):
    result = _call_handler(server, {
        "op": "write",
        "file": "foo.md",
        "content": "x",
        "type": "user", "name": "x", "description": "x",
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "PATH_OUTSIDE_MEMORY_ROOT"


# ── 8. Empty file path rejected ───────────────────────────────────────────

def test_empty_file_path_rejected(server):
    result = _call_handler(server, {
        "op": "write",
        "file": "",
        "content": "x",
        "type": "user", "name": "x", "description": "x",
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_FILE"


# ── 9. Missing frontmatter fields rejected on create ──────────────────────

def test_missing_frontmatter_fields_rejected_on_create(memory_dir, server):
    target = memory_dir / "missing.md"
    result = _call_handler(server, {
        "op": "write",
        "file": str(target),
        "content": "x",
        "type": "user",
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] in ("MISSING_NAME", "MISSING_DESCRIPTION")


# ── 10. Invalid op rejected ───────────────────────────────────────────────

def test_invalid_op_rejected(server):
    result = _call_handler(server, {"op": "delete", "file": "x"})
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_OP"


# ── 11. update-index handles malformed frontmatter ───────────────────────

def test_update_index_handles_malformed_frontmatter(memory_dir, server):
    bad = memory_dir / "bad.md"
    bad.write_text("---\nnot valid yaml: [[\n---\ncontent", encoding="utf-8")
    good = memory_dir / "good.md"
    good.write_text(
        "---\nname: Good\ndescription: Good memory\ntype: user\n---\nbody",
        encoding="utf-8",
    )
    result = _call_handler(server, {
        "op": "update-index",
        "memory_dir": str(memory_dir),
    })
    data = json.loads(result)
    assert data["ok"] is True
    assert data["entries_count"] == 1
    assert data["partial"] is True
    assert any(s["file"] == "bad.md" for s in data["skipped"])


# ── 12. Read nonexistent file returns FILE_NOT_FOUND ──────────────────────

def test_read_nonexistent_file_returns_not_found(memory_dir, server):
    target = memory_dir / "ghost.md"
    result = _call_handler(server, {
        "op": "read",
        "file": str(target),
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "FILE_NOT_FOUND"


# ── 13. Read permission error returns READ_FAILED ────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="chmod 000 semantics differ on Windows")
def test_read_permission_error_returns_read_failed(memory_dir, server):
    target = memory_dir / "locked.md"
    target.write_text("secret", encoding="utf-8")
    os.chmod(target, 0o000)
    try:
        result = _call_handler(server, {
            "op": "read",
            "file": str(target),
        })
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"] == "READ_FAILED"
    finally:
        os.chmod(target, 0o644)


# ── 14. tools/list parity ────────────────────────────────────────────────

def test_tools_list_schema_handlers_parity():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "graq_memory" in names
    assert "kogni_memory" in names
    graq = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_memory")
    kogni = next(t for t in TOOL_DEFINITIONS if t["name"] == "kogni_memory")
    assert graq["inputSchema"] == kogni["inputSchema"]
    assert graq["description"] == kogni["description"]


# ── 15. Non-dict arguments rejected ───────────────────────────────────────

def test_arguments_non_dict_rejected(server):
    result = _call_handler(server, None)
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_ARGUMENTS"


# ── 16. Non-string memory_dir rejected ────────────────────────────────────

def test_memory_dir_non_string_rejected(server):
    result = _call_handler(server, {
        "op": "update-index",
        "memory_dir": 123,
    })
    data = json.loads(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_MEMORY_DIR"


# ── 17. Forced index-update failure surfaces partial success ─────────────

def test_forced_index_update_failure_surfaces_partial_success(memory_dir, server):
    target = memory_dir / "normal.md"
    with patch("graqle.plugins.mcp_dev_server._update_memory_index") as mock:
        mock.side_effect = _MemoryIndexError("forced failure")
        result = _call_handler(server, {
            "op": "write",
            "file": str(target),
            "content": "body",
            "type": "user",
            "name": "N",
            "description": "D",
        })
    data = json.loads(result)
    assert data["ok"] is True
    assert data["index_updated"] is False
    assert data.get("index_error") == "forced failure"
    assert target.exists()


# ── Helper unit tests ────────────────────────────────────────────────────

def test_resolve_memory_path_accepts_valid(memory_dir):
    target = memory_dir / "valid.md"
    target.write_text("x")
    ok, canon, err = _resolve_memory_path(str(target))
    assert ok is True, err
    assert err is None


def test_resolve_memory_path_rejects_none():
    ok, canon, err = _resolve_memory_path(None)
    assert ok is False
    assert canon is None


def test_resolve_memory_path_rejects_non_file(memory_dir):
    # memory_dir itself is a directory, not a file
    ok, _, err = _resolve_memory_path(str(memory_dir))
    assert ok is False


def test_resolve_memory_dir_rejects_outside_home():
    ok, _, err = _resolve_memory_dir("/tmp/fake/not/under/home")
    assert ok is False


# ── Frontmatter helper edge cases ─────────────────────────────────────────

def test_parse_frontmatter_empty():
    assert _parse_frontmatter("") == {}


def test_parse_frontmatter_no_block():
    assert _parse_frontmatter("no frontmatter here") == {}


def test_parse_frontmatter_no_closing_fence_is_malformed():
    text = "---\nname: X\ndescription: D\n"
    fm = _parse_frontmatter(text)
    assert fm.get(_FRONTMATTER_MALFORMED_KEY) is True


def test_parse_frontmatter_crlf():
    text = "---\r\nname: X\r\ndescription: D\r\ntype: user\r\n---\r\nbody"
    fm = _parse_frontmatter(text)
    assert fm.get("name") == "X"
    assert fm.get("description") == "D"
    assert fm.get("type") == "user"


# ── Markdown escape tests ────────────────────────────────────────────────

def test_escape_md_inline_basic():
    assert _escape_md_inline("simple") == "simple"


def test_escape_md_inline_brackets():
    assert _escape_md_inline("name [with] (parens)") == "name \\[with\\] \\(parens\\)"


def test_escape_md_inline_newlines_stripped():
    assert "\n" not in _escape_md_inline("line1\nline2")


# ── Filename extraction from existing index ──────────────────────────────

def test_extract_indexed_filenames():
    text = (
        "# Memory Index\n\n"
        "## Feedback\n"
        "- [One](one.md) — first\n"
        "- [Two](two.md) — second\n\n"
        "## Project\n"
        "- [Three](three.md) — third\n"
    )
    found = _extract_indexed_filenames(text)
    assert found == {"one.md", "two.md", "three.md"}


def test_extract_indexed_filenames_rejects_path_injection():
    text = "- [Bad](../escape.md) — evil\n- [Good](safe.md) — fine"
    found = _extract_indexed_filenames(text)
    assert found == {"safe.md"}
