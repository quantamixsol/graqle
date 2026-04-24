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

"""Causal Governance Failure Chain Predictor (R19 ADR-202).

Predicts governance workflow failures BEFORE they happen by analyzing
governance topology and execution trace history. Each predicted failure
is a causal chain DAG with a probability score.

    P(F | G, H) = sigma(w * phi(G, H))

TS-2 Gate: Weight values (w) are core IP. Expose predictions only.

PSE Class III compound composition: extends graq_predict with
mode="causal_chain" for governance-specific prediction.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from graqle.governance.failure_features import (
    GovernanceFailureFeatures,
    extract_features,
)

logger = logging.getLogger("graqle.governance.failure_predictor")


# ---------------------------------------------------------------------------
# Causal Chain DAG Models
# ---------------------------------------------------------------------------


class CausalNode(BaseModel):
    """A node in a predicted failure causal chain."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: str  # "gate", "tool", "clearance", "topology"
    risk_score: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)


class CausalEdge(BaseModel):
    """A causal edge between nodes in a failure chain."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relation: str  # "causes", "escalates_to", "blocks", "triggers"


class CausalChainDAG(BaseModel):
    """A predicted governance failure chain as a DAG.

    The chain is a directed acyclic graph where nodes are governance
    gates or reasoning tasks and edges are causal relationships.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    chain: list[str] = Field(default_factory=list)  # ordered node IDs
    nodes: list[CausalNode] = Field(default_factory=list)
    edges: list[CausalEdge] = Field(default_factory=list)
    probability: float = 0.0
    root_cause: str | None = None
    leaf_failure: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class CausalChainPrediction(BaseModel):
    """A ranked prediction result."""

    model_config = ConfigDict(extra="forbid")

    chain: CausalChainDAG
    probability: float
    rank: int
    lead_time_hours: float | None = None  # estimated time before failure


class FailurePredictionResult(BaseModel):
    """Complete prediction output from predict_governance_failures()."""

    model_config = ConfigDict(extra="forbid")

    predictions: list[CausalChainPrediction] = Field(default_factory=list)
    features_used: GovernanceFailureFeatures | None = None
    trace_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Prediction Engine
# ---------------------------------------------------------------------------

# Minimum trace count for meaningful predictions
_MIN_TRACES = 10


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid activation."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _dot_product(w: list[float], phi: list[float]) -> float:
    """Dot product of weight vector and feature vector."""
    return sum(wi * pi for wi, pi in zip(w, phi))


