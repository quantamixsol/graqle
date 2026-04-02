"""S0 Measurement Integrity Gate — regression tests for B1/B3/B4/B5 fixes.

ADR-144: These tests certify measurement infrastructure correctness
BEFORE any calibration sprint proceeds.
"""

from __future__ import annotations

import warnings

import pytest

from graqle.core.types import CalibrationOutcome, ReasoningResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(**overrides) -> ReasoningResult:
    """Build a ReasoningResult with sane defaults, applying *overrides*."""
    defaults = dict(
        query="test query",
        answer="test answer",
        confidence=0.75,
        rounds_completed=1,
        active_nodes=["node_a"],
        message_trace=[],
        cost_usd=0.001,
        latency_ms=42.0,
    )
    defaults.update(overrides)
    return ReasoningResult(**defaults)


# ---------------------------------------------------------------------------
# B1: confidence validation
# ---------------------------------------------------------------------------

class TestConfidenceValidation:
    """B1: ReasoningResult must reject None confidence and warn on 0.0."""

    def test_confidence_none_raises(self):
        with pytest.raises(ValueError, match="confidence must not be None"):
            _make_result(confidence=None)

    def test_confidence_zero_emits_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _make_result(confidence=0.0)
            assert result.confidence == 0.0
            zero_warnings = [
                w for w in caught
                if "confidence" in str(w.message).lower()
            ]
            assert len(zero_warnings) >= 1, (
                f"Expected a warning about zero confidence, got: {caught}"
            )

    def test_confidence_normal_passes_silently(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _make_result(confidence=0.75)
            assert result.confidence == 0.75
            conf_warnings = [
                w for w in caught
                if "confidence" in str(w.message).lower()
            ]
            assert conf_warnings == [], (
                f"Unexpected confidence warnings: {conf_warnings}"
            )


# ---------------------------------------------------------------------------
# B4: cost_usd validation
# ---------------------------------------------------------------------------

class TestCostValidation:
    """B4: ReasoningResult must reject None cost_usd."""

    def test_cost_usd_none_raises(self):
        with pytest.raises(ValueError, match="cost_usd must not be None"):
            _make_result(cost_usd=None)

    def test_cost_usd_zero_is_valid(self):
        result = _make_result(cost_usd=0.0)
        assert result.cost_usd == 0.0


# ---------------------------------------------------------------------------
# B5: CalibrationOutcome enum identity & JSON-safety
# ---------------------------------------------------------------------------

class TestCalibrationOutcomeEnum:
    """B5: enum members must be distinct and str-subclassed for JSON."""

    def test_skipped_low_confidence_not_equal_dry_run(self):
        assert (
            CalibrationOutcome.SKIPPED_LOW_CONFIDENCE
            != CalibrationOutcome.DRY_RUN
        )
        assert (
            CalibrationOutcome.SKIPPED_LOW_CONFIDENCE.value
            != CalibrationOutcome.DRY_RUN.value
        )

    def test_members_are_str_subclass(self):
        for member in CalibrationOutcome:
            assert isinstance(member, str), (
                f"CalibrationOutcome.{member.name} is not a str subclass"
            )
            assert isinstance(member.value, str)

    def test_all_expected_members_exist(self):
        expected = {
            "WRITTEN", "DRY_RUN", "SKIPPED_LOW_CONFIDENCE",
            "SKIPPED_DUPLICATE", "SKIPPED_GENERATION_ERROR",
            "FAILED", "NOT_APPLICABLE",
        }
        actual = {m.name for m in CalibrationOutcome}
        assert expected == actual


# ---------------------------------------------------------------------------
# B3: reclassify_mcp module import invariant
# ---------------------------------------------------------------------------

class TestReclassifyMcpImport:
    """B3: reclassify_mcp module must import without RuntimeError."""

    def test_import_succeeds(self):
        import importlib
        importlib.import_module("graqle.scanner.reclassify_mcp")


# ---------------------------------------------------------------------------
# B1: BridgeReconciler._pick_winner with None confidence
# ---------------------------------------------------------------------------

class TestPickWinnerNoneConfidence:
    """B1: _pick_winner must handle None confidence without crashing."""

    def test_none_confidence_sorts_last(self):
        from graqle.merge.reconcile import BridgeReconciler
        from graqle.analysis.bridge import BridgeCandidate

        good = BridgeCandidate(
            source_id="good", target_id="t", relationship="BRIDGE_TO",
            confidence=0.9, method="exact_name",
        )
        # Bypass __post_init__ validation to simulate deserialized/corrupted data
        bad = object.__new__(BridgeCandidate)
        bad.source_id = "bad"
        bad.target_id = "t"
        bad.relationship = "BRIDGE_TO"
        bad.confidence = None
        bad.method = "exact_name"
        bad.language = "unknown"
        bad.metadata = {}

        winner = BridgeReconciler._pick_winner([bad, good])
        assert winner.source_id == "good"

    def test_all_none_confidence_does_not_crash(self):
        from graqle.merge.reconcile import BridgeReconciler
        from graqle.analysis.bridge import BridgeCandidate

        # Bypass __post_init__ to simulate corrupted data
        a = object.__new__(BridgeCandidate)
        a.source_id = "a"
        a.target_id = "t"
        a.relationship = "BRIDGE_TO"
        a.confidence = None
        a.method = "exact_name"
        a.language = "unknown"
        a.metadata = {}

        b = object.__new__(BridgeCandidate)
        b.source_id = "b"
        b.target_id = "t"
        b.relationship = "BRIDGE_TO"
        b.confidence = None
        b.method = "exact_name"
        b.language = "unknown"
        b.metadata = {}

        # Should not raise — just pick one deterministically
        winner = BridgeReconciler._pick_winner([a, b])
        assert winner is not None
