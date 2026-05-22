"""Tests for the durable local replay queue (v0.59.0 PR-4, R25-EU01 CONDITION-3).

Deterministic + offline: a fake anchor (success / fail / flaky) is injected, and
the breaker clock is injected so cooldowns are exact. Covers durability + FIFO,
the 5-state overflow protocol, the independent circuit-breaker, integrity checks,
on_queue_full policy, audited operator override, and recovery/drain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.config.attestation_config import ReplayQueueConfig
from graqle.governance.tamper_evidence.anchors.sigstore_rekor import (
    AnchorError,
    RekorReceipt,
)
from graqle.governance.tamper_evidence.local_replay_queue import (
    BreakerState,
    LocalReplayQueue,
    OverflowState,
    QueueFullError,
    QueuedRoot,
    ReplayQueueError,
    _checksum,
)


# ---- fakes / helpers ----------------------------------------------------------


def _receipt() -> RekorReceipt:
    return RekorReceipt(1, "logid", "sth", "cert", 1_700_000_000)


class _OkAnchor:
    available = True

    def __init__(self):
        self.anchored: list[bytes] = []

    def anchor(self, root_bytes: bytes) -> RekorReceipt:
        self.anchored.append(root_bytes)
        return _receipt()


class _FailAnchor:
    available = True

    def __init__(self):
        self.calls = 0

    def anchor(self, root_bytes: bytes) -> RekorReceipt:
        self.calls += 1
        raise AnchorError("rekor down")


class _FlakyAnchor:
    """Fails until `fail_until` calls have happened, then succeeds."""

    available = True

    def __init__(self, fail_until: int):
        self.fail_until = fail_until
        self.calls = 0

    def anchor(self, root_bytes: bytes) -> RekorReceipt:
        self.calls += 1
        if self.calls <= self.fail_until:
            raise AnchorError(f"transient {self.calls}")
        return _receipt()


class _FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float):
        self.t += dt


def _cfg(**over) -> ReplayQueueConfig:
    # NOTE: ReplayQueueConfig enforces max_entries >= 100 (PR-0). Tests that
    # exercise overflow RATIOS use the smallest legal value (100) and fill
    # proportionally; the pure ratio->state mapping is unit-tested directly via
    # _compute_state(count) without persisting 100 files.
    base = dict(
        directory=".graqle/replay_queue/",
        max_entries=100,
        integrity_check=True,
        max_retries=3,
        retry_backoff_seconds=[5, 30, 300],
        on_queue_full="pause_writes",
    )
    base.update(over)
    return ReplayQueueConfig(**base)


def _root_hex(i: int) -> str:
    return f"{i:064x}"


def _entries(q_root: Path) -> list[Path]:
    d = Path(q_root) / "replay_queue"
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.name.endswith(".json") and not p.name.startswith("."))


# ---- separation from the WAL --------------------------------------------------


def test_queue_dir_is_replay_queue_not_uncommitted(tmp_path):
    """The replay queue lives in replay_queue/, never the WAL's uncommitted/."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    assert q.queue_dir == Path(tmp_path) / "replay_queue"
    assert q.queue_dir.is_dir()
    assert "uncommitted" not in str(q.queue_dir)


# ---- durable enqueue + FIFO ---------------------------------------------------


def test_enqueue_persists_entry(tmp_path):
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    state = q.enqueue(_root_hex(1), batch_id="b1")
    assert state == OverflowState.NORMAL
    assert q.depth == 1
    assert len(_entries(tmp_path)) == 1


def test_enqueue_rejects_empty_root(tmp_path):
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    with pytest.raises(ReplayQueueError, match="non-empty"):
        q.enqueue("", batch_id="b1")


def test_entries_drain_in_fifo_seq_order(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor)
    for i in range(5):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    drained = q.drain()
    assert drained == 5
    assert q.depth == 0
    # FIFO: anchored in enqueue order 0..4
    assert anchor.anchored == [bytes.fromhex(_root_hex(i)) for i in range(5)]


