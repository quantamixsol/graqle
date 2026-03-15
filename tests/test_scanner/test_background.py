"""Tests for graqle.scanner.background — background scan manager."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_background
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, time, dataclasses, pathlib +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from graqle.scanner.background import BackgroundScanManager, ScanProgress


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path


@dataclass
class _MockResult:
    nodes_added: int = 5
    edges_added: int = 3


# ---------------------------------------------------------------------------
# ScanProgress
# ---------------------------------------------------------------------------


class TestScanProgress:
    def test_defaults(self) -> None:
        p = ScanProgress()
        assert p.status == "idle"
        assert p.total == 0
        assert p.processed == 0
        assert p.errors == []

    def test_custom_values(self) -> None:
        p = ScanProgress(status="running", total=10, processed=3)
        assert p.status == "running"
        assert p.total == 10


# ---------------------------------------------------------------------------
# Manager construction
# ---------------------------------------------------------------------------


class TestManagerConstruction:
    def test_initial_state(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)
        assert not mgr.is_running
        progress = mgr.get_progress()
        assert progress.status == "idle"


# ---------------------------------------------------------------------------
# Start / complete
# ---------------------------------------------------------------------------


class TestStartComplete:
    def test_start_and_complete(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def scanner_fn(progress_cb):
            for i in range(3):
                progress_cb(Path(f"file_{i}.md"), i, 3)
                time.sleep(0.01)
            return _MockResult()

        mgr.start(scanner_fn, total_files=3)
        assert mgr.is_running

        # Wait for completion
        result = mgr.wait(timeout=5)
        assert result.status == "completed"
        assert result.nodes_added == 5
        assert result.edges_added == 3
        assert not mgr.is_running

    def test_progress_during_scan(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)
        started = False

        def scanner_fn(progress_cb):
            nonlocal started
            started = True
            progress_cb(Path("a.md"), 0, 2)
            time.sleep(0.1)
            progress_cb(Path("b.md"), 1, 2)
            return _MockResult()

        mgr.start(scanner_fn, total_files=2)
        time.sleep(0.05)
        assert started
        mgr.wait(timeout=5)

    def test_double_start_raises(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def slow_fn(cb):
            time.sleep(1)
            return _MockResult()

        mgr.start(slow_fn, total_files=1)
        with pytest.raises(RuntimeError, match="already running"):
            mgr.start(slow_fn, total_files=1)
        mgr.cancel()
        mgr.wait(timeout=5)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_cancel_stops_scan(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)
        processed_count = 0

        def scanner_fn(progress_cb):
            nonlocal processed_count
            for i in range(100):
                progress_cb(Path(f"file_{i}.md"), i, 100)
                processed_count += 1
                time.sleep(0.01)
            return _MockResult()

        mgr.start(scanner_fn, total_files=100)
        time.sleep(0.05)
        mgr.cancel()
        result = mgr.wait(timeout=5)

        assert result.status == "cancelled"
        assert processed_count < 100  # Should have stopped early


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_scanner_exception(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def failing_fn(progress_cb):
            raise ValueError("Parse error in file")

        mgr.start(failing_fn, total_files=1)
        result = mgr.wait(timeout=5)

        assert result.status == "failed"
        assert len(result.errors) >= 1
        assert "Parse error" in result.errors[0]


# ---------------------------------------------------------------------------
# State file persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_state_file_written(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def scanner_fn(progress_cb):
            progress_cb(Path("x.md"), 0, 1)
            return _MockResult()

        mgr.start(scanner_fn, total_files=1)
        mgr.wait(timeout=5)

        state_file = state_dir / ".graqle-scan-state.json"
        assert state_file.is_file()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert data["nodes_added"] == 5

    def test_cross_process_progress(self, state_dir: Path) -> None:
        """A second manager instance can read the state file."""
        mgr1 = BackgroundScanManager(state_dir)

        def scanner_fn(progress_cb):
            return _MockResult()

        mgr1.start(scanner_fn, total_files=1)
        mgr1.wait(timeout=5)

        # Second instance reads state from file
        mgr2 = BackgroundScanManager(state_dir)
        progress = mgr2.get_progress()
        assert progress.status == "completed"
        assert progress.nodes_added == 5


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_removes_state(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def scanner_fn(progress_cb):
            return _MockResult()

        mgr.start(scanner_fn, total_files=1)
        mgr.wait(timeout=5)

        state_file = state_dir / ".graqle-scan-state.json"
        assert state_file.is_file()

        mgr.cleanup()
        assert not state_file.is_file()

    def test_cleanup_noop_no_file(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)
        mgr.cleanup()  # Should not raise


# ---------------------------------------------------------------------------
# Wait timeout
# ---------------------------------------------------------------------------


class TestWaitTimeout:
    def test_wait_returns_on_complete(self, state_dir: Path) -> None:
        mgr = BackgroundScanManager(state_dir)

        def scanner_fn(progress_cb):
            return _MockResult()

        mgr.start(scanner_fn, total_files=1)
        result = mgr.wait(timeout=5)
        assert result.status == "completed"
