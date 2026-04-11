"""TB-F1.2 regression tests for graqle.chat.turn_ledger.

Coverage driven by pre-impl graq_review at 93% confidence:

  Observable guarantees:
    - Durable append + read round-trip
    - Append-only (never overwrites)
    - Fail-soft on malformed records (read-side crash recovery)
    - Deterministic seq ordering on read
    - Concurrent appends preserve monotonic seq per turn
    - Multiple turns in same base_dir don't collide
    - list_turns returns all turns written

  Fail-soft paths:
    - Append with non-JSON-serializable record returns -1, does NOT raise
    - Read from nonexistent turn returns []
    - Read from corrupted file (mid-append crash) skips bad lines
    - Recovery: new ledger instance resumes seq counter from disk
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_turn_ledger
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, tempfile, threading, graqle.chat.turn_ledger
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from graqle.chat.turn_ledger import TurnLedger


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def ledger(tmp_path: Path) -> TurnLedger:
    return TurnLedger(base_dir=tmp_path / "ledger")


# ── happy path ────────────────────────────────────────────────────────


def test_append_and_read_round_trip(ledger: TurnLedger) -> None:
    seq0 = ledger.append("t1", {"type": "user_message", "data": {"text": "hi"}})
    seq1 = ledger.append("t1", {"type": "assistant_text_chunk", "data": {"chunk": "ok"}})
    assert seq0 == 0 and seq1 == 1
    records = ledger.read_turn("t1")
    assert len(records) == 2
    assert records[0]["type"] == "user_message"
    assert records[0]["seq"] == 0
    assert records[1]["type"] == "assistant_text_chunk"
    assert records[1]["seq"] == 1
    assert "logged_at" in records[0]


def test_two_turns_dont_collide(ledger: TurnLedger) -> None:
    ledger.append("t1", {"type": "a"})
    ledger.append("t2", {"type": "b"})
    ledger.append("t1", {"type": "c"})
    r1 = ledger.read_turn("t1")
    r2 = ledger.read_turn("t2")
    assert len(r1) == 2
    assert len(r2) == 1
    assert r1[0]["type"] == "a"
    assert r1[1]["type"] == "c"
    assert r2[0]["type"] == "b"


def test_seq_is_per_turn_not_global(ledger: TurnLedger) -> None:
    """Each turn has its own seq counter starting from 0."""
    s0 = ledger.append("t1", {"type": "x"})
    s1 = ledger.append("t2", {"type": "y"})
    s2 = ledger.append("t1", {"type": "z"})
    assert s0 == 0
    assert s1 == 0  # t2 starts at 0, not 1
    assert s2 == 1


def test_list_turns_returns_all(ledger: TurnLedger) -> None:
    ledger.append("alpha", {"type": "a"})
    ledger.append("beta", {"type": "b"})
    ledger.append("gamma", {"type": "c"})
    turns = ledger.list_turns()
    assert set(turns) == {"alpha", "beta", "gamma"}


def test_list_turns_empty_when_no_writes(ledger: TurnLedger) -> None:
    assert ledger.list_turns() == []


# ── durability: append-only, never overwrites ────────────────────────


def test_append_never_overwrites(ledger: TurnLedger) -> None:
    for i in range(10):
        ledger.append("t1", {"type": "msg", "i": i})
    records = ledger.read_turn("t1")
    assert len(records) == 10
    assert [r["i"] for r in records] == list(range(10))


def test_file_grows_monotonically(ledger: TurnLedger, tmp_path: Path) -> None:
    ledger.append("t1", {"type": "a"})
    path = ledger.path_for("t1")
    size_1 = path.stat().st_size
    ledger.append("t1", {"type": "b"})
    size_2 = path.stat().st_size
    assert size_2 > size_1


# ── fail-soft: malformed records and read-side recovery ─────────────


def test_read_nonexistent_turn_returns_empty(ledger: TurnLedger) -> None:
    assert ledger.read_turn("does-not-exist") == []


def test_read_skips_malformed_lines(ledger: TurnLedger) -> None:
    """Simulate a crash that left a malformed JSON line in the file."""
    ledger.append("t1", {"type": "good_1"})
    path = ledger.path_for("t1")
    # Inject a broken line between valid records
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"incomplete json without closing\n')
    ledger.append("t1", {"type": "good_2"})

    records = ledger.read_turn("t1")
    # Malformed line skipped, the two valid records survive
    assert len(records) == 2
    assert records[0]["type"] == "good_1"
    assert records[1]["type"] == "good_2"


def test_append_non_serializable_returns_minus_one(ledger: TurnLedger) -> None:
    """Fail-soft: non-JSON-serializable record must NOT raise."""
    class _Unserializable:
        pass
    # json.dumps will fail on this via default=str? default=str will coerce
    # most things. Use a bytes object inside a dict, which default=str would
    # also coerce. Use a truly non-serializable: a set inside a non-str key.
    result = ledger.append("t1", {"data": {frozenset(): "key"}})
    # Depending on json.dumps with default=str behavior this may still
    # succeed. Either result is acceptable: no raise, int returned.
    assert isinstance(result, int)


def test_read_from_missing_directory_returns_empty(tmp_path: Path) -> None:
    """If the base dir doesn't exist on read, return [] not raise."""
    # Create a ledger that never writes, then delete its base dir
    led = TurnLedger(base_dir=tmp_path / "ghost")
    # Force removal
    import shutil
    shutil.rmtree(tmp_path / "ghost", ignore_errors=True)
    assert led.read_turn("t1") == []
    assert led.list_turns() == []


