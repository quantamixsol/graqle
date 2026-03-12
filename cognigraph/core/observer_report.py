"""ObserverReport — structured findings from the MasterObserver."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConflictPair:
    """Two nodes whose outputs contradict each other."""

    node_a: str
    node_b: str
    claim_a: str
    claim_b: str
    round_detected: int
    severity: str = "medium"  # low, medium, high, critical


@dataclass
class PatternInsight:
    """A pattern detected across multiple node interactions."""

    pattern_type: str  # "convergence", "echo_chamber", "flip_flop", "isolation", "dominance"
    description: str
    involved_nodes: list[str]
    confidence: float
    round_detected: int
    recommendation: str = ""


@dataclass
class AnomalyFlag:
    """An anomaly detected in the reasoning process."""

    anomaly_type: str  # "confidence_spike", "confidence_drop", "contradicts_self", "timeout", "empty_response"
    node_id: str
    description: str
    round: int
    severity: str = "medium"


@dataclass
class NodeContribution:
    """How much a node contributed to the final answer."""

    node_id: str
    messages_sent: int
    avg_confidence: float
    reasoning_types: dict[str, int]  # type -> count
    influence_score: float  # 0-1, how much this node shaped the outcome
    was_contradicted: bool = False
    flip_count: int = 0  # how many times it changed its position


@dataclass
class ObserverReport:
    """Full transparency report from the MasterObserver.

    This report provides human-readable transparency into how the
    distributed reasoning process arrived at its answer. It catches
    errors, finds patterns, and flags anomalies that would be
    impossible for a human to track across dozens of concurrent agents.
    """

    # Summary
    query: str
    total_rounds: int
    total_messages: int
    total_nodes: int
    overall_confidence: float

    # Conflicts
    conflicts: list[ConflictPair] = field(default_factory=list)

    # Patterns
    patterns: list[PatternInsight] = field(default_factory=list)

    # Anomalies
    anomalies: list[AnomalyFlag] = field(default_factory=list)

    # Per-node contributions
    contributions: dict[str, NodeContribution] = field(default_factory=dict)

    # Confidence trajectory (per round)
    confidence_trajectory: list[float] = field(default_factory=list)

    # Learnings — what the observer discovered
    learnings: list[str] = field(default_factory=list)

    # Metadata
    observer_model: str = ""
    observer_cost_usd: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)

    @property
    def pattern_count(self) -> int:
        return len(self.patterns)

    @property
    def health_score(self) -> float:
        """Overall reasoning health score (0-1).

        Penalizes for conflicts, anomalies, and unhealthy patterns.
        Scales penalties by node count to avoid false-low scores when
        many nodes reason in parallel (e.g., 20-node ChunkScorer).

        With N nodes, the maximum possible conflict pairs is N*(N-1)/2.
        We normalize conflict penalty so that even worst-case multi-node
        scenarios don't drive health to 0% from perspective diversity alone.
        """
        score = 1.0
        n = max(self.total_nodes, 1)

        # Conflict penalty — scaled by node count.
        # With 1-3 nodes (PCST era): 0.05 per conflict (original).
        # With 20 nodes: max_pairs=190, so per-conflict penalty shrinks
        # to keep the score meaningful. Cap total conflict penalty at 0.4.
        if n <= 3:
            conflict_penalty_each = 0.05
        else:
            # Scale: penalty = 0.4 / max_pairs, so 100% conflicts → -0.4
            max_pairs = n * (n - 1) / 2
            conflict_penalty_each = min(0.05, 0.4 / max(max_pairs, 1))
        score -= len(self.conflicts) * conflict_penalty_each

        # Anomaly penalty — scale by node count (more nodes = more anomalies expected)
        critical = sum(1 for a in self.anomalies if a.severity in ("high", "critical"))
        anomaly_penalty_each = 0.1 if n <= 3 else 0.1 / (n / 3)
        score -= critical * anomaly_penalty_each

        # Penalty for echo chambers
        echo = sum(1 for p in self.patterns if p.pattern_type == "echo_chamber")
        score -= echo * 0.15

        # Penalty for flip-flopping nodes — scale by node count
        flips = sum(c.flip_count for c in self.contributions.values())
        flip_penalty_each = 0.02 if n <= 3 else 0.02 / (n / 3)
        score -= flips * flip_penalty_each

        return max(0.0, min(1.0, score))

    def to_summary(self) -> str:
        """Generate a concise human-readable summary."""
        lines = [
            f"## Observer Report",
            f"Health: {self.health_score:.0%} | "
            f"Confidence: {self.overall_confidence:.0%} | "
            f"Rounds: {self.total_rounds} | "
            f"Nodes: {self.total_nodes}",
        ]

        if self.conflicts:
            lines.append(f"\n### Conflicts ({len(self.conflicts)})")
            for c in self.conflicts:
                lines.append(
                    f"- [{c.severity.upper()}] {c.node_a} vs {c.node_b} "
                    f"(round {c.round_detected})"
                )

        if self.patterns:
            lines.append(f"\n### Patterns ({len(self.patterns)})")
            for p in self.patterns:
                lines.append(
                    f"- [{p.pattern_type}] {p.description} "
                    f"(confidence: {p.confidence:.0%})"
                )

        if self.anomalies:
            lines.append(f"\n### Anomalies ({len(self.anomalies)})")
            for a in self.anomalies:
                lines.append(
                    f"- [{a.severity.upper()}] {a.anomaly_type} at {a.node_id} "
                    f"(round {a.round})"
                )

        if self.learnings:
            lines.append(f"\n### Learnings")
            for l in self.learnings:
                lines.append(f"- {l}")

        # Top contributors
        if self.contributions:
            sorted_contribs = sorted(
                self.contributions.values(),
                key=lambda c: c.influence_score,
                reverse=True,
            )
            lines.append(f"\n### Top Contributors")
            for c in sorted_contribs[:5]:
                lines.append(
                    f"- {c.node_id}: influence={c.influence_score:.0%}, "
                    f"confidence={c.avg_confidence:.0%}, "
                    f"messages={c.messages_sent}"
                )

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "health_score": self.health_score,
            "overall_confidence": self.overall_confidence,
            "total_rounds": self.total_rounds,
            "total_nodes": self.total_nodes,
            "total_messages": self.total_messages,
            "conflicts": len(self.conflicts),
            "anomalies": len(self.anomalies),
            "patterns": len(self.patterns),
            "learnings": self.learnings,
            "confidence_trajectory": self.confidence_trajectory,
            "contributions": {
                k: {
                    "influence": v.influence_score,
                    "avg_confidence": v.avg_confidence,
                    "messages": v.messages_sent,
                    "contradicted": v.was_contradicted,
                }
                for k, v in self.contributions.items()
            },
        }
