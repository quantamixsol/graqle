"""Tests for R10 alignment types and cosine similarity."""

from __future__ import annotations

import json

import numpy as np

from graqle.alignment.types import (
    AlignmentPair,
    AlignmentReport,
    DiagnosisResult,
    cosine_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_zero_vector(self):
        a = np.zeros(3)
        b = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(a, b) == 0.0

    def test_both_zero(self):
        assert cosine_similarity(np.zeros(3), np.zeros(3)) == 0.0


class TestAlignmentPair:
    def test_default_values(self):
        p = AlignmentPair(
            ts_node_id="ts1", py_node_id="py1",
            ts_embedding=np.zeros(3), py_embedding=np.zeros(3),
            tool_name="graq_reason",
        )
        assert p.cosine_sim == 0.0
        assert p.tier == ""


class TestAlignmentReport:
    def test_to_dict_serializable(self):
        pair = AlignmentPair(
            ts_node_id="ts1", py_node_id="py1",
            ts_embedding=np.array([1.0, 2.0]), py_embedding=np.array([3.0, 4.0]),
            tool_name="graq_reason", cosine_sim=0.9, tier="GREEN",
        )
        report = AlignmentReport(
            pairs=[pair], mean_cosine=0.9, median_cosine=0.9,
            std_cosine=0.0, tier_distribution={"GREEN": 1},
        )
        d = report.to_dict()
        # Must be JSON-serializable
        json_str = json.dumps(d)
        assert "ts_node_id" in json_str
        assert d["pairs"][0]["ts_embedding"] == [1.0, 2.0]

    def test_empty_report(self):
        report = AlignmentReport(pairs=[], diagnosis="no_pairs_found")
        d = report.to_dict()
        assert d["pairs"] == []
        assert d["diagnosis"] == "no_pairs_found"


class TestDiagnosisResult:
    def test_to_dict_with_numpy(self):
        result = DiagnosisResult(
            diagnosis="systematic_shift",
            confidence=0.8,
            evidence={"centroid_magnitude": np.float64(0.5), "array": np.array([1, 2])},
            recommended_correction="procrustes",
        )
        d = result.to_dict()
        json_str = json.dumps(d)
        assert "systematic_shift" in json_str
        assert d["evidence"]["centroid_magnitude"] == 0.5
        assert d["evidence"]["array"] == [1, 2]
