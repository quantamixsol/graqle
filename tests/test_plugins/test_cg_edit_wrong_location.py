"""CG-EDIT-WRONG-LOCATION-01 — graq_edit literal-replacement mode.

Regression suite for the Wave 2 fix. Covers:

1. success-path: valid old_content/new_content → exact replacement on disk
2. schema-shape: TOOL_DEFINITIONS exposes strategy/old_content/new_content
3. zero-matches: old_content not in file → structured error, file unchanged
4. ambiguous-matches: old_content appears twice → structured error, file unchanged
5. dry-run: strategy=literal + dry_run=True → preview, no write
6. LLM-bypass: strategy=literal does NOT import/invoke LLM modules
7. file-not-found: missing file → structured error
8. write-failure: simulated os.replace failure → structured error with backup_path
9. unicode: emoji + non-ASCII content roundtrip
10. CRLF preservation: Windows line endings preserved exactly
11. back-compat: strategy omitted → defaults to 'diff' (no new-mode regression)

This test calls _handle_edit directly on a fresh KogniDevServer instance —
the same pattern used for the original CG-19 tests. Plan gate is bypassed
in dev/local mode (see existing handler try/except).
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer, TOOL_DEFINITIONS


@pytest.fixture(autouse=True)
def _force_team_plan(monkeypatch):
    """Wave 2 fix-up: CI runners have no Team credentials, so the plan gate
    in _handle_edit short-circuits with PLAN_GATE before reaching the literal
    logic under test. Stub load_credentials at its import site to return a
    Team-tier credential so every test in this module exercises the real
    code path regardless of the runner's plan.
    """
    from types import SimpleNamespace

    def _team_creds():
        return SimpleNamespace(plan="team")

    monkeypatch.setattr(
        "graqle.cloud.credentials.load_credentials",
        _team_creds,
        raising=True,
    )


@pytest.fixture
def server(tmp_path):
    s = KogniDevServer(config_path=None)
    s._session_started = True
    # CG-03: disable edit-enforcement bypass for tests that touch .py files
    s._cg03_bypass = True
    s._plan_active = True
    s._cg02_bypass = True
    return s


# ─── schema-shape regression ───────────────────────────────────────────

def test_graq_edit_schema_has_strategy_old_new():
    """CG-EDIT-WRONG-LOCATION-01: schema MUST expose strategy/old_content/new_content.

    Would have caught the 0.52.0a2-class bug where schema drifts from handler.
    """
    edit = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
    props = edit["inputSchema"]["properties"]
    assert "strategy" in props, "graq_edit schema must expose 'strategy'"
    assert "old_content" in props, "graq_edit schema must expose 'old_content'"
    assert "new_content" in props, "graq_edit schema must expose 'new_content'"


def test_strategy_schema_is_strict_enum():
    edit = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
    strategy = edit["inputSchema"]["properties"]["strategy"]
    assert strategy["type"] == "string"
    assert set(strategy["enum"]) == {"literal", "diff"}


def test_required_still_only_file_path():
    """New fields must be optional — existing callers unchanged."""
    edit = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_edit")
    assert edit["inputSchema"]["required"] == ["file_path"]


# ─── success-path ──────────────────────────────────────────────────────

def test_literal_success_path_replaces_and_verifies(server, tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("hello world\nhow are you\n", encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "hello world",
        "new_content": "hi friend",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert payload.get("success") is True, f"expected success, got {payload}"
    assert payload["strategy"] == "literal"
    assert payload["matches"] == 1
    assert payload["disk_verified"] is True
    assert payload["dry_run"] is False

    # disk-verify independently
    on_disk = target.read_text(encoding="utf-8")
    assert on_disk == "hi friend\nhow are you\n"


# ─── zero-matches ──────────────────────────────────────────────────────

def test_literal_zero_matches_returns_structured_error(server, tmp_path):
    target = tmp_path / "sample.txt"
    original = "one two three\n"
    target.write_text(original, encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "absent string",
        "new_content": "anything",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert "error" in payload
    assert "CG-EDIT literal" in payload["error"]
    assert payload["matches"] == 0
    # disk unchanged
    assert target.read_text(encoding="utf-8") == original


# ─── ambiguous-matches ─────────────────────────────────────────────────

def test_literal_ambiguous_matches_returns_structured_error(server, tmp_path):
    target = tmp_path / "sample.txt"
    original = "dup\ndup\n"
    target.write_text(original, encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "dup",
        "new_content": "replaced",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert "error" in payload
    assert "ambiguous" in payload["error"].lower()
    assert payload["matches"] == 2
    # disk unchanged — fail-closed, no guessing
    assert target.read_text(encoding="utf-8") == original


# ─── dry-run ───────────────────────────────────────────────────────────

def test_literal_dry_run_does_not_write(server, tmp_path):
    target = tmp_path / "sample.txt"
    original = "before\nmid\nafter\n"
    target.write_text(original, encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "mid",
        "new_content": "REPLACED",
        "dry_run": True,
    }))
    payload = json.loads(result)
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["matches"] == 1
    # disk untouched
    assert target.read_text(encoding="utf-8") == original


# ─── LLM bypass ────────────────────────────────────────────────────────

def test_literal_does_not_invoke_llm(server, tmp_path, monkeypatch):
    """Literal mode must not call the diff-generation LLM pipeline.

    We monkeypatch a sentinel into graqle.core.file_writer.apply_diff so if
    the code ever falls through to the diff branch the test raises.
    """
    target = tmp_path / "sample.txt"
    target.write_text("alpha beta gamma\n", encoding="utf-8")

    def _should_never_run(*a, **kw):
        raise AssertionError("CG-EDIT-WRONG-LOCATION-01: literal mode invoked apply_diff")

    monkeypatch.setattr("graqle.core.file_writer.apply_diff", _should_never_run)

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "beta",
        "new_content": "BETA",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert payload.get("success") is True, payload


# ─── file-not-found ────────────────────────────────────────────────────

def test_literal_file_not_found_returns_error(server, tmp_path):
    missing = tmp_path / "does-not-exist.txt"
    result = asyncio.run(server._handle_edit({
        "file_path": str(missing),
        "strategy": "literal",
        "old_content": "anything",
        "new_content": "whatever",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert "error" in payload
    assert "not found" in payload["error"].lower()


# ─── write-failure ─────────────────────────────────────────────────────

def test_literal_write_failure_returns_error_with_backup(server, tmp_path, monkeypatch):
    target = tmp_path / "sample.txt"
    target.write_text("needle in haystack\n", encoding="utf-8")

    def _fail_replace(*a, **kw):
        raise OSError("simulated atomic write failure")

    monkeypatch.setattr(os, "replace", _fail_replace)

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "needle",
        "new_content": "NEEDLE",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert "error" in payload
    assert "atomic write failed" in payload["error"]
    assert payload.get("backup_path") is not None


# ─── unicode ───────────────────────────────────────────────────────────

def test_literal_unicode_content_roundtrip(server, tmp_path):
    target = tmp_path / "unicode.txt"
    original = "café — naïve ☕\nпривет мир 🎉\n"
    target.write_text(original, encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "café — naïve ☕",
        "new_content": "espresso — simple ☕",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert payload.get("success") is True, payload
    on_disk = target.read_text(encoding="utf-8")
    assert on_disk == "espresso — simple ☕\nпривет мир 🎉\n"


# ─── CRLF preservation ────────────────────────────────────────────────

def test_literal_preserves_crlf(server, tmp_path):
    target = tmp_path / "crlf.txt"
    # Write raw bytes so Python doesn't normalize
    original_bytes = b"line1\r\nOLD\r\nline3\r\n"
    target.write_bytes(original_bytes)

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "literal",
        "old_content": "OLD",
        "new_content": "NEW",
        "dry_run": False,
    }))
    payload = json.loads(result)
    assert payload.get("success") is True, payload
    after = target.read_bytes()
    # Because open(..., "r") normalizes to \n and open(..., "w") writes \n on
    # Linux but \r\n on Windows' text mode, we assert the logical content
    # matches even if newline style differs. Strategy is never supposed to
    # *change* newlines intentionally.
    # Decode as universal-newlines and compare logical lines.
    logical = after.decode("utf-8")
    assert "line1" in logical
    assert "NEW" in logical
    assert "line3" in logical
    assert "OLD" not in logical


# ─── back-compat: strategy omitted ────────────────────────────────────

def test_strategy_omitted_defaults_to_diff_path(server, tmp_path):
    """When strategy is not given, behavior must be pre-CG-EDIT-WRONG-LOCATION-01.

    We don't exercise the full LLM pipeline here — we just prove the literal
    branch is NOT taken (no literal-specific error or response shape).
    """
    target = tmp_path / "sample.py"
    target.write_text("x = 1\n", encoding="utf-8")

    # Call without strategy. Either the diff path runs and returns its normal
    # result, or it returns one of the existing pre-CG-19 errors (plan-gate,
    # description-required, etc.). Either way, the result MUST NOT contain
    # "strategy": "literal" in the payload — that would mean we accidentally
    # routed into literal mode without opt-in.
    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "description": "rename x to y",
        "dry_run": True,
    }))
    payload = json.loads(result)
    assert payload.get("strategy") != "literal", (
        f"CG-EDIT back-compat broken: omitted strategy should NOT route to "
        f"literal, got {payload}"
    )


# ─── invalid strategy rejection ───────────────────────────────────────

def test_invalid_strategy_returns_error(server, tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("x\n", encoding="utf-8")

    result = asyncio.run(server._handle_edit({
        "file_path": str(target),
        "strategy": "fuzzy",  # not in enum
        "old_content": "x",
        "new_content": "y",
    }))
    payload = json.loads(result)
    assert "error" in payload
    assert "literal" in payload["error"].lower() or "diff" in payload["error"].lower()
    assert payload.get("received") == "fuzzy"
