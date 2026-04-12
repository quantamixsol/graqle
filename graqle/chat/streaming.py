"""ChatAgentLoop v4 streaming events .

ChatEvent is the wire envelope the SDK emits to its client (the VS Code
extension webview, or any future MCP consumer). Each turn has a monotonic
per-turn ``event_sequence`` so the long-poll handler can resume from a
cursor without losing or duplicating events.

Design decisions (validated by graq_reason at 91% conf and graq_review
at 93% conf):

- ChatEvent is a frozen slotted dataclass, NOT Pydantic. Streaming hot
  paths cannot afford the Pydantic validation cost per event.
- Per-turn sequences are allocated by ChatEventBuffer under a single
  threading.Lock so concurrent producers cannot interleave or skip.
- Long-poll cursor semantics: ``poll`` returns ``(events, next_seq, done)``
  where ``done`` is True after a TURN_COMPLETE event has been observed.

This module has zero dependencies on other graqle packages so it can be
imported in isolation by the chat package and by tests.
"""

# ── graqle:intelligence ──
# module: graqle.chat.streaming
# risk: LOW (impact radius: 0 modules at will rise to ~10 by # consumers: graqle.chat.agent_loop graqle.plugins.mcp_dev_server # dependencies: dataclasses, enum, json, threading, time, typing, datetime
# constraints: zero intra-graqle deps, JSON-serializable
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "ChatEventType",
    "ChatEvent",
    "ChatEventBuffer",
    "PollResult",
    "poll_events",
]


