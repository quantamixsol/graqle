"""Calibration methods for confidence score post-hoc calibration.

Provides temperature scaling (numpy-only), Platt scaling (scipy),
and isotonic calibration (sklearn) with graceful fallback.
"""

# ── graqle:intelligence ──
# module: graqle.calibration.methods
# risk: MEDIUM (impact radius: 3 modules)
# consumers: calibration.engine, calibration.pipeline, reasoning
# dependencies: __future__, abc, json, logging, pathlib, numpy
# optional_dependencies: scipy, sklearn
# constraints: TemperatureScaling must always be available (numpy-only)
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

_EPS = 1e-7


def _safe_logit(p: float | np.ndarray) -> float | np.ndarray:
    """Numerically-safe logit: log(p / (1-p)), clamped to [eps, 1-eps]."""
    p = np.clip(p, _EPS, 1.0 - _EPS)
    return np.log(p / (1.0 - p))


def _sigmoid(x: float | np.ndarray) -> float | np.ndarray:
    """Numerically-stable sigmoid."""
    x = np.asarray(x, dtype=np.float64)
    return np.where(
        x >= 0,
        1.0 / (1.0 + np.exp(-x)),
        np.exp(x) / (1.0 + np.exp(x)),
    )


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseCalibrator(ABC):
    """Abstract base class for confidence calibrators."""

    @property
    @abstractmethod
    def fitted(self) -> bool:
        """Return True if the calibrator has been fitted to data."""

    @abstractmethod
    def fit(self, confidences: np.ndarray, correctness: np.ndarray) -> None:
        """Fit the calibrator on observed confidences and binary correctness.

        Parameters
        ----------
        confidences:
            1-D array of predicted confidence scores in [0, 1].
        correctness:
            1-D binary array (0 or 1) indicating whether each prediction
            was correct.
        """

    @abstractmethod
    def calibrate(self, confidence: float) -> float:
        """Map a raw confidence score to a calibrated probability.

        Parameters
        ----------
        confidence:
            A single raw confidence value in [0, 1].

        Returns
        -------
        float
            Calibrated confidence in [0, 1].
        """

    @abstractmethod
    def save(self, path: str) -> None:
        """Persist calibrator parameters to *path*."""

    @classmethod
    @abstractmethod
    def load(cls, path: str) -> BaseCalibrator:
        """Load a calibrator from a previously saved file."""


# ---------------------------------------------------------------------------
# Temperature Scaling (numpy-only — always available)
# ---------------------------------------------------------------------------


class TemperatureScaling(BaseCalibrator):
    """Post-hoc temperature scaling calibrator.

    Learns a single scalar *T* such that ``sigmoid(logit(p) / T)`` is
    well-calibrated.  Fitting uses a grid search over 500 candidates
    minimising Brier score — no external optimiser required.
    """

    def __init__(self, temperature: float = 1.0) -> None:
        if temperature <= 0:
            raise ValueError(f"temperature must be positive, got {temperature}")
        self._temperature: float = temperature
        self._fitted: bool = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def temperature(self) -> float:
        return self._temperature

    def fit(self, confidences: np.ndarray, correctness: np.ndarray) -> None:
        confidences = np.asarray(confidences, dtype=np.float64)
        correctness = np.asarray(correctness, dtype=np.float64)

        if len(confidences) == 0:
            raise ValueError("fit() requires at least one sample")
        if confidences.shape != correctness.shape:
            raise ValueError(
                f"confidences and correctness must have the same shape; "
                f"got {confidences.shape} vs {correctness.shape}"
            )
        if not np.all((correctness == 0) | (correctness == 1)):
            raise ValueError("correctness must be a binary array of 0s and 1s")

        logits = _safe_logit(confidences)
        best_t = 1.0
        best_loss = float("inf")

        for t in np.linspace(0.1, 5.0, 500):
            calibrated = _sigmoid(logits / t)
            brier = float(np.mean((calibrated - correctness) ** 2))
            if brier < best_loss:
                best_loss = brier
                best_t = float(t)

        self._temperature = best_t
        self._fitted = True

        if best_t <= 0.1 or best_t >= 5.0:
            logger.warning(
                "TemperatureScaling: best_t=%.4f hit search boundary; "
                "consider widening range", best_t,
            )
        logger.info(
            "TemperatureScaling fitted: T=%.4f, Brier=%.6f", best_t, best_loss,
        )

    def calibrate(self, confidence: float) -> float:
        if not self._fitted:
            raise RuntimeError("Calibrator not fitted. Call fit() first.")
        logit = _safe_logit(confidence)
        return float(_sigmoid(logit / self._temperature))

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps({"temperature": self._temperature}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str) -> TemperatureScaling:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            temp = float(data["temperature"])
        except KeyError as exc:
            raise ValueError(
                f"Invalid calibrator file {path!r}: missing key 'temperature'"
            ) from exc
        if temp <= 0:
            raise ValueError(
                f"Invalid calibrator file {path!r}: temperature must be positive, got {temp}"
            )
        inst = cls(temperature=temp)
        inst._fitted = True
        return inst


