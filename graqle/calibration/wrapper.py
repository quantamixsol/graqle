"""CalibrationWrapper — intercepts ReasoningResult.confidence post-areason().

Applies post-hoc confidence calibration using pluggable methods
(Platt scaling, temperature scaling, isotonic regression).
"""

# ── graqle:intelligence ──
# module: graqle.calibration.wrapper
# risk: MEDIUM (impact radius: 3 modules)
# consumers: core.graph, orchestrator, benchmark_runner
# dependencies: __future__, dataclasses, logging, pathlib, pickle, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import pickle
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from graqle.calibration import metrics
from graqle.calibration.methods import create_calibrator
from graqle.config.settings import CalibrationConfig
from graqle.core.types import ReasoningResult

logger = logging.getLogger("graqle.calibration")


class CalibrationWrapper:
    """Post-hoc confidence calibration for reasoning results.

    Wraps a calibrator created via :func:`create_calibrator` and applies it
    to ``ReasoningResult.confidence`` after each ``areason()`` call.

    Usage::

        wrapper = CalibrationWrapper(config)
        wrapper.fit(benchmark_pairs)
        calibrated = wrapper.calibrate_result(raw_result)
    """

    def __init__(self, config: CalibrationConfig) -> None:
        self._config = config
        self._calibrator = create_calibrator(
            config.method,
            temperature=config.temperature,
        )
        self._fitted: bool = False
        self._fit_samples: int = 0
        self._fit_metrics: dict[str, float] = {}
        self._calibration_count: int = 0

    # ── Result calibration ───────────────────────────────────────

    def calibrate_result(self, result: ReasoningResult) -> ReasoningResult:
        """Return a new ``ReasoningResult`` with calibrated confidence.

        If calibration is not enabled the result is returned unchanged.
        Saves raw_confidence, applies calibrator, sets calibration_method.
        """
        if not self._config.enabled:
            return result

        raw_confidence = result.confidence
        calibrated = float(self._calibrator.calibrate(raw_confidence))
        self._calibration_count += 1

        return replace(
            result,
            confidence=calibrated,
            raw_confidence=raw_confidence,
            calibration_method=self._config.method,
        )

    # ── Fitting ──────────────────────────────────────────────────

    def fit(self, pairs: list[tuple[float, bool]]) -> dict[str, float]:
        """Fit the calibrator on ``(predicted_confidence, was_correct)`` pairs.

        Returns dict with ``ece``, ``mce``, and ``brier`` scores.

        Raises:
            ValueError: If fewer than ``min_benchmark_samples`` pairs provided.
        """
        if len(pairs) < self._config.min_benchmark_samples:
            raise ValueError(
                f"Need at least {self._config.min_benchmark_samples} samples "
                f"to fit calibrator, got {len(pairs)}"
            )

        confidences = np.array([p[0] for p in pairs], dtype=np.float64)
        outcomes = np.array([float(p[1]) for p in pairs], dtype=np.float64)

        self._calibrator.fit(confidences, outcomes)
        self._fitted = True
        self._fit_samples = len(pairs)

        ece_val, _ = metrics.compute_ece(confidences, outcomes, self._config.bins)
        self._fit_metrics = {
            "ece": ece_val,
            "mce": metrics.compute_mce(confidences, outcomes, self._config.bins),
            "brier": metrics.compute_brier_score(confidences, outcomes),
        }
        logger.info(
            "Calibrator fitted (%s, %d samples): ECE=%.4f MCE=%.4f Brier=%.4f",
            self._config.method, len(pairs),
            self._fit_metrics["ece"], self._fit_metrics["mce"],
            self._fit_metrics["brier"],
        )
        return dict(self._fit_metrics)

    # ── Persistence ──────────────────────────────────────────────

    def save(self) -> None:
        """Persist fitted calibrator to ``config.persist_path``."""
        path = Path(self._config.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "calibrator": self._calibrator,
            "fitted": self._fitted,
            "fit_samples": self._fit_samples,
            "metrics": self._fit_metrics,
        }
        with open(path, "wb") as fh:
            pickle.dump(state, fh)
        logger.info("Calibration state saved to %s", path)

    def load(self) -> None:
        """Load calibrator state from ``config.persist_path``."""
        path = Path(self._config.persist_path)
        with open(path, "rb") as fh:
            state: dict[str, Any] = pickle.load(fh)  # noqa: S301
        self._calibrator = state["calibrator"]
        self._fitted = state.get("fitted", False)
        self._fit_samples = state.get("fit_samples", 0)
        self._fit_metrics = state.get("metrics", {})
        logger.info("Calibration state loaded from %s", path)

    # ── Introspection ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return current calibration statistics and configuration summary."""
        return {
            "enabled": self._config.enabled,
            "method": self._config.method,
            "fitted": self._fitted,
            "fit_samples": self._fit_samples,
            "calibration_count": self._calibration_count,
            "fit_metrics": dict(self._fit_metrics),
            "persist_path": str(self._config.persist_path),
        }