class ChatEventType(str, Enum):
    """The 11 event types ChatAgentLoop v4 emits.

    Wire format is the str value (lowercase, snake_case) so the webview
    can dispatch on a string switch without import-time enum parsing.
    """

    USER_MESSAGE = "user_message"
    ASSISTANT_TEXT_CHUNK = "assistant_text_chunk"
    TOOL_PLANNED = "tool_planned"
    GOVERNANCE_CHIP = "governance_chip"
    TOOL_STARTED = "tool_started"
    TOOL_OUTPUT_CHUNK = "tool_output_chunk"
    TOOL_ENDED = "tool_ended"
    TOOL_ERROR = "tool_error"
    DEBATE_CHIP = "debate_chip"
    PERMISSION_REQUESTED = "permission_requested"
    TURN_COMPLETE = "turn_complete"


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """Immutable per-turn event envelope.

    Fields:
      type: ChatEventType
      turn_id: stable per-turn identifier (UUIDv7-style)
      event_sequence: monotonic per-turn sequence allocated by ChatEventBuffer
      timestamp: ISO-8601 UTC string
      data: arbitrary JSON-serializable payload
      tool_call_id: optional, set on tool_* and permission_requested events
      parent_event_id: optional, links a follow-up event back to its trigger
    """

    type: ChatEventType
    turn_id: str
    event_sequence: int
    timestamp: str
    data: dict[str, Any]
    tool_call_id: str | None = None
    parent_event_id: str | None = None

    # ── serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "type": self.type.value,
            "turn_id": self.turn_id,
            "event_sequence": self.event_sequence,
            "timestamp": self.timestamp,
            "data": self.data,
            "tool_call_id": self.tool_call_id,
            "parent_event_id": self.parent_event_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatEvent":
        """Construct from a dict (raises ValueError on missing/invalid type)."""
        if not isinstance(raw, dict):
            raise ValueError(
                f"ChatEvent.from_dict expected dict, got {type(raw).__name__}"
            )
        # Strict validation: every required field must be present and the
        # right shape. Coerce-friendly fields stay narrow (event_sequence
        # accepts int-like strings since web JSON sometimes serializes
        # ints as strings, but everything else is type-checked).
        for key in ("type", "turn_id", "event_sequence", "timestamp"):
            if key not in raw:
                raise ValueError(f"ChatEvent.from_dict missing field: {key!r}")
        type_str = raw["type"]
        turn_id = raw["turn_id"]
        timestamp = raw["timestamp"]
        if not isinstance(turn_id, str):
            raise ValueError(
                f"ChatEvent.from_dict 'turn_id' must be str, got {type(turn_id).__name__}"
            )
        if not isinstance(timestamp, str):
            raise ValueError(
                f"ChatEvent.from_dict 'timestamp' must be str, got {type(timestamp).__name__}"
            )
        try:
            event_sequence = int(raw["event_sequence"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"ChatEvent.from_dict 'event_sequence' must be int-like: {exc}"
            ) from None
        if event_sequence < 0:
            raise ValueError("ChatEvent.from_dict 'event_sequence' must be >= 0")
        data = raw.get("data") or {}
        try:
            event_type = ChatEventType(type_str)
        except ValueError:
            raise ValueError(
                f"ChatEvent.from_dict unknown type {type_str!r}"
            ) from None
        if not isinstance(data, dict):
            raise ValueError(
                f"ChatEvent.from_dict 'data' must be dict, got {type(data).__name__}"
            )
        # Optional metadata fields must be str-or-None when present.
        tool_call_id = raw.get("tool_call_id")
        if tool_call_id is not None and not isinstance(tool_call_id, str):
            raise ValueError(
                f"ChatEvent.from_dict 'tool_call_id' must be str|None"
            )
        parent_event_id = raw.get("parent_event_id")
        if parent_event_id is not None and not isinstance(parent_event_id, str):
            raise ValueError(
                f"ChatEvent.from_dict 'parent_event_id' must be str|None"
            )
        return cls(
            type=event_type,
            turn_id=turn_id,
            event_sequence=event_sequence,
            timestamp=timestamp,
            data=data,
            tool_call_id=tool_call_id,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def from_json(cls, raw: str) -> "ChatEvent":
        try:
            return cls.from_dict(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"ChatEvent.from_json invalid JSON: {exc}") from None


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PollResult:
    """Result of a long-poll cursor read."""

    events: list[ChatEvent]
    next_seq: int
    done: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "next_seq": self.next_seq,
            "done": self.done,
        }


class ChatEventBuffer:
    """Per-turn append-only buffer with monotonic sequence allocation.

    Thread-safe: ``append`` is serialized through an internal Lock so
    concurrent producers cannot allocate the same sequence number or
    interleave under a sequence allocation. ``snapshot_since`` is also
    locked for read consistency.
    """

    def __init__(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._lock = threading.Lock()
        self._events: list[ChatEvent] = []
        self._next_seq: int = 0
        # Sequence of the TURN_COMPLETE event, if observed. -1 means not yet.
        # Replaces the previous bool flag with an explicit terminal cursor
        # so snapshot_since can compute done unambiguously.
        self._terminal_seq: int = -1

    @property
    def turn_id(self) -> str:
        return self._turn_id

    @property
    def done(self) -> bool:
        return self._terminal_seq >= 0

    def append(
        self,
        event_type: ChatEventType,
        data: dict[str, Any] | None = None,
        *,
        tool_call_id: str | None = None,
        parent_event_id: str | None = None,
    ) -> ChatEvent:
        """Allocate the next sequence number and append a new event."""
        with self._lock:
            # SDK-HF-02 / hardening: validate JSON-serializability
            # at append time so producers fail fast at the boundary, not
            # later in to_json() / on the wire.
            payload = dict(data or {})
            try:
                json.dumps(payload, default=str, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"ChatEventBuffer.append: data must be JSON-serializable: {exc}"
                ) from None
            evt = ChatEvent(
                type=event_type,
                turn_id=self._turn_id,
                event_sequence=self._next_seq,
                timestamp=_utc_iso_now(),
                data=payload,
                tool_call_id=tool_call_id,
                parent_event_id=parent_event_id,
            )
            self._events.append(evt)
            if event_type is ChatEventType.TURN_COMPLETE:
                self._terminal_seq = self._next_seq
            self._next_seq += 1
            return evt

    def snapshot_since(self, since_seq: int) -> PollResult:
        """Return all events with event_sequence >= since_seq, plus the cursor.

        ``done`` is True iff a TURN_COMPLETE event has been observed AND
        the caller has now seen it (i.e. the cursor has advanced past it).
        """
        with self._lock:
            tail = [e for e in self._events if e.event_sequence >= since_seq]
            next_seq = self._next_seq
            # Done iff a TURN_COMPLETE was observed (terminal_seq >= 0)
            # AND the caller's snapshot now contains that terminal event
            # (i.e. terminal_seq is in the returned tail).
            done_flag = (
                self._terminal_seq >= 0 and self._terminal_seq >= since_seq
            )
            return PollResult(events=tail, next_seq=next_seq, done=done_flag)

    def all_events(self) -> list[ChatEvent]:
        """Return a copy of all events seen so far (snapshot)."""
        with self._lock:
            return list(self._events)


def poll_events(
    buffer: ChatEventBuffer,
    since_seq: int,
    timeout: float = 0.0,
    poll_interval: float = 0.05,
) -> PollResult:
    """Long-poll helper: wait up to ``timeout`` seconds for new events.

    Returns immediately if events are already available or if ``timeout`` is 0.
    Polls the buffer every ``poll_interval`` seconds until either new events
    appear or the deadline expires.
    """
    if timeout <= 0:
        return buffer.snapshot_since(since_seq)

    deadline = time.monotonic() + timeout
    while True:
        snap = buffer.snapshot_since(since_seq)
        if snap.events or snap.done:
            return snap
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return snap
        time.sleep(min(poll_interval, remaining))
