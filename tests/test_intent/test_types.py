"""Tests for R6 intent classification types."""

from __future__ import annotations

from graqle.intent.types import (
    CorrectionRecord,
    EvaluationMetrics,
    LearnerCheckpoint,
    ToolPrediction,
)


class TestCorrectionRecord:
    def test_create_generates_id_and_timestamp(self):
        record = CorrectionRecord.create(
            raw_query="test query",
            normalized_query="test query",
            activated_nodes=["n1"],
            activated_node_types=["FUNCTION"],
            activation_scores=[0.9],
            predicted_tool="graq_context",
            corrected_tool="graq_reason",
            confidence_at_prediction=0.8,
            keyword_rules_matched=["rule1"],
            correction_source="explicit",
            session_id="s1",
        )
        assert record.id  # uuid generated
        assert record.timestamp  # ISO8601 generated
        assert record.raw_query == "test query"
        assert record.schema_version == "1.0"

    def test_to_dict_from_dict_roundtrip(self):
        record = CorrectionRecord.create(
            raw_query="roundtrip test",
            normalized_query="roundtrip test",
            activated_nodes=["n1", "n2"],
            activated_node_types=["ENTITY"],
            activation_scores=[0.5],
            predicted_tool="graq_impact",
            corrected_tool="graq_reason",
            confidence_at_prediction=0.6,
            keyword_rules_matched=[],
            correction_source="api",
            session_id="s2",
        )
        d = record.to_dict()
        restored = CorrectionRecord.from_dict(d)
        assert restored.id == record.id
        assert restored.raw_query == record.raw_query
        assert restored.corrected_tool == record.corrected_tool
        assert restored.activation_scores == record.activation_scores


class TestLearnerCheckpoint:
    def test_to_dict_from_dict_roundtrip(self):
        cp = LearnerCheckpoint(
            rule_weights={"rule1": 1.5, "rule2": 0.8},
            node_type_weights={"FUNCTION|graq_impact": 0.3},
            correction_count=25,
            weight_version=25,
        )
        d = cp.to_dict()
        restored = LearnerCheckpoint.from_dict(d)
        assert restored.rule_weights == cp.rule_weights
        assert restored.correction_count == 25
        assert restored.schema_version == "1.0"


class TestToolPrediction:
    def test_to_dict_from_dict_roundtrip(self):
        pred = ToolPrediction(
            tool="graq_reason", confidence=0.92, method="learned", weight_version=10,
        )
        d = pred.to_dict()
        restored = ToolPrediction.from_dict(d)
        assert restored.tool == "graq_reason"
        assert restored.confidence == 0.92
        assert restored.method == "learned"


class TestEvaluationMetrics:
    def test_to_dict_from_dict_roundtrip(self):
        metrics = EvaluationMetrics(
            top1_accuracy=0.87,
            top2_accuracy=0.96,
            ece=0.05,
            cold_start_accuracy=0.72,
            total_samples=100,
            correction_count=50,
        )
        d = metrics.to_dict()
        restored = EvaluationMetrics.from_dict(d)
        assert restored.top1_accuracy == 0.87
        assert restored.cold_start_accuracy == 0.72

    def test_none_cold_start(self):
        metrics = EvaluationMetrics(
            top1_accuracy=0.5,
            top2_accuracy=0.7,
            ece=0.1,
            cold_start_accuracy=None,
            total_samples=5,
            correction_count=0,
        )
        d = metrics.to_dict()
        restored = EvaluationMetrics.from_dict(d)
        assert restored.cold_start_accuracy is None
