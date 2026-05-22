"""Tests for the crash-safe WAL batcher (v0.59.0 PR-3, R25-EU01 Task 1.3).

Two complementary crash-simulation mechanisms (the hybrid matrix decided at
INVESTIGATE, graq_reason 90%):

* **Real-kill scenarios** — a ``batcher_worker.py`` subprocess advances to a
  ``--phase`` boundary and the parent kills it with a real OS signal
  (``Popen.terminate()`` / ``.kill()``). This is genuine crash semantics on both
  Windows (``TerminateProcess``) and POSIX (``SIGTERM``/``SIGKILL``) — cleanup
  handlers never run. Used where only a real abrupt death is convincing.
* **In-process fault injection** — monkeypatch a WAL phase-boundary primitive to
  raise, simulating a crash at exactly that point (before temp-write, after
  temp-write-before-fsync, after-fsync-before-replace, after-replace-before-ack,
  mid-drain). Fast and deterministic, no subprocess flakiness.

Invariant across the whole matrix: after the simulated crash, a fresh
``WalBatcher`` over the same WAL root drains the leftover entries and commits
each record EXACTLY once (SHA-256 content-addressed dedup makes replay a no-op).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from graqle.config.attestation_config import AttestationConfig
from graqle.governance.tamper_evidence.batcher import (
    _MAX_WAL_ENTRY_BYTES,
    WAL_SUBDIR,
    BatcherError,
    WalBatcher,
    _idempotency_key,
    _is_valid_key,
    _safe_dir_fsync,
)
from graqle.governance.tamper_evidence.merkle import MerkleTree


# ---- helpers ------------------------------------------------------------------


def _record(i: int) -> dict:
    """A minimally valid leaf-input record (mirrors test_merkle._record)."""
    return {
        "proof_format_version": "1.0.0",
        "record_id": f"tr_{i:06d}",
        "content_hash": hashlib.sha256(f"payload-{i}".encode()).hexdigest(),
        "timestamp_unix": 1_700_000_000 + i,
        "governance_metadata": {"decision": "ALLOW", "seq": i},
    }


class _RecordingCommitter:
    """Captures every (records, tree) flush so tests can assert exactly-once."""

    def __init__(self) -> None:
        self.batches: list[tuple[list[dict], MerkleTree]] = []
        self.fail_next = False

    def __call__(self, records: list[dict], tree: MerkleTree) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected committer failure")
        # Defensive copy: the batcher clears its pending dict after we return.
        self.batches.append((list(records), tree))

    @property
    def committed_record_ids(self) -> list[str]:
        ids: list[str] = []
        for records, _tree in self.batches:
            ids.extend(r["record_id"] for r in records)
        return ids


def _wal_entries(wal_root: Path) -> list[Path]:
    d = Path(wal_root) / WAL_SUBDIR
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.name.endswith(".wal.json"))


def _config(**overrides) -> AttestationConfig:
    base = {"batch_max_records": 1000, "batch_max_seconds": 5}
    base.update(overrides)
    return AttestationConfig(**base)


# ---- basic enqueue / flush ----------------------------------------------------


def test_enqueue_persists_to_wal_before_commit(tmp_path):
    """A record is durably in the WAL immediately after enqueue, before any flush."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    key = b.enqueue(_record(1))
    assert b.pending_count == 1
    entries = _wal_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].name == f"{key}.wal.json"
    assert entries[0].stat().st_size > 0  # not a zero-byte / partial entry


def test_flush_builds_tree_and_clears_wal(tmp_path):
    """flush() commits the batch, hands a tree to the committer, and empties the WAL."""
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    for i in range(5):
        b.enqueue(_record(i))
    committed = b.flush()
    assert committed == 5
    assert b.pending_count == 0
    assert _wal_entries(tmp_path) == []  # WAL cleared only after commit success
    assert len(committer.batches) == 1
    records, tree = committer.batches[0]
    assert tree.size == 5
    assert [r["record_id"] for r in records] == [f"tr_{i:06d}" for i in range(5)]


def test_empty_flush_is_noop(tmp_path):
    """An empty flush returns 0 and never builds a (rejected) zero-leaf tree."""
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    assert b.flush() == 0
    assert committer.batches == []


def test_size_trigger_flushes_inline(tmp_path):
    """Reaching batch_max_records flushes inline during enqueue."""
    committer = _RecordingCommitter()
    b = WalBatcher(_config(batch_max_records=3), wal_root=tmp_path, committer=committer)
    b.enqueue(_record(0))
    b.enqueue(_record(1))
    assert len(committer.batches) == 0  # not yet at ceiling
    b.enqueue(_record(2))  # hits ceiling -> inline flush
    assert len(committer.batches) == 1
    assert committer.batches[0][1].size == 3
    assert b.pending_count == 0