def test_seq_survives_restart(tmp_path):
    """A new queue instance over the same dir continues the sequence (durable order)."""
    q1 = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    q1.enqueue(_root_hex(1), batch_id="b1")
    q1.enqueue(_root_hex(2), batch_id="b2")
    q2 = LocalReplayQueue(_cfg(), queue_root=tmp_path)  # "restart"
    q2.enqueue(_root_hex(3), batch_id="b3")
    seqs = sorted(int(p.name.split("-", 1)[0]) for p in _entries(tmp_path))
    assert seqs == [1, 2, 3]  # contiguous, no collision


# ---- drain requires an anchor -------------------------------------------------


def test_drain_without_anchor_raises(tmp_path):
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)  # no anchor
    q.enqueue(_root_hex(1), batch_id="b1")
    with pytest.raises(ReplayQueueError, match="no anchor"):
        q.drain()


def test_drain_max_items_limits_batch(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor)
    for i in range(5):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    assert q.drain(max_items=2) == 2
    assert q.depth == 3


# ---- on_queue_full policy -----------------------------------------------------


def test_on_queue_full_reject_raises_and_does_not_persist(tmp_path):
    q = LocalReplayQueue(_cfg(max_entries=100, on_queue_full="reject"), queue_root=tmp_path)
    for i in range(100):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    with pytest.raises(QueueFullError):
        q.enqueue(_root_hex(100), batch_id="b100")
    assert q.depth == 100  # overflow not persisted


def test_on_queue_full_pause_persists_and_signals_pause(tmp_path):
    """pause_writes NEVER drops a root: it persists AND returns PAUSE (AC-9)."""
    q = LocalReplayQueue(_cfg(max_entries=100, on_queue_full="pause_writes"), queue_root=tmp_path)
    for i in range(100):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    state = q.enqueue(_root_hex(100), batch_id="b100")
    assert state == OverflowState.PAUSE
    assert q.depth == 101  # root WAS persisted despite full queue


# ---- 5-state overflow protocol (ratio->state mapping, unit-tested directly) ----
#
# _compute_state(count) is the pure mapping; testing it directly avoids
# persisting 100 files per ratio while still exercising every branch realistically.


def test_compute_state_ratios_closed_breaker(tmp_path):
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path)
    assert q._compute_state(0) == OverflowState.NORMAL
    assert q._compute_state(40) == OverflowState.NORMAL    # 40% < 50%
    assert q._compute_state(50) == OverflowState.DEGRADED  # 50%
    assert q._compute_state(79) == OverflowState.DEGRADED  # <80%
    assert q._compute_state(80) == OverflowState.ALERT     # 80%
    assert q._compute_state(99) == OverflowState.ALERT     # <100%
    assert q._compute_state(100) == OverflowState.PAUSE    # full


def test_compute_state_max_entries_zero_is_safe(tmp_path):
    """Guard the divide-by-zero branch: a 0 ceiling never raises."""
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path)
    # Force the ceiling to 0 to hit the `if max_entries else 0.0` guard.
    object.__setattr__(q._config, "max_entries", 0)
    # count >= 0 (== max_entries) -> PAUSE per the full check.
    assert q._compute_state(0) == OverflowState.PAUSE


def test_state_reflects_real_depth(tmp_path):
    """The `state` property uses the real on-disk depth (integration sanity)."""
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path)
    for i in range(50):  # 50% -> DEGRADED
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    assert q.state == OverflowState.DEGRADED


def test_state_recovery_while_breaker_open_and_draining(tmp_path):
    """With the breaker tripped and the queue low-but-nonzero, state is RECOVERY."""
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(20):  # 20% (< recovery_ratio 25%) but nonzero
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # all fail -> breaker opens after threshold
    assert q.breaker_state == BreakerState.OPEN
    # Breaker open + queue nonzero below recovery_ratio -> RECOVERY.
    assert q.state == OverflowState.RECOVERY


