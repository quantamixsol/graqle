"""Tests for R6 OnlineLearner — perceptron weight updater."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.intent.online_learner import OnlineLearner
from graqle.intent.types import CorrectionRecord


def _make_correction(
    predicted: str = "graq_context",
    corrected: str = "graq_reason",
    rules: list[str] | None = None,
    node_types: list[str] | None = None,
) -> CorrectionRecord:
    return CorrectionRecord.create(
        raw_query="test",
        normalized_query="test",
        activated_nodes=["n1"],
        activated_node_types=node_types or ["FUNCTION"],
        activation_scores=[0.9],
        predicted_tool=predicted,
        corrected_tool=corrected,
        confidence_at_prediction=0.7,
        keyword_rules_matched=rules or ["rule_arch"],
        correction_source="explicit",
        session_id="test",
    )


class TestOnlineLearner:
    def test_cold_start_guard_below_threshold(self):
        learner = OnlineLearner(known_rules=["rule_arch"], min_corrections=10)
        assert not learner.is_ready()

    def test_cold_start_guard_at_threshold(self):
        learner = OnlineLearner(known_rules=["rule_arch"], min_corrections=5)
        for _ in range(5):
            learner.update(_make_correction())
        assert learner.is_ready()

    def test_weight_update_wrong_prediction(self):
        learner = OnlineLearner(known_rules=["rule_arch"])
        initial_weight = learner.rule_weights["rule_arch"]
        # Wrong prediction: penalty
        learner.update(_make_correction(predicted="graq_context", corrected="graq_reason"))
        assert learner.rule_weights["rule_arch"] < initial_weight

    def test_weight_update_correct_prediction(self):
        learner = OnlineLearner(known_rules=["rule_arch"])
        initial_weight = learner.rule_weights["rule_arch"]
        # Correct prediction: reward
        learner.update(_make_correction(predicted="graq_reason", corrected="graq_reason"))
        assert learner.rule_weights["rule_arch"] > initial_weight

    def test_weight_floor(self):
        learner = OnlineLearner(
            known_rules=["rule_arch"], weight_floor=0.01, learning_rate=0.99,
        )
        # Many wrong predictions should not go below floor
        for _ in range(100):
            learner.update(_make_correction(predicted="wrong", corrected="right"))
        assert learner.rule_weights["rule_arch"] >= 0.01

    def test_weight_ceiling(self):
        learner = OnlineLearner(
            known_rules=["rule_arch"], weight_ceiling=5.0, learning_rate=0.5,
        )
        for _ in range(100):
            learner.update(_make_correction(predicted="graq_reason", corrected="graq_reason"))
        assert learner.rule_weights["rule_arch"] <= 5.0

    def test_node_type_weights_update(self):
        learner = OnlineLearner(known_rules=[])
        learner.update(_make_correction(
            predicted="graq_context",
            corrected="graq_reason",
            node_types=["FUNCTION"],
        ))
        # Correct tool should get positive weight
        assert learner.node_type_weights[("FUNCTION", "graq_reason")] > 0

    def test_classify_returns_tool_prediction(self):
        learner = OnlineLearner(known_rules=["rule_arch"], min_corrections=1)
        learner.update(_make_correction())
        result = learner.classify(
            matched_rules=[("rule_arch", "graq_reason")],
            activated_node_types=["FUNCTION"],
            known_tools=["graq_reason", "graq_context", "graq_impact"],
        )
        assert result.tool in ["graq_reason", "graq_context", "graq_impact"]
        assert 0.0 <= result.confidence <= 1.0
        assert result.method in ["learned", "rules_only"]

    def test_classify_rules_only_below_threshold(self):
        learner = OnlineLearner(known_rules=["rule_arch"], min_corrections=100)
        result = learner.classify(
            matched_rules=[("rule_arch", "graq_reason")],
            activated_node_types=[],
            known_tools=["graq_reason", "graq_context"],
        )
        assert result.method == "rules_only"

    def test_checkpoint_roundtrip(self, tmp_path: Path):
        learner = OnlineLearner(known_rules=["rule_arch", "rule_impact"])
        for _ in range(5):
            learner.update(_make_correction())

        cp_path = str(tmp_path / "weights.json")
        learner.checkpoint(cp_path)

        restored = OnlineLearner.from_checkpoint(cp_path)
        assert restored.correction_count == learner.correction_count
        assert restored.weight_version == learner.weight_version
        assert restored.rule_weights == learner.rule_weights

    def test_checkpoint_corrupt_file(self, tmp_path: Path):
        cp_path = str(tmp_path / "bad.json")
        with open(cp_path, "w") as f:
            f.write("NOT JSON")
        with pytest.raises((json.JSONDecodeError, Exception)):
            OnlineLearner.from_checkpoint(cp_path)

    def test_softmax_numerical_stability(self):
        # Large values should not overflow
        scores = {"a": 1000.0, "b": 1001.0, "c": 999.0}
        result = OnlineLearner._softmax(scores)
        assert abs(sum(result.values()) - 1.0) < 1e-6

    def test_softmax_empty(self):
        assert OnlineLearner._softmax({}) == {}

    def test_version_increments(self):
        learner = OnlineLearner(known_rules=[])
        assert learner.weight_version == 0
        learner.update(_make_correction())
        assert learner.weight_version == 1
        learner.update(_make_correction())
        assert learner.weight_version == 2
