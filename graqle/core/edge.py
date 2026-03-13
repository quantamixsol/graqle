"""CogniEdge — a knowledge graph edge that serves as a message channel."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from graqle.core.message import Message


@dataclass
class CogniEdge:
    """A KG edge that serves as a message channel between CogniNode agents.

    Edges carry typed relationships (e.g., "regulates", "conflicts_with")
    and serve as communication channels during message passing rounds.
    """

    id: str
    source_id: str
    target_id: str
    relationship: str = "RELATED_TO"
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0

    # Message channel
    _messages: deque[Message] = field(default_factory=deque, repr=False)
    capacity: int = 100

    def send(self, message: Message) -> None:
        """Send a message along this edge."""
        if len(self._messages) >= self.capacity:
            self._messages.popleft()  # drop oldest
        self._messages.append(message)

    def receive(self) -> Message | None:
        """Receive the next message from this edge (FIFO)."""
        if self._messages:
            return self._messages.popleft()
        return None

    def receive_all(self) -> list[Message]:
        """Receive all pending messages."""
        messages = list(self._messages)
        self._messages.clear()
        return messages

    def peek(self) -> list[Message]:
        """View pending messages without consuming them."""
        return list(self._messages)

    def clear(self) -> None:
        """Clear all pending messages."""
        self._messages.clear()

    @property
    def pending_count(self) -> int:
        """Number of messages waiting to be received."""
        return len(self._messages)

    @property
    def semantic_distance(self) -> float:
        """Compute semantic distance (inverse weight) for PCST cost."""
        return max(1.0 - self.weight, 0.01)
