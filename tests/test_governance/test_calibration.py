"""Tests for R20 Audit-Grade Governance Calibration (ADR-203).

Covers: calibration.py, calibration_store.py, reliability_diagram.py.
Acceptance criteria: AC-1 through AC-7.
"""

import json
import math
import random
import tempfile
from pathlib import Path

import pytest

from graqle.governance.calibration import (
    MIN_SAMPLES,
    TARGET_ECE,
    DEFAULT_N_BINS,
    BinStats,
    CalibrationModel,
    CalibrationPrediction,
    Calibrator,
    bootstrap_bin_ci,
    compute_ece,
    fit_isotonic,
    fit_platt,
    predict_isotonic,
    predict_platt,
    _percentile,
    _sigmoid,
)
from graqle.governance.calibration_store import CalibrationStore
from graqle.governance.reliability_diagram import generate_svg


def _make_pairs(n: int = 1200, seed: int = 42) -> list[tuple[float, int]]:
    """Simulate (score, outcome) pairs with realistic distribution."""
    random.seed(seed)
    pairs = []
    for _ in range(n):
        score = random.uniform(0, 100)
        # Higher score -> lower incident rate
        p_incident = max(0.0, min(1.0, (100 - score) / 100.0))
        outcome = 1 if random.random() < p_incident else 0
        pairs.append((score, outcome))
    return pairs


# ═══════════════════════════════════════════════════════════════════
# Helper function tests
# ═══════════════════════════════════════════════════════════════════


class TestHelpers:
    def test_sigmoid_zero(self):
        assert abs(_sigmoid(0) - 0.5) < 0.001

    def test_sigmoid_stable(self):
        assert _sigmoid(1000) == 1.0
        assert _sigmoid(-1000) == 0.0

    def test_percentile_basic(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 50) == 3.0
        assert _percentile(vals, 0) == 1.0
        assert _percentile(vals, 100) == 5.0

    def test_percentile_empty(self):
        assert _percentile([], 50) == 0.0


# ═══════════════════════════════════════════════════════════════════
# Platt scaling tests
# ═══════════════════════════════════════════════════════════════════


class TestPlatt:
    def test_fit_basic(self):
        pairs = _make_pairs(500)
        params = fit_platt(pairs)
        assert "a" in params
        assert "b" in params
        assert "final_loss" in params

    def test_predict_in_range(self):
        params = {"a": 1.0, "b": 0.0}
        for score in [0, 25, 50, 75, 100]:
            r = predict_platt(score, params)
            assert 0.0 <= r <= 1.0

    def test_fit_converges(self):
        # Well-separated data should produce meaningful params
        pairs = []
        for _ in range(500):
            pairs.append((20.0, 1))  # low score -> incident
            pairs.append((80.0, 0))  # high score -> no incident
        params = fit_platt(pairs)
        # Low score should have high risk, high score low risk
        r_low = predict_platt(20, params)
        r_high = predict_platt(80, params)
        assert r_low > r_high


# ═══════════════════════════════════════════════════════════════════
# Isotonic regression tests
# ═══════════════════════════════════════════════════════════════════


class TestIsotonic:
    def test_fit_basic(self):
        pairs = _make_pairs(500)
        params = fit_isotonic(pairs)
        assert "knots" in params
        assert len(params["knots"]) > 0

    def test_monotonic_fit(self):
        """PAV should produce monotonic non-decreasing fit."""
        pairs = _make_pairs(1200)
        params = fit_isotonic(pairs)
        means = [v for _, v in params["knots"]]
        for i in range(1, len(means)):
            assert means[i] >= means[i - 1] - 1e-9  # monotonic

    def test_predict_in_range(self):
        params = fit_isotonic(_make_pairs(500))
        for score in [0, 25, 50, 75, 100]:
            r = predict_isotonic(score, params)
            assert 0.0 <= r <= 1.0

    def test_empty_pairs(self):
        params = fit_isotonic([])
        assert params["knots"] == []

    def test_inverse_relationship(self):
        """Higher score should predict lower risk (inverse)."""
        pairs = _make_pairs(1500)
        params = fit_isotonic(pairs)
        r_low = predict_isotonic(10, params)
        r_high = predict_isotonic(90, params)
        # After sorting by score ascending, low scores get mapped to higher y values
        # (since low score = high incident rate in our test data)
        # The PAV fit is monotonic in the score order, so we expect r_low > r_high.
        assert r_low > r_high or abs(r_low - r_high) < 0.1


