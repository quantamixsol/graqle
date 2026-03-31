"""R6 Learned Intent Classification — data types."""

# ── graqle:intelligence ──
# module: graqle.intent.types
# risk: LOW (impact radius: 3 modules)
# consumers: intent_learner, intent_classifier, correction_store
# dependencies: __future__, dataclasses, uuid, datetime, typing
# constraints: TS-2 (no hardcoded confidence thresholds)
# ── /graqle:intelligence ──

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class CorrectionRecord:
    """A single developer correction mapping predicted → corrected tool."""

    id: str
    timestamp: str
    raw_query: str
    normalized_query: str
    activated_nodes: List[str]
    activated_node_types: List[str]
    activation_scores: List[float]
    predicted_tool: str
    corrected_tool: str
    confidence_at_prediction: float
    keyword_rules_matched: List[str]
    correction_source: str  # "explicit" | "implicit_retry" | "api"
    session_id: str
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CorrectionRecord:
        """Deserialize a CorrectionRecord from a dictionary."""
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            raw_query=data["raw_query"],
            normalized_query=data["normalized_query"],
            activated_nodes=list(data.get("activated_nodes", [])),
            activated_node_types=list(data.get("activated_node_types", [])),
            activation_scores=[float(s) for s in data.get("activation_scores", [])],
            predicted_tool=data["predicted_tool"],
            corrected_tool=data["corrected_tool"],
            confidence_at_prediction=float(data["confidence_at_prediction"]),
            keyword_rules_matched=list(data.get("keyword_rules_matched", [])),
            correction_source=data["correction_source"],
            session_id=data["session_id"],
            schema_version=data.get("schema_version", "1.0"),
        )

    @classmethod
    def create(
        cls,
        *,
        raw_query: str,
        normalized_query: str,
        activated_nodes: List[str],
        activated_node_types: List[str],
        activation_scores: List[float],
        predicted_tool: str,
        corrected_tool: str,
        confidence_at_prediction: float,
        keyword_rules_matched: List[str],
        correction_source: str,
        session_id: str,
        schema_version: str = "1.0",
    ) -> CorrectionRecord:
        """Factory that auto-generates id (uuid4) and timestamp (ISO8601 UTC)."""
        return cls(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_query=raw_query,
            normalized_query=normalized_query,
            activated_nodes=list(activated_nodes),
            activated_node_types=list(activated_node_types),
            activation_scores=list(activation_scores),
            predicted_tool=predicted_tool,
            corrected_tool=corrected_tool,
            confidence_at_prediction=confidence_at_prediction,
            keyword_rules_matched=list(keyword_rules_matched),
            correction_source=correction_source,
            session_id=session_id,
            schema_version=schema_version,
        )


@dataclass
class LearnerCheckpoint:
    """Serializable snapshot of learned weights for persistence."""

    rule_weights: Dict[str, float]
    node_type_weights: Dict[str, float]
    correction_count: int
    weight_version: int
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LearnerCheckpoint:
        """Deserialize a LearnerCheckpoint from a dictionary."""
        return cls(
            rule_weights=dict(data.get("rule_weights", {})),
            node_type_weights=dict(data.get("node_type_weights", {})),
            correction_count=int(data["correction_count"]),
            weight_version=int(data["weight_version"]),
            schema_version=data.get("schema_version", "1.0"),
        )


@dataclass
class ToolPrediction:
    """Result of a single tool classification inference."""

    tool: str
    confidence: float
    method: str  # "learned" | "rules_only"
    weight_version: int

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolPrediction:
        """Deserialize a ToolPrediction from a dictionary."""
        return cls(
            tool=data["tool"],
            confidence=float(data["confidence"]),
            method=data["method"],
            weight_version=int(data["weight_version"]),
        )


@dataclass
class EvaluationMetrics:
    """Aggregate accuracy and calibration metrics for the intent classifier."""

    top1_accuracy: float
    top2_accuracy: float
    ece: float
    cold_start_accuracy: Optional[float]
    total_samples: int
    correction_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvaluationMetrics:
        """Deserialize an EvaluationMetrics from a dictionary."""
        cold_start = data.get("cold_start_accuracy")
        return cls(
            top1_accuracy=float(data["top1_accuracy"]),
            top2_accuracy=float(data["top2_accuracy"]),
            ece=float(data["ece"]),
            cold_start_accuracy=float(cold_start) if cold_start is not None else None,
            total_samples=int(data["total_samples"]),
            correction_count=int(data["correction_count"]),
        )
