"""Tests for the AnchoringWorker scheduler (ADR-221 §4.4 / R2-PR1).

The worker is pure scheduling over the shipped Committer + LocalReplayQueue, so these
tests use lightweight fakes (the worker only touches flush()/status_counts()/drain()/depth)
and an injected clock — deterministic, no real Merkle/Rekor.
"""

from __future__ import annotations

import threading

import pytest

from graqle.governance.tamper_evidence.worker import (
    AnchoringWorker,
    WorkerError,
    WorkerHealth,
)


class _Cfg:
    """Minimal stand-in for AttestationConfig (only the fields the worker reads)."""

    def __init__(self, *, fail_open=False, batch_max_seconds=5):
        self.fail_open_on_anchor_error = fail_open
        self.batch_max_seconds = batch_max_seconds


class _FakeCommitter:
    def __init__(self, flush_returns=None, status=None, raise_on_flush=False):
        self._flush_returns = list(flush_returns or [])
        self.flush_calls = 0
        self._status = status or {"PENDING": 0, "ANCHORED": 0}
        self._raise_on_flush = raise_on_flush

    def flush(self) -> int:
        self.flush_calls += 1
        if self._raise_on_flush:
            raise RuntimeError("flush boom")
        if self._flush_returns:
            return self._flush_returns.pop(0)
        return 0

    def status_counts(self) -> dict:
        return dict(self._status)


class _FakeReplayQueue:
    def __init__(self, drain_returns=None, depth=0, raise_on_drain=False):
        self._drain_returns = list(drain_returns or [])
        self.drain_calls = 0
        self._depth = depth
        self._raise_on_drain = raise_on_drain

    def drain(self, max_items=None) -> int:
        self.drain_calls += 1
        if self._raise_on_drain:
            raise RuntimeError("rekor down")
        if self._drain_returns:
            return self._drain_returns.pop(0)
        return 0

    @property
    def depth(self) -> int:
        return self._depth