def test_time_trigger_flushes_via_maybe_flush(tmp_path):
    """maybe_flush() flushes once batch_max_seconds elapses for the oldest record."""
    fake = {"t": 1000.0}
    committer = _RecordingCommitter()
    b = WalBatcher(
        _config(batch_max_seconds=5),
        wal_root=tmp_path,
        committer=committer,
        clock=lambda: fake["t"],
    )
    b.enqueue(_record(0))
    assert b.maybe_flush() is False  # 0s elapsed
    fake["t"] = 1004.0
    assert b.maybe_flush() is False  # 4s < 5s
    fake["t"] = 1005.0
    assert b.maybe_flush() is True  # 5s reached
    assert len(committer.batches) == 1
    assert b.pending_count == 0


def test_maybe_flush_empty_is_false(tmp_path):
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.maybe_flush() is False


# ---- ordering guarantee -------------------------------------------------------


def test_commit_order_is_enqueue_order(tmp_path):
    """The committed batch preserves enqueue order (insertion-ordered pending dict)."""
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    for i in (4, 2, 7, 0, 9):
        b.enqueue(_record(i))
    b.flush()
    records, _ = committer.batches[0]
    assert [r["record_id"] for r in records] == [
        "tr_000004", "tr_000002", "tr_000007", "tr_000000", "tr_000009"
    ]


# ---- idempotency / content-addressing -----------------------------------------


def test_duplicate_enqueue_is_idempotent(tmp_path):
    """Enqueuing the same record twice yields one WAL entry, one leaf, same key."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    k1 = b.enqueue(_record(1))
    k2 = b.enqueue(_record(1))
    assert k1 == k2
    assert b.pending_count == 1
    assert len(_wal_entries(tmp_path)) == 1


def test_idempotency_key_is_content_address(tmp_path):
    """The WAL filename stem equals the SHA-256 of the record's canonical bytes."""
    rec = _record(42)
    b = WalBatcher(_config(), wal_root=tmp_path)
    key = b.enqueue(rec)
    assert key == _idempotency_key(rec)
    assert _wal_entries(tmp_path)[0].name == f"{key}.wal.json"


def test_distinct_records_distinct_keys(tmp_path):
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.enqueue(_record(1)) != b.enqueue(_record(2))
    assert b.pending_count == 2


def test_enqueue_rejects_non_dict(tmp_path):
    b = WalBatcher(_config(), wal_root=tmp_path)
    with pytest.raises(BatcherError):
        b.enqueue(["not", "a", "dict"])  # type: ignore[arg-type]


# ---- C-P0-1: durable-before-ack -----------------------------------------------


def test_cp0_1_record_durable_before_enqueue_returns(tmp_path, monkeypatch):
    """C-P0-1: the WAL entry is fsync'd before enqueue() returns (ack boundary).

    We assert the entry is on disk the instant enqueue returns, and that the
    fsync of the file descriptor actually happened (counted via monkeypatch).
    """
    fsync_calls = {"n": 0}
    real_fsync = os.fsync

    def counting_fsync(fd):
        fsync_calls["n"] += 1
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    b = WalBatcher(_config(), wal_root=tmp_path)
    key = b.enqueue(_record(1))
    # File present + non-empty the moment enqueue returned.
    entry = Path(tmp_path) / WAL_SUBDIR / f"{key}.wal.json"
    assert entry.exists() and entry.stat().st_size > 0
    # The file descriptor was fsync'd at least once (data durability).
    assert fsync_calls["n"] >= 1


