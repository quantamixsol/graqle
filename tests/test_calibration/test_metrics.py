"""Unit tests for calibration metrics (ECE, MCE, Brier score)."""

from __future__ import annotations

import numpy as np
import pytest

from graqle.calibration.metrics import (
    compute_brier_score,
    compute_ece,
    compute_mce,
)


class TestComputeEce:
    """Tests for Expected Calibration Error."""

    def test_perfectly_calibrated(self) -> None:
        """Confidences matching actual accuracy per bin -> ECE ~= 0."""
        rng = np.random.RandomState(42)
        n = 10_000
        confs = rng.uniform(0.0, 1.0, size=n)
        correctness = (rng.uniform(0.0, 1.0, size=n) < confs).astype(float)
        ece, _ = compute_ece(confs, correctness, n_bins=10)
        assert ece < 0.05, f"ECE should be near 0 for calibrated predictions, got {ece}"

    def test_maximally_miscalibrated(self) -> None:
        """All confidence 1.0 but all wrong -> ECE = 1.0."""
        confs = np.ones(100)
        correctness = np.zeros(100)
        ece, _ = compute_ece(confs, correctness, n_bins=10)
        assert ece == pytest.approx(1.0, abs=1e-9)

    def test_empty_raises(self) -> None:
        """Empty arrays should raise ValueError."""
        with pytest.raises(ValueError):
            compute_ece(np.array([]), np.array([]))

    def test_size_mismatch_raises(self) -> None:
        """Different size arrays should raise ValueError."""
        with pytest.raises(ValueError):
            compute_ece(np.array([0.5, 0.6]), np.array([1.0]))

    def test_out_of_range_raises(self) -> None:
        """Confidence >1 or <0 should raise ValueError."""
        with pytest.raises(ValueError):
            compute_ece(np.array([1.5]), np.array([1.0]))
        with pytest.raises(ValueError):
            compute_ece(np.array([-0.1]), np.array([1.0]))

    def test_single_sample(self) -> None:
        """One element should work without error."""
        ece, _ = compute_ece(np.array([0.8]), np.array([1.0]), n_bins=10)
        assert isinstance(ece, float)
        assert 0.0 <= ece <= 1.0

    def test_n_bins_zero_raises(self) -> None:
        """n_bins=0 should raise ValueError."""
        with pytest.raises(ValueError):
            compute_ece(np.array([0.5]), np.array([1.0]), n_bins=0)

    def test_reliability_diagram_structure(self) -> None:
        """Reliability diagram returns dict with (accuracy, confidence, count) tuples."""
        confs = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        correctness = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
        _, diagram = compute_ece(confs, correctness, n_bins=5)
        assert isinstance(diagram, dict)
        for key, val in diagram.items():
            assert isinstance(key, float)
            assert len(val) == 3  # (accuracy, confidence, count)
            acc, conf, count = val
            assert 0.0 <= acc <= 1.0
            assert 0.0 <= conf <= 1.0
            assert count >= 1


class TestComputeMce:
    """Tests for Maximum Calibration Error."""

    def test_worst_bin(self) -> None:
        """MCE should capture the worst single-bin calibration gap."""
        confs = np.ones(50)
        correctness = np.zeros(50)
        mce = compute_mce(confs, correctness, n_bins=10)
        assert mce == pytest.approx(1.0, abs=1e-9)

    def test_mce_gte_ece(self) -> None:
        """MCE >= ECE always (worst bin >= weighted average)."""
        rng = np.random.RandomState(7)
        confs = rng.uniform(0.0, 1.0, size=200)
        correctness = (rng.uniform(0.0, 1.0, size=200) < confs).astype(float)
        ece, _ = compute_ece(confs, correctness, n_bins=10)
        mce = compute_mce(confs, correctness, n_bins=10)
        assert mce >= ece - 1e-9, f"MCE ({mce}) should be >= ECE ({ece})"


class TestBrierScore:
    """Tests for Brier score."""

    def test_perfect_prediction(self) -> None:
        """Confidence matches outcome exactly -> Brier = 0."""
        confs = np.array([1.0, 0.0, 1.0, 0.0])
        outcomes = np.array([1.0, 0.0, 1.0, 0.0])
        score = compute_brier_score(confs, outcomes)
        assert score == pytest.approx(0.0, abs=1e-9)

    def test_worst_prediction(self) -> None:
        """Confidence opposite of outcome -> Brier = 1."""
        confs = np.array([1.0, 1.0, 0.0, 0.0])
        outcomes = np.array([0.0, 0.0, 1.0, 1.0])
        score = compute_brier_score(confs, outcomes)
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_baseline(self) -> None:
        """All confidence 0.5 on balanced outcomes -> Brier ~= 0.25."""
        confs = np.full(100, 0.5)
        outcomes = np.concatenate([np.ones(50), np.zeros(50)])
        score = compute_brier_score(confs, outcomes)
        assert score == pytest.approx(0.25, abs=1e-9)
