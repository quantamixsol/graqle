"""ObserverReport — structured findings from the MasterObserver."""

# ── graqle:intelligence ──
# module: graqle.core.observer_report
# risk: LOW (impact radius: 1 modules)
# consumers: observer
# dependencies: __future__, dataclasses, datetime, typing
# constraints: none
# ── /graqle:intelligence ──

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

        v0.12 overhaul: designed for ChunkScorer era where 10-20 nodes
        reason in parallel. Perspective diversity is HEALTHY, not penalized.

        Scoring philosophy:
        - Start at 1.0 (healthy until proven otherwise)
        - Only GENUINE conflicts reduce score (not perspective diversity)
        - Anomalies are expected at scale — only critical ones matter
        - Cap total penalties so score stays meaningful (floor at 0.3
          unless there are critical-severity issues)

        With the v0.12 conflict detection (stricter thresholds, mutual
        reference required), conflict counts should be 0-5 for typical
        20-node queries, not 100+.
        """
        score = 1.0
        n = max(self.total_nodes, 1)

        # --- Conflict penalty ---
        # Conflicts are now pre-filtered by severity in _detect_conflicts.
        # High/critical conflicts matter more than low/medium.
        high_conflicts = sum(
            1 for c in self.conflicts if c.severity in ("high", "critical")
        )
        med_conflicts = sum(
            1 for c in self.conflicts if c.severity == "medium"
        )
        low_conflicts = sum(
            1 for c in self.conflicts if c.severity == "low"
        )
        # High conflicts: -0.08 each (capped at -0.32)
        score -= min(high_conflicts * 0.08, 0.32)
        # Medium conflicts: -0.03 each (capped at -0.15)
        score -= min(med_conflicts * 0.03, 0.15)
        # Low conflicts: -0.01 each (capped at -0.05)
        score -= min(low_conflicts * 0.01, 0.05)

        # --- Anomaly penalty ---
        # Only critical anomalies matter; confidence spikes/drops at scale
        # are normal multi-agent behavior, not problems.
        critical_anomalies = sum(
            1 for a in self.anomalies if a.severity == "critical"
        )
        high_anomalies = sum(
            1 for a in self.anomalies if a.severity == "high"
        )
        score -= min(critical_anomalies * 0.10, 0.20)
        # High anomalies scaled by node count (more nodes = more expected)
        anomaly_scale = max(1.0, n / 5.0)
        score -= min(high_anomalies * (0.03 / anomaly_scale), 0.10)

        # --- Echo chamber penalty ---
        echo = sum(1 for p in self.patterns if p.pattern_type == "echo_chamber")
        # Scale by node count: with 20 nodes, some overlap is expected
        echo_penalty = 0.10 if n <= 5 else 0.05
        score -= min(echo * echo_penalty, 0.15)

        # --- Flip-flop penalty (minor) ---
        flips = sum(c.flip_count for c in self.contributions.values())
        flip_scale = max(1.0, n / 3.0)
        score -= min(flips * (0.01 / flip_scale), 0.05)

        return max(0.0, min(1.0, score))

    def to_summary(self) -> str:
        """Generate a concise human-readable summary."""
        lines = [
            "## Observer Report",
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
            lines.append("\n### Learnings")
            for l in self.learnings:
                lines.append(f"- {l}")

        # Top contributors
        if self.contributions:
            sorted_contribs = sorted(
                self.contributions.values(),
                key=lambda c: c.influence_score,
                reverse=True,
            )
            lines.append("\n### Top Contributors")
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
