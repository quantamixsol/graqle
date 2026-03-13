"""Tests for Bug 10 — metrics double-counting fix.

Verifies that:
- record_query() no longer inflates tokens_saved
- record_context_load() is the sole source of token savings
- _DEFAULT_TOKENS_WITHOUT uses the realistic value (2000)
- reduction_factor formula is correct (not inverted)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from graqle.metrics.engine import MetricsEngine, _DEFAULT_TOKENS_WITHOUT


@pytest.fixture
def engine(tmp_path: Path) -> MetricsEngine:
    """Fresh MetricsEngine writing to a temp directory."""
    return MetricsEngine(metrics_dir=tmp_path)


class TestRecordQueryDoesNotInflateTokens:
    def test_record_query_does_not_inflate_tokens(self, engine: MetricsEngine) -> None:
        """record_query must NOT add anything to tokens_saved."""
        assert engine.tokens_saved == 0
        engine.record_query("what is auth lambda?", result_tokens=500)
        engine.record_query("show me CORS lessons", result_tokens=300)
        assert engine.tokens_saved == 0
        assert engine.queries == 2


class TestRecordContextLoadTracksSavings:
    def test_record_context_load_tracks_savings(self, engine: MetricsEngine) -> None:
        """record_context_load should be the sole source of tokens_saved."""
        engine.record_context_load("auth-lambda", tokens_returned=200)
        expected = _DEFAULT_TOKENS_WITHOUT - 200
        assert engine.tokens_saved == expected
        assert engine.context_loads == 1

    def test_savings_with_custom_tokens_without(self, engine: MetricsEngine) -> None:
        """Explicit tokens_without should override the default."""
        engine.record_context_load("auth-lambda", tokens_returned=100, tokens_without=5000)
        assert engine.tokens_saved == 4900

    def test_savings_clamp_to_zero(self, engine: MetricsEngine) -> None:
        """If tokens_returned > tokens_without, savings should be 0 (not negative)."""
        engine.record_context_load("auth-lambda", tokens_returned=5000, tokens_without=2000)
        assert engine.tokens_saved == 0


class TestNoDoubleCounting:
    def test_no_double_counting(self, engine: MetricsEngine) -> None:
        """Calling both record_query and record_context_load should not double-count.

        tokens_saved must equal exactly the savings from context loads.
        """
        engine.record_query("question 1", result_tokens=400)
        engine.record_query("question 2", result_tokens=600)
        engine.record_context_load("svc-a", tokens_returned=300)
        engine.record_context_load("svc-b", tokens_returned=500)

        expected = (_DEFAULT_TOKENS_WITHOUT - 300) + (_DEFAULT_TOKENS_WITHOUT - 500)
        assert engine.tokens_saved == expected
        assert engine.queries == 2
        assert engine.context_loads == 2


class TestDefaultTokensWithoutIsRealistic:
    def test_default_tokens_without_is_realistic(self) -> None:
        """_DEFAULT_TOKENS_WITHOUT must be 2000 (realistic single-file load)."""
        assert _DEFAULT_TOKENS_WITHOUT == 2000


class TestReductionFactorFormula:
    def test_reduction_factor_formula(self, engine: MetricsEngine) -> None:
        """reduction_factor = _DEFAULT_TOKENS_WITHOUT / avg_tokens_returned.

        For 2 loads saving 1800 + 1500 = 3300 tokens total:
          avg_saved_per_load = 3300 / 2 = 1650
          avg_tokens_returned = 2000 - 1650 = 350
          reduction_factor = round(2000 / 350, 1) = 5.7
        """
        engine.record_context_load("svc-a", tokens_returned=200)   # saves 1800
        engine.record_context_load("svc-b", tokens_returned=500)   # saves 1500

        report = engine.get_roi_report()
        # Extract the reduction factor from the report string
        match = re.search(r"Reduction factor:\s+([\d.]+)x", report)
        assert match is not None, f"Could not find reduction factor in report:\n{report}"
        factor = float(match.group(1))
        assert factor == pytest.approx(5.7, abs=0.1)

    def test_reduction_factor_with_zero_loads(self, engine: MetricsEngine) -> None:
        """With 0 context loads the reduction factor must be 0 (no division by zero)."""
        report = engine.get_roi_report()
        match = re.search(r"Reduction factor:\s+([\d.]+)x", report)
        assert match is not None
        factor = float(match.group(1))
        assert factor == 0
