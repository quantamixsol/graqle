"""Tests for graqle.compliance.periodic_assessment (CR-010 PR-010e — Q16.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.compliance.periodic_assessment import (
    PeriodicAssessment,
    QualityMetrics,
    RemediationAction,
    THRESHOLD_DEGRADED_RATE,
    THRESHOLD_LOW_MEAN_CONFIDENCE,
    THRESHOLD_OUTCOME_NOT_OK_RATE,
    _iter_traces_in_window,
    _percentile,
    assess_window,
    compute_quality_metrics,
    compute_remediation_actions,
    to_jsonl,
)


def _trace(ts: str, **kwargs):
    """Minimal trace shim."""
    return {"timestamp_iso": ts, **kwargs}


class TestConstants:
    def test_threshold_outcome_not_ok_rate(self):
        assert THRESHOLD_OUTCOME_NOT_OK_RATE == 0.02

    def test_threshold_degraded_rate(self):
        assert THRESHOLD_DEGRADED_RATE == 0.05

    def test_threshold_low_mean_confidence(self):
        assert THRESHOLD_LOW_MEAN_CONFIDENCE == 0.6


class TestWindowFilter:
    def test_inclusive_lower_exclusive_upper(self):
        traces = [
            _trace("2026-06-01T00:00:00Z"),
            _trace("2026-06-15T00:00:00Z"),
            _trace("2026-07-01T00:00:00Z"),  # exclusive boundary — excluded
        ]
        filtered = _iter_traces_in_window(
            traces, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        assert len(filtered) == 2

    def test_skips_traces_missing_timestamp(self):
        traces = [{"outcome": "OK"}, _trace("2026-06-15T00:00:00Z")]
        filtered = _iter_traces_in_window(
            traces, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        assert len(filtered) == 1

    def test_supports_generated_at_iso_alias(self):
        traces = [{"generated_at_iso": "2026-06-15T00:00:00Z"}]
        filtered = _iter_traces_in_window(
            traces, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        assert len(filtered) == 1


class TestPercentile:
    def test_empty_list_returns_zero(self):
        assert _percentile([], 0.95) == 0.0

    def test_single_value(self):
        assert _percentile([0.5], 0.95) == 0.5

    def test_p95_of_uniform_distribution(self):
        vals = [i / 100 for i in range(101)]  # 0.00..1.00 step 0.01
        p95 = _percentile(vals, 0.95)
        assert abs(p95 - 0.95) < 0.01


class TestQualityMetrics:
    def test_empty_traces(self):
        q = compute_quality_metrics([])
        assert q.mean_confidence == 0.0
        assert q.p95_confidence == 0.0
        assert q.n_degraded == 0
        assert q.n_outcome_not_ok == 0
        assert q.n_governance_refusals == 0

    def test_mean_confidence(self):
        traces = [
            _trace("2026-06-01T00:00:00Z", confidence=0.8),
            _trace("2026-06-02T00:00:00Z", confidence=0.6),
            _trace("2026-06-03T00:00:00Z", confidence=0.7),
        ]
        q = compute_quality_metrics(traces)
        assert abs(q.mean_confidence - 0.7) < 1e-9

    def test_degraded_counted(self):
        traces = [
            _trace("t", graph_health={"degraded": True}),
            _trace("t", graph_health={"degraded": False}),
            _trace("t"),  # no graph_health
        ]
        q = compute_quality_metrics(traces)
        assert q.n_degraded == 1

    def test_outcome_not_ok_counted(self):
        traces = [
            _trace("t", outcome="OK"),
            _trace("t", outcome="FAILED"),
            _trace("t", outcome="BLOCKED"),
        ]
        q = compute_quality_metrics(traces)
        assert q.n_outcome_not_ok == 2

    def test_governance_refused_counted(self):
        traces = [
            _trace("t", governance={"refused": True}),
            _trace("t", governance={"refused": False}),
            _trace("t"),
        ]
        q = compute_quality_metrics(traces)
        assert q.n_governance_refusals == 1

    def test_non_dict_entries_skipped_defensively(self):
        """Sentinel pass 1 MAJOR-2: malformed feed shouldn't break aggregation."""
        traces = [
            _trace("t", confidence=0.8, outcome="OK"),
            "not_a_dict",  # type: ignore[list-item]
            None,  # type: ignore[list-item]
            _trace("t", confidence=0.6, outcome="FAILED"),
        ]
        q = compute_quality_metrics(traces)  # type: ignore[arg-type]
        assert abs(q.mean_confidence - 0.7) < 1e-9
        assert q.n_outcome_not_ok == 1

    def test_nan_inf_confidence_skipped(self):
        traces = [
            _trace("t", confidence=0.8),
            _trace("t", confidence=float("nan")),
            _trace("t", confidence=float("inf")),
            _trace("t", confidence=0.6),
        ]
        q = compute_quality_metrics(traces)
        # Only finite values contribute to mean: (0.8+0.6)/2 = 0.7
        assert abs(q.mean_confidence - 0.7) < 1e-9