def test_compute_state_breaker_open_ratio_bands(tmp_path):
    """Breaker-open branch covers ALERT/DEGRADED/RECOVERY bands too."""
    clock = _FakeClock()
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=_FailAnchor(), clock=clock)
    q._breaker.state = BreakerState.OPEN
    assert q._compute_state(85) == OverflowState.ALERT      # >=80% while open
    assert q._compute_state(60) == OverflowState.DEGRADED   # >=50% while open
    assert q._compute_state(30) == OverflowState.RECOVERY   # >25% while open
    assert q._compute_state(10) == OverflowState.RECOVERY   # <=25% but nonzero
    assert q._compute_state(0) == OverflowState.NORMAL      # empty while open


# ---- circuit-breaker ----------------------------------------------------------


def test_breaker_opens_after_threshold_failures(tmp_path):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(5):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()
    assert q.breaker_state == BreakerState.OPEN
    # The breaker stops the drain early: not all 5 were attempted.
    assert anchor.calls >= 3  # opened at the threshold


def test_breaker_open_suppresses_drain(tmp_path):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(4):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # opens breaker
    calls_after_open = anchor.calls
    # While still in cooldown, a second drain does nothing (no new anchor calls).
    assert q.drain() == 0
    assert anchor.calls == calls_after_open


def test_breaker_half_opens_after_cooldown_and_closes_on_success(tmp_path):
    clock = _FakeClock()
    anchor = _FlakyAnchor(fail_until=3)  # first 3 fail (open breaker), then succeed
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(5):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # 3 failures -> OPEN
    assert q.breaker_state == BreakerState.OPEN
    # Advance past cooldown -> next drain half-opens, probe succeeds -> CLOSED.
    clock.advance(31.0)
    q.drain()
    assert q.breaker_state == BreakerState.CLOSED
    assert q.depth == 0  # remaining roots drained once breaker closed


def test_breaker_reopens_if_probe_fails(tmp_path):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(4):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # OPEN
    clock.advance(31.0)
    q.drain()  # half-open probe fails -> re-OPEN
    assert q.breaker_state == BreakerState.OPEN


# ---- per-entry retry / max_retries --------------------------------------------


def test_failed_entry_bumps_attempts_and_is_retained(tmp_path):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100, max_retries=3), queue_root=tmp_path, anchor=anchor, clock=clock)
    q.enqueue(_root_hex(1), batch_id="b1")
    q.drain()
    # The single entry stays (never dropped); its attempt counter incremented.
    assert q.depth == 1
    entry = _entries(tmp_path)[0]
    data = json.loads(entry.read_text())
    assert data["attempts"] == 1


def test_entry_exceeding_max_retries_is_retained_for_operator(tmp_path):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100, max_retries=1), queue_root=tmp_path, anchor=anchor, clock=clock)
    q.enqueue(_root_hex(1), batch_id="b1")
    # Drain repeatedly; reset breaker each time so the entry keeps being tried.
    for _ in range(3):
        q.drain()
        q.operator_override("reset_breaker", reason="test forced retry")
    # Even past max_retries the root is NEVER dropped.
    assert q.depth == 1


# ---- integrity checks ---------------------------------------------------------


def test_integrity_check_skips_tampered_entry(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(integrity_check=True), queue_root=tmp_path, anchor=anchor)
    q.enqueue(_root_hex(1), batch_id="b1")
    # Tamper with the persisted entry's root, leaving the stale checksum.
    entry = _entries(tmp_path)[0]
    data = json.loads(entry.read_text())
    data["root_hex"] = _root_hex(999)  # checksum no longer matches
    entry.write_text(json.dumps(data))
    # Drain: the tampered entry fails integrity -> skipped, not anchored.
    assert q.drain() == 0
    assert anchor.anchored == []


def test_integrity_disabled_accepts_entry_without_checksum(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(integrity_check=False), queue_root=tmp_path, anchor=anchor)
    q.enqueue(_root_hex(1), batch_id="b1")
    entry = _entries(tmp_path)[0]
    assert "checksum" not in json.loads(entry.read_text())
    assert q.drain() == 1


def test_corrupt_json_entry_is_skipped(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor)
    qdir = Path(tmp_path) / "replay_queue"
    (qdir / f"{'0'*12}-{_root_hex(1)}.json").write_text("{ not json")
    assert q.drain() == 0
    assert anchor.anchored == []


