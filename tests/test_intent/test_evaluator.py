"""Tests for R6 ClassifierEvaluator metrics suite."""

from __future__ import annotations

from graqle.intent.evaluator import ClassifierEvaluator, EvalSample


class TestClassifierEvaluator:
    def test_empty_results(self):
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate([])
        assert metrics.top1_accuracy == 0.0
        assert metrics.total_samples == 0

    def test_perfect_accuracy(self):
        samples = [
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=0.95,
                top2_tools=["graq_reason", "graq_impact"],
                correction_count_at_prediction=20,
            )
            for _ in range(10)
        ]
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate(samples, correction_count=20)
        assert metrics.top1_accuracy == 1.0
        assert metrics.top2_accuracy == 1.0
        assert metrics.total_samples == 10

    def test_zero_accuracy(self):
        samples = [
            EvalSample(
                predicted_tool="graq_context",
                corrected_tool="graq_reason",
                confidence=0.9,
                top2_tools=["graq_context", "graq_impact"],
                correction_count_at_prediction=20,
            )
            for _ in range(5)
        ]
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate(samples)
        assert metrics.top1_accuracy == 0.0
        assert metrics.top2_accuracy == 0.0

    def test_top2_accuracy_higher_than_top1(self):
        samples = [
            EvalSample(
                predicted_tool="graq_impact",
                corrected_tool="graq_reason",
                confidence=0.7,
                top2_tools=["graq_impact", "graq_reason"],  # correct in top2
                correction_count_at_prediction=15,
            )
            for _ in range(10)
        ]
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate(samples)
        assert metrics.top1_accuracy == 0.0
        assert metrics.top2_accuracy == 1.0

    def test_ece_perfect_calibration(self):
        # Confidence matches accuracy → ECE should be near 0
        samples = [
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=1.0,
                top2_tools=["graq_reason"],
                correction_count_at_prediction=20,
            )
            for _ in range(10)
        ]
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate(samples)
        assert metrics.ece < 0.1

    def test_cold_start_accuracy(self):
        cold_samples = [
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=0.6,
                top2_tools=["graq_reason"],
                correction_count_at_prediction=3,  # below threshold
            )
            for _ in range(5)
        ]
        warm_samples = [
            EvalSample(
                predicted_tool="graq_context",
                corrected_tool="graq_reason",
                confidence=0.8,
                top2_tools=["graq_context"],
                correction_count_at_prediction=50,
            )
            for _ in range(5)
        ]
        evaluator = ClassifierEvaluator(cold_start_threshold=10)
        metrics = evaluator.evaluate(cold_samples + warm_samples)
        assert metrics.cold_start_accuracy == 1.0  # all cold samples correct

    def test_cold_start_none_when_no_samples(self):
        samples = [
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=0.9,
                top2_tools=["graq_reason"],
                correction_count_at_prediction=100,  # all above threshold
            )
        ]
        evaluator = ClassifierEvaluator(cold_start_threshold=10)
        metrics = evaluator.evaluate(samples)
        assert metrics.cold_start_accuracy is None

    def test_learning_curve(self):
        samples = [
            EvalSample(
                predicted_tool="graq_context",
                corrected_tool="graq_reason",
                confidence=0.5,
                top2_tools=["graq_context"],
                correction_count_at_prediction=0,
            ),
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=0.8,
                top2_tools=["graq_reason"],
                correction_count_at_prediction=10,
            ),
        ]
        evaluator = ClassifierEvaluator()
        curve = evaluator.learning_curve(samples)
        assert len(curve) == 2
        # First point: 0% accuracy, second: 50% running accuracy
        assert curve[0] == (0, 0.0)
        assert curve[1] == (10, 0.5)

    def test_single_sample(self):
        samples = [
            EvalSample(
                predicted_tool="graq_reason",
                corrected_tool="graq_reason",
                confidence=0.9,
                top2_tools=["graq_reason"],
                correction_count_at_prediction=5,
            )
        ]
        evaluator = ClassifierEvaluator()
        metrics = evaluator.evaluate(samples)
        assert metrics.top1_accuracy == 1.0
        assert metrics.total_samples == 1