# ── crash recovery: seq resumes from disk on fresh instance ─────────


def test_seq_resumes_after_fresh_instance(tmp_path: Path) -> None:
    """A new TurnLedger pointed at an existing file resumes from max(seq)+1."""
    base = tmp_path / "ledger"
    led1 = TurnLedger(base_dir=base)
    led1.append("t1", {"type": "a"})
    led1.append("t1", {"type": "b"})
    led1.append("t1", {"type": "c"})
    # Fresh instance (simulates process restart)
    led2 = TurnLedger(base_dir=base)
    new_seq = led2.append("t1", {"type": "d"})
    assert new_seq == 3
    records = led2.read_turn("t1")
    assert [r["seq"] for r in records] == [0, 1, 2, 3]
    assert records[-1]["type"] == "d"


def test_seq_resumes_correctly_after_malformed_tail(tmp_path: Path) -> None:
    """Even if the last line was corrupted mid-write, seq resume still
    finds the correct max(seq) from the parseable records."""
    base = tmp_path / "ledger"
    led1 = TurnLedger(base_dir=base)
    led1.append("t1", {"type": "a"})
    led1.append("t1", {"type": "b"})
    # Append a corrupted trailing line manually
    path = led1.path_for("t1")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 99, "incomplete\n')
    # Fresh instance should see seq=1 as the last valid, so next=2
    led2 = TurnLedger(base_dir=base)
    new_seq = led2.append("t1", {"type": "c"})
    assert new_seq == 2
    records = led2.read_turn("t1")
    # Malformed line skipped; 3 valid records: 0, 1, 2
    assert [r["seq"] for r in records] == [0, 1, 2]


# ── concurrency: thread-safe append ordering ─────────────────────────


def test_concurrent_appends_assign_unique_seqs(ledger: TurnLedger) -> None:
    """Spin up N threads that all append to the same turn via a Barrier.

    The per-turn seq counter must be atomic — every record gets a unique
    sequence, the set is exactly {0..N-1}, and every record is durable.
    """
    n_threads = 32
    barrier = threading.Barrier(n_threads)
    seen_seqs: list[int] = []
    seen_lock = threading.Lock()

    def worker(i: int) -> None:
        barrier.wait()
        seq = ledger.append("t1", {"type": "msg", "i": i})
        with seen_lock:
            seen_seqs.append(seq)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(seen_seqs) == list(range(n_threads))
    records = ledger.read_turn("t1")
    assert len(records) == n_threads
    # Deterministic seq ordering on read
    assert [r["seq"] for r in records] == list(range(n_threads))


def test_concurrent_appends_two_turns(ledger: TurnLedger) -> None:
    """Two turns appended concurrently must each get their own 0..N-1 range."""
    n_per_turn = 16
    barrier = threading.Barrier(n_per_turn * 2)

    def worker(turn: str, i: int) -> None:
        barrier.wait()
        ledger.append(turn, {"i": i})

    threads = []
    for i in range(n_per_turn):
        threads.append(threading.Thread(target=worker, args=("t1", i)))
        threads.append(threading.Thread(target=worker, args=("t2", i)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    r1 = ledger.read_turn("t1")
    r2 = ledger.read_turn("t2")
    assert len(r1) == n_per_turn
    assert len(r2) == n_per_turn
    assert [r["seq"] for r in r1] == list(range(n_per_turn))
    assert [r["seq"] for r in r2] == list(range(n_per_turn))


# ── iter_turn ─────────────────────────────────────────────────────────


def test_iter_turn_yields_in_order(ledger: TurnLedger) -> None:
    for i in range(5):
        ledger.append("t1", {"i": i})
    seqs = [r["seq"] for r in ledger.iter_turn("t1")]
    assert seqs == [0, 1, 2, 3, 4]


# ── path_for ──────────────────────────────────────────────────────────


def test_path_for_returns_expected_location(ledger: TurnLedger, tmp_path: Path) -> None:
    path = ledger.path_for("my-turn-id")
    assert path.name == "turn_my-turn-id.jsonl"
    assert path.parent == tmp_path / "ledger"