def test_cp1_1_zero_byte_entry_rejected(tmp_path, monkeypatch):
    """A post-write stat showing a zero-length entry is rejected (S-015).

    Rather than monkeypatch ``Path.stat`` (which also intercepts the
    ``final_path.exists()`` precheck and short-circuits the write), we wrap
    ``os.replace`` so the real rename happens AND the final file is then
    truncated to 0 bytes. The production code's genuine post-write
    ``stat().st_size == 0`` check then fires on a real, real-zero file.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)
    real_replace = os.replace

    def truncating_replace(src, dst):
        real_replace(src, dst)
        # Simulate a silent truncation between rename and the size check.
        with open(dst, "wb"):
            pass  # opening 'wb' truncates to zero length

    monkeypatch.setattr(os, "replace", truncating_replace)
    with pytest.raises(BatcherError, match="zero-length"):
        b.enqueue(_record(1))


# ---- _safe_dir_fsync portability ----------------------------------------------


def test_safe_dir_fsync_never_raises(tmp_path):
    """_safe_dir_fsync is best-effort: it must not raise on any platform."""
    _safe_dir_fsync(tmp_path)  # real dir
    _safe_dir_fsync(tmp_path / "does-not-exist")  # missing dir -> swallowed


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory fsync only")
def test_safe_dir_fsync_calls_fsync_on_posix(tmp_path, monkeypatch):
    """On POSIX, _safe_dir_fsync opens the directory and fsyncs it."""
    seen = {"fsync": False}
    real_fsync = os.fsync

    def spy_fsync(fd):
        seen["fsync"] = True
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    _safe_dir_fsync(tmp_path)
    assert seen["fsync"] is True


@pytest.mark.skipif(os.name == "posix", reason="Windows no-op path")
def test_safe_dir_fsync_is_noop_on_windows(tmp_path, monkeypatch):
    """On Windows, _safe_dir_fsync does not attempt os.open/os.fsync at all."""
    called = {"open": False}
    real_open = os.open

    def spy_open(*a, **k):
        called["open"] = True
        return real_open(*a, **k)

    monkeypatch.setattr(os, "open", spy_open)
    _safe_dir_fsync(tmp_path)
    assert called["open"] is False


# ---- crash recovery: in-process fault injection (fast/deterministic) ----------
#
# Each test crashes at a distinct WAL phase boundary, then a FRESH batcher over
# the same root must drain + commit exactly once.


def _commit_all_after_recovery(tmp_path) -> _RecordingCommitter:
    """Build a fresh batcher (drains WAL in __init__), flush, return the committer."""
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    b.flush()
    return committer


def test_crash_before_temp_write(tmp_path, monkeypatch):
    """Crash before the temp file is even created: no entry, nothing to recover."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    import tempfile as _tf

    def boom(*a, **k):
        raise OSError("crash before temp write")

    monkeypatch.setattr(_tf, "NamedTemporaryFile", boom)
    with pytest.raises(OSError):
        b.enqueue(_record(0))
    monkeypatch.undo()
    # Nothing was acked or persisted.
    assert _wal_entries(tmp_path) == []
    committer = _commit_all_after_recovery(tmp_path)
    assert committer.committed_record_ids == []


def test_crash_after_temp_write_before_fsync(tmp_path, monkeypatch):
    """Crash after writing the temp file but before fsync: no committed entry.

    The atomic rename never happened, so only an orphan .tmp may exist — never a
    final .wal.json. Recovery commits nothing.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)

    def boom(fd):
        raise OSError("crash before fsync")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        b.enqueue(_record(0))
    monkeypatch.undo()
    assert _wal_entries(tmp_path) == []  # no final entry
    committer = _commit_all_after_recovery(tmp_path)
    assert committer.committed_record_ids == []


def test_crash_after_fsync_before_replace(tmp_path, monkeypatch):
    """Crash after fsync but before os.replace: temp is durable but not visible.

    The final WAL path was never created, so the next startup sees no committable
    entry — at-least-once still holds (the record was never acked).
    """
    b = WalBatcher(_config(), wal_root=tmp_path)

    def boom(src, dst):
        raise OSError("crash before replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        b.enqueue(_record(0))
    monkeypatch.undo()
    assert _wal_entries(tmp_path) == []
    committer = _commit_all_after_recovery(tmp_path)
    assert committer.committed_record_ids == []


def test_crash_after_replace_before_ack(tmp_path, monkeypatch):
    """Crash after os.replace but before enqueue returns: entry IS durable.

    This is the C-P0-1 boundary: the record is on disk (renamed into place) but
    the caller never received the ack. Recovery MUST commit it exactly once.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)

    # Let the rename complete, then crash in the post-replace dir-fsync step
    # (which is AFTER the entry is durably in place).
    import graqle.governance.tamper_evidence.batcher as bat

    def boom(_dir):
        raise OSError("crash after replace, before ack")

    monkeypatch.setattr(bat, "_safe_dir_fsync", boom)
    with pytest.raises(OSError):
        b.enqueue(_record(0))
    monkeypatch.undo()
    # The final entry exists (rename succeeded before the crash).
    assert len(_wal_entries(tmp_path)) == 1
    # Fresh batcher drains + commits the orphaned record exactly once.
    committer = _commit_all_after_recovery(tmp_path)
    assert committer.committed_record_ids == ["tr_000000"]


