"""NS-07 ConversationIndex + graq_session_list tests (Wave 2 Phase 9).

Covers:
  - Helpers: _fingerprint_workspace, _truncate_summary (4 tests)
  - ConversationRecord round-trip (3 tests)
  - ConversationIndex append/load (4 tests)
  - list_sessions filter + sort + limit (5 tests)
  - Corrupt-line + IO resilience (2 tests)
  - Thread safety (1 test)
  - MCP schema + handler (5 tests)
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from graqle.chat.conversation_index import (
    ConversationIndex,
    ConversationRecord,
    _LIST_LIMIT_DEFAULT,
    _LIST_LIMIT_MAX,
    _fingerprint_workspace,
    _truncate_summary,
    _utc_now_iso,
    build_session_list_response,
    record_turn,
)


# ── Helpers ───────────────────────────────────────────────────────────


def test_fingerprint_is_deterministic(tmp_path: Path):
    assert _fingerprint_workspace(tmp_path) == _fingerprint_workspace(tmp_path)


def test_fingerprint_is_64_hex(tmp_path: Path):
    fp = _fingerprint_workspace(tmp_path)
    assert len(fp) == 64
    int(fp, 16)  # parseable hex


def test_fingerprint_differs_by_path(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert _fingerprint_workspace(a) != _fingerprint_workspace(b)


def test_truncate_summary_limits_and_coerces():
    assert _truncate_summary("x" * 300) == "x" * 200
    assert _truncate_summary("short") == "short"
    assert _truncate_summary(None) == ""
    assert _truncate_summary(123) == "123"  # coerced
    assert _truncate_summary("") == ""


# ── ConversationRecord ────────────────────────────────────────────────


def test_record_round_trip():
    r = ConversationRecord(
        id="t1", workspace_fingerprint="abc",
        last_active="2026-04-23T10:00:00Z",
        summary="hello", turn_count=1, status="completed",
    )
    r2 = ConversationRecord.from_json_line(r.to_json_line())
    assert r == r2


def test_record_from_json_missing_required_raises():
    with pytest.raises(KeyError):
        ConversationRecord.from_json_line('{"id": "t1"}')  # missing required


def test_record_from_json_defaults_applied():
    line = '{"id":"t1","workspace_fingerprint":"abc","last_active":"x"}'
    r = ConversationRecord.from_json_line(line)
    assert r.summary == ""
    assert r.turn_count == 1
    assert r.status == "completed"


# ── ConversationIndex append / load ──────────────────────────────────


def test_index_missing_file_returns_empty(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    assert idx.load_records() == []


def test_index_append_creates_parent_dir(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    r = ConversationRecord(
        id="t1", workspace_fingerprint="abc",
        last_active=_utc_now_iso(), summary="x",
    )
    idx.append_record(r)
    assert idx.index_path.exists()
    assert idx.index_path.parent.exists()


def test_index_load_returns_all_records_in_order(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    for i in range(3):
        idx.append_record(ConversationRecord(
            id=f"t{i}", workspace_fingerprint="w",
            last_active=f"2026-04-23T10:0{i}:00Z",
            summary=f"m{i}",
        ))
    records = idx.load_records()
    assert [r.id for r in records] == ["t0", "t1", "t2"]


def test_index_custom_path_override(tmp_path: Path):
    custom = tmp_path / "nested" / "deep" / "sessions.jsonl"
    idx = ConversationIndex(root=tmp_path, index_path=custom)
    idx.append_record(ConversationRecord(
        id="t1", workspace_fingerprint="w", last_active="x", summary="m",
    ))
    assert custom.exists()
    assert not (tmp_path / ".graqle" / "conversations.jsonl").exists()


# ── list_sessions ────────────────────────────────────────────────────


def test_list_sessions_sorts_most_recent_first(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    # Append oldest first
    for i in range(5):
        idx.append_record(ConversationRecord(
            id=f"t{i}", workspace_fingerprint="w",
            last_active=f"2026-04-23T10:0{i}:00Z",
            summary=f"m{i}",
        ))
    sessions = idx.list_sessions()
    assert sessions[0]["id"] == "t4"
    assert sessions[-1]["id"] == "t0"


def test_list_sessions_filters_by_workspace_fingerprint(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    idx.append_record(ConversationRecord(
        id="t1", workspace_fingerprint="alpha",
        last_active="2026-04-23T10:00:00Z", summary="a",
    ))
    idx.append_record(ConversationRecord(
        id="t2", workspace_fingerprint="beta",
        last_active="2026-04-23T10:01:00Z", summary="b",
    ))
    alpha_sessions = idx.list_sessions(workspace_fingerprint="alpha")
    assert len(alpha_sessions) == 1
    assert alpha_sessions[0]["id"] == "t1"


def test_list_sessions_limit_clamped(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    for i in range(10):
        idx.append_record(ConversationRecord(
            id=f"t{i}", workspace_fingerprint="w",
            last_active=f"2026-04-23T10:0{i}:00Z", summary="x",
        ))
    # Excessive limit clamped to max
    sessions = idx.list_sessions(limit=99999)
    assert len(sessions) == 10  # only 10 records exist
    # Zero/negative clamped to 1
    sessions = idx.list_sessions(limit=0)
    assert len(sessions) == 1
    sessions = idx.list_sessions(limit=-5)
    assert len(sessions) == 1


def test_list_sessions_default_limit_50():
    assert _LIST_LIMIT_DEFAULT == 50
    assert _LIST_LIMIT_MAX == 500


def test_list_sessions_folds_same_id_latest_wins(tmp_path: Path):
    """Multiple records with same id: latest wins + turn_count incremented."""
    idx = ConversationIndex(root=tmp_path)
    idx.append_record(ConversationRecord(
        id="t1", workspace_fingerprint="w",
        last_active="2026-04-23T10:00:00Z", summary="first",
    ))
    idx.append_record(ConversationRecord(
        id="t1", workspace_fingerprint="w",
        last_active="2026-04-23T10:05:00Z", summary="second",
    ))
    sessions = idx.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["summary"] == "second"
    assert sessions[0]["turn_count"] == 2


# ── Resilience ───────────────────────────────────────────────────────


def test_corrupt_line_skipped(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    idx.append_record(ConversationRecord(
        id="t1", workspace_fingerprint="w", last_active="x", summary="a",
    ))
    # Append garbage + another valid record
    with open(idx.index_path, "a", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write("{{ broken\n")
    idx.append_record(ConversationRecord(
        id="t2", workspace_fingerprint="w", last_active="y", summary="b",
    ))
    loaded = idx.load_records()
    assert len(loaded) == 2
    assert {r.id for r in loaded} == {"t1", "t2"}


def test_empty_lines_skipped(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    with open(idx.index_path.parent.mkdir(parents=True, exist_ok=True) or idx.index_path, "w", encoding="utf-8") as f:
        f.write("\n\n\n")
    assert idx.load_records() == []


# ── Thread safety ────────────────────────────────────────────────────


def test_concurrent_appends_no_corruption(tmp_path: Path):
    idx = ConversationIndex(root=tmp_path)
    errors: list[Exception] = []

    def worker(i: int):
        try:
            for j in range(5):
                idx.append_record(ConversationRecord(
                    id=f"t_{i}_{j}", workspace_fingerprint="w",
                    last_active=f"2026-04-23T10:{i:02d}:{j:02d}Z",
                    summary=f"msg {i}/{j}",
                ))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    loaded = idx.load_records()
    # 8 threads * 5 records = 40
    assert len(loaded) == 40
    # All ids unique
    assert len({r.id for r in loaded}) == 40


# ── MCP tool ─────────────────────────────────────────────────────────


def test_mcp_tool_registered():
    import graqle.plugins.mcp_dev_server as m

    tool = next(
        (t for t in m.TOOL_DEFINITIONS if t["name"] == "graq_session_list"),
        None,
    )
    assert tool is not None
    assert hasattr(m.KogniDevServer, "_handle_session_list")


def test_mcp_tool_schema_shape():
    import graqle.plugins.mcp_dev_server as m

    tool = next(t for t in m.TOOL_DEFINITIONS if t["name"] == "graq_session_list")
    props = tool["inputSchema"]["properties"]
    assert "workspace_fingerprint" in props
    assert "limit" in props
    assert props["limit"]["default"] == 50
    assert props["limit"]["maximum"] == 500
    assert props["limit"]["minimum"] == 1


@pytest.mark.asyncio
async def test_mcp_handler_empty_returns_empty_list(tmp_path: Path, monkeypatch):
    import graqle.plugins.mcp_dev_server as m

    # Redirect cwd to tmp_path so the default index_path is isolated
    monkeypatch.chdir(tmp_path)

    class _Srv:
        _graph_file = None

    result = json.loads(await m.KogniDevServer._handle_session_list(
        _Srv(), {},
    ))
    assert result["conversations"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_mcp_handler_returns_appended_records(tmp_path: Path, monkeypatch):
    import graqle.plugins.mcp_dev_server as m

    monkeypatch.chdir(tmp_path)
    idx = ConversationIndex(root=tmp_path)
    for i in range(3):
        idx.append_record(ConversationRecord(
            id=f"t{i}", workspace_fingerprint="w",
            last_active=f"2026-04-23T10:0{i}:00Z",
            summary=f"msg {i}", status="completed",
        ))

    class _Srv:
        _graph_file = None

    result = json.loads(await m.KogniDevServer._handle_session_list(
        _Srv(), {"limit": 10},
    ))
    assert result["count"] == 3
    assert result["conversations"][0]["id"] == "t2"  # most-recent first


@pytest.mark.asyncio
async def test_mcp_handler_invalid_args_returns_empty():
    import graqle.plugins.mcp_dev_server as m

    class _Srv:
        _graph_file = None

    # args=None should not crash
    result = json.loads(await m.KogniDevServer._handle_session_list(
        _Srv(), None,
    ))
    assert "conversations" in result


# ── record_turn fire-and-forget ──────────────────────────────────────


def test_record_turn_fire_and_forget_never_raises(tmp_path: Path, monkeypatch):
    """record_turn must never raise — it's called from chat handler."""
    monkeypatch.chdir(tmp_path)
    record_turn(turn_id="t1", message="hello", status="completed")
    # File should exist
    assert (tmp_path / ".graqle" / "conversations.jsonl").exists()


def test_record_turn_swallows_internal_errors(tmp_path: Path, monkeypatch):
    """Even if the index write fails for some reason, record_turn does not raise."""
    # Point to an impossible path
    import graqle.chat.conversation_index as ci
    original_init = ci.ConversationIndex.__init__

    def failing_init(self, *a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(ci.ConversationIndex, "__init__", failing_init)
    # Must not raise:
    record_turn(turn_id="t1", message="hi", status="error")


def test_build_session_list_response_shape():
    out = build_session_list_response([{"id": "t1"}, {"id": "t2"}])
    assert out == {"conversations": [{"id": "t1"}, {"id": "t2"}], "count": 2}