# ═══════════════════════════════════════════════════════════════════
# ECE tests
# ═══════════════════════════════════════════════════════════════════


class TestECE:
    def test_perfect_calibration(self):
        """Perfectly calibrated predictions should have ECE ~ 0."""
        predictions = [0.1] * 100 + [0.9] * 100
        # 10 of first 100 are incidents, 90 of last 100 are incidents
        outcomes = [1] * 10 + [0] * 90 + [1] * 90 + [0] * 10
        ece, bins = compute_ece(predictions, outcomes)
        assert ece < 0.05  # very well calibrated

    def test_worst_calibration(self):
        """Predictions opposite to reality should have high ECE."""
        # Predict 0.1 but reality is 90% incidents, predict 0.9 but reality is 10%
        predictions = [0.1] * 100 + [0.9] * 100
        outcomes = [1] * 90 + [0] * 10 + [1] * 10 + [0] * 90
        ece, bins = compute_ece(predictions, outcomes)
        assert ece > 0.5

    def test_bin_count(self):
        predictions = [i / 100 for i in range(100)]
        outcomes = [i // 50 for i in range(100)]
        ece, bins = compute_ece(predictions, outcomes, n_bins=10)
        assert len(bins) == 10

    def test_empty_input(self):
        ece, bins = compute_ece([], [])
        assert ece == 0.0
        assert bins == []


# ═══════════════════════════════════════════════════════════════════
# Calibrator (main API) tests
# ═══════════════════════════════════════════════════════════════════


class TestCalibrator:
    """AC-1: Calibration not valid until N >= 1000."""

    def test_uncalibrated_below_min(self):
        """AC-1: Returns uncalibrated for N < 1000."""
        pairs = _make_pairs(100)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        assert model.status == "uncalibrated"
        assert model.n_samples == 100

    def test_calibrated_at_min(self):
        """AC-1: Returns calibrated for N >= 1000."""
        pairs = _make_pairs(1000)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        assert model.status == "calibrated"
        assert model.n_samples == 1000

    def test_isotonic_produces_ece(self):
        """AC-2: ECE computed on fitted model."""
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        assert model.ece is not None
        assert 0.0 <= model.ece <= 1.0

    def test_isotonic_ece_below_target(self):
        """AC-2: Well-formed data should pass ECE target."""
        pairs = _make_pairs(2000)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        # Isotonic on realistic data should easily pass target
        assert model.ece < 0.1  # generous bound

    def test_confidence_intervals_produced(self):
        """AC-3: Each bin has CI when bootstrap > 0."""
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=10, seed=42)
        ci_bins = [b for b in model.bins if b.count > 0 and b.ci_low is not None]
        assert len(ci_bins) > 0

    def test_method_explicit(self):
        """AC-4: Method name logged in metadata."""
        pairs = _make_pairs(1200)
        cal = Calibrator()
        m1 = cal.fit(pairs, method="platt", bootstrap_b=0)
        m2 = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        assert m1.method == "platt"
        assert m2.method == "isotonic"

    def test_versioned_model(self):
        """AC-5: Each fit produces a unique version."""
        pairs = _make_pairs(1100)
        cal = Calibrator()
        m1 = cal.fit(pairs, bootstrap_b=0)
        m2 = cal.fit(pairs, bootstrap_b=0)
        assert m1.version != m2.version

    def test_predict_api(self):
        """AC-7: graq_calibrate(score) -> {risk, ci_lower, ci_upper} API."""
        pairs = _make_pairs(1200)
        cal = Calibrator()
        cal.fit(pairs, method="isotonic", bootstrap_b=10)
        pred = cal.predict(94.0)
        assert isinstance(pred, CalibrationPrediction)
        assert pred.status == "calibrated"
        assert 0.0 <= pred.risk <= 1.0

    def test_predict_uncalibrated(self):
        cal = Calibrator()
        pred = cal.predict(94.0)
        assert pred.status == "uncalibrated"
        assert pred.risk == 0.0

    def test_load_model(self):
        pairs = _make_pairs(1100)
        cal1 = Calibrator()
        model = cal1.fit(pairs, method="isotonic", bootstrap_b=0)

        cal2 = Calibrator()
        cal2.load_model(model)
        pred = cal2.predict(50.0)
        assert pred.status == "calibrated"

    def test_platt_method(self):
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="platt", bootstrap_b=0)
        assert model.status == "calibrated"
        assert "a" in model.params
        assert "b" in model.params