def test_crash_mid_drain_recovers_remaining(tmp_path, monkeypatch):
    """Crash partway through draining the WAL: a later restart commits all of them.

    First populate a WAL with 3 entries (via a clean batcher that we abandon
    before flush). Then a second batcher crashes mid-drain. A third batcher must
    still recover and commit all 3 exactly once.

    NOTE on order: crash-RECOVERY commits in deterministic content-address
    (filename-sorted) order, NOT original enqueue order — the WAL is
    content-addressed, so the on-disk filenames are SHA-256 hashes that carry no
    sequence. The live (non-crashed) path preserves enqueue order
    (test_commit_order_is_enqueue_order); recovery order is deterministic but
    independent of it. For tamper-evidence this is sound: every record still gets
    exactly one leaf with a valid inclusion proof, and the recovered batch's root
    is reproducible. We therefore assert exactly-once as a SET, plus the
    deterministic sorted order recovery actually uses.
    """
    # Populate 3 durable entries, abandon before flush (simulates prior crash).
    seed = WalBatcher(_config(), wal_root=tmp_path)
    for i in range(3):
        seed.enqueue(_record(i))
    del seed
    assert len(_wal_entries(tmp_path)) == 3

    # Second batcher: blow up during the drain loop after reading 1 entry.
    import graqle.governance.tamper_evidence.batcher as bat

    real_leaf = bat.leaf_hash_for_record
    state = {"calls": 0}

    def flaky_leaf(record):
        state["calls"] += 1
        if state["calls"] == 2:  # fail on the second recovered record
            raise OSError("crash mid-drain")
        return real_leaf(record)

    monkeypatch.setattr(bat, "leaf_hash_for_record", flaky_leaf)
    with pytest.raises(OSError):
        WalBatcher(_config(), wal_root=tmp_path)
    monkeypatch.undo()

    # All 3 entries still on disk (the partial drain committed nothing).
    assert len(_wal_entries(tmp_path)) == 3
    # Third batcher drains cleanly and commits all 3 exactly once.
    committer = _commit_all_after_recovery(tmp_path)
    ids = committer.committed_record_ids
    # Exactly-once (set equality): no record lost, none duplicated.
    assert set(ids) == {"tr_000000", "tr_000001", "tr_000002"}
    assert len(ids) == 3
    # Recovery order is deterministic = WAL filenames (content addresses) sorted.
    expected_order = [
        rec["record_id"]
        for rec in sorted((_record(i) for i in range(3)), key=_idempotency_key)
    ]
    assert ids == expected_order


def test_committer_failure_leaves_wal_intact(tmp_path):
    """If the committer raises, the WAL is NOT cleared — the batch retries intact.

    Exercises the no-partial-commit guarantee: a failed downstream commit must
    leave every record recoverable, never half-committed.
    """
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    for i in range(4):
        b.enqueue(_record(i))
    committer.fail_next = True
    with pytest.raises(RuntimeError, match="injected committer failure"):
        b.flush()
    # WAL intact, pending intact — nothing was committed or dropped.
    assert len(_wal_entries(tmp_path)) == 4
    assert b.pending_count == 4
    # Retry succeeds and commits all 4 exactly once.
    assert b.flush() == 4
    assert committer.committed_record_ids == ["tr_%06d" % i for i in range(4)]
    assert _wal_entries(tmp_path) == []


def test_failed_unlink_degrades_gracefully_and_logs(tmp_path, monkeypatch, caplog):
    """A failed WAL-entry unlink after commit does NOT raise, but IS logged.

    The commit already succeeded downstream, so a failure to clean up the WAL
    entry must not propagate (it would falsely report a commit failure). The
    redundant entry is harmless (content-addressed re-drain is a no-op), but the
    error is logged at WARNING so a recurring leak is observable.
    """
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    b.enqueue(_record(0))

    def boom_unlink(self, *a, **k):
        raise OSError("unlink denied")

    monkeypatch.setattr(Path, "unlink", boom_unlink)
    with caplog.at_level("WARNING"):
        committed = b.flush()  # must NOT raise despite the unlink failure
    assert committed == 1
    assert committer.committed_record_ids == ["tr_000000"]
    assert any("failed to remove committed WAL entry" in r.message for r in caplog.records)


def test_recovery_skips_corrupt_entry(tmp_path):
    """A corrupt WAL entry is skipped (left on disk); valid entries still commit."""
    seed = WalBatcher(_config(), wal_root=tmp_path)
    good_key = seed.enqueue(_record(0))
    del seed
    # Write a corrupt entry alongside the good one.
    wal_dir = Path(tmp_path) / WAL_SUBDIR
    corrupt = wal_dir / "deadbeef.wal.json"
    corrupt.write_text("{ not valid json", encoding="utf-8")
    # Fresh batcher: drains only the good entry; corrupt one is skipped + retained.
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    assert b.pending_count == 1  # only the good record recovered
    b.flush()
    assert committer.committed_record_ids == ["tr_000000"]
    assert corrupt.exists()  # left in place for operator inspection
    # The committed (good) entry was removed.
    assert not (wal_dir / f"{good_key}.wal.json").exists()


