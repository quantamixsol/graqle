"""Clearance-aware streaming events for reasoning coordination.

Implements the event model described in every streaming event
carries a ``ClearanceLevel`` so that viewers only receive events they
are permitted to see.  Complete suppression semantics — even timing
metadata is considered leakage for above-clearance events.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator

from graqle.core.types import ClearanceLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class StreamEventType(str, Enum):
    """Event types emitted during wave-based reasoning coordination."""

    COORDINATOR_STARTED = "coordinator_started"
    TASKS_PLANNED = "tasks_planned"
    WAVE_STARTED = "wave_started"
    NODE_ACTIVATED = "node_activated"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    WAVE_COMPLETED = "wave_completed"
    SYNTHESIS_STARTED = "synthesis_started"
    SYNTHESIS_COMPLETE = "synthesis_complete"


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamEvent:
    """A single clearance-tagged streaming event.

    Frozen to guarantee immutability once emitted — no post-hoc
    clearance escalation is possible.
    """

    event: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC
    timestamp: float = field(default_factory=time.time)
    round_num: int | None = None
    wave_num: int | None = None
    task_id: str | None = None
    agent_id: str | None = None

    def visible_to(self, viewer_clearance: ClearanceLevel) -> bool:
        """Return ``True`` if *viewer_clearance* dominates this event's clearance.

        Lattice monotonicity: ``event.clearance <= viewer_clearance``.
        """
        return self.clearance <= viewer_clearance

    def redacted_for(self, viewer_clearance: ClearanceLevel) -> StreamEvent:
        """Return *self* if visible, or a redacted copy preserving metadata.

        Metadata-preserving redaction allows audit trails while protecting
        data content. Event type, timestamp, and structural fields remain visible.
        """
        if self.visible_to(viewer_clearance):
            return self
        return StreamEvent(
            event=self.event,
            data={"redacted": True},
            clearance=self.clearance,
            timestamp=self.timestamp,
            round_num=self.round_num,
            wave_num=self.wave_num,
            task_id=self.task_id,
            agent_id=self.agent_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for SSE transport (``app.py _stream_reason`` compat)."""
        return {
            "event": self.event.value,
            "data": self.data,
            "clearance": self.clearance.value,
            "timestamp": self.timestamp,
            "round_num": self.round_num,
            "wave_num": self.wave_num,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
        }


# ---------------------------------------------------------------------------
# ClearanceAwareEventStream
# ---------------------------------------------------------------------------


class ClearanceAwareEventStream:
    """Accumulates :class:`StreamEvent` instances, filtering by viewer clearance.

    Events exceeding the viewer's clearance are silently suppressed
    (logged at DEBUG level for audit trails).
    """

    def __init__(self, viewer_clearance: ClearanceLevel) -> None:
        self._viewer_clearance = viewer_clearance
        self._events: list[StreamEvent] = []
        self._suppressed_count: int = 0
        self._queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

    def emit(self, event: StreamEvent) -> bool:
        """Emit *event* if the viewer's clearance permits it.

        Returns ``True`` when emitted, ``False`` when suppressed.
        """
        if event.visible_to(self._viewer_clearance):
            self._events.append(event)
            self._queue.put_nowait(event)
            return True

        self._suppressed_count += 1
        logger.debug(
            "Suppressed %s event (clearance=%s, viewer=%s)",
            event.event.value,
            event.clearance,
            self._viewer_clearance,
        )
        return False

    async def stream(self) -> AsyncGenerator[StreamEvent, None]:
        """Yield emitted events as they arrive.

        Call :meth:`close` to signal end-of-stream.
        """
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item

    def close(self) -> None:
        """Signal end-of-stream to any active ``stream()`` consumer."""
        self._queue.put_nowait(None)

    @property
    def suppressed_count(self) -> int:
        """Number of events suppressed due to clearance filtering."""
        return self._suppressed_count

    @property
    def events(self) -> list[StreamEvent]:
        """All events that passed clearance filtering."""
        return list(self._events)
