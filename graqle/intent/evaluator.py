"""ClassifierEvaluator — R6 Component 4: Metrics Suite."""

# ── graqle:intelligence ──
# module: graqle.intent.evaluator
# risk: LOW (impact radius: 1 module)
# consumers: intent.classifier, benchmarks, tests
# dependencies: __future__, dataclasses, logging, collections, graqle.intent.types
# constraints: no hardcoded confidence thresholds (TS-2)
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from graqle.intent.types import EvaluationMetrics

logger = logging.getLogger("graqle.intent.evaluator")


@dataclass
class EvalSample:
    """Single evaluation sample capturing a prediction and its correction."""

    predicted_tool: str
    corrected_tool: str
    confidence: float
    top2_tools: List[str] = field(default_factory=list)
    correction_count_at_prediction: int = 0


class ClassifierEvaluator:
    """Computes 5 metrics from a list of :class:`EvalSample` tuples.

    Metrics:
        1. Top-1 Accuracy  (target > 85%)
        2. Top-2 Accuracy  (target > 95%)
        3. ECE — Expected Calibration Error (target < 0.08)
        4. Learning Curve  — ``(correction_count, running_accuracy)`` pairs
        5. Cold-Start Accuracy (target > 70%)
    """

    def __init__(self, cold_start_threshold: int = 10) -> None:
        self._cold_start_threshold = cold_start_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self, results: List[EvalSample], correction_count: int = 0,
    ) -> EvaluationMetrics:
        """Compute all 5 metrics and return an ``EvaluationMetrics`` dataclass."""
        total = len(results)

        if total == 0:
            logger.warning("evaluate() called with empty results list")
            return EvaluationMetrics(
                top1_accuracy=0.0,
                top2_accuracy=0.0,
                ece=0.0,
                cold_start_accuracy=None,
                total_samples=0,
                correction_count=correction_count,
            )

        top1 = self._top1_accuracy(results, total)
        top2 = self._top2_accuracy(results, total)
        ece = self._expected_calibration_error(results, total)
        cold = self._cold_start_accuracy(results)

        logger.info(
            "Evaluation complete: top1=%.3f top2=%.3f ece=%.4f "
            "cold_start=%s samples=%d",
            top1, top2, ece,
            f"{cold:.3f}" if cold is not None else "N/A",
            total,
        )

        return EvaluationMetrics(
            top1_accuracy=top1,
            top2_accuracy=top2,
            ece=ece,
            cold_start_accuracy=cold,
            total_samples=total,
            correction_count=correction_count,
        )

    def learning_curve(
        self, results: List[EvalSample],
    ) -> List[Tuple[int, float]]:
        """Running accuracy grouped by ``correction_count_at_prediction``.

        Returns a list of ``(correction_count, running_accuracy)`` tuples.
        Should be monotone increasing if the learner is actually learning.
        """
        return self._learning_curve(results)

    # ------------------------------------------------------------------
    # Private metric helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _top1_accuracy(results: List[EvalSample], total: int) -> float:
        correct = sum(1 for s in results if s.predicted_tool == s.corrected_tool)
        return correct / total

    @staticmethod
    def _top2_accuracy(results: List[EvalSample], total: int) -> float:
        correct = sum(1 for s in results if s.corrected_tool in s.top2_tools)
        return correct / total

    @staticmethod
    def _expected_calibration_error(
        results: List[EvalSample], total: int,
    ) -> float:
        """ECE with 10 equal-width bins over [0.0, 1.0]."""
        num_bins = 10
        bins_correct: List[List[bool]] = [[] for _ in range(num_bins)]
        bins_confidence: List[List[float]] = [[] for _ in range(num_bins)]

        for s in results:
            conf = max(0.0, min(1.0, s.confidence))
            idx = min(int(conf * num_bins), num_bins - 1)
            bins_correct[idx].append(s.predicted_tool == s.corrected_tool)
            bins_confidence[idx].append(conf)

        ece = 0.0
        for correct_list, conf_list in zip(bins_correct, bins_confidence):
            if not correct_list:
                continue
            bin_size = len(correct_list)
            bin_accuracy = sum(correct_list) / bin_size
            bin_confidence = sum(conf_list) / bin_size
            ece += (bin_size / total) * abs(bin_accuracy - bin_confidence)

        return ece

    @staticmethod
    def _learning_curve(results: List[EvalSample]) -> List[Tuple[int, float]]:
        """Running accuracy grouped by ``correction_count_at_prediction``."""
        groups: defaultdict[int, List[bool]] = defaultdict(list)
        for s in results:
            groups[s.correction_count_at_prediction].append(
                s.predicted_tool == s.corrected_tool,
            )

        running_correct = 0
        running_total = 0
        curve: List[Tuple[int, float]] = []
        for count in sorted(groups):
            entries = groups[count]
            running_correct += sum(entries)
            running_total += len(entries)
            curve.append((count, running_correct / running_total))

        return curve

    def _cold_start_accuracy(self, results: List[EvalSample]) -> Optional[float]:
        cold = [
            s for s in results
            if s.correction_count_at_prediction < self._cold_start_threshold
        ]
        if not cold:
            logger.debug(
                "No cold-start samples (threshold=%d)", self._cold_start_threshold,
            )
            return None
        correct = sum(1 for s in cold if s.predicted_tool == s.corrected_tool)
        return correct / len(cold)