def test_recovery_rejects_filename_content_mismatch(tmp_path):
    """An entry whose content does not match its filename address is rejected."""
    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    rec = _record(5)
    real_key = _idempotency_key(rec)
    # Store the real record under a WRONG filename (a different valid-looking key).
    import json as _json

    wrong = wal_dir / ("0" * 64 + ".wal.json")
    wrong.write_text(
        _json.dumps({"idempotency_key": "0" * 64, "record": rec}),
        encoding="utf-8",
    )
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    # The content's true address != the stored key/filename -> rejected.
    assert b.pending_count == 0
    assert real_key != "0" * 64


@pytest.mark.parametrize(
    "payload",
    [
        "[1, 2, 3]",  # valid JSON but not an object -> rejected
        '{"record": {"x": 1}}',  # missing idempotency_key
        '{"idempotency_key": "abc"}',  # missing record
        '{"idempotency_key": 123, "record": {"x": 1}}',  # non-string key
        '{"idempotency_key": "abc", "record": "not-a-dict"}',  # non-dict record
    ],
)
def test_recovery_rejects_malformed_entries(tmp_path, payload):
    """Structurally-malformed WAL entries are skipped, not committed (defensive drain)."""
    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    (wal_dir / ("a" * 64 + ".wal.json")).write_text(payload, encoding="utf-8")
    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    assert b.pending_count == 0  # nothing recovered from a malformed entry
    assert b.flush() == 0


def test_recovery_rejects_noncanonical_record(tmp_path):
    """A WAL record that fails canonicalization is rejected during recovery."""
    import json as _json

    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    # A record with a non-JSON-native value (NaN-as-string won't trip it; use a
    # nested float NaN which canon() rejects). JSON can't hold NaN literally, so
    # emit it via allow_nan and let canon() reject on read.
    bad = {"idempotency_key": "b" * 64,
           "record": {"proof_format_version": "1.0.0", "v": float("nan")}}
    (wal_dir / ("b" * 64 + ".wal.json")).write_text(
        _json.dumps(bad), encoding="utf-8"
    )
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.pending_count == 0  # non-canonical record skipped


def test_wal_dir_property_points_at_uncommitted(tmp_path):
    """The wal_dir property exposes the .../uncommitted directory."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.wal_dir == Path(tmp_path) / WAL_SUBDIR
    assert b.wal_dir.is_dir()


# ---- security hardening: path-traversal + DoS guards --------------------------


@pytest.mark.parametrize(
    "key,valid",
    [
        ("a" * 64, True),  # well-formed
        ("0123456789abcdef" * 4, True),  # all hex digits, len 64
        ("A" * 64, False),  # uppercase not allowed (digest is lowercase)
        ("a" * 63, False),  # too short
        ("a" * 65, False),  # too long
        ("../../etc/passwd" + "a" * 48, False),  # traversal chars
        ("g" * 64, False),  # non-hex char
        ("", False),  # empty
    ],
)
def test_is_valid_key(key, valid):
    """_is_valid_key accepts only 64-char lowercase hex (path-traversal guard)."""
    assert _is_valid_key(key) is valid


def test_wal_path_rejects_malformed_key(tmp_path):
    """_wal_path refuses a non-hex key so it can never become a traversal path."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    with pytest.raises(BatcherError, match="malformed idempotency key"):
        b._wal_path("../../etc/passwd")


def test_recovery_rejects_traversal_filename(tmp_path):
    """A WAL entry whose stored key is a traversal string is rejected on drain."""
    import json as _json

    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    rec = _record(1)
    # Filename uses a benign hex stem, but the stored key is a traversal string.
    evil = wal_dir / ("c" * 64 + ".wal.json")
    evil.write_text(
        _json.dumps({"idempotency_key": "../../../../evil", "record": rec}),
        encoding="utf-8",
    )
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.pending_count == 0  # malformed key rejected, nothing recovered


def test_recovery_skips_oversized_entry(tmp_path, monkeypatch):
    """An on-disk WAL entry larger than the cap is skipped without being read.

    We shrink the cap via monkeypatch and write an entry just over it, then
    assert it is neither recovered nor loaded into memory.
    """
    import graqle.governance.tamper_evidence.batcher as bat

    monkeypatch.setattr(bat, "_MAX_WAL_ENTRY_BYTES", 128)
    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    rec = _record(1)
    key = _idempotency_key(rec)
    import json as _json

    payload = _json.dumps({"idempotency_key": key, "record": rec})
    payload += " " * (200 - len(payload))  # pad well over the 128-byte cap
    (wal_dir / f"{key}.wal.json").write_text(payload, encoding="utf-8")
    assert (wal_dir / f"{key}.wal.json").stat().st_size > 128

    read_calls = {"n": 0}
    real_read = Path.read_bytes

    def counting_read(self, *a, **k):
        read_calls["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", counting_read)
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.pending_count == 0  # oversized entry skipped
    assert read_calls["n"] == 0  # never read into memory (size check came first)


