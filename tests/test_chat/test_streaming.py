"""TB-F1.1 regression tests for graqle.chat.streaming.

Coverage targets driven by the pre-impl graq_review at 93% confidence:

  Happy path:
    - ChatEvent JSON round-trip
    - ChatEventBuffer monotonic sequence allocation
    - snapshot_since cursor semantics
    - poll_events long-poll with new events arriving
    - TURN_COMPLETE → done flag

  Negative path:
    - from_dict with missing/wrong-type fields
    - from_dict unknown event type
    - from_json invalid JSON
    - empty-buffer poll returns empty + correct next_seq
    - poll_events timeout expiry

  Concurrency:
    - threading.Barrier-based deterministic monotonicity check
      (no two events get the same sequence under contention)
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_streaming
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, threading, json, graqle.chat.streaming
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import threading
import time

import pytest

from graqle.chat.streaming import (
    ChatEvent,
    ChatEventBuffer,
    ChatEventType,
    PollResult,
    poll_events,
)


# ── ChatEvent serialization ───────────────────────────────────────────


def test_chat_event_to_dict_round_trip() -> None:
    e = ChatEvent(
        type=ChatEventType.USER_MESSAGE,
        turn_id="t1",
        event_sequence=0,
        timestamp="2026-04-11T12:00:00+00:00",
        data={"text": "hello"},
    )
    d = e.to_dict()
    assert d["type"] == "user_message"
    assert d["turn_id"] == "t1"
    assert d["event_sequence"] == 0
    assert d["data"] == {"text": "hello"}
    assert d["tool_call_id"] is None


def test_chat_event_json_round_trip() -> None:
    e = ChatEvent(
        type=ChatEventType.TOOL_PLANNED,
        turn_id="t2",
        event_sequence=5,
        timestamp="2026-04-11T12:00:01+00:00",
        data={"tool_name": "graq_generate", "rationale": "codegen intent"},
        tool_call_id="call-1",
    )
    raw = e.to_json()
    parsed = json.loads(raw)
    assert parsed["tool_call_id"] == "call-1"
    e2 = ChatEvent.from_json(raw)
    assert e2.type is ChatEventType.TOOL_PLANNED
    assert e2.event_sequence == 5
    assert e2.tool_call_id == "call-1"


# ── from_dict negative paths ─────────────────────────────────────────


def test_from_dict_missing_field_raises() -> None:
    with pytest.raises(ValueError, match="missing field"):
        ChatEvent.from_dict({"type": "user_message", "turn_id": "t1"})


def test_from_dict_unknown_type_raises() -> None:
    raw = {
        "type": "not_a_real_event",
        "turn_id": "t1",
        "event_sequence": 0,
        "timestamp": "2026-04-11T00:00:00+00:00",
        "data": {},
    }
    with pytest.raises(ValueError, match="unknown type"):
        ChatEvent.from_dict(raw)


def test_from_dict_non_dict_raises() -> None:
    with pytest.raises(ValueError, match="expected dict"):
        ChatEvent.from_dict([])  # type: ignore[arg-type]


def test_from_dict_data_must_be_dict() -> None:
    raw = {
        "type": "user_message",
        "turn_id": "t1",
        "event_sequence": 0,
        "timestamp": "2026-04-11T00:00:00+00:00",
        "data": "not a dict",
    }
    with pytest.raises(ValueError, match="must be dict"):
        ChatEvent.from_dict(raw)


def test_from_json_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        ChatEvent.from_json("not { json")


def test_from_dict_event_sequence_coerces_int() -> None:
    raw = {
        "type": "user_message",
        "turn_id": "t1",
        "event_sequence": "3",  # str → int
        "timestamp": "2026-04-11T00:00:00+00:00",
        "data": {},
    }
    e = ChatEvent.from_dict(raw)
    assert e.event_sequence == 3


# ── ChatEventBuffer monotonic allocation ─────────────────────────────


def test_buffer_allocates_monotonic_sequences() -> None:
    buf = ChatEventBuffer("t1")
    e0 = buf.append(ChatEventType.USER_MESSAGE, {"text": "hi"})
    e1 = buf.append(ChatEventType.ASSISTANT_TEXT_CHUNK, {"chunk": "a"})
    e2 = buf.append(ChatEventType.ASSISTANT_TEXT_CHUNK, {"chunk": "b"})
    assert (e0.event_sequence, e1.event_sequence, e2.event_sequence) == (0, 1, 2)
    assert buf.done is False


def test_buffer_done_after_turn_complete() -> None:
    buf = ChatEventBuffer("t1")
    buf.append(ChatEventType.USER_MESSAGE, {})
    buf.append(ChatEventType.TURN_COMPLETE, {})
    assert buf.done is True


# ── snapshot_since cursor semantics ──────────────────────────────────


def test_snapshot_since_returns_tail() -> None:
    buf = ChatEventBuffer("t1")
    for i in range(5):
        buf.append(ChatEventType.ASSISTANT_TEXT_CHUNK, {"i": i})
    snap = buf.snapshot_since(2)
    assert len(snap.events) == 3
    assert [e.event_sequence for e in snap.events] == [2, 3, 4]
    assert snap.next_seq == 5
    assert snap.done is False


def test_snapshot_since_returns_empty_at_cursor_end() -> None:
    buf = ChatEventBuffer("t1")
    buf.append(ChatEventType.USER_MESSAGE, {})
    snap = buf.snapshot_since(1)  # cursor at end
    assert snap.events == []
    assert snap.next_seq == 1
    assert snap.done is False


def test_snapshot_since_done_true_after_turn_complete_observed() -> None:
    buf = ChatEventBuffer("t1")
    buf.append(ChatEventType.USER_MESSAGE, {})
    buf.append(ChatEventType.TURN_COMPLETE, {})
    snap = buf.snapshot_since(0)
    # Caller has now observed all events including TURN_COMPLETE
    assert snap.done is True
    assert snap.events[-1].type is ChatEventType.TURN_COMPLETE


# ── poll_events long-poll behavior ───────────────────────────────────


def test_poll_events_returns_immediately_with_zero_timeout() -> None:
    buf = ChatEventBuffer("t1")
    buf.append(ChatEventType.USER_MESSAGE, {})
    snap = poll_events(buf, since_seq=0, timeout=0)
    assert len(snap.events) == 1


def test_poll_events_empty_returns_immediately_with_zero_timeout() -> None:
    buf = ChatEventBuffer("t1")
    snap = poll_events(buf, since_seq=0, timeout=0)
    assert snap.events == []
    assert snap.next_seq == 0


def test_poll_events_timeout_expires() -> None:
    buf = ChatEventBuffer("t1")
    start = time.monotonic()
    snap = poll_events(buf, since_seq=0, timeout=0.15, poll_interval=0.05)
    elapsed = time.monotonic() - start
    assert snap.events == []
    assert 0.10 <= elapsed < 1.0  # actually waited (allow scheduling slack)


def test_poll_events_returns_when_event_arrives() -> None:
    buf = ChatEventBuffer("t1")

    def producer() -> None:
        time.sleep(0.05)
        buf.append(ChatEventType.ASSISTANT_TEXT_CHUNK, {"chunk": "delayed"})

    t = threading.Thread(target=producer)
    t.start()
    snap = poll_events(buf, since_seq=0, timeout=1.0, poll_interval=0.02)
    t.join()
    assert len(snap.events) == 1
    assert snap.events[0].data == {"chunk": "delayed"}


# ── concurrency: barrier-based deterministic monotonicity ────────────


def test_buffer_concurrent_appends_no_duplicates_or_gaps() -> None:
    """Spin up N threads that all append simultaneously via a Barrier.

    The lock inside ChatEventBuffer.append must serialize them so that
    every event has a unique sequence and the set is exactly {0..N-1}.
    """
    buf = ChatEventBuffer("t1")
    n_threads = 32
    barrier = threading.Barrier(n_threads)
    seen: list[int] = []
    seen_lock = threading.Lock()

    def worker(i: int) -> None:
        barrier.wait()
        e = buf.append(ChatEventType.ASSISTANT_TEXT_CHUNK, {"i": i})
        with seen_lock:
            seen.append(e.event_sequence)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(seen) == list(range(n_threads))
    assert len(buf.all_events()) == n_threads


# ── PollResult.to_dict ───────────────────────────────────────────────


def test_pollresult_to_dict() -> None:
    buf = ChatEventBuffer("t1")
    buf.append(ChatEventType.USER_MESSAGE, {"text": "hi"})
    snap = buf.snapshot_since(0)
    d = snap.to_dict()
    assert "events" in d
    assert d["next_seq"] == 1
    assert d["done"] is False
    assert d["events"][0]["type"] == "user_message"
