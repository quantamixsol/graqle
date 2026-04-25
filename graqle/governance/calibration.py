# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26166054.2 (Divisional, Claims F-J), owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Audit-Grade Governance Calibration (R20 ADR-203).

Calibrates governance scores against real outcomes using established
statistical methods (Platt scaling, isotonic regression). Returns
calibrated incident probabilities with confidence intervals.

Target: Expected Calibration Error (ECE) < 0.05

Pure Python — no scipy dependency.

TS-2 Gate: Calibration curve is proprietary IP.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# Minimum sample size for valid calibration (Niculescu-Mizil & Caruana, 2005)
MIN_SAMPLES = 1000

# Default ECE binning
DEFAULT_N_BINS = 10

# Target ECE for audit-grade calibration
TARGET_ECE = 0.05

# Score range (LoopObserver governance scores are 0-100)
SCORE_MIN = 0.0
SCORE_MAX = 100.0


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class BinStats(BaseModel):
    """Statistics for a single calibration bin."""

    model_config = ConfigDict(extra="forbid")

    index: int
    lower: float
    upper: float
    count: int
    avg_pred: float = 0.0  # mean predicted probability in bin
    avg_actual: float = 0.0  # mean observed outcome in bin
    gap: float = 0.0  # |avg_actual - avg_pred|
    ci_low: float | None = None  # bootstrap lower bound
    ci_high: float | None = None  # bootstrap upper bound