def test_max_wal_entry_bytes_is_sane():
    """The DoS cap is a positive, generous-but-bounded value."""
    assert 0 < _MAX_WAL_ENTRY_BYTES <= 64 * 1024 * 1024


# ---- latent failure-chain guards (from graq_predict adjudication) -------------


def test_recovery_ignores_orphan_temp_files(tmp_path):
    """A leftover .tmp file (crash mid-write) is NOT picked up by recovery.

    Recovery globs only ``*.wal.json``; an orphaned NamedTemporaryFile
    (``.{key}.*.tmp``) from a crash before os.replace must be ignored, never
    parsed as a committable entry.
    """
    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    # One valid entry + one orphan temp file mimicking a pre-replace crash.
    rec = _record(0)
    key = _idempotency_key(rec)
    import json as _json

    (wal_dir / f"{key}.wal.json").write_text(
        _json.dumps({"idempotency_key": key, "record": rec}), encoding="utf-8"
    )
    (wal_dir / f".{key}.abcd.tmp").write_text("partial garbage", encoding="utf-8")

    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    assert b.pending_count == 1  # only the .wal.json entry, never the .tmp
    b.flush()
    assert committer.committed_record_ids == ["tr_000000"]
    assert (wal_dir / f".{key}.abcd.tmp").exists()  # orphan left for cleanup


def test_concurrent_enqueue_same_record_dedups(tmp_path):
    """Many threads enqueuing the SAME record yield exactly one WAL entry/leaf.

    Proves the lock makes the (check pending -> write WAL -> insert) sequence
    atomic: no duplicate entries, no torn pending state under contention.
    """
    import threading

    b = WalBatcher(_config(batch_max_records=10_000), wal_root=tmp_path)
    rec = _record(7)
    keys: list[str] = []
    keys_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximize contention: all start together
        k = b.enqueue(rec)
        with keys_lock:
            keys.append(k)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(keys)) == 1  # all threads agree on the one key
    assert b.pending_count == 1  # exactly one pending record
    assert len(_wal_entries(tmp_path)) == 1  # exactly one WAL entry