def test_read_entry_missing_required_field_skipped(tmp_path):
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(integrity_check=False), queue_root=tmp_path, anchor=anchor)
    qdir = Path(tmp_path) / "replay_queue"
    (qdir / f"{'0'*12}-{_root_hex(1)}.json").write_text(json.dumps({"seq": 1}))  # no root_hex
    assert q.drain() == 0


# ---- audited operator override ------------------------------------------------


def test_operator_override_reset_breaker(tmp_path, caplog):
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(4):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()
    assert q.breaker_state == BreakerState.OPEN
    with caplog.at_level("WARNING"):
        q.operator_override("reset_breaker", reason="manual recovery")
    assert q.breaker_state == BreakerState.CLOSED
    assert any("OPERATOR OVERRIDE reset_breaker" in r.message for r in caplog.records)


def test_operator_override_clear_pause_is_audited(tmp_path, caplog):
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    with caplog.at_level("WARNING"):
        q.operator_override("clear_pause", reason="ack")
    assert any("OPERATOR OVERRIDE clear_pause" in r.message for r in caplog.records)


def test_operator_override_unknown_action_raises(tmp_path):
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    with pytest.raises(ReplayQueueError, match="unknown operator override"):
        q.operator_override("delete_everything", reason="nope")


# ---- recovery: Rekor returns, queue drains ------------------------------------


def test_full_recovery_cycle(tmp_path):
    """Rekor down -> queue fills -> Rekor up -> queue drains to empty (NORMAL)."""
    clock = _FakeClock()
    anchor = _FlakyAnchor(fail_until=3)
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(6):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # breaker opens after 3 failures
    assert q.breaker_state == BreakerState.OPEN
    clock.advance(31.0)
    q.drain()  # half-open probe succeeds -> drains the rest
    assert q.depth == 0
    assert q.state == OverflowState.NORMAL


# ---- checksum helper ----------------------------------------------------------


def test_checksum_is_stable_and_order_independent(tmp_path):
    a = {"seq": 1, "root_hex": "ab", "batch_id": "b"}
    b = {"batch_id": "b", "root_hex": "ab", "seq": 1}  # different key order
    assert _checksum(a) == _checksum(b)


def test_queued_root_dataclass_defaults():
    qr = QueuedRoot(seq=1, root_hex="ab", batch_id="b")
    assert qr.attempts == 0
    assert qr.metadata == {}


# ---- coverage completion: realistic defensive-path exercise -------------------


def test_half_open_probe_path_allows_attempt(tmp_path):
    """A drain while the breaker is already HALF_OPEN proceeds with the probe."""
    clock = _FakeClock()
    anchor = _FlakyAnchor(fail_until=3)
    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path, anchor=anchor, clock=clock)
    for i in range(4):
        q.enqueue(_root_hex(i), batch_id=f"b{i}")
    q.drain()  # OPEN
    # Manually set HALF_OPEN to exercise the half-open allow-attempt branch.
    q._breaker.state = BreakerState.HALF_OPEN
    q.drain()  # half-open probe (call 4) succeeds -> CLOSED, drains rest
    assert q.breaker_state == BreakerState.CLOSED
    assert q.depth == 0


def test_bump_attempts_rewrites_entry_with_incremented_counter(tmp_path):
    """A failed-but-retryable entry is rewritten in place with attempts+1."""
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100, max_retries=5), queue_root=tmp_path, anchor=anchor, clock=clock)
    q.enqueue(_root_hex(1), batch_id="b1")
    q.drain()  # 1 failure -> bump to attempts=1
    data = json.loads(_entries(tmp_path)[0].read_text())
    assert data["attempts"] == 1
    assert data["root_hex"] == _root_hex(1)  # same root, rewritten


