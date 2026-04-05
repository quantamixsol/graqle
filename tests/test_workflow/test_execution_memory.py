# tests/test_workflow/test_execution_memory.py
"""
Tests for ExecutionMemory — filesystem state tracking.

Covers:
- Snapshot creation and hash computation
- Changed-since-snapshot detection
- History recording
- Error context generation for retries
- Summary output
- Edge cases (missing files, empty paths)
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from graqle.workflow.execution_memory import (
    ExecutionMemory,
    FileSnapshot,
    MemoryEntry,
)


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary working directory with sample files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass")
    (tmp_path / "src" / "api.py").write_text("def endpoint(): pass")
    return tmp_path


@pytest.fixture
def memory(work_dir):
    return ExecutionMemory(work_dir)


# ============================================================================
# Snapshot Tests (6 tests)
# ============================================================================


class TestSnapshot:
    """FileSnapshot creation and content hashing."""

    def test_snapshot_existing_file(self, memory, work_dir):
        """Snapshot of existing file has correct hash and size."""
        snaps = memory.snapshot(["src/auth.py"])
        assert "src/auth.py" in snaps
        snap = snaps["src/auth.py"]
        assert snap.exists is True
        assert snap.size_bytes > 0
        assert len(snap.content_hash) == 64  # SHA-256 hex

    def test_snapshot_nonexistent_file(self, memory):
        """Snapshot of nonexistent file has exists=False."""
        snaps = memory.snapshot(["nonexistent.py"])
        assert snaps["nonexistent.py"].exists is False
        assert snaps["nonexistent.py"].content_hash == ""
        assert snaps["nonexistent.py"].size_bytes == 0

    def test_snapshot_multiple_files(self, memory):
        """Snapshot multiple files at once."""
        snaps = memory.snapshot(["src/auth.py", "src/api.py"])
        assert len(snaps) == 2
        assert snaps["src/auth.py"].exists is True
        assert snaps["src/api.py"].exists is True

    def test_snapshot_consistent_hash(self, memory):
        """Same file content produces same hash."""
        snap1 = memory.snapshot(["src/auth.py"])
        snap2 = memory.snapshot(["src/auth.py"])
        assert snap1["src/auth.py"].content_hash == snap2["src/auth.py"].content_hash

    def test_snapshot_detects_change(self, memory, work_dir):
        """Modified file produces different hash."""
        snap_before = memory.snapshot(["src/auth.py"])
        (work_dir / "src" / "auth.py").write_text("def login(): return True")
        snap_after = memory.snapshot(["src/auth.py"])
        assert snap_before["src/auth.py"].content_hash != snap_after["src/auth.py"].content_hash

    def test_snapshot_empty_paths(self, memory):
        """Empty paths list returns empty dict."""
        snaps = memory.snapshot([])
        assert snaps == {}


# ============================================================================
# Changed Since Snapshot Tests (4 tests)
# ============================================================================


class TestChangedSince:
    """Detect files changed since a baseline snapshot."""

    def test_no_changes_returns_empty(self, memory):
        """Unchanged files return empty list."""
        baseline = memory.snapshot(["src/auth.py"])
        changed = memory.changed_since_snapshot(["src/auth.py"], baseline)
        assert changed == []

    def test_modified_file_detected(self, memory, work_dir):
        """Modified file appears in changed list."""
        baseline = memory.snapshot(["src/auth.py"])
        (work_dir / "src" / "auth.py").write_text("MODIFIED CONTENT")
        changed = memory.changed_since_snapshot(["src/auth.py"], baseline)
        assert "src/auth.py" in changed

    def test_new_file_detected(self, memory, work_dir):
        """File not in baseline is detected as changed."""
        baseline = memory.snapshot(["src/auth.py"])
        (work_dir / "src" / "new.py").write_text("new file")
        changed = memory.changed_since_snapshot(["src/new.py"], baseline)
        assert "src/new.py" in changed

    def test_deleted_file_detected(self, memory, work_dir):
        """Deleted file is detected as changed."""
        baseline = memory.snapshot(["src/auth.py"])
        (work_dir / "src" / "auth.py").unlink()
        changed = memory.changed_since_snapshot(["src/auth.py"], baseline)
        assert "src/auth.py" in changed


# ============================================================================
# History Recording Tests (5 tests)
# ============================================================================


class TestHistoryRecording:
    """MemoryEntry recording and retrieval."""

    def test_record_creates_entry(self, memory):
        """record() adds a MemoryEntry to history."""
        entry = memory.record(
            attempt=0,
            diff_applied="--- a/f.py\n+++ b/f.py",
            result_exit_code=0,
            test_output="5 passed",
            modified_files=["f.py"],
        )
        assert isinstance(entry, MemoryEntry)
        assert len(memory.history) == 1

    def test_multiple_records(self, memory):
        """Multiple records are appended in order."""
        for i in range(3):
            memory.record(
                attempt=i,
                diff_applied=f"diff-{i}",
                result_exit_code=i,
                test_output=f"output-{i}",
                modified_files=[f"file-{i}.py"],
            )
        assert memory.attempt_count == 3
        assert memory.history[0].attempt == 0
        assert memory.history[2].attempt == 2

    def test_history_is_copy(self, memory):
        """history property returns a copy, not the internal list."""
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=0,
            test_output="", modified_files=[],
        )
        h = memory.history
        h.clear()
        assert memory.attempt_count == 1  # internal not affected

    def test_clear_resets_history(self, memory):
        """clear() removes all entries."""
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=0,
            test_output="", modified_files=[],
        )
        memory.clear()
        assert memory.attempt_count == 0

    def test_entry_to_dict(self):
        """MemoryEntry.to_dict() is JSON-serializable."""
        entry = MemoryEntry(
            attempt=1, diff_applied="diff", result_exit_code=1,
            test_output="fail", modified_files=["a.py"],
            error_message="AssertionError",
        )
        d = entry.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)


# ============================================================================
# Error Context Tests (4 tests)
# ============================================================================


class TestErrorContext:
    """Error context generation for FIX->GENERATE re-entry."""

    def test_error_context_empty_when_no_history(self, memory):
        """No history returns empty string."""
        assert memory.error_context_for_retry() == ""

    def test_error_context_includes_exit_code(self, memory):
        """Error context mentions exit code."""
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=1,
            test_output="FAILED", modified_files=["a.py"],
            error_message="AssertionError: x != y",
        )
        ctx = memory.error_context_for_retry()
        assert "exit_code=1" in ctx

    def test_error_context_includes_error_message(self, memory):
        """Error context includes the error message."""
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=1,
            test_output="", modified_files=[],
            error_message="KeyError: 'session'",
        )
        ctx = memory.error_context_for_retry()
        assert "KeyError" in ctx

    def test_error_context_truncates_test_output(self, memory):
        """Error context truncates test output to 2000 chars."""
        long_output = "x" * 5000
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=1,
            test_output=long_output, modified_files=[],
        )
        ctx = memory.error_context_for_retry()
        # The truncated output should be <= 2000 chars of test output
        assert "last 2000 chars" in ctx


# ============================================================================
# Summary Tests (2 tests)
# ============================================================================


class TestSummary:
    """summary() output."""

    def test_summary_structure(self, memory):
        """summary() returns dict with expected keys."""
        s = memory.summary()
        assert "total_attempts" in s
        assert "working_dir" in s
        assert "entries" in s

    def test_summary_json_serializable(self, memory):
        """summary() is JSON-serializable."""
        memory.record(
            attempt=0, diff_applied="d", result_exit_code=0,
            test_output="pass", modified_files=["f.py"],
        )
        serialized = json.dumps(memory.summary())
        assert isinstance(serialized, str)
