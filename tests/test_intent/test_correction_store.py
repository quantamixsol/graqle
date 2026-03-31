"""Comprehensive tests for R6 CorrectionRecord persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.intent.correction_store import CorrectionStore, RingBuffer
from graqle.intent.types import CorrectionRecord


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_record(**overrides) -> CorrectionRecord:
    """Factory for CorrectionRecord with sensible defaults."""
    defaults = dict(
        raw_query="how do I deploy auth-service?",
        normalized_query="how do i deploy auth-service?",
        activated_nodes=["node_1", "node_2"],
        activated_node_types=["FUNCTION", "ENTITY"],
        activation_scores=[0.9, 0.8],
        predicted_tool="graq_context",
        corrected_tool="graq_preflight",
        confidence_at_prediction=0.75,
        keyword_rules_matched=["rule_arch"],
        correction_source="explicit",
        session_id="test-session",
    )
    defaults.update(overrides)
    return CorrectionRecord.create(**defaults)


# ===========================================================================
# RingBuffer
# ===========================================================================


class TestRingBuffer:
    """Unit tests for the bounded in-memory RingBuffer."""

    def test_append_and_len(self):
        buf = RingBuffer(max_size=3)
        for i in range(3):
            buf.append(_make_record(raw_query=f"q{i}", normalized_query=f"q{i}"))
        assert len(buf) == 3

    def test_eviction_at_capacity(self):
        buf = RingBuffer(max_size=3)
        for i in range(4):
            buf.append(_make_record(raw_query=f"q{i}", normalized_query=f"q{i}"))
        assert len(buf) == 3

    def test_recent_within_window(self):
        buf = RingBuffer(max_size=10)
        # All records created with current timestamp should be within window
        for i in range(3):
            buf.append(_make_record(raw_query=f"q{i}", normalized_query=f"q{i}"))
        recent = buf.recent(window_seconds=60)
        assert len(recent) == 3

    def test_recent_empty_buffer(self):
        buf = RingBuffer(max_size=5)
        assert buf.recent(window_seconds=60) == []

    def test_preserves_newest(self):
        buf = RingBuffer(max_size=3)
        for i in range(6):
            buf.append(_make_record(raw_query=f"q{i}", normalized_query=f"q{i}"))
        assert len(buf) == 3
        recent = buf.recent(window_seconds=3600)
        queries = {r.raw_query for r in recent}
        assert queries == {"q3", "q4", "q5"}


# ===========================================================================
# CorrectionStore
# ===========================================================================


class TestCorrectionStore:
    """Persistence tests for CorrectionStore."""

    def test_write_read_roundtrip(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        records = [
            _make_record(raw_query=f"query-{i}", normalized_query=f"query-{i}")
            for i in range(3)
        ]
        for r in records:
            CorrectionStore.persist_correction(r, filepath)

        loaded = CorrectionStore.load_corrections(filepath)
        assert len(loaded) == 3
        for i, rec in enumerate(loaded):
            assert rec.raw_query == f"query-{i}"
            assert rec.corrected_tool == "graq_preflight"

    def test_dedup_identical_corrections(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        ring = RingBuffer(max_size=100)
        record = _make_record()
        CorrectionStore.persist_correction(record, filepath, ring)
        CorrectionStore.persist_correction(record, filepath, ring)  # dedup

        loaded = CorrectionStore.load_corrections(filepath)
        assert len(loaded) == 1, "Duplicate should be deduplicated"

    def test_no_dedup_without_ring_buffer(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        record = _make_record()
        CorrectionStore.persist_correction(record, filepath)
        CorrectionStore.persist_correction(record, filepath)

        loaded = CorrectionStore.load_corrections(filepath)
        assert len(loaded) == 2, "Without ring_buffer, both should be written"

    def test_dedup_different_tools(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        ring = RingBuffer(max_size=100)
        CorrectionStore.persist_correction(
            _make_record(corrected_tool="graq_preflight"), filepath, ring,
        )
        CorrectionStore.persist_correction(
            _make_record(corrected_tool="graq_impact"), filepath, ring,
        )
        loaded = CorrectionStore.load_corrections(filepath)
        assert len(loaded) == 2, "Different tools should not be deduped"

    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        filepath = str(tmp_path / "nonexistent.jsonl")
        loaded = CorrectionStore.load_corrections(filepath)
        assert loaded == []

    def test_corrupt_jsonl_skips_bad_lines(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        CorrectionStore.persist_correction(
            _make_record(raw_query="valid_first", normalized_query="valid_first"),
            filepath,
        )
        with open(filepath, "a") as f:
            f.write("NOT VALID JSON\n")
        CorrectionStore.persist_correction(
            _make_record(raw_query="valid_second", normalized_query="valid_second"),
            filepath,
        )

        loaded = CorrectionStore.load_corrections(filepath)
        assert len(loaded) == 2, "Bad line should be skipped"
        queries = [r.raw_query for r in loaded]
        assert "valid_first" in queries
        assert "valid_second" in queries

    def test_fsync_called(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        record = _make_record()
        with patch("graqle.intent.correction_store.os.fsync") as mock_fsync:
            CorrectionStore.persist_correction(record, filepath)
            assert mock_fsync.called, "os.fsync should be called"

    def test_append_only(self, tmp_path: Path):
        filepath = str(tmp_path / "corrections.jsonl")
        CorrectionStore.persist_correction(
            _make_record(raw_query="first", normalized_query="first"), filepath,
        )
        CorrectionStore.persist_correction(
            _make_record(raw_query="second", normalized_query="second"), filepath,
        )
        with open(filepath) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2