def test_bump_attempts_keeps_same_filename_and_seq(tmp_path):
    """The atomic bump preserves the entry's seq + filename (in-place overwrite).

    graq_predict failure-chain #1 guard: the bump must NOT remove-then-rewrite
    (which would lose the root on a crash between the two). Same seq+root => same
    deterministic path => os.replace overwrites atomically, so the root is on
    disk the whole time and exactly ONE entry exists before and after.
    """
    clock = _FakeClock()
    anchor = _FailAnchor()
    q = LocalReplayQueue(_cfg(max_entries=100, max_retries=5), queue_root=tmp_path, anchor=anchor, clock=clock)
    q.enqueue(_root_hex(1), batch_id="b1")
    name_before = _entries(tmp_path)[0].name
    seq_before = json.loads(_entries(tmp_path)[0].read_text())["seq"]
    q.drain()  # fail -> atomic in-place bump
    entries_after = _entries(tmp_path)
    assert len(entries_after) == 1  # still exactly one entry (no gap, no dup)
    assert entries_after[0].name == name_before  # same filename
    assert json.loads(entries_after[0].read_text())["seq"] == seq_before  # same seq


def test_bumped_entry_anchors_once_when_rekor_recovers(tmp_path):
    """After bumps, a recovered Rekor anchors the root exactly once (no double on disk)."""

    class _FlakyRecordingAnchor:
        available = True

        def __init__(self, fail_until):
            self.fail_until = fail_until
            self.calls = 0
            self.anchored: list[bytes] = []

        def anchor(self, root_bytes):
            self.calls += 1
            if self.calls <= self.fail_until:
                raise AnchorError(f"transient {self.calls}")
            self.anchored.append(root_bytes)
            return _receipt()

    clock = _FakeClock()
    anchor = _FlakyRecordingAnchor(fail_until=1)  # 1st attempt fails (bump), then succeeds
    q = LocalReplayQueue(_cfg(max_entries=100, max_retries=5), queue_root=tmp_path, anchor=anchor, clock=clock)
    q.enqueue(_root_hex(1), batch_id="b1")
    q.drain()  # attempt 1 fails -> bumped, still queued
    assert q.depth == 1
    q.drain()  # attempt 2 succeeds -> removed
    assert q.depth == 0
    assert anchor.anchored == [bytes.fromhex(_root_hex(1))]  # anchored once


def test_remove_entry_missing_file_is_noop(tmp_path):
    """_remove_entry tolerates an already-deleted file (FileNotFoundError arm)."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    q._remove_entry(Path(tmp_path) / "replay_queue" / "nope.json")  # must not raise


def test_read_entry_non_dict_json_skipped(tmp_path):
    """A JSON array (not an object) is rejected by _read_entry (line 440 path)."""
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(integrity_check=False), queue_root=tmp_path, anchor=anchor)
    qdir = Path(tmp_path) / "replay_queue"
    (qdir / f"{'0'*12}-{_root_hex(1)}.json").write_text("[1,2,3]")
    assert q.drain() == 0


def test_list_entries_unreadable_dir_returns_empty(tmp_path, monkeypatch):
    """If the queue dir cannot be listed, _list_entries degrades to [] (line 465)."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    q.enqueue(_root_hex(1), batch_id="b1")

    def boom_iterdir(self):
        raise OSError("iterdir denied")

    monkeypatch.setattr(Path, "iterdir", boom_iterdir)
    assert q._list_entries() == []
    assert q.depth == 0  # depth uses _list_entries


def test_write_entry_temp_cleanup_failure_is_swallowed(tmp_path, monkeypatch):
    """If a write fails AND the orphan-temp cleanup unlink also fails, no crash (403-406)."""
    import os as _os

    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)

    def boom_fsync(fd):
        raise OSError("fsync failed")

    def boom_unlink(path):
        raise OSError("unlink failed")

    monkeypatch.setattr(_os, "fsync", boom_fsync)
    monkeypatch.setattr(_os, "unlink", boom_unlink)
    # The fsync OSError propagates; the cleanup-unlink failure is swallowed.
    with pytest.raises(OSError, match="fsync failed"):
        q.enqueue(_root_hex(1), batch_id="b1")