class _Clock:
    """Deterministic monotonic clock; advance() steps it."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt):
        self.t += dt


# -- construction / fail-closed precondition ---------------------------------


class TestConstruction:
    def test_rejects_fail_open_config(self):
        with pytest.raises(WorkerError, match="fail_open_on_anchor_error=False"):
            AnchoringWorker(_FakeCommitter(), _Cfg(fail_open=True))

    def test_rejects_non_positive_tick(self):
        with pytest.raises(WorkerError, match="tick_seconds must be > 0"):
            AnchoringWorker(_FakeCommitter(), _Cfg(), tick_seconds=0)

    def test_default_tick_from_config(self):
        w = AnchoringWorker(_FakeCommitter(), _Cfg(batch_max_seconds=12))
        assert w._tick_seconds == 12.0

    def test_explicit_tick_overrides_config(self):
        w = AnchoringWorker(_FakeCommitter(), _Cfg(batch_max_seconds=12), tick_seconds=2)
        assert w._tick_seconds == 2.0


# -- tick --------------------------------------------------------------------


class TestTick:
    def test_tick_flushes_and_counts(self):
        c = _FakeCommitter(flush_returns=[3])
        w = AnchoringWorker(c, _Cfg(), clock=_Clock())
        committed = w.tick()
        assert committed == 3
        assert c.flush_calls == 1
        h = w.health()
        assert h.records_committed == 3 and h.records_anchored == 3 and h.ticks == 1

    def test_tick_drains_replay_queue(self):
        c = _FakeCommitter(flush_returns=[0])
        rq = _FakeReplayQueue(drain_returns=[2], depth=5)
        w = AnchoringWorker(c, _Cfg(), replay_queue=rq, clock=_Clock())
        w.tick()
        assert rq.drain_calls == 1
        assert w.health().backfill_count == 2

    def test_tick_passes_drain_max_items(self):
        captured = {}
        rq = _FakeReplayQueue()
        orig = rq.drain
        def spy(max_items=None):
            captured["max_items"] = max_items
            return orig(max_items=max_items)
        rq.drain = spy
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), replay_queue=rq, drain_max_items=7)
        w.tick()
        assert captured["max_items"] == 7

    def test_tick_drain_error_is_recorded_not_raised(self):
        rq = _FakeReplayQueue(raise_on_drain=True)
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), replay_queue=rq, clock=_Clock())
        w.tick()  # must not raise
        assert w.health().last_error_type == "RuntimeError"

    def test_tick_without_replay_queue(self):
        w = AnchoringWorker(_FakeCommitter(flush_returns=[1]), _Cfg(), clock=_Clock())
        assert w.tick() == 1  # no replay queue -> just flushes

    def test_last_anchor_time_updates_on_work(self):
        clk = _Clock()
        w = AnchoringWorker(_FakeCommitter(flush_returns=[0, 1]), _Cfg(), clock=clk)
        w.tick()  # 0 committed -> no anchor timestamp
        assert w.health().seconds_since_last_anchor is None
        clk.advance(10)
        w.tick()  # 1 committed -> timestamp set
        clk.advance(4)
        assert w.health().seconds_since_last_anchor == 4.0


# -- run loop ----------------------------------------------------------------


class TestRunLoop:
    def test_run_max_ticks(self):
        c = _FakeCommitter(flush_returns=[1, 1, 1])
        # sleep injected as no-op so the loop runs instantly
        w = AnchoringWorker(c, _Cfg(), tick_seconds=0.01, clock=_Clock(), sleep=lambda s: None)
        w.run(max_ticks=3)
        # 3 loop ticks + 1 shutdown flush = 4 flush calls
        assert c.flush_calls == 4
        assert w.health().ticks == 3
        assert not w.health().running

    def test_run_already_running_guard(self):
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), tick_seconds=0.01, sleep=lambda s: None)
        with w._lock:
            w._running = True
        with pytest.raises(WorkerError, match="already running"):
            w.run(max_ticks=1)

    def test_stop_breaks_loop(self):
        c = _FakeCommitter(flush_returns=[0] * 100)
        w = AnchoringWorker(c, _Cfg(), tick_seconds=5, clock=_Clock())
        # stop() before run -> the event is set, loop runs one tick then exits at the wait
        t = threading.Thread(target=w.run)
        w.stop()
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()
        assert not w.health().running

    def test_shutdown_final_flush_counts(self):
        c = _FakeCommitter(flush_returns=[0, 2])  # tick=0, shutdown flush=2
        w = AnchoringWorker(c, _Cfg(), tick_seconds=0.01, clock=_Clock(), sleep=lambda s: None)
        w.run(max_ticks=1)
        assert w.health().records_committed == 2  # the shutdown flush sealed 2

    def test_shutdown_flush_error_surfaced_not_raised(self):
        class _C(_FakeCommitter):
            def __init__(self):
                super().__init__(flush_returns=[0])
                self._calls = 0
            def flush(self):
                self._calls += 1
                if self._calls >= 2:  # the shutdown flush raises
                    raise RuntimeError("shutdown boom")
                return 0
        w = AnchoringWorker(_C(), _Cfg(), tick_seconds=0.01, clock=_Clock(), sleep=lambda s: None)
        w.run(max_ticks=1)  # must not raise
        assert w.health().last_error_type == "RuntimeError"
        assert not w.health().running


# -- health ------------------------------------------------------------------


class TestHealth:
    def test_health_snapshot_shape(self):
        rq = _FakeReplayQueue(depth=4)
        c = _FakeCommitter(status={"PENDING": 1, "ANCHORED": 9})
        w = AnchoringWorker(c, _Cfg(), replay_queue=rq, clock=_Clock())
        h = w.health()
        assert isinstance(h, WorkerHealth)
        assert h.replay_queue_depth == 4
        assert h.status_counts == {"PENDING": 1, "ANCHORED": 9}
        d = h.to_dict()
        assert d["replay_queue_depth"] == 4 and d["running"] is False
        assert set(d) == {
            "running", "ticks", "records_committed", "records_anchored",
            "backfill_count", "replay_queue_depth", "seconds_since_last_anchor",
            "last_error_type", "status_counts",
        }

    def test_health_depth_unavailable_sentinel(self):
        rq = _FakeReplayQueue()
        type(rq).depth = property(lambda self: (_ for _ in ()).throw(RuntimeError("disk gone")))
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), replay_queue=rq, clock=_Clock())
        assert w.health().replay_queue_depth == -1

    def test_health_status_counts_error_empty(self):
        class _C(_FakeCommitter):
            def status_counts(self):
                raise RuntimeError("no committer state")
        w = AnchoringWorker(_C(), _Cfg(), clock=_Clock())
        assert w.health().status_counts == {}

    def test_health_no_replay_queue_depth_zero(self):
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), clock=_Clock())
        assert w.health().replay_queue_depth == 0


# -- shutdown flush timeout ---------------------------------------------------


class TestShutdownFlushTimeout:
    def test_rejects_non_positive_timeout(self):
        with pytest.raises(WorkerError, match="shutdown_flush_timeout_seconds"):
            AnchoringWorker(_FakeCommitter(), _Cfg(), shutdown_flush_timeout_seconds=0)

    def test_allows_none_timeout(self):
        # None disables the cap (operator opt-in to unbounded wait).
        w = AnchoringWorker(_FakeCommitter(), _Cfg(), shutdown_flush_timeout_seconds=None)
        assert w._shutdown_flush_timeout is None

    def test_hanging_shutdown_flush_times_out(self):
        """A flush that never returns must NOT block run() from exiting."""
        import time as _time

        class _HangCommitter(_FakeCommitter):
            def __init__(self):
                super().__init__(flush_returns=[0])
                self._calls = 0

            def flush(self):
                self._calls += 1
                if self._calls >= 2:  # the shutdown flush hangs
                    _time.sleep(10)  # would block forever without the timeout
                return 0

        w = AnchoringWorker(
            _HangCommitter(), _Cfg(), tick_seconds=0.01, clock=_Clock(),
            sleep=lambda s: None, shutdown_flush_timeout_seconds=0.1,
        )
        start = _time.monotonic()
        w.run(max_ticks=1)
        elapsed = _time.monotonic() - start
        assert elapsed < 2.0, f"shutdown blocked for {elapsed}s (timeout did not fire)"
        assert w.health().last_error_type == "TimeoutError"
        assert not w.health().running

    def test_normal_shutdown_flush_records_committed_count(self):
        # Sanity: the timeout path does not break the happy path (parity with earlier
        # test_shutdown_final_flush_counts; the refactor still records the committed count).
        c = _FakeCommitter(flush_returns=[0, 3])
        w = AnchoringWorker(c, _Cfg(), tick_seconds=0.01, clock=_Clock(), sleep=lambda s: None)
        w.run(max_ticks=1)
        assert w.health().records_committed == 3
