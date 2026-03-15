"""ExplanationTrace — full provenance chain for reasoning transparency.

Tracks which nodes said what, how messages flowed through the graph,
and how each node's output influenced the final answer. This creates
an auditable trail that answers: "Why did Graqle say X?"
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.explanation
# risk: LOW (impact radius: 1 modules)
# consumers: test_explanation
# dependencies: __future__, dataclasses, typing, message
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graqle.core.message import Message


@dataclass
class NodeClaim:
    """A single claim made by a node during reasoning."""

    node_id: str
    round_num: int
    content: str
    confidence: float
    reasoning_type: str
    influenced_by: list[str] = field(default_factory=list)  # node IDs that informed this


@dataclass
class InfluenceEdge:
    """How one node's output influenced another."""

    source_node_id: str
    target_node_id: str
    round_num: int
    influence_strength: float  # 0-1, based on confidence delta


@dataclass
class ExplanationTrace:
    """Full provenance chain for a reasoning result.

    Answers: which nodes contributed, how they influenced each other,
    and what claims led to the final answer.
    """

    query: str
    claims: list[NodeClaim] = field(default_factory=list)
    influences: list[InfluenceEdge] = field(default_factory=list)
    final_answer: str = ""
    total_rounds: int = 0

    def add_round(
        self,
        round_num: int,
        messages: dict[str, Message],
        previous_messages: dict[str, Message] | None = None,
        neighbor_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Record one round of reasoning."""
        for node_id, msg in messages.items():
            # Which neighbors informed this node?
            influenced_by: list[str] = []
            if previous_messages and neighbor_map:
                for neighbor_id in neighbor_map.get(node_id, []):
                    if neighbor_id in previous_messages:
                        influenced_by.append(neighbor_id)

            self.claims.append(NodeClaim(
                node_id=node_id,
                round_num=round_num,
                content=msg.content[:500],
                confidence=msg.confidence,
                reasoning_type=msg.reasoning_type.value,
                influenced_by=influenced_by,
            ))

            # Compute influence edges
            if previous_messages:
                prev_conf = previous_messages.get(node_id)
                if prev_conf is not None:
                    delta = abs(msg.confidence - prev_conf.confidence)
                    for src_id in influenced_by:
                        self.influences.append(InfluenceEdge(
                            source_node_id=src_id,
                            target_node_id=node_id,
                            round_num=round_num,
                            influence_strength=min(delta * 2, 1.0),
                        ))

        self.total_rounds = max(self.total_rounds, round_num + 1)

    @property
    def contributing_nodes(self) -> list[str]:
        """Unique node IDs that contributed claims."""
        return list(set(c.node_id for c in self.claims))

    @property
    def top_influencers(self) -> list[tuple[str, float]]:
        """Nodes ranked by total outgoing influence."""
        influence_totals: dict[str, float] = {}
        for edge in self.influences:
            influence_totals[edge.source_node_id] = (
                influence_totals.get(edge.source_node_id, 0.0) + edge.influence_strength
            )
        return sorted(influence_totals.items(), key=lambda x: x[1], reverse=True)

    def get_node_journey(self, node_id: str) -> list[NodeClaim]:
        """Get all claims from a specific node across rounds."""
        return [c for c in self.claims if c.node_id == node_id]

    def to_summary(self) -> str:
        """Human-readable provenance summary."""
        lines = [
            f"## Explanation Trace",
            f"Query: {self.query}",
            f"Rounds: {self.total_rounds} | Nodes: {len(self.contributing_nodes)} | Claims: {len(self.claims)}",
        ]

        # Top influencers
        if self.top_influencers:
            lines.append("\n### Top Influencers")
            for node_id, score in self.top_influencers[:5]:
                lines.append(f"- {node_id}: influence={score:.2f}")

        # Claim timeline
        lines.append("\n### Claim Timeline")
        for claim in self.claims:
            influenced = f" ← {', '.join(claim.influenced_by)}" if claim.influenced_by else ""
            lines.append(
                f"- R{claim.round_num} [{claim.node_id}] "
                f"({claim.confidence:.0%}, {claim.reasoning_type}): "
                f"{claim.content[:100]}{influenced}"
            )

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "query": self.query,
            "total_rounds": self.total_rounds,
            "contributing_nodes": self.contributing_nodes,
            "top_influencers": [
                {"node_id": nid, "influence": score}
                for nid, score in self.top_influencers
            ],
            "claims": [
                {
                    "node_id": c.node_id,
                    "round": c.round_num,
                    "content": c.content,
                    "confidence": c.confidence,
                    "reasoning_type": c.reasoning_type,
                    "influenced_by": c.influenced_by,
                }
                for c in self.claims
            ],
            "influences": [
                {
                    "source": e.source_node_id,
                    "target": e.target_node_id,
                    "round": e.round_num,
                    "strength": e.influence_strength,
                }
                for e in self.influences
            ],
        }