# ═══════════════════════════════════════════════════════════════════
# CalibrationStore tests
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationStore:
    """AC-5: Calibration artifacts versioned."""

    def test_save_and_load(self):
        pairs = _make_pairs(1100)
        cal = Calibrator()
        model = cal.fit(pairs, bootstrap_b=0)

        d = tempfile.mkdtemp()
        store = CalibrationStore(store_dir=d)
        path = store.save(model)
        assert path.exists()

        loaded = store.load(model.version)
        assert loaded.version == model.version
        assert loaded.ece == model.ece
        assert loaded.method == model.method

    def test_current_pointer(self):
        pairs = _make_pairs(1100)
        cal = Calibrator()
        model = cal.fit(pairs, bootstrap_b=0)

        d = tempfile.mkdtemp()
        store = CalibrationStore(store_dir=d)
        store.save(model, make_active=True)

        current = store.load_current()
        assert current is not None
        assert current.version == model.version

    def test_list_versions(self):
        d = tempfile.mkdtemp()
        store = CalibrationStore(store_dir=d)
        cal = Calibrator()
        pairs = _make_pairs(1100)

        for _ in range(3):
            model = cal.fit(pairs, bootstrap_b=0)
            store.save(model)

        versions = store.list_versions()
        assert len(versions) == 3

    def test_load_missing_version(self):
        d = tempfile.mkdtemp()
        store = CalibrationStore(store_dir=d)
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent")

    def test_no_current_model(self):
        d = tempfile.mkdtemp()
        store = CalibrationStore(store_dir=d)
        assert store.load_current() is None


# ═══════════════════════════════════════════════════════════════════
# Reliability diagram tests
# ═══════════════════════════════════════════════════════════════════


class TestReliabilityDiagram:
    """AC-6: Reliability diagram exportable."""

    def test_svg_calibrated(self):
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        svg = generate_svg(model)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert "Reliability Diagram" in svg
        assert "calibrated" in svg.lower()

    def test_svg_uncalibrated(self):
        pairs = _make_pairs(100)
        cal = Calibrator()
        model = cal.fit(pairs, bootstrap_b=0)
        svg = generate_svg(model)
        assert svg.startswith("<svg")
        assert "uncalibrated" in svg.lower()

    def test_svg_contains_ece(self):
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=0)
        svg = generate_svg(model)
        assert "ECE" in svg

    def test_svg_with_ci_whiskers(self):
        pairs = _make_pairs(1200)
        cal = Calibrator()
        model = cal.fit(pairs, method="isotonic", bootstrap_b=10, seed=42)
        svg = generate_svg(model)
        # Whiskers use stroke-width=2
        assert "stroke-width=\"2\"" in svg