def _build_candidate_chains(features: GovernanceFailureFeatures) -> list[CausalChainDAG]:
    """Generate candidate causal chains from feature signals.

    Each chain represents a plausible governance failure path.
    Candidates are generated from feature anomalies.
    """
    chains: list[CausalChainDAG] = []

    # Chain 1: High block rate -> escalation gap -> tool failure
    if features.gate.block_ratio > 0.1:
        chain = CausalChainDAG(
            chain=["high_block_rate", "escalation_gap", "tool_failure"],
            nodes=[
                CausalNode(id="high_block_rate", label="High gate block rate", kind="gate",
                           risk_score=features.gate.block_ratio),
                CausalNode(id="escalation_gap", label="Clearance escalation gap", kind="clearance",
                           risk_score=features.clearance.escalation_gap_mean),
                CausalNode(id="tool_failure", label="Tool execution failure", kind="tool",
                           risk_score=features.tool.failure_rate),
            ],
            edges=[
                CausalEdge(source="high_block_rate", target="escalation_gap", relation="escalates_to"),
                CausalEdge(source="escalation_gap", target="tool_failure", relation="causes"),
            ],
            root_cause="high_block_rate",
            leaf_failure="tool_failure",
        )
        chains.append(chain)

    # Chain 2: Latency anomaly -> timeout -> blocked workflow
    if features.latency.anomaly_count > 0:
        chain = CausalChainDAG(
            chain=["latency_anomaly", "timeout_risk", "workflow_blocked"],
            nodes=[
                CausalNode(id="latency_anomaly", label="Latency anomaly detected", kind="tool",
                           risk_score=min(features.latency.anomaly_count / max(features.tool.total_calls, 1), 1.0)),
                CausalNode(id="timeout_risk", label="Timeout risk elevated", kind="tool",
                           risk_score=features.latency.p95_ms / max(features.latency.max_ms, 1.0)),
                CausalNode(id="workflow_blocked", label="Workflow blocked by timeout", kind="gate",
                           risk_score=features.tool.blocked_rate),
            ],
            edges=[
                CausalEdge(source="latency_anomaly", target="timeout_risk", relation="triggers"),
                CausalEdge(source="timeout_risk", target="workflow_blocked", relation="blocks"),
            ],
            root_cause="latency_anomaly",
            leaf_failure="workflow_blocked",
        )
        chains.append(chain)

    # Chain 3: Low governance coverage -> undetected violation -> compliance failure
    if features.decision_patterns.decision_entropy < 1.0 and features.topology.edge_count > 0:
        chain = CausalChainDAG(
            chain=["low_governance_coverage", "undetected_violation", "compliance_failure"],
            nodes=[
                CausalNode(id="low_governance_coverage", label="Low governance topology coverage", kind="topology",
                           risk_score=1.0 - min(features.decision_patterns.decision_entropy / 1.585, 1.0)),
                CausalNode(id="undetected_violation", label="Potential undetected violation", kind="gate",
                           risk_score=features.gate.warn_ratio),
                CausalNode(id="compliance_failure", label="Compliance failure risk", kind="gate",
                           risk_score=max(features.gate.block_ratio, features.tool.failure_rate)),
            ],
            edges=[
                CausalEdge(source="low_governance_coverage", target="undetected_violation", relation="causes"),
                CausalEdge(source="undetected_violation", target="compliance_failure", relation="escalates_to"),
            ],
            root_cause="low_governance_coverage",
            leaf_failure="compliance_failure",
        )
        chains.append(chain)

    # Chain 4: Override pattern -> weakened governance -> repeated failure
    if features.gate.override_rate > 0.05:
        chain = CausalChainDAG(
            chain=["override_pattern", "weakened_governance", "repeated_failure"],
            nodes=[
                CausalNode(id="override_pattern", label="Frequent human overrides", kind="gate",
                           risk_score=features.gate.override_rate),
                CausalNode(id="weakened_governance", label="Governance effectiveness degraded", kind="topology",
                           risk_score=features.gate.override_rate * 2),
                CausalNode(id="repeated_failure", label="Repeated governance failure", kind="tool",
                           risk_score=features.tool.failure_rate),
            ],
            edges=[
                CausalEdge(source="override_pattern", target="weakened_governance", relation="causes"),
                CausalEdge(source="weakened_governance", target="repeated_failure", relation="triggers"),
            ],
            root_cause="override_pattern",
            leaf_failure="repeated_failure",
        )
        chains.append(chain)

    # Default chain if no specific signals
    if not chains:
        chains.append(CausalChainDAG(
            chain=["baseline"],
            nodes=[CausalNode(id="baseline", label="Baseline governance state", kind="topology", risk_score=0.0)],
            edges=[],
            root_cause="baseline",
            leaf_failure="baseline",
        ))

    return chains


def predict_governance_failures(
    topology_edges: list[dict[str, Any]] | None = None,
    traces: list[dict[str, Any]] | None = None,
    threshold: float = 0.3,
) -> FailurePredictionResult:
    """Predict governance failure chains from topology and trace history.

    Parameters
    ----------
    topology_edges:
        GovernanceEdge dicts from GovernanceTopology.
    traces:
        GovernedTrace dicts from TraceStore.
    threshold:
        Minimum probability to include a prediction in results.

    Returns
    -------
    FailurePredictionResult with ranked causal chain predictions.
    """
    features = extract_features(topology_edges=topology_edges, traces=traces)
    phi = features.to_vector()
    trace_count = len(traces) if traces else 0

    # Generate candidate chains
    candidates = _build_candidate_chains(features)

    # Score each chain using sigmoid over risk-weighted features
    predictions: list[CausalChainPrediction] = []
    for chain in candidates:
        # Chain-specific scoring: aggregate node risk scores
        if chain.nodes:
            chain_risk = sum(n.risk_score for n in chain.nodes) / len(chain.nodes)
        else:
            chain_risk = 0.0

        # Combine with overall feature signal
        feature_signal = sum(phi) / max(len(phi), 1)
        combined = chain_risk * 0.7 + feature_signal * 0.3

        probability = _sigmoid(combined * 4 - 2)  # scale to useful sigmoid range
        chain.probability = probability

        if probability >= threshold:
            predictions.append(CausalChainPrediction(
                chain=chain,
                probability=probability,
                rank=0,  # assigned below
            ))

    # Rank by probability descending
    predictions.sort(key=lambda p: p.probability, reverse=True)
    for i, pred in enumerate(predictions):
        pred.rank = i + 1

    # Overall confidence based on trace count and prediction strength
    if predictions and trace_count >= _MIN_TRACES:
        confidence = min(predictions[0].probability, trace_count / 500.0, 1.0)
    else:
        confidence = 0.0

    return FailurePredictionResult(
        predictions=predictions,
        features_used=features,
        trace_count=trace_count,
        confidence=confidence,
    )
