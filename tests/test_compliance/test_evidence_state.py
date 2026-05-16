"""Tests for graqle.compliance.evidence_state (CR-010 PR-010e — Q16.5 Layer B)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from graqle.compliance.evidence_state import (
    DRIFT_ALARM_SIGMA,
    FeedbackRecord,
    FeedbackTrend,
    WelfordAccumulator,
    _validate_record,
    append_feedback_record,
    build_feedback_trend,
    compute_drift_indicator,
    ingest_feedback_jsonl,
)


# ---------------------------------------------------------------------------
# WelfordAccumulator
# ---------------------------------------------------------------------------


class TestWelfordAccumulator:
    def test_initial_state(self):
        acc = WelfordAccumulator()
        assert acc.n == 0
        assert acc.mean == 0.0
        assert acc.stdev == 0.0

    def test_single_value(self):
        acc = WelfordAccumulator()
        acc.add(5.0)
        assert acc.n == 1
        assert acc.mean == 5.0
        assert acc.stdev == 0.0  # n<2

    def test_running_mean(self):
        acc = WelfordAccumulator()
        for x in [1, 2, 3, 4, 5]:
            acc.add(x)
        assert abs(acc.mean - 3.0) < 1e-9

    def test_running_stdev_matches_naive(self):
        """Welford should match a naive batch computation."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        acc = WelfordAccumulator()
        for x in values:
            acc.add(x)
        # Sample stdev (n-1 denominator) of [1,2,3,4,5] = sqrt(2.5) ≈ 1.5811
        expected = math.sqrt(2.5)
        assert abs(acc.stdev - expected) < 1e-9

    def test_nan_raises(self):
        acc = WelfordAccumulator()
        with pytest.raises(ValueError, match="finite"):
            acc.add(float("nan"))

    def test_inf_raises(self):
        acc = WelfordAccumulator()
        with pytest.raises(ValueError, match="finite"):
            acc.add(float("inf"))

    def test_non_numeric_raises(self):
        acc = WelfordAccumulator()
        with pytest.raises(TypeError, match="real number"):
            acc.add("not_a_number")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_drift_indicator
# ---------------------------------------------------------------------------


class TestComputeDriftIndicator:
    def test_zero_baseline_stdev_returns_none(self):
        result = compute_drift_indicator(
            current_mean=1.0,
            baseline_mean=0.0,
            baseline_stdev=0.0,
        )
        assert result is None

    def test_negative_baseline_stdev_returns_none(self):
        # Defensive: stdev should never be negative, but if it is, return None
        result = compute_drift_indicator(
            current_mean=1.0,
            baseline_mean=0.0,
            baseline_stdev=-0.5,
        )
        assert result is None

    def test_correct_z_score(self):
        """d = (M_today - M_baseline) / σ_baseline"""
        result = compute_drift_indicator(
            current_mean=3.0,
            baseline_mean=2.0,
            baseline_stdev=0.5,
        )
        assert abs(result - 2.0) < 1e-9  # (3-2)/0.5 = 2.0

    def test_negative_drift(self):
        result = compute_drift_indicator(
            current_mean=1.0,
            baseline_mean=2.0,
            baseline_stdev=0.5,
        )
        assert abs(result - (-2.0)) < 1e-9

    def test_nan_inputs_raise(self):
        with pytest.raises(ValueError, match="finite"):
            compute_drift_indicator(
                current_mean=float("nan"),
                baseline_mean=2.0,
                baseline_stdev=0.5,
            )


# ---------------------------------------------------------------------------
# FeedbackTrend builder
# ---------------------------------------------------------------------------


def _rec(rating: float, source: str = "explicit_cli", **kwargs):
    return FeedbackRecord(
        source=source,
        rating=rating,
        timestamp_iso="2026-06-15T00:00:00Z",
        **kwargs,
    )


class TestBuildFeedbackTrend:
    def test_returns_feedback_trend(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(4.0), _rec(5.0)],
        )
        assert isinstance(trend, FeedbackTrend)
        assert trend.source == "explicit_cli"

    def test_n_samples_correct(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(4.0), _rec(5.0), _rec(3.0)],
        )
        assert trend.n_samples == 3

    def test_mean_correct(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(4.0), _rec(5.0), _rec(3.0)],
        )
        assert abs(trend.mean - 4.0) < 1e-9

    def test_drift_alert_emitted_at_2_sigma(self):
        # Current mean=4.0, baseline mean=2.0, baseline_stdev=1.0
        # drift = (4-2)/1 = 2.0 -> ALERT
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(4.0)],
            baseline_mean=2.0,
            baseline_stdev=1.0,
        )
        assert trend.drift_alert_emitted is True

    def test_drift_alert_not_emitted_below_2_sigma(self):
        # drift = (3-2)/1 = 1.0 -> NO ALERT
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(3.0)],
            baseline_mean=2.0,
            baseline_stdev=1.0,
        )
        assert trend.drift_alert_emitted is False

    def test_drift_alert_not_emitted_when_baseline_stdev_zero(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(100.0)],
            baseline_mean=0.0,
            baseline_stdev=0.0,
        )
        assert trend.drift_alert_emitted is False
        assert trend.drift_indicator is None

    def test_default_window_days(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[],
        )
        assert trend.window_days == 30


