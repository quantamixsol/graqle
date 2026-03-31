"""Tests for R6 KG Node-Type Routing Hypothesis validation."""

from __future__ import annotations

from graqle.intent.kg_routing import (
    ROUTING_HYPOTHESES,
    compute_mutual_information,
    validate_hypothesis,
)
from graqle.intent.types import CorrectionRecord


def _make_correction(
    corrected_tool: str = "graq_reason",
    node_types: list[str] | None = None,
) -> CorrectionRecord:
    return CorrectionRecord.create(
        raw_query="test",
        normalized_query="test",
        activated_nodes=["n1"],
        activated_node_types=node_types or ["ENTITY"],
        activation_scores=[0.9],
        predicted_tool="graq_context",
        corrected_tool=corrected_tool,
        confidence_at_prediction=0.7,
        keyword_rules_matched=[],
        correction_source="explicit",
        session_id="test",
    )


class TestRoutingHypotheses:
    def test_all_seven_hypotheses_defined(self):
        expected = {"PRODUCT", "ENTITY", "FUNCTION", "METHOD", "DOCUMENT", "SECTION", "KNOWLEDGE"}
        assert set(ROUTING_HYPOTHESES.keys()) == expected

    def test_function_maps_to_impact(self):
        assert ROUTING_HYPOTHESES["FUNCTION"] == "graq_impact"

    def test_entity_maps_to_reason(self):
        assert ROUTING_HYPOTHESES["ENTITY"] == "graq_reason"


class TestMutualInformation:
    def test_empty_table(self):
        assert compute_mutual_information({}) == 0.0

    def test_perfect_correlation(self):
        # Each row maps to exactly one column → high MI
        contingency = {
            "FUNCTION": {"graq_impact": 50},
            "ENTITY": {"graq_reason": 50},
        }
        mi = compute_mutual_information(contingency)
        assert mi > 0.5, "Perfect correlation should have high MI"

    def test_uniform_distribution(self):
        # Uniform: every row equally distributed → low MI
        contingency = {
            "FUNCTION": {"graq_impact": 25, "graq_reason": 25},
            "ENTITY": {"graq_impact": 25, "graq_reason": 25},
        }
        mi = compute_mutual_information(contingency)
        assert mi < 0.01, "Uniform distribution should have near-zero MI"

    def test_zero_count_cells_safe(self):
        contingency = {"FUNCTION": {"graq_impact": 10, "graq_reason": 0}}
        mi = compute_mutual_information(contingency)
        assert mi >= 0.0


class TestValidateHypothesis:
    def test_insufficient_data(self):
        corrections = [_make_correction() for _ in range(10)]
        result = validate_hypothesis(corrections, min_samples=30)
        assert result["status"] == "insufficient_data"

    def test_sufficient_data_returns_all_fields(self):
        corrections = [
            _make_correction(corrected_tool="graq_reason", node_types=["ENTITY"])
            for _ in range(40)
        ]
        result = validate_hypothesis(corrections, min_samples=30)
        assert "mutual_information" in result
        assert "hypothesis_supported" in result
        assert "hypothesis_precision" in result
        assert "recommendation" in result

    def test_strong_hypothesis_supported(self):
        # All FUNCTION → graq_impact, all ENTITY → graq_reason
        corrections = (
            [_make_correction(corrected_tool="graq_impact", node_types=["FUNCTION"]) for _ in range(20)]
            + [_make_correction(corrected_tool="graq_reason", node_types=["ENTITY"]) for _ in range(20)]
        )
        result = validate_hypothesis(corrections, min_samples=30)
        assert result["hypothesis_supported"] is True
        assert result["recommendation"] == "enable_kg_routing"

    def test_weak_hypothesis_not_supported(self):
        # Random: no correlation between node type and tool
        import random
        random.seed(42)
        tools = ["graq_reason", "graq_impact", "graq_context"]
        types = ["FUNCTION", "ENTITY", "DOCUMENT"]
        corrections = [
            _make_correction(
                corrected_tool=random.choice(tools),
                node_types=[random.choice(types)],
            )
            for _ in range(50)
        ]
        result = validate_hypothesis(corrections, min_samples=30)
        # With random assignment, MI should be low
        assert result["mutual_information"] < 0.5

    def test_precision_per_hypothesis(self):
        corrections = [
            _make_correction(corrected_tool="graq_impact", node_types=["FUNCTION"])
            for _ in range(35)
        ]
        result = validate_hypothesis(corrections, min_samples=30)
        assert result["hypothesis_precision"]["FUNCTION"] == 1.0
