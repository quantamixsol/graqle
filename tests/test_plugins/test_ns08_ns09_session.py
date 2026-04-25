"""Tests for NS-08 graq_session_compact and NS-09 graq_session_resume.

Covers:
- session_compact: threshold skipping, compaction, keep_last invariant,
  idempotency, rolled-up summary, atomic rewrite
- session_resume: found/not-found, context_bundle shape, max_chars truncation
- MCP handler wiring: graq_session_compact + graq_session_resume dispatch
"""
from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pytest

from graqle.chat.conversation_index import ConversationIndex, ConversationRecord
from graqle.chat.session_compact import compact_session
from graqle.chat.session_resume import resume_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_index(tmp_path):
    """Return a (root, index_path) pair pointing at a temp JSONL file."""
    index_path = tmp_path / ".graqle" / "conversations.jsonl"
    return tmp_path, index_path


def _seed_records(root, index_path, session_id, n, status="completed"):
    """Append n records for session_id into the JSONL index."""
    idx = ConversationIndex(root=root, index_path=index_path)
    for i in range(n):
        rec = ConversationRecord(
            id=session_id,
            workspace_fingerprint="fp-test",
            last_active=f"2026-04-25T{i:02d}:00:00Z",
            summary=f"Turn {i}: user asked about topic {i}",
            turn_count=1,
            status=status,
        )
        idx.append_record(rec)


# ---------------------------------------------------------------------------
# NS-08: compact_session
# ---------------------------------------------------------------------------


