"""Unit tests for calibration methods."""

from __future__ import annotations

import numpy as np
import pytest

from graqle.calibration.methods import (
    IsotonicCalibration,
    PlattScaling,
    TemperatureScaling,
    create_calibrator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_data(n: int = 200, seed: int = 42):
    """Return (confidences, labels) where confidences are poorly calibrated."""
    rng = np.random.RandomState(seed)
    labels = rng.randint(0, 2, size=n).astype(np.float64)
    # Overconfident predictions: push towards extremes with noise
    raw = labels * 0.7 + (1 - labels) * 0.3 + rng.normal(0, 0.15, size=n)
    confidences = np.clip(raw, 0.01, 0.99)
    return confidences, labels


def _brier_score(probs: np.ndarray, labels: np.ndarray) -> float:
    """Mean squared error between predicted probabilities and binary labels."""
    return float(np.mean((probs - labels) ** 2))


# ---------------------------------------------------------------------------
# TestTemperatureScaling
# ---------------------------------------------------------------------------


class TestTemperatureScaling:
    """Tests for TemperatureScaling calibrator."""

    def test_fit_reduces_brier(self):
        """Fit on synthetic data, verify Brier score decreases."""
        confidences, labels = _synthetic_data()
        cal = TemperatureScaling()

        brier_before = _brier_score(confidences, labels)
        cal.fit(confidences, labels)

        calibrated = np.array([cal.calibrate(float(c)) for c in confidences])
        brier_after = _brier_score(calibrated, labels)

        assert brier_after <= brier_before + 1e-6, (
            f"Brier score should decrease after fitting: "
            f"{brier_before:.4f} -> {brier_after:.4f}"
        )

    def test_calibrate_unfitted_raises(self):
        """Calling calibrate before fit raises RuntimeError."""
        cal = TemperatureScaling()
        with pytest.raises(RuntimeError):
            cal.calibrate(0.5)

    def test_calibrate_preserves_range(self):
        """Output is in [0, 1]."""
        confidences, labels = _synthetic_data()
        cal = TemperatureScaling()
        cal.fit(confidences, labels)

        test_values = [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
        for v in test_values:
            result = cal.calibrate(v)
            assert 0.0 <= result <= 1.0, (
                f"calibrate({v}) = {result} is outside [0, 1]"
            )

    def test_save_and_load(self, tmp_path):
        """Round-trip via temp file."""
        confidences, labels = _synthetic_data()
        cal = TemperatureScaling()
        cal.fit(confidences, labels)

        filepath = str(tmp_path / "temp_scaling.json")
        cal.save(filepath)

        cal2 = TemperatureScaling.load(filepath)

        # Verify identical outputs after round-trip
        for v in [0.1, 0.5, 0.9]:
            assert abs(cal.calibrate(v) - cal2.calibrate(v)) < 1e-9, (
                f"Loaded calibrator diverges at input {v}"
            )

    def test_negative_temperature_raises(self):
        """temperature=0 or negative raises ValueError."""
        with pytest.raises(ValueError):
            TemperatureScaling(temperature=0.0)

        with pytest.raises(ValueError):
            TemperatureScaling(temperature=-1.0)


# ---------------------------------------------------------------------------
# TestPlattScaling
# ---------------------------------------------------------------------------


class TestPlattScaling:
    """Tests for PlattScaling calibrator."""

    def test_fit_and_calibrate(self):
        """Fit on data, verify calibrate returns float in [0, 1]."""
        confidences, labels = _synthetic_data()
        cal = PlattScaling()
        cal.fit(confidences, labels)

        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            result = cal.calibrate(v)
            assert isinstance(result, float), (
                f"Expected float, got {type(result)}"
            )
            assert 0.0 <= result <= 1.0, (
                f"calibrate({v}) = {result} is outside [0, 1]"
            )

    def test_unfitted_raises(self):
        """Calling calibrate before fit raises RuntimeError."""
        cal = PlattScaling()
        with pytest.raises(RuntimeError):
            cal.calibrate(0.5)


# ---------------------------------------------------------------------------
# TestIsotonicCalibration
# ---------------------------------------------------------------------------


class TestIsotonicCalibration:
    """Tests for IsotonicCalibration calibrator."""

    def test_fit_and_calibrate(self):
        """Fit, verify output is float in [0, 1]."""
        confidences, labels = _synthetic_data()
        cal = IsotonicCalibration()
        cal.fit(confidences, labels)

        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            result = cal.calibrate(v)
            assert isinstance(result, float), (
                f"Expected float, got {type(result)}"
            )
            assert 0.0 <= result <= 1.0, (
                f"calibrate({v}) = {result} is outside [0, 1]"
            )

    def test_unfitted_raises(self):
        """Calling calibrate before fit raises RuntimeError."""
        cal = IsotonicCalibration()
        with pytest.raises(RuntimeError):
            cal.calibrate(0.5)

    def test_monotonicity(self):
        """Calibrated values preserve ordering of inputs."""
        confidences, labels = _synthetic_data(n=500, seed=7)
        cal = IsotonicCalibration()
        cal.fit(confidences, labels)

        inputs = np.linspace(0.05, 0.95, 50)
        outputs = [cal.calibrate(float(v)) for v in inputs]

        for i in range(1, len(outputs)):
            assert outputs[i] >= outputs[i - 1] - 1e-9, (
                f"Monotonicity violated: calibrate({inputs[i-1]:.3f})="
                f"{outputs[i-1]:.4f} > calibrate({inputs[i]:.3f})="
                f"{outputs[i]:.4f}"
            )


# ---------------------------------------------------------------------------
# TestCreateCalibrator
# ---------------------------------------------------------------------------


class TestCreateCalibrator:
    """Tests for the create_calibrator factory function."""

    def test_temperature_default(self):
        """create_calibrator('temperature') returns TemperatureScaling."""
        cal = create_calibrator("temperature")
        assert isinstance(cal, TemperatureScaling)

    def test_unknown_falls_back(self):
        """create_calibrator('bogus') returns TemperatureScaling."""
        cal = create_calibrator("bogus")
        assert isinstance(cal, TemperatureScaling)

    def test_platt_with_scipy(self):
        """Returns PlattScaling if scipy available."""
        cal = create_calibrator("platt")
        assert isinstance(cal, PlattScaling)
