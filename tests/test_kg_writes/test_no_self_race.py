"""T04 (v0.51.6) — KG-write self-race regression.

Acceptance per .gcc/branches/hotfix-v0.51.6/EXECUTION-PATH.md §T04:
  100 sequential _write_with_lock calls from one thread = 0 WRITE_COLLISION.
Plus a re-entrancy test: predict -> auto_grow -> learn must not deadlock
on the module-level RLock (predict-confirmed risk).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from graqle.core.graph import (
    _write_with_lock,
    kg_diag_snapshot,
)


def _minimal_graph_payload(n_nodes: int = 1) -> str:
    """Smallest valid graqle JSON the shrink-guard accepts."""
    return json.dumps({
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": f"n{i}", "label": f"N{i}"} for i in range(n_nodes)],
        "links": [],
    })


class TestSequentialWritesNoCollision:
    """The headline T04 acceptance: 100 sequential writes from one thread."""

    @pytest.mark.timeout(30)
    def test_100_sequential_writes_zero_collisions(self, tmp_path: Path):
        target = tmp_path / "graqle.json"
        # Seed with 100-node payload so shrink-guard never blocks subsequent writes
        target.write_text(_minimal_graph_payload(100), encoding="utf-8")

        attempts_log = []
        for i in range(100):
            # Each write keeps node count steady at 100 (shrink-guard happy)
            attempts = _write_with_lock(str(target), _minimal_graph_payload(100))
            attempts_log.append(attempts)

        # Zero retries means zero collisions — the headline acceptance
        assert all(a == 0 for a in attempts_log), (
            f"Some writes needed retries: {[i for i, a in enumerate(attempts_log) if a > 0]}"
        )

    @pytest.mark.timeout(30)
    def test_diag_snapshot_records_writes(self, tmp_path: Path):
        target = tmp_path / "graqle.json"
        target.write_text(_minimal_graph_payload(100), encoding="utf-8")
        for _ in range(5):
            _write_with_lock(str(target), _minimal_graph_payload(100))

        snap = kg_diag_snapshot()
        assert snap["total_writes_recorded"] >= 5
        # Most recent write should be present and have caller info
        recent = snap["recent_writes"]
        assert len(recent) >= 5
        last = recent[-1]
        assert last["outcome"] == "OK"
        assert last["attempts"] == 0
        assert "caller" in last
        assert "func" in last["caller"]


class TestReentrantSelfCallNoDeadlock:
    """T04 re-entrancy guard.

    Predict-confirmed risk: graq_predict(fold_back=True) calls auto_grow which
    calls graq_learn — all three hit _write_with_lock on the same file. With a
    plain (non-reentrant) Lock, the second acquire deadlocks. Module-level
    threading.RLock allows the same thread to re-acquire safely.
    """

    @pytest.mark.timeout(15)
    def test_reentrant_call_completes(self, tmp_path: Path):
        target = tmp_path / "graqle.json"
        target.write_text(_minimal_graph_payload(100), encoding="utf-8")

        completed = []

        def outer_then_inner():
            # Simulate predict -> auto_grow -> learn: outer write, then while
            # holding the path's RLock, an inner write to the same path.
            from graqle.core.graph import _get_thread_lock
            lock = _get_thread_lock(str(target))
            with lock:
                # Outer caller is "holding" the RLock conceptually
                _write_with_lock(str(target), _minimal_graph_payload(100))
                # Inner re-entry on the same thread + same file — must not deadlock
                _write_with_lock(str(target), _minimal_graph_payload(100))
                completed.append(True)

        t = threading.Thread(target=outer_then_inner)
        t.start()
        t.join(timeout=10)

        assert not t.is_alive(), "Thread deadlocked on re-entrant RLock acquire"
        assert completed == [True]


class TestErrorMessageNamesActualWriter:
    """T04 error-message contract — surface the suspected writer.

    When the budget is exhausted, the error must NOT claim 'another MCP
    client may be writing concurrently' (the misleading v0.51.5 text).
    Instead it must include the caller stack and the suspected_writer hint.
    """

    @pytest.mark.timeout(20)
    def test_error_message_format(self, tmp_path: Path, monkeypatch):
        # Force the budget down so a single forced PermissionError exhausts it
        monkeypatch.setenv("GRAQLE_WRITE_RETRY_BUDGET_MS", "10")

        target = tmp_path / "graqle.json"
        target.write_text(_minimal_graph_payload(100), encoding="utf-8")

        # Patch os.replace to always raise PermissionError, simulating Windows lock
        import os as os_mod
        original_replace = os_mod.replace
        call_count = {"n": 0}

        def always_collide(src, dst):
            call_count["n"] += 1
            raise PermissionError("simulated WinError 5")

        monkeypatch.setattr(os_mod, "replace", always_collide)

        with pytest.raises(PermissionError) as exc_info:
            _write_with_lock(str(target), _minimal_graph_payload(100))

        msg = str(exc_info.value)
        # New message format requirements
        assert "retry budget exhausted" in msg, msg
        assert "caller=" in msg, msg
        assert "graq_kg_diag" in msg, msg
        # Must NOT contain the misleading old text
        assert "another MCP client" not in msg, msg
