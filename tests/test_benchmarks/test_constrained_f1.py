"""Tests for constrained F1 metric — governance accuracy + token F1."""

# ── graqle:intelligence ──
# module: tests.test_benchmarks.test_constrained_f1
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, benchmark_runner
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.benchmarks.benchmark_runner import (
    constrained_f1_score,
    f1_score,
    QuestionResult,
)


class TestConstrainedF1Score:
    def test_perfect_scores(self):
        score = constrained_f1_score(token_f1=1.0, governance_accuracy=1.0)
        assert score == pytest.approx(1.0)

    def test_zero_scores(self):
        score = constrained_f1_score(token_f1=0.0, governance_accuracy=0.0)
        assert score == pytest.approx(0.0)

    def test_high_f1_low_governance(self):
        """Right keywords but wrong governance — should penalize."""
        score = constrained_f1_score(token_f1=0.9, governance_accuracy=0.2)
        assert score == pytest.approx(0.55)
        assert score < 0.9  # Lower than token F1 alone

    def test_low_f1_high_governance(self):
        """Few matching keywords but proper governance."""
        score = constrained_f1_score(token_f1=0.2, governance_accuracy=0.9)
        assert score == pytest.approx(0.55)
        assert score > 0.2  # Higher than token F1 alone

    def test_custom_weights(self):
        score = constrained_f1_score(
            token_f1=0.8, governance_accuracy=0.4,
            weight_token=0.7, weight_governance=0.3,
        )
        assert score == pytest.approx(0.7 * 0.8 + 0.3 * 0.4)

    def test_equal_weights_default(self):
        score = constrained_f1_score(token_f1=0.6, governance_accuracy=0.8)
        assert score == pytest.approx(0.5 * 0.6 + 0.5 * 0.8)

    def test_governance_only(self):
        score = constrained_f1_score(
            token_f1=0.0, governance_accuracy=1.0,
            weight_token=0.0, weight_governance=1.0,
        )
        assert score == pytest.approx(1.0)

    def test_token_only(self):
        score = constrained_f1_score(
            token_f1=0.75, governance_accuracy=0.0,
            weight_token=1.0, weight_governance=0.0,
        )
        assert score == pytest.approx(0.75)


class TestQuestionResultConstrainedF1:
    def test_question_result_has_constrained_f1_fields(self):
        qr = QuestionResult(
            question_id="Q1",
            question="test",
            gold_answer="answer",
            predicted_answer="answer",
            exact_match=1.0,
            f1=0.8,
            latency_ms=100,
            cost_usd=0.01,
            total_tokens=100,
            convergence_rounds=1,
            active_nodes=1,
            method="test",
            governance_accuracy=0.9,
            framework_fidelity=0.95,
            scope_adherence=0.85,
            cross_reference_score=0.9,
            constrained_f1=0.85,
        )
        assert qr.governance_accuracy == 0.9
        assert qr.constrained_f1 == 0.85

    def test_question_result_defaults_zero(self):
        qr = QuestionResult(
            question_id="Q1", question="test", gold_answer="a",
            predicted_answer="a", exact_match=1.0, f1=1.0,
            latency_ms=0, cost_usd=0, total_tokens=0,
            convergence_rounds=0, active_nodes=0, method="test",
        )
        assert qr.governance_accuracy == 0.0
        assert qr.constrained_f1 == 0.0

    def test_to_dict_includes_governance_fields(self):
        qr = QuestionResult(
            question_id="Q1", question="test", gold_answer="a",
            predicted_answer="a", exact_match=1.0, f1=1.0,
            latency_ms=0, cost_usd=0, total_tokens=0,
            convergence_rounds=0, active_nodes=0, method="test",
            governance_accuracy=0.8, constrained_f1=0.9,
        )
        d = qr.to_dict()
        assert "governance_accuracy" in d
        assert "constrained_f1" in d
        assert d["governance_accuracy"] == 0.8
