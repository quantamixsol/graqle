# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26167849.4, owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Governance Failure Feature Extraction (R19 ADR-202).

Extracts a fixed-order feature vector phi(G, H) from:
- G: GovernanceTopology (from reasoning/coordinator.py)
- H: Execution history (R18 TraceStore JSONL)

The feature vector feeds the causal chain predictor:
    P(F | G, H) = sigma(w * phi(G, H))

Feature families:
1. Gate behavior (pass/block/warn ratios)
2. Clearance escalation patterns
3. Tool reliability metrics
4. Latency anomaly signals
5. Governance decision patterns
6. Topology structure metrics

TS-2 Gate: Feature selection and ordering is core IP.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Feature Sub-Models
# ---------------------------------------------------------------------------


class GateMetrics(BaseModel):
    """Gate pass/block/warn behavior from trace history."""

    model_config = ConfigDict(extra="forbid")

    total_decisions: int = 0
    pass_ratio: float = 0.0
    block_ratio: float = 0.0
    warn_ratio: float = 0.0
    override_rate: float = 0.0


class ClearanceMetrics(BaseModel):
    """Clearance escalation patterns."""

    model_config = ConfigDict(extra="forbid")

    escalation_gap_mean: float = 0.0
    escalation_gap_max: float = 0.0
    distinct_levels_used: int = 0


class ToolMetrics(BaseModel):
    """Tool reliability from trace outcomes."""

    model_config = ConfigDict(extra="forbid")

    total_calls: int = 0
    failure_rate: float = 0.0
    blocked_rate: float = 0.0
    distinct_tools: int = 0


class LatencyMetrics(BaseModel):
    """Latency anomaly signals."""

    model_config = ConfigDict(extra="forbid")

    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    anomaly_count: int = 0


class DecisionPatternMetrics(BaseModel):
    """Governance decision structural patterns."""

    model_config = ConfigDict(extra="forbid")

    complies_with_count: int = 0
    amends_count: int = 0
    governs_count: int = 0
    decision_entropy: float = 0.0


class TopologyMetrics(BaseModel):
    """Governance graph structural metrics."""

    model_config = ConfigDict(extra="forbid")

    node_count: int = 0
    edge_count: int = 0
    avg_degree: float = 0.0


class TraceWindowMetrics(BaseModel):
    """Trace window metadata."""

    model_config = ConfigDict(extra="forbid")

    sample_count: int = 0
    window_hours: float = 0.0


# ---------------------------------------------------------------------------
# Top-Level Feature Bundle
# ---------------------------------------------------------------------------


VECTOR_SIZE = 25


class GovernanceFailureFeatures(BaseModel):
    """Complete feature vector for failure chain prediction.

    All numeric fields are deterministic for a given (G, H) input.
    Serializes to a fixed-order vector via to_vector().
    """

    model_config = ConfigDict(extra="forbid")

    feature_version: str = "r19.1"
    gate: GateMetrics = Field(default_factory=GateMetrics)
    clearance: ClearanceMetrics = Field(default_factory=ClearanceMetrics)
    tool: ToolMetrics = Field(default_factory=ToolMetrics)
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    decision_patterns: DecisionPatternMetrics = Field(default_factory=DecisionPatternMetrics)
    topology: TopologyMetrics = Field(default_factory=TopologyMetrics)
    trace_window: TraceWindowMetrics = Field(default_factory=TraceWindowMetrics)

    def to_vector(self) -> list[float]:
        """Serialize to fixed-order numeric vector for w * phi(G,H)."""
        return [
            # Gate (5)
            float(self.gate.total_decisions),
            self.gate.pass_ratio,
            self.gate.block_ratio,
            self.gate.warn_ratio,
            self.gate.override_rate,
            # Clearance (3)
            self.clearance.escalation_gap_mean,
            self.clearance.escalation_gap_max,
            float(self.clearance.distinct_levels_used),
            # Tool (4)
            float(self.tool.total_calls),
            self.tool.failure_rate,
            self.tool.blocked_rate,
            float(self.tool.distinct_tools),
            # Latency (4)
            self.latency.p50_ms,
            self.latency.p95_ms,
            self.latency.max_ms,
            float(self.latency.anomaly_count),
            # Decision patterns (4)
            float(self.decision_patterns.complies_with_count),
            float(self.decision_patterns.amends_count),
            float(self.decision_patterns.governs_count),
            self.decision_patterns.decision_entropy,
            # Topology (3)
            float(self.topology.node_count),
            float(self.topology.edge_count),
            self.topology.avg_degree,
            # Trace window (2)
            float(self.trace_window.sample_count),
            self.trace_window.window_hours,
        ]

    @staticmethod
    def feature_names() -> list[str]:
        """Fixed-order feature names matching to_vector() output."""
        return [
            "gate.total_decisions", "gate.pass_ratio", "gate.block_ratio",
            "gate.warn_ratio", "gate.override_rate",
            "clearance.escalation_gap_mean", "clearance.escalation_gap_max",
            "clearance.distinct_levels_used",
            "tool.total_calls", "tool.failure_rate", "tool.blocked_rate",
            "tool.distinct_tools",
            "latency.p50_ms", "latency.p95_ms", "latency.max_ms",
            "latency.anomaly_count",
            "decision.complies_with", "decision.amends", "decision.governs",
            "decision.entropy",
            "topology.node_count", "topology.edge_count", "topology.avg_degree",
            "trace.sample_count", "trace.window_hours",
        ]