class TestFeedbackTrendContentAddressing:
    def test_trend_id_is_sha256_hex(self):
        trend = build_feedback_trend(
            source="explicit_cli",
            records=[_rec(4.0)],
        )
        assert len(trend.trend_id) == 64
        int(trend.trend_id, 16)


# ---------------------------------------------------------------------------
# FeedbackRecord persistence
# ---------------------------------------------------------------------------


class TestAppendFeedbackRecord:
    def test_writes_jsonl_line(self, tmp_path):
        rec = _rec(4.0)
        out = tmp_path / "feedback.jsonl"
        append_feedback_record(rec, out)
        assert out.exists()
        line = out.read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        assert parsed["rating"] == 4.0
        assert parsed["source"] == "explicit_cli"

    def test_append_accumulates(self, tmp_path):
        out = tmp_path / "feedback.jsonl"
        append_feedback_record(_rec(4.0), out)
        append_feedback_record(_rec(5.0), out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_nan_rating_raises(self, tmp_path):
        rec = FeedbackRecord(
            source="explicit_cli",
            rating=float("nan"),
            timestamp_iso="2026-06-15T00:00:00Z",
        )
        out = tmp_path / "feedback.jsonl"
        with pytest.raises(ValueError, match="finite"):
            append_feedback_record(rec, out)

    def test_oversized_note_raises(self, tmp_path):
        rec = FeedbackRecord(
            source="explicit_cli",
            rating=4.0,
            timestamp_iso="2026-06-15T00:00:00Z",
            note="x" * 5000,  # > 4096
        )
        out = tmp_path / "feedback.jsonl"
        with pytest.raises(ValueError, match="exceeds maximum length"):
            append_feedback_record(rec, out)


class TestIngestFeedbackJsonl:
    def test_parses_valid_jsonl(self, tmp_path):
        input_file = tmp_path / "in.jsonl"
        input_file.write_text(
            json.dumps({
                "source": "external_jsonl",
                "rating": 4.5,
                "timestamp_iso": "2026-06-15T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        records = ingest_feedback_jsonl(input_file)
        assert len(records) == 1
        assert records[0].rating == 4.5

    def test_skips_empty_lines(self, tmp_path):
        input_file = tmp_path / "in.jsonl"
        input_file.write_text(
            "\n"
            + json.dumps({
                "source": "external_jsonl",
                "rating": 4.5,
                "timestamp_iso": "2026-06-15T00:00:00Z",
            }) + "\n"
            + "\n",
            encoding="utf-8",
        )
        records = ingest_feedback_jsonl(input_file)
        assert len(records) == 1

    def test_invalid_json_raises_value_error(self, tmp_path):
        input_file = tmp_path / "in.jsonl"
        input_file.write_text("not json at all\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            ingest_feedback_jsonl(input_file)

    def test_missing_required_field_raises(self, tmp_path):
        input_file = tmp_path / "in.jsonl"
        input_file.write_text(
            json.dumps({"source": "external_jsonl"}) + "\n",  # missing rating
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing/invalid fields"):
            ingest_feedback_jsonl(input_file)

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest_feedback_jsonl(tmp_path / "nonexistent.jsonl")

    def test_writes_to_output_when_supplied(self, tmp_path):
        input_file = tmp_path / "in.jsonl"
        input_file.write_text(
            json.dumps({
                "source": "external_jsonl",
                "rating": 4.5,
                "timestamp_iso": "2026-06-15T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        output = tmp_path / "feedback_log.jsonl"
        records = ingest_feedback_jsonl(input_file, output_path=output)
        assert output.exists()
        assert len(records) == 1


# ---------------------------------------------------------------------------
# OBSERVATION-ONLY invariant (companion to test_q165_no_active_recalibration_path.py)
# ---------------------------------------------------------------------------


class TestObservationOnlyInvariant:
    def test_feedback_trend_is_frozen(self):
        trend = build_feedback_trend(source="explicit_cli", records=[])
        with pytest.raises(Exception):  # FrozenInstanceError
            trend.drift_alert_emitted = True  # type: ignore[misc]

    def test_drift_alarm_sigma_is_two(self):
        assert DRIFT_ALARM_SIGMA == 2.0
