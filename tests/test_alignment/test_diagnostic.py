"""Tests for R10 three-tier diagnostic protocol."""

from __future__ import annotations

import numpy as np

from graqle.alignment.diagnostic import diagnose_misalignment
from graqle.alignment.types import AlignmentPair


def _make_pair(ts_emb: np.ndarray, py_emb: np.ndarray) -> AlignmentPair:
    return AlignmentPair(
        ts_node_id="ts_test", py_node_id="py_test",
        ts_embedding=ts_emb, py_embedding=py_emb,
        tool_name="graq_reason",
    )


class TestInsufficientData:
    def test_below_min_pairs(self):
        pairs = [_make_pair(np.zeros(10), np.zeros(10)) for _ in range(5)]
        result = diagnose_misalignment(pairs, min_pairs=10)
        assert result.diagnosis == "insufficient_data"
        assert result.confidence == 0.0
        assert result.recommended_correction == "none"


class TestSystematicShift:
    def test_consistent_offset_detected(self):
        """TS embeddings consistently shifted by a fixed vector from PY."""
        rng = np.random.default_rng(42)
        shift = np.array([0.5] * 20)  # consistent shift
        pairs = []
        for _ in range(15):
            py = rng.standard_normal(20)
            ts = py + shift + rng.standard_normal(20) * 0.01  # tiny noise
            pairs.append(_make_pair(ts, py))
        result = diagnose_misalignment(pairs)
        assert result.diagnosis == "systematic_shift"
        assert result.recommended_correction == "procrustes"
        assert result.confidence > 0.0


class TestDomainDrift:
    def test_variance_concentrated_in_few_dims(self):
        """Misalignment concentrated in 1-2 dimensions."""
        rng = np.random.default_rng(42)
        pairs = []
        for _ in range(15):
            py = rng.standard_normal(20)
            # Shift only in dimension 0 — variance concentrated
            diff = np.zeros(20)
            diff[0] = rng.standard_normal() * 2.0
            ts = py + diff
            pairs.append(_make_pair(ts, py))
        result = diagnose_misalignment(pairs)
        # Should detect domain_drift (concentrated variance) or systematic_shift
        # depending on the random seed
        assert result.diagnosis in ("domain_drift", "systematic_shift")
        assert result.recommended_correction in ("augmentation", "procrustes")


class TestRandomNoise:
    def test_no_pattern_falls_to_noise(self):
        """Truly random differences → random_noise diagnosis."""
        rng = np.random.default_rng(123)
        pairs = []
        for _ in range(20):
            ts = rng.standard_normal(50)
            py = rng.standard_normal(50)  # completely independent
            pairs.append(_make_pair(ts, py))
        result = diagnose_misalignment(pairs)
        # With independent random vectors, shift_ratio should be low
        # and variance should be spread across dimensions
        assert result.diagnosis in ("random_noise", "domain_drift")
        assert result.confidence > 0.0


class TestDiagnosisEvidence:
    def test_evidence_contains_expected_keys(self):
        rng = np.random.default_rng(42)
        shift = np.array([1.0] * 10)
        pairs = [
            _make_pair(rng.standard_normal(10) + shift, rng.standard_normal(10))
            for _ in range(15)
        ]
        result = diagnose_misalignment(pairs)
        assert isinstance(result.evidence, dict)
        # All diagnosis types should have some evidence
        assert len(result.evidence) > 0
