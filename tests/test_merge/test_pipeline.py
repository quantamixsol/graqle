"""Tests for graqle.merge.pipeline — R2 Bridge Injection Pipeline (ADR-133)."""

from __future__ import annotations

import pytest

from graqle.merge.pipeline import (
    BridgeMetrics,
    BridgePipeline,
    PipelineReport,
    _R2_MIN_BDS,
    _R2_MIN_CC_DELTA,
    _R2_MIN_CROSS_EDGES,
)


# ---------------------------------------------------------------------------
# BridgeMetrics
# ---------------------------------------------------------------------------


class TestBridgeMetrics:
    def test_default_values(self):
        m = BridgeMetrics()
        assert m.cc_delta == 0
        assert m.cross_edges == 0
        assert m.bds == 0.0
        assert m.meets_success_criteria is False

    def test_meets_success_exact_boundary(self):
        m = BridgeMetrics(cc_delta=12, cross_edges=15, bds=0.03)
        assert m.meets_success_criteria is True

    def test_below_cc_delta(self):
        m = BridgeMetrics(cc_delta=11, cross_edges=15, bds=0.03)
        assert m.meets_success_criteria is False

    def test_below_cross_edges(self):
        m = BridgeMetrics(cc_delta=12, cross_edges=14, bds=0.03)
        assert m.meets_success_criteria is False

    def test_below_bds(self):
        m = BridgeMetrics(cc_delta=12, cross_edges=15, bds=0.029)
        assert m.meets_success_criteria is False

    def test_all_above(self):
        m = BridgeMetrics(cc_delta=20, cross_edges=30, bds=0.05)
        assert m.meets_success_criteria is True

    def test_constants_match_adr133(self):
        assert _R2_MIN_CC_DELTA == 12
        assert _R2_MIN_CROSS_EDGES == 15
        assert _R2_MIN_BDS == 0.03


# ---------------------------------------------------------------------------
# PipelineReport
# ---------------------------------------------------------------------------


class TestPipelineReport:
    def test_cc_delta_property(self):
        r = PipelineReport(cc_before=110, cc_after=95)
        assert r.cc_delta == 15

    def test_cc_delta_zero(self):
        r = PipelineReport(cc_before=110, cc_after=110)
        assert r.cc_delta == 0

    def test_default_values(self):
        r = PipelineReport()
        assert r.injected_count == 0
        assert r.errors == []
        assert r.cc_delta == 0


# ---------------------------------------------------------------------------
# BridgePipeline
# ---------------------------------------------------------------------------


class TestBridgePipeline:
    def test_invalid_confidence_threshold(self):
        with pytest.raises(ValueError, match="must be in"):
            BridgePipeline(graph=object(), confidence_threshold=40)

    def test_negative_confidence_threshold(self):
        with pytest.raises(ValueError, match="must be in"):
            BridgePipeline(graph=object(), confidence_threshold=-0.1)

    def test_valid_confidence_threshold(self):
        """Should not raise for valid threshold."""
        # Use a mock-like object with minimal interface
        class FakeGraph:
            nodes = {}
            edges = {}
        BridgePipeline(graph=FakeGraph(), confidence_threshold=0.5)