class TestRemediationActions:
    def test_no_actions_when_below_thresholds(self):
        q = QualityMetrics(
            mean_confidence=0.95,
            p95_confidence=0.99,
            n_degraded=0,
            n_outcome_not_ok=0,
            n_governance_refusals=0,
        )
        actions = compute_remediation_actions(100, q)
        assert actions == ()

    def test_outcome_not_ok_high_severity(self):
        q = QualityMetrics(
            mean_confidence=0.95,
            p95_confidence=0.99,
            n_degraded=0,
            n_outcome_not_ok=5,  # 5% > 2% threshold
            n_governance_refusals=0,
        )
        actions = compute_remediation_actions(100, q)
        assert any(a.severity == "high" for a in actions)
        assert any("outcome_not_ok_rate_exceeded" == a.trigger for a in actions)

    def test_degraded_warn_severity(self):
        q = QualityMetrics(
            mean_confidence=0.95,
            p95_confidence=0.99,
            n_degraded=10,  # 10% > 5% threshold
            n_outcome_not_ok=0,
            n_governance_refusals=0,
        )
        actions = compute_remediation_actions(100, q)
        assert any(a.trigger == "degraded_graph_rate_exceeded" for a in actions)

    def test_low_mean_confidence_warn(self):
        q = QualityMetrics(
            mean_confidence=0.4,  # below 0.6 threshold
            p95_confidence=0.5,
            n_degraded=0,
            n_outcome_not_ok=0,
            n_governance_refusals=0,
        )
        actions = compute_remediation_actions(100, q)
        assert any(a.trigger == "mean_confidence_below_threshold" for a in actions)

    def test_no_actions_on_empty_window(self):
        q = QualityMetrics(
            mean_confidence=0.0,
            p95_confidence=0.0,
            n_degraded=0,
            n_outcome_not_ok=0,
            n_governance_refusals=0,
        )
        actions = compute_remediation_actions(0, q)
        # Even with mean_confidence=0.0 < 0.6, no actions on empty window
        assert actions == ()


class TestAssessWindow:
    def test_returns_periodic_assessment(self):
        result = assess_window(
            traces=[_trace("2026-06-15T00:00:00Z", confidence=0.8, outcome="OK")],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            cadence="monthly",
        )
        assert isinstance(result, PeriodicAssessment)
        assert result.n_calls == 1
        assert result.cadence == "monthly"

    def test_baseline_id_passed_through(self):
        result = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            baseline_id="abc123",
        )
        assert result.baseline_id == "abc123"

    def test_default_baseline_id_is_empty(self):
        result = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
        )
        assert result.baseline_id == ""

    def test_empty_window_returns_zero_calls(self):
        result = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
        )
        assert result.n_calls == 0
        assert result.remediation_actions == ()


class TestAssessmentId:
    """AC-Q163-7 — idempotency."""

    def test_deterministic_for_same_inputs(self):
        a1 = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            baseline_id="abc",
        )
        a2 = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            baseline_id="abc",
        )
        # Same inputs (empty traces, same window, same baseline) -> same id
        assert a1.assessment_id == a2.assessment_id

    def test_different_baseline_id_different_assessment_id(self):
        a1 = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            baseline_id="abc",
        )
        a2 = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
            baseline_id="xyz",
        )
        assert a1.assessment_id != a2.assessment_id

    def test_different_window_different_assessment_id(self):
        a1 = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
        )
        a2 = assess_window(
            traces=[],
            period_start_iso="2026-07-01T00:00:00Z",
            period_end_iso="2026-08-01T00:00:00Z",
        )
        assert a1.assessment_id != a2.assessment_id


class TestJsonlEmitter:
    def test_writes_file(self, tmp_path):
        a = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
        )
        out = tmp_path / "assessment.jsonl"
        to_jsonl(a, out)
        assert out.exists()

    def test_emitted_line_has_assessment_id(self, tmp_path):
        a = assess_window(
            traces=[],
            period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z",
        )
        out = tmp_path / "assessment.jsonl"
        to_jsonl(a, out)
        parsed = json.loads(out.read_text(encoding="utf-8").strip())
        assert "assessment_id" in parsed
        assert parsed["assessment_id"] == a.assessment_id

    def test_append_mode_accumulates(self, tmp_path):
        a1 = assess_window(traces=[], period_start_iso="2026-06-01T00:00:00Z", period_end_iso="2026-07-01T00:00:00Z")
        a2 = assess_window(traces=[], period_start_iso="2026-07-01T00:00:00Z", period_end_iso="2026-08-01T00:00:00Z")
        out = tmp_path / "assessment.jsonl"
        to_jsonl(a1, out)
        to_jsonl(a2, out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
