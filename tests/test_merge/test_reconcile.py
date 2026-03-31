"""Tests for graqle.merge.reconcile — R2 Bridge-Edge Reconciliation (ADR-133)."""

from __future__ import annotations

import pytest

from graqle.analysis.bridge import BridgeCandidate, BridgeDetectionReport
from graqle.merge.reconcile import BridgeReconciler, ReconciliationReport


def _candidate(
    source: str = "a.py",
    target: str = "entity_a",
    confidence: float = 0.9,
    method: str = "exact_name",
    language: str = "python",
) -> BridgeCandidate:
    return BridgeCandidate(
        source_id=source,
        target_id=target,
        confidence=confidence,
        method=method,
        language=language,
    )


class TestBridgeReconciler:
    def test_empty_report(self):
        report = BridgeDetectionReport()
        result = BridgeReconciler(report).reconcile()
        assert len(result.accepted) == 0
        assert len(result.merged) == 0
        assert result.stats == {}

    def test_single_candidate_passthrough(self):
        report = BridgeDetectionReport(candidates=[_candidate()])
        result = BridgeReconciler(report).reconcile()
        assert len(result.accepted) == 1
        assert len(result.merged) == 0
        assert result.stats == {"exact_name": 1}

    def test_higher_confidence_wins(self):
        c_high = _candidate(confidence=0.95)
        c_low = _candidate(confidence=0.7, method="token_overlap")
        report = BridgeDetectionReport(candidates=[c_low, c_high])
        result = BridgeReconciler(report).reconcile()
        assert len(result.accepted) == 1
        assert result.accepted[0].confidence == 0.95
        assert len(result.merged) == 1

    def test_confidence_tie_method_priority(self):
        c_exact = _candidate(confidence=0.9, method="exact_name")
        c_token = _candidate(confidence=0.9, method="token_overlap")
        report = BridgeDetectionReport(candidates=[c_token, c_exact])
        result = BridgeReconciler(report).reconcile()
        assert len(result.accepted) == 1
        assert result.accepted[0].method == "exact_name"

    def test_different_targets_both_accepted(self):
        c1 = _candidate(target="entity_a")
        c2 = _candidate(target="entity_b")
        report = BridgeDetectionReport(candidates=[c1, c2])
        result = BridgeReconciler(report).reconcile()
        assert len(result.accepted) == 2
        assert len(result.merged) == 0

    def test_cross_language_conflict(self):
        c_py = _candidate(language="python", confidence=0.9)
        c_js = _candidate(language="javascript", confidence=0.8)
        report = BridgeDetectionReport(candidates=[c_py, c_js])
        result = BridgeReconciler(report).reconcile()
        # Different dedup keys → both accepted
        assert len(result.accepted) == 2

    def test_stats_count(self):
        c1 = _candidate(target="e1", method="exact_name")
        c2 = _candidate(target="e2", method="token_overlap", source="b.py")
        report = BridgeDetectionReport(candidates=[c1, c2])
        result = BridgeReconciler(report).reconcile()
        assert result.stats.get("exact_name") == 1
        assert result.stats.get("token_overlap") == 1

    def test_missing_candidates_attr(self):
        """Report object without .candidates returns empty result."""
        result = BridgeReconciler(object()).reconcile()
        assert len(result.accepted) == 0


class TestReconciliationReport:
    def test_default_construction(self):
        r = ReconciliationReport()
        assert r.accepted == []
        assert r.merged == []
        assert r.stats == {}