class CalibrationModel(BaseModel):
    """A fitted calibration model with audit metadata."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default_factory=lambda: f"cal-{uuid4().hex[:8]}")
    method: Literal["platt", "isotonic"]
    status: Literal["calibrated", "uncalibrated"]
    n_samples: int
    ece: float | None = None
    target_ece: float = TARGET_ECE
    ece_passed: bool = False
    bins: list[BinStats] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    ci_method: str = "bootstrap"
    ci_bootstrap_b: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str | None = None


class CalibrationPrediction(BaseModel):
    """Output of calibrator.predict(score)."""

    model_config = ConfigDict(extra="forbid")

    score: float
    risk: float  # calibrated incident probability
    ci_lower: float | None = None
    ci_upper: float | None = None
    status: Literal["calibrated", "uncalibrated"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    lower_idx = int(math.floor(rank))
    upper_idx = int(math.ceil(rank))
    frac = rank - lower_idx
    return sorted_values[lower_idx] * (1 - frac) + sorted_values[upper_idx] * frac


def _normalize_score(score: float) -> float:
    """Map score from [0, 100] to [0, 1]."""
    return max(0.0, min(1.0, (score - SCORE_MIN) / (SCORE_MAX - SCORE_MIN)))


# ---------------------------------------------------------------------------
# Platt Scaling
# ---------------------------------------------------------------------------


def fit_platt(
    pairs: list[tuple[float, int]],
    learning_rate: float = 0.01,
    max_iter: int = 500,
    l2: float = 0.001,
) -> dict[str, float]:
    """Fit Platt scaling: r(s) = sigmoid(a*s + b).

    Parameters
    ----------
    pairs:
        List of (score, outcome) pairs. outcome in {0, 1}.
    learning_rate:
        Gradient descent step size.
    max_iter:
        Maximum iterations.
    l2:
        L2 regularization coefficient.

    Returns
    -------
    Dict with fitted parameters a, b, final_loss.
    """
    if not pairs:
        return {"a": 0.0, "b": 0.0, "final_loss": 0.0}

    # Normalize scores to [0, 1] for numerical stability
    xs = [_normalize_score(s) for s, _ in pairs]
    ys = [float(y) for _, y in pairs]
    n = len(pairs)

    a = 0.0
    b = 0.0

    for _ in range(max_iter):
        # Forward pass
        preds = [_sigmoid(a * x + b) for x in xs]

        # Gradients
        da = sum((p - y) * x for p, y, x in zip(preds, ys, xs)) / n + l2 * a
        db = sum(p - y for p, y in zip(preds, ys)) / n

        a -= learning_rate * da
        b -= learning_rate * db

    # Final loss
    final_preds = [_sigmoid(a * x + b) for x in xs]
    # Clip for log stability
    eps = 1e-12
    loss = -sum(
        y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
        for p, y in zip(final_preds, ys)
    ) / n

    return {"a": a, "b": b, "final_loss": loss}


def predict_platt(score: float, params: dict[str, float]) -> float:
    """Apply Platt calibration to a score."""
    x = _normalize_score(score)
    return _sigmoid(params["a"] * x + params["b"])


# ---------------------------------------------------------------------------
# Isotonic Regression (Pool Adjacent Violators)
# ---------------------------------------------------------------------------


def fit_isotonic(pairs: list[tuple[float, int]]) -> dict[str, Any]:
    """Fit isotonic regression using PAV algorithm.

    Returns a list of knots (score_upper_bound, fitted_value) that
    define a step function from score to calibrated probability.
    """
    if not pairs:
        return {"knots": []}

    # Sort by score
    sorted_pairs = sorted(pairs, key=lambda p: p[0])

    # Initialize blocks: each point is its own block
    blocks = [
        {"sum_y": float(y), "count": 1, "mean": float(y), "score_max": s}
        for s, y in sorted_pairs
    ]

    # PAV: merge adjacent blocks that violate monotonicity
    i = 0
    while i < len(blocks) - 1:
        if blocks[i]["mean"] > blocks[i + 1]["mean"]:
            # Merge blocks[i] and blocks[i+1]
            merged = {
                "sum_y": blocks[i]["sum_y"] + blocks[i + 1]["sum_y"],
                "count": blocks[i]["count"] + blocks[i + 1]["count"],
                "score_max": blocks[i + 1]["score_max"],
            }
            merged["mean"] = merged["sum_y"] / merged["count"]
            blocks = blocks[:i] + [merged] + blocks[i + 2:]
            # Move back to check new neighbor
            if i > 0:
                i -= 1
        else:
            i += 1

    # Build knots: (score_upper_bound, mean)
    knots = [(b["score_max"], b["mean"]) for b in blocks]
    return {"knots": knots}


def predict_isotonic(score: float, params: dict[str, Any]) -> float:
    """Apply isotonic calibration to a score via step function."""
    knots = params.get("knots", [])
    if not knots:
        return 0.5  # uninformative default

    # Find the first knot with score_upper >= score
    for score_upper, value in knots:
        if score <= score_upper:
            return value
    # Score above all knots — use last knot value
    return knots[-1][1]


# ---------------------------------------------------------------------------
# Expected Calibration Error (ECE)
# ---------------------------------------------------------------------------


def compute_ece(
    predictions: list[float],
    outcomes: list[int],
    n_bins: int = DEFAULT_N_BINS,
) -> tuple[float, list[BinStats]]:
    """Compute Expected Calibration Error with equal-width bins.

    Returns
    -------
    (ece, bin_stats) tuple.
    """
    if not predictions or len(predictions) != len(outcomes):
        return 0.0, []

    n = len(predictions)
    bins: list[BinStats] = []

    for i in range(n_bins):
        lower = i / n_bins
        upper = (i + 1) / n_bins
        # Last bin is inclusive on upper bound
        in_bin = [
            (p, y) for p, y in zip(predictions, outcomes)
            if (p >= lower and p < upper) or (i == n_bins - 1 and p == 1.0)
        ]
        count = len(in_bin)
        if count == 0:
            bins.append(BinStats(
                index=i, lower=lower, upper=upper, count=0,
            ))
            continue

        avg_pred = sum(p for p, _ in in_bin) / count
        avg_actual = sum(y for _, y in in_bin) / count
        gap = abs(avg_actual - avg_pred)

        bins.append(BinStats(
            index=i,
            lower=lower,
            upper=upper,
            count=count,
            avg_pred=avg_pred,
            avg_actual=avg_actual,
            gap=gap,
        ))

    # ECE = weighted gap
    ece = sum(b.count / n * b.gap for b in bins)
    return ece, bins


# ---------------------------------------------------------------------------
# Bootstrap Confidence Intervals
# ---------------------------------------------------------------------------


def bootstrap_bin_ci(
    pairs: list[tuple[float, int]],
    method: str,
    bins: list[BinStats],
    b: int = 100,
    seed: int | None = None,
) -> list[BinStats]:
    """Compute bootstrap confidence intervals for each bin.

    Resamples pairs B times with replacement, refits calibration,
    recomputes bin stats, and returns 2.5/97.5 percentile CIs.
    """
    if not pairs or b < 2:
        return bins

    rng = random.Random(seed)
    n = len(pairs)

    # Per-bin bootstrap accumulator: {bin_index: [actual_rates]}
    bin_actuals: dict[int, list[float]] = {i: [] for i in range(len(bins))}

    for _ in range(b):
        sample = [rng.choice(pairs) for _ in range(n)]
        # Refit
        if method == "platt":
            params = fit_platt(sample)
            preds = [predict_platt(s, params) for s, _ in sample]
        else:
            params = fit_isotonic(sample)
            preds = [predict_isotonic(s, params) for s, _ in sample]
        outcomes = [y for _, y in sample]
        _, boot_bins = compute_ece(preds, outcomes, n_bins=len(bins))
        for bs in boot_bins:
            if bs.count > 0:
                bin_actuals[bs.index].append(bs.avg_actual)

    # Compute percentiles per bin
    updated_bins = []
    for bs in bins:
        actuals = sorted(bin_actuals[bs.index])
        if len(actuals) >= 2:
            ci_low = _percentile(actuals, 2.5)
            ci_high = _percentile(actuals, 97.5)
            updated_bins.append(bs.model_copy(update={"ci_low": ci_low, "ci_high": ci_high}))
        else:
            updated_bins.append(bs)
    return updated_bins


# ---------------------------------------------------------------------------
# Main Calibrator
# ---------------------------------------------------------------------------


class Calibrator:
    """Audit-grade governance score calibrator.

    Usage::

        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic")
        prediction = cal.predict(score=94.0)
        # -> CalibrationPrediction(risk=0.002, ci_lower=0.001, ci_upper=0.005, ...)
    """

    def __init__(self) -> None:
        self._model: CalibrationModel | None = None

    @property
    def model(self) -> CalibrationModel | None:
        return self._model

    def fit(
        self,
        pairs: list[tuple[float, int]],
        method: Literal["platt", "isotonic"] = "isotonic",
        bootstrap_b: int = 100,
        seed: int | None = None,
    ) -> CalibrationModel:
        """Fit a calibration model on (score, outcome) pairs.

        Parameters
        ----------
        pairs:
            List of (score, outcome) tuples. Score in [0, 100], outcome in {0, 1}.
        method:
            "platt" or "isotonic".
        bootstrap_b:
            Number of bootstrap resamples for CI (0 to skip).
        seed:
            Optional random seed for reproducibility.

        Returns
        -------
        CalibrationModel with status="uncalibrated" if N < 1000.
        """
        n = len(pairs)

        if n < MIN_SAMPLES:
            self._model = CalibrationModel(
                method=method,
                status="uncalibrated",
                n_samples=n,
                notes=f"N={n} below minimum {MIN_SAMPLES}",
            )
            return self._model

        # Fit chosen method
        if method == "platt":
            params = fit_platt(pairs)
            preds = [predict_platt(s, params) for s, _ in pairs]
        else:
            params = fit_isotonic(pairs)
            preds = [predict_isotonic(s, params) for s, _ in pairs]

        outcomes = [y for _, y in pairs]
        ece, bins = compute_ece(preds, outcomes, n_bins=DEFAULT_N_BINS)

        # Bootstrap CIs
        if bootstrap_b >= 2:
            bins = bootstrap_bin_ci(pairs, method, bins, b=bootstrap_b, seed=seed)

        # For isotonic: make knots JSON-safe
        if method == "isotonic":
            params = {"knots": [[float(k[0]), float(k[1])] for k in params["knots"]]}

        self._model = CalibrationModel(
            method=method,
            status="calibrated",
            n_samples=n,
            ece=ece,
            ece_passed=ece < TARGET_ECE,
            bins=bins,
            params=params,
            ci_bootstrap_b=bootstrap_b,
        )
        return self._model

    def predict(self, score: float) -> CalibrationPrediction:
        """Predict calibrated risk for a given governance score."""
        if self._model is None or self._model.status != "calibrated":
            return CalibrationPrediction(
                score=score,
                risk=0.0,
                status="uncalibrated",
            )

        if self._model.method == "platt":
            # Reconstruct knots-free params for isotonic handling
            params = self._model.params
            risk = predict_platt(score, params)
        else:
            # Convert list-of-lists back to list-of-tuples
            params = {"knots": [(k[0], k[1]) for k in self._model.params.get("knots", [])]}
            risk = predict_isotonic(score, params)

        # CI from nearest matching bin
        ci_lower = None
        ci_upper = None
        for b in self._model.bins:
            if b.count > 0 and b.lower <= risk < b.upper + 0.001:
                ci_lower = b.ci_low
                ci_upper = b.ci_high
                break

        return CalibrationPrediction(
            score=score,
            risk=risk,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            status="calibrated",
        )

    def load_model(self, model: CalibrationModel) -> None:
        """Load a pre-fitted calibration model."""
        self._model = model