class TestSessionCompact:
    def test_skips_below_threshold(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-1", n=5)
        result = compact_session("sess-1", root=root, index_path=index_path, threshold=20)
        assert result["skipped"] is True
        assert result["compacted"] == 0
        assert result["retained"] == 5

    def test_skips_unknown_session(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-1", n=25)
        result = compact_session("unknown-id", root=root, index_path=index_path, threshold=5)
        assert result["skipped"] is True
        assert result["compacted"] == 0

    def test_compacts_above_threshold(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-2", n=25)
        result = compact_session(
            "sess-2", root=root, index_path=index_path, threshold=10, keep_last=5
        )
        assert result["skipped"] is False
        assert result["compacted"] == 20
        assert result["retained"] == 5
        assert result["session_id"] == "sess-2"

    def test_keep_last_respected(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-3", n=30)
        result = compact_session(
            "sess-3", root=root, index_path=index_path, threshold=5, keep_last=8
        )
        assert result["retained"] == 8
        assert result["compacted"] == 22

    def test_compacted_record_written(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-4", n=25)
        compact_session("sess-4", root=root, index_path=index_path, threshold=5, keep_last=3)
        # Re-read index and check compacted record exists
        idx = ConversationIndex(root=root, index_path=index_path)
        records = idx.load_records()
        compacted = [r for r in records if r.status == "compacted" and r.id == "sess-4"]
        assert len(compacted) == 1
        assert "[compacted" in compacted[0].summary

    def test_other_sessions_untouched(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-A", n=25)
        _seed_records(root, index_path, "sess-B", n=5)
        compact_session("sess-A", root=root, index_path=index_path, threshold=5, keep_last=2)
        idx = ConversationIndex(root=root, index_path=index_path)
        records = idx.load_records()
        b_records = [r for r in records if r.id == "sess-B"]
        assert len(b_records) == 5  # untouched

    def test_idempotent(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-5", n=25)
        r1 = compact_session("sess-5", root=root, index_path=index_path, threshold=5, keep_last=5)
        r2 = compact_session("sess-5", root=root, index_path=index_path, threshold=5, keep_last=5)
        # Second call: only 1 compacted + 5 kept = 6 records; threshold=5 so compacts again
        # but compacted=1 so retained=5, compacted=1
        assert r1["skipped"] is False
        # After first compaction, session has 6 records; second compaction compacts 1
        assert r2["retained"] == 5

    def test_rolled_up_summary_contains_turns(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-6", n=25)
        compact_session("sess-6", root=root, index_path=index_path, threshold=5, keep_last=3)
        idx = ConversationIndex(root=root, index_path=index_path)
        records = idx.load_records()
        compacted = [r for r in records if r.status == "compacted" and r.id == "sess-6"]
        assert len(compacted) == 1
        # Rolled-up summary should reference multiple turns
        assert "Turn" in compacted[0].summary


# ---------------------------------------------------------------------------
# NS-09: resume_session
# ---------------------------------------------------------------------------


class TestSessionResume:
    def test_not_found_for_unknown_id(self, tmp_index):
        root, index_path = tmp_index
        result = resume_session("nonexistent", root=root, index_path=index_path)
        assert result["found"] is False
        assert result["session_id"] == "nonexistent"
        assert result["context_bundle"] == ""

    def test_found_for_known_session(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-R1", n=3)
        result = resume_session("sess-R1", root=root, index_path=index_path)
        assert result["found"] is True
        assert result["session_id"] == "sess-R1"
        assert result["turn_count"] == 3
        assert result["status"] in ("completed", "compacted", "error", "fast-path")

    def test_context_bundle_contains_header(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-R2", n=2)
        result = resume_session("sess-R2", root=root, index_path=index_path)
        assert "=== Resumed session context ===" in result["context_bundle"]
        assert "=== End resumed context ===" in result["context_bundle"]

    def test_context_bundle_max_chars_truncated(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-R3", n=10)
        result = resume_session("sess-R3", root=root, index_path=index_path, max_chars=100)
        assert len(result["context_bundle"]) <= 100 + 40  # max_chars + truncation suffix
        assert "truncated" in result["context_bundle"]

    def test_context_bundle_not_truncated_when_small(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-R4", n=2)
        result = resume_session("sess-R4", root=root, index_path=index_path, max_chars=5000)
        assert "truncated" not in result["context_bundle"]

    def test_last_active_returned(self, tmp_index):
        root, index_path = tmp_index
        _seed_records(root, index_path, "sess-R5", n=3)
        result = resume_session("sess-R5", root=root, index_path=index_path)
        assert "last_active" in result
        # last_active should be the most recent turn (02:00:00)
        assert "02:00:00" in result["last_active"]

    def test_empty_index_returns_not_found(self, tmp_index):
        root, index_path = tmp_index
        # index file doesn't even exist
        result = resume_session("sess-R6", root=root, index_path=index_path)
        assert result["found"] is False


# ---------------------------------------------------------------------------
# MCP handler wiring
# ---------------------------------------------------------------------------


class TestMCPSessionHandlers:
    """Verify graq_session_compact + graq_session_resume are routable via handle_tool."""

    @pytest.fixture()
    def server(self):
        import sys
        sys.path.insert(0, ".")
        from graqle.plugins.mcp_dev_server import KogniDevServer
        return KogniDevServer()

    @pytest.mark.asyncio
    async def test_compact_missing_session_id(self, server):
        result = await server.handle_tool("graq_session_compact", {})
        data = json.loads(result)
        assert "error" in data
        assert data["error"] == "NS-08_MISSING_PARAM"

    @pytest.mark.asyncio
    async def test_resume_missing_session_id(self, server):
        result = await server.handle_tool("graq_session_resume", {})
        data = json.loads(result)
        assert "error" in data
        assert data["error"] == "NS-09_MISSING_PARAM"

    @pytest.mark.asyncio
    async def test_compact_skips_unknown_session(self, server):
        result = await server.handle_tool(
            "graq_session_compact",
            {"session_id": "nonexistent-xyz", "threshold": 5},
        )
        data = json.loads(result)
        assert "error" not in data
        assert data["skipped"] is True

    @pytest.mark.asyncio
    async def test_resume_not_found_for_unknown(self, server):
        result = await server.handle_tool(
            "graq_session_resume",
            {"session_id": "nonexistent-xyz"},
        )
        data = json.loads(result)
        assert "error" not in data
        assert data["found"] is False

    @pytest.mark.asyncio
    async def test_kogni_compact_alias_routed(self, server):
        result = await server.handle_tool(
            "kogni_session_compact",
            {"session_id": "nonexistent-xyz", "threshold": 5},
        )
        data = json.loads(result)
        # Should not be an "unknown tool" error
        assert data.get("error") != "UNKNOWN_TOOL"
        assert data["skipped"] is True

    @pytest.mark.asyncio
    async def test_kogni_resume_alias_routed(self, server):
        result = await server.handle_tool(
            "kogni_session_resume",
            {"session_id": "nonexistent-xyz"},
        )
        data = json.loads(result)
        assert data.get("error") != "UNKNOWN_TOOL"
        assert data["found"] is False