# ---------------------------------------------------------------------------
# Feature Extraction
# ---------------------------------------------------------------------------

# Clearance level ordinals for gap computation
_CLEARANCE_ORDINAL = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}


def _safe_entropy(counts: list[int]) -> float:
    """Shannon entropy over a list of counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    return -sum(p * math.log2(p) for p in probs)


def _percentile(values: list[float], pct: float) -> float:
    """Simple percentile calculation."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100.0)
    idx = min(idx, len(sorted_v) - 1)
    return sorted_v[idx]


def extract_features(
    topology_edges: list[dict[str, Any]] | None = None,
    traces: list[dict[str, Any]] | None = None,
) -> GovernanceFailureFeatures:
    """Extract GovernanceFailureFeatures from topology and trace history.

    Parameters
    ----------
    topology_edges:
        List of GovernanceEdge dicts (source, target, relation, properties).
        Can be None if no topology available.
    traces:
        List of GovernedTrace dicts from TraceStore.read_traces().
        Can be None if no traces available.

    Returns
    -------
    GovernanceFailureFeatures with all metrics computed.
    """
    features = GovernanceFailureFeatures()

    # ── Topology features ──
    if topology_edges:
        nodes = set()
        for e in topology_edges:
            nodes.add(e.get("source", ""))
            nodes.add(e.get("target", ""))
        nodes.discard("")
        features.topology = TopologyMetrics(
            node_count=len(nodes),
            edge_count=len(topology_edges),
            avg_degree=(2 * len(topology_edges) / len(nodes)) if nodes else 0.0,
        )
        # Decision pattern counts from topology relations
        rel_counts = {"COMPLIES_WITH": 0, "AMENDS": 0, "GOVERNS": 0}
        for e in topology_edges:
            rel = e.get("relation", "")
            if rel in rel_counts:
                rel_counts[rel] += 1
        features.decision_patterns = DecisionPatternMetrics(
            complies_with_count=rel_counts["COMPLIES_WITH"],
            amends_count=rel_counts["AMENDS"],
            governs_count=rel_counts["GOVERNS"],
            decision_entropy=_safe_entropy(list(rel_counts.values())),
        )

    # ── Trace features ──
    if not traces:
        return features

    features.trace_window = TraceWindowMetrics(sample_count=len(traces))

    # Compute time window
    timestamps = []
    for t in traces:
        ts = t.get("timestamp")
        if isinstance(ts, str):
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except (ValueError, TypeError):
                pass
    if len(timestamps) >= 2:
        span = max(timestamps) - min(timestamps)
        features.trace_window.window_hours = span.total_seconds() / 3600.0

    # Gate metrics from governance_decisions
    total_decisions = 0
    pass_count = 0
    block_count = 0
    warn_count = 0
    override_count = 0
    for t in traces:
        if t.get("human_override"):
            override_count += 1
        for gd in t.get("governance_decisions", []):
            total_decisions += 1
            decision = gd.get("decision", "")
            if decision == "PASS":
                pass_count += 1
            elif decision == "BLOCK":
                block_count += 1
            elif decision == "WARN":
                warn_count += 1

    if total_decisions > 0:
        features.gate = GateMetrics(
            total_decisions=total_decisions,
            pass_ratio=pass_count / total_decisions,
            block_ratio=block_count / total_decisions,
            warn_ratio=warn_count / total_decisions,
            override_rate=override_count / len(traces) if traces else 0.0,
        )

    # Clearance metrics
    levels_seen = set()
    for t in traces:
        cl = t.get("clearance_level", "")
        if cl in _CLEARANCE_ORDINAL:
            levels_seen.add(cl)
    if levels_seen:
        ordinals = sorted(_CLEARANCE_ORDINAL[l] for l in levels_seen)
        gaps = [ordinals[i + 1] - ordinals[i] for i in range(len(ordinals) - 1)]
        features.clearance = ClearanceMetrics(
            escalation_gap_mean=statistics.mean(gaps) if gaps else 0.0,
            escalation_gap_max=max(gaps) if gaps else 0.0,
            distinct_levels_used=len(levels_seen),
        )

    # Tool metrics
    outcomes = [t.get("outcome", "") for t in traces]
    distinct_tools = set(t.get("tool_name", "") for t in traces)
    distinct_tools.discard("")
    failure_count = sum(1 for o in outcomes if o == "FAILURE")
    blocked_count = sum(1 for o in outcomes if o == "BLOCKED")
    features.tool = ToolMetrics(
        total_calls=len(traces),
        failure_rate=failure_count / len(traces) if traces else 0.0,
        blocked_rate=blocked_count / len(traces) if traces else 0.0,
        distinct_tools=len(distinct_tools),
    )

    # Latency metrics
    latencies = [t.get("latency_ms", 0.0) for t in traces if isinstance(t.get("latency_ms"), (int, float))]
    if latencies:
        mean_lat = statistics.mean(latencies)
        std_lat = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        anomaly_threshold = mean_lat + 2 * std_lat if std_lat > 0 else float("inf")
        features.latency = LatencyMetrics(
            p50_ms=_percentile(latencies, 50),
            p95_ms=_percentile(latencies, 95),
            max_ms=max(latencies),
            anomaly_count=sum(1 for l in latencies if l > anomaly_threshold),
        )

    return features
