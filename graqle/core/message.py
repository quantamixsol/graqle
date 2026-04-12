"""Message — the fundamental unit of inter-agent communication in Graqle."""

# ── graqle:intelligence ──
# module: graqle.core.message
# risk: HIGH (impact radius: 26 modules)
# consumers: __init__, base_agent, slm_agent, edge, graph +21 more
# dependencies: __future__, uuid, dataclasses, datetime, types
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from graqle.core.types import ReasoningType


@dataclass
class Message:
    """A message passed between CogniNode agents.

    Messages carry reasoning fragments, confidence scores, and full provenance.
    They are the atomic unit of the emergent reasoning process — insights emerge
    from message EXCHANGES, not from any single agent.
    """

    # Identity
    source_node_id: str
    target_node_id: str
    round: int

    # Content
    content: str
    reasoning_type: ReasoningType = ReasoningType.ASSERTION
    confidence: float = 0.5

    # Provenance
    evidence: list[str] = field(default_factory=list)
    parent_messages: list[str] = field(default_factory=list)

    # Metadata
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = field(default_factory=datetime.utcnow)
    token_count: int = 0
    metadata: dict = field(default_factory=dict)  # extensible metadata (truncation, etc.)

    def to_prompt_context(self) -> str:
        """Format message for inclusion in an SLM prompt."""
        type_label = self.reasoning_type.value.upper()
        conf = f"{self.confidence:.0%}"
        return (
            f"[{type_label} from {self.source_node_id} | confidence={conf}]\n"
            f"{self.content}"
        )

    def to_dict(self) -> dict:
        """Serialize for tracing and logging."""
        return {
            "id": self.id,
            "source": self.source_node_id,
            "target": self.target_node_id,
            "round": self.round,
            "type": self.reasoning_type.value,
            "content": self.content,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "parents": self.parent_messages,
            "tokens": self.token_count,
            "timestamp": self.timestamp.isoformat(),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def create_query_broadcast(
        cls, query: str, target_node_id: str
    ) -> Message:
        """Create an initial query message broadcast to a node."""
        return cls(
            source_node_id="__query__",
            target_node_id=target_node_id,
            round=0,
            content=query,
            reasoning_type=ReasoningType.QUESTION,
            confidence=1.0,
        )