def test_concurrent_enqueue_distinct_records_all_persist(tmp_path):
    """Threads enqueuing DISTINCT records all persist, none lost under contention."""
    import threading

    n = 32
    b = WalBatcher(_config(batch_max_records=10_000), wal_root=tmp_path)
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        b.enqueue(_record(i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert b.pending_count == n
    assert len(_wal_entries(tmp_path)) == n


def test_tree_uses_enqueue_time_leaf_hashes_not_recommit_hash(tmp_path):
    """The Merkle tree is built from leaf hashes frozen at enqueue, not re-hashed.

    Even if a record dict is mutated in place after enqueue (a misbehaving
    committer / caller), the committed tree's root must match a tree built from
    the ORIGINAL records — proving tree integrity does not depend on the live
    record dict staying immutable.
    """
    from graqle.governance.tamper_evidence.merkle import MerkleTree as _MT

    captured = {}

    def capturing_committer(records, tree):
        captured["root"] = tree.root_hex
        # Simulate an ill-behaved committer mutating a handed-out record.
        records[0]["governance_metadata"]["decision"] = "MUTATED"

    b = WalBatcher(_config(), wal_root=tmp_path, committer=capturing_committer)
    originals = [_record(i) for i in range(4)]
    for rec in originals:
        b.enqueue({k: (dict(v) if isinstance(v, dict) else v) for k, v in rec.items()})
    b.flush()

    expected_root = _MT.from_records(originals).root_hex
    assert captured["root"] == expected_root  # tree used enqueue-time hashes


# ---- coverage completion: realistic exercise of defensive paths ---------------
#
# These cover the remaining defensive branches by triggering the real fault each
# guards (not by hiding them). Each asserts the GRACEFUL-DEGRADATION behavior the
# branch exists to provide, so coverage stays meaningful.


def test_flush_without_committer_clears_wal(tmp_path):
    """flush() with committer=None builds the tree, skips commit, clears the WAL.

    Covers the `committer is None` branch: the no-downstream-commit integration
    point (and the pre-PR-5 default). The records are still drained from the WAL.
    """
    b = WalBatcher(_config(), wal_root=tmp_path, committer=None)
    for i in range(3):
        b.enqueue(_record(i))
    assert len(_wal_entries(tmp_path)) == 3
    committed = b.flush()
    assert committed == 3
    assert b.pending_count == 0
    assert _wal_entries(tmp_path) == []  # WAL cleared even with no committer


def test_write_wal_entry_idempotent_when_file_exists(tmp_path):
    """_write_wal_entry is a no-op if the final path already exists (in-flight retry).

    Covers the `final_path.exists(): return` early return: a second write for an
    already-persisted key must not rewrite or corrupt the entry.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)
    rec = _record(1)
    key = b.enqueue(rec)
    entry = Path(tmp_path) / WAL_SUBDIR / f"{key}.wal.json"
    before = entry.read_bytes()
    # Direct second write for the same key: must early-return without touching it.
    b._write_wal_entry(key, rec)
    assert entry.read_bytes() == before  # unchanged
    assert len(_wal_entries(tmp_path)) == 1


def test_post_write_stat_oserror_becomes_batcher_error(tmp_path, monkeypatch):
    """An OSError from the post-write stat() surfaces as a BatcherError (line 409).

    Covers the except-OSError arm of the S-015 size check: if the just-written
    entry cannot even be stat'd, we refuse to acknowledge it.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)
    real_replace = os.replace

    def replace_then_break_stat(src, dst):
        real_replace(src, dst)
        # After the real rename, make the next stat() on the final path raise.
        orig_stat = Path.stat

        def boom_stat(self, *a, **k):
            if self.name.endswith(".wal.json"):
                raise OSError("stat denied")
            return orig_stat(self, *a, **k)

        monkeypatch.setattr(Path, "stat", boom_stat)

    monkeypatch.setattr(os, "replace", replace_then_break_stat)
    with pytest.raises(BatcherError, match="could not be stat'd"):
        b.enqueue(_record(1))


def test_temp_cleanup_unlink_failure_is_swallowed(tmp_path, monkeypatch):
    """If the write fails AND the temp-file cleanup unlink also fails, no crash.

    Covers the finally-block `except OSError: pass` around the orphan temp unlink:
    a cleanup failure must never mask the original error nor raise on its own.
    """
    b = WalBatcher(_config(), wal_root=tmp_path)

    # Make fsync fail (crash before rename) so the finally cleanup path runs...
    def boom_fsync(fd):
        raise OSError("fsync failed")

    # ...and make the cleanup unlink ALSO fail.
    def boom_unlink(self, *a, **k):
        raise OSError("unlink failed")

    def boom_os_unlink(path):
        raise OSError("unlink failed")

    monkeypatch.setattr(os, "fsync", boom_fsync)
    monkeypatch.setattr(os, "unlink", boom_os_unlink)  # cleanup uses os.unlink
    # The original fsync OSError propagates; the unlink failure is swallowed.
    with pytest.raises(OSError, match="fsync failed"):
        b.enqueue(_record(1))


def test_remove_wal_entry_missing_file_is_noop(tmp_path):
    """_remove_wal_entry tolerates an already-deleted entry (FileNotFoundError arm)."""
    b = WalBatcher(_config(), wal_root=tmp_path)
    key = "d" * 64  # well-formed but no such file
    b._remove_wal_entry(key)  # must not raise


def test_recovery_rejects_valid_hex_key_not_matching_filename(tmp_path):
    """A valid-hex stored key that differs from its filename stem is rejected (line 495).

    Both key and filename are well-formed hex (so _is_valid_key passes), but they
    DISAGREE — the entry was renamed or the filename was tampered. It must be
    skipped before the content re-hash, so the filename↔key binding is enforced.
    """
    import json as _json

    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    rec = _record(1)
    # Filename stem = all 'a'; stored key = all 'b'. Both valid hex, but unequal.
    (wal_dir / ("a" * 64 + ".wal.json")).write_text(
        _json.dumps({"idempotency_key": "b" * 64, "record": rec}), encoding="utf-8"
    )
    b = WalBatcher(_config(), wal_root=tmp_path)
    assert b.pending_count == 0  # stem != key => rejected at the binding check


def test_recovery_no_double_leaf_for_same_content_under_two_filenames(tmp_path):
    """INVARIANT GUARD: the same record under two different filenames cannot yield
    two pending leaves on recovery.

    This is the test that justifies removing the in-loop dedup branch: the
    key==filename-stem binding is what guarantees one pending entry per content.
    The canonical file (stem == content-address) is accepted; any second file
    carrying the same record under a DIFFERENT stem is rejected because its stem
    cannot equal the content's true address. So recovery produces exactly one
    leaf for the content — proven here, not assumed.
    """
    import json as _json

    wal_dir = Path(tmp_path) / WAL_SUBDIR
    wal_dir.mkdir(parents=True, exist_ok=True)
    rec = _record(9)
    true_key = _idempotency_key(rec)
    # File A: canonical (stem == true content-address) -> accepted.
    (wal_dir / f"{true_key}.wal.json").write_text(
        _json.dumps({"idempotency_key": true_key, "record": rec}), encoding="utf-8"
    )
    # File B: SAME record, but a different valid-hex stem with a matching stored
    # key. Its stored key == its stem, but that key != the content's true address,
    # so the content re-hash check rejects it.
    decoy = "f" * 64
    (wal_dir / f"{decoy}.wal.json").write_text(
        _json.dumps({"idempotency_key": decoy, "record": rec}), encoding="utf-8"
    )

    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    # Exactly ONE pending entry for the content (the canonical file); the decoy is
    # rejected by the content-address re-hash, so no second leaf is produced.
    assert b.pending_count == 1
    b.flush()
    assert committer.committed_record_ids == ["tr_000009"]
    assert len(committer.batches[0][1]._leaves) == 1  # one leaf, not two


def test_recover_from_wal_unreadable_dir_is_noop(tmp_path, monkeypatch):
    """If the WAL dir cannot be listed, recovery degrades to a no-op (lines 453-454)."""
    b = WalBatcher(_config(), wal_root=tmp_path)

    def boom_iterdir(self):
        raise OSError("iterdir denied")

    monkeypatch.setattr(Path, "iterdir", boom_iterdir)
    # A second batcher over the same root: recovery hits the OSError and returns.
    b2 = WalBatcher(_config(), wal_root=tmp_path)
    assert b2.pending_count == 0


# ---- crash recovery: REAL process kill (genuine crash semantics) --------------

_WORKER = Path(__file__).with_name("batcher_worker.py")


# Repo root (where the `graqle` package lives): tests/test_tamper_evidence/ -> up 2.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _spawn_worker(wal_root: Path, phase: str, count: int = 3) -> subprocess.Popen:
    """Spawn the crash worker; return the Popen once it reports READY:<phase>.

    The subprocess does NOT inherit pytest's injected sys.path, and the
    site-packages ``graqle`` may be an older build, so we put the worktree repo
    root on PYTHONPATH explicitly to import the under-test ``graqle`` package.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) + (os.pathsep + existing if existing else "")
    )
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER),
         "--wal-root", str(wal_root), "--phase", phase, "--count", str(count)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    # Wait for the READY line so the on-disk state is exactly at the boundary.
    deadline = time.monotonic() + 30.0
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.startswith("READY:"):
            return proc
        if proc.poll() is not None:  # worker died before READY
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"worker exited early (rc={proc.returncode}): {err}")
    proc.kill()
    raise AssertionError(f"worker never reached READY:{phase}")


def _kill(proc: subprocess.Popen) -> None:
    """Abrupt kill (TerminateProcess / SIGKILL), then reap to avoid a zombie."""
    proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        pass


@pytest.mark.parametrize("phase", ["after-enqueue", "mid-batch", "before-flush"])
def test_real_kill_recovers_exactly_once(tmp_path, phase):
    """REAL OS kill at each WAL boundary: a fresh batcher recovers exactly once.

    The worker durably writes records to the WAL, parks at ``phase``, and the
    parent kills it with a real signal. A fresh in-parent ``WalBatcher`` over the
    same root then drains the WAL and commits every recovered record once.
    """
    count = 3
    proc = _spawn_worker(tmp_path, phase, count=count)
    _kill(proc)

    expected = count - 1 if phase == "mid-batch" else count
    assert len(_wal_entries(tmp_path)) == expected  # durable across the kill

    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    assert b.pending_count == expected
    committed = b.flush()
    assert committed == expected
    # Exactly-once: no duplicates, count matches, WAL drained.
    ids = committer.committed_record_ids
    assert len(ids) == len(set(ids)) == expected
    assert _wal_entries(tmp_path) == []


def test_real_kill_then_resubmit_is_idempotent(tmp_path):
    """After a real kill, re-submitting the same records adds no duplicate leaves.

    Models the producer that retries on restart: the recovered WAL entries and
    the resubmitted records collapse to one leaf each (content-addressed dedup).
    """
    count = 3
    proc = _spawn_worker(tmp_path, "after-enqueue", count=count)
    _kill(proc)
    assert len(_wal_entries(tmp_path)) == count

    committer = _RecordingCommitter()
    b = WalBatcher(_config(), wal_root=tmp_path, committer=committer)
    # Producer resubmits the same records post-restart.
    for i in range(count):
        b.enqueue(_record(i))
    assert b.pending_count == count  # no duplicates despite resubmission
    b.flush()
    assert sorted(committer.committed_record_ids) == [f"tr_{i:06d}" for i in range(count)]