def test_remove_entry_oserror_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    """A non-FileNotFound OSError on unlink is logged at WARNING, not raised (430-431)."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    q.enqueue(_root_hex(1), batch_id="b1")
    entry = _entries(tmp_path)[0]

    def boom_unlink(self):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", boom_unlink)
    with caplog.at_level("WARNING"):
        q._remove_entry(entry)  # must not raise
    assert any("failed to remove replay-queue entry" in r.message for r in caplog.records)


def test_enqueue_rejects_non_hex_root(tmp_path):
    """A non-hex root is refused at enqueue (it would fail bytes.fromhex at anchor)."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path)
    with pytest.raises(ReplayQueueError, match="hex"):
        q.enqueue("nothex!!", batch_id="b1")
    with pytest.raises(ReplayQueueError, match="hex"):
        q.enqueue("abc", batch_id="b1")  # odd length
    assert q.depth == 0


def test_subdir_never_escapes_queue_root(tmp_path):
    """A traversal-style config.directory cannot place the queue outside queue_root."""
    q = LocalReplayQueue(_cfg(directory="../../../../etc/evil"), queue_root=tmp_path)
    # Only the last component is used; it stays under queue_root.
    assert q.queue_dir.parent == Path(tmp_path)
    assert q.queue_dir.name == "evil"


def test_subdir_dotdot_falls_back_to_default(tmp_path):
    """A config.directory whose last component is '..' falls back to replay_queue."""
    q = LocalReplayQueue(_cfg(directory="foo/.."), queue_root=tmp_path)
    assert q.queue_dir == Path(tmp_path) / "replay_queue"


def test_drain_skips_nonhex_root_on_disk(tmp_path):
    """A non-hex root that reached disk (tamper) is skipped, not crashed (drain guard)."""
    anchor = _OkAnchor()
    q = LocalReplayQueue(_cfg(integrity_check=False), queue_root=tmp_path, anchor=anchor)
    qdir = Path(tmp_path) / "replay_queue"
    (qdir / f"{'0'*12}-deadbeef.json").write_text(
        json.dumps({"seq": 1, "root_hex": "nothex", "batch_id": "b", "attempts": 0, "metadata": {}})
    )
    assert q.drain() == 0  # skipped, no crash
    assert anchor.anchored == []


def test_concurrent_enqueue_all_persist(tmp_path):
    """Concurrent enqueues from many threads all persist with unique seqs (lock)."""
    import threading

    q = LocalReplayQueue(_cfg(max_entries=100), queue_root=tmp_path)
    barrier = threading.Barrier(16)

    def worker(i):
        barrier.wait()
        q.enqueue(_root_hex(i), batch_id=f"b{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.depth == 16
    seqs = [int(p.name.split("-", 1)[0]) for p in _entries(tmp_path)]
    assert len(set(seqs)) == 16  # every entry got a unique sequence number


def test_corrupt_json_is_logged(tmp_path, caplog):
    """A corrupt JSON entry is logged at WARNING when read (observability)."""
    q = LocalReplayQueue(_cfg(), queue_root=tmp_path, anchor=_OkAnchor())
    qdir = Path(tmp_path) / "replay_queue"
    (qdir / f"{'0'*12}-{_root_hex(1)}.json").write_text("{ not json")
    with caplog.at_level("WARNING"):
        q.drain()
    assert any("unreadable/corrupt" in r.message for r in caplog.records)


def test_highest_seq_ignores_malformed_filename(tmp_path):
    """A non-numeric seq prefix is skipped by _highest_seq_on_disk (line 474)."""
    qdir = Path(tmp_path) / "replay_queue"
    qdir.mkdir(parents=True, exist_ok=True)
    # A file whose prefix before '-' is not an int.
    (qdir / f"notanumber-{_root_hex(1)}.json").write_text(
        json.dumps({"seq": 1, "root_hex": _root_hex(1), "batch_id": "b", "attempts": 0, "metadata": {}})
    )
    # Construction calls _highest_seq_on_disk; malformed prefix must not crash.
    q = LocalReplayQueue(_cfg(integrity_check=False), queue_root=tmp_path)
    assert q._next_seq >= 1  # survived the malformed filename