# ---------------------------------------------------------------------------
# Platt Scaling (requires scipy)
# ---------------------------------------------------------------------------


class PlattScaling(BaseCalibrator):
    """Two-parameter Platt scaling: ``sigmoid(a * logit(p) + b)``.

    Fits *a* and *b* by minimising negative log-likelihood via
    ``scipy.optimize.minimize``.  Scipy is imported lazily inside
    ``fit()`` so the class can be instantiated without scipy.
    """

    def __init__(self, a: float = 1.0, b: float = 0.0) -> None:
        self._a: float = a
        self._b: float = b
        self._fitted: bool = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, confidences: np.ndarray, correctness: np.ndarray) -> None:
        try:
            from scipy.optimize import minimize  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PlattScaling requires scipy. Install with: pip install scipy"
            ) from exc

        confidences = np.asarray(confidences, dtype=np.float64)
        correctness = np.asarray(correctness, dtype=np.float64)
        logits = _safe_logit(confidences)

        def _nll(params: np.ndarray) -> float:
            a, b = params
            p = _sigmoid(a * logits + b)
            p = np.clip(p, _EPS, 1.0 - _EPS)
            return float(-np.mean(
                correctness * np.log(p) + (1.0 - correctness) * np.log(1.0 - p)
            ))

        result = minimize(_nll, x0=np.array([1.0, 0.0]), method="Nelder-Mead")
        self._a = float(result.x[0])
        self._b = float(result.x[1])
        self._fitted = True
        logger.info("PlattScaling fitted: a=%.4f, b=%.4f", self._a, self._b)

    def calibrate(self, confidence: float) -> float:
        if not self._fitted:
            raise RuntimeError("Calibrator not fitted. Call fit() first.")
        logit = _safe_logit(confidence)
        return float(_sigmoid(self._a * logit + self._b))

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps({"a": self._a, "b": self._b}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str) -> PlattScaling:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        inst = cls(a=float(data["a"]), b=float(data["b"]))
        inst._fitted = True
        return inst


# ---------------------------------------------------------------------------
# Isotonic Calibration (requires sklearn)
# ---------------------------------------------------------------------------


class IsotonicCalibration(BaseCalibrator):
    """Isotonic regression calibrator.

    Wraps ``sklearn.isotonic.IsotonicRegression`` with
    ``y_min=0, y_max=1, out_of_bounds='clip'``.  Sklearn is imported
    lazily inside ``fit()``.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._fitted: bool = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, confidences: np.ndarray, correctness: np.ndarray) -> None:
        try:
            from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "IsotonicCalibration requires scikit-learn. "
                "Install with: pip install scikit-learn"
            ) from exc

        confidences = np.asarray(confidences, dtype=np.float64)
        correctness = np.asarray(correctness, dtype=np.float64)

        self._model = IsotonicRegression(
            y_min=0, y_max=1, out_of_bounds="clip",
        )
        self._model.fit(confidences, correctness)
        self._fitted = True
        logger.info("IsotonicCalibration fitted on %d samples", len(confidences))

    def calibrate(self, confidence: float) -> float:
        if not self._fitted:
            raise RuntimeError("Calibrator not fitted. Call fit() first.")
        return float(self._model.predict([confidence])[0])

    def save(self, path: str) -> None:
        import pickle

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(pickle.dumps(self._model))

    @classmethod
    def load(cls, path: str) -> IsotonicCalibration:
        import pickle

        inst = cls()
        inst._model = pickle.loads(Path(path).read_bytes())  # noqa: S301
        inst._fitted = True
        return inst


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_METHOD_MAP: dict[str, type[BaseCalibrator]] = {
    "temperature": TemperatureScaling,
    "platt": PlattScaling,
    "isotonic": IsotonicCalibration,
}


def create_calibrator(method: str, **kwargs: Any) -> BaseCalibrator:
    """Create a calibrator by name with graceful fallback.

    Parameters
    ----------
    method:
        One of ``"temperature"``, ``"platt"``, or ``"isotonic"``.
    **kwargs:
        Forwarded to the calibrator constructor.

    Returns
    -------
    BaseCalibrator
        The requested calibrator, or ``TemperatureScaling`` if the
        required optional dependency is unavailable.
    """
    calibrator_cls = _METHOD_MAP.get(method.lower())
    if calibrator_cls is None:
        logger.warning(
            "Unknown calibration method %r; falling back to TemperatureScaling",
            method,
        )
        return TemperatureScaling(**kwargs)

    if calibrator_cls is PlattScaling:
        try:
            import scipy  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            logger.warning(
                "scipy not available; falling back to TemperatureScaling",
            )
            return TemperatureScaling(**kwargs)

    if calibrator_cls is IsotonicCalibration:
        try:
            import sklearn  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            logger.warning(
                "scikit-learn not available; falling back to TemperatureScaling",
            )
            return TemperatureScaling(**kwargs)

    return calibrator_cls(**kwargs)
