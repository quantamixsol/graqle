# tests/test_workflow/test_loop_observer.py
"""
Tests for LoopObserver — transparency, cost tracking, and violation reporting.

Covers:
- State transition recording and callbacks
- LLM cost and latency tracking
- Violation detection and auto-correction
- Governance score computation
- Summary report generation
- Progress formatting for CLI
- Edge cases (empty observer, no violations)
"""
from __future__ import annotations

import json
import time
import pytest

from graqle.workflow.loop_observer import (
    IterationMetrics,
    LoopObserver,
    Violation,
    ViolationType,
)


# ============================================================================
# State Transition Recording (6 tests)
# ============================================================================


class TestTransitionRecording:
    """Record and query state transitions."""

    def test_record_single_transition(self):
        """Record one transition creates one iteration."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.finalize()
        summary = obs.summary()
        assert summary["total_iterations"] == 1

    def test_record_multiple_transitions(self):
        """Multiple transitions create multiple iterations."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.record_transition("GENERATE", "WRITE", attempt=0)
        obs.record_transition("WRITE", "TEST", attempt=0)
        obs.finalize()
        summary = obs.summary()
        assert summary["total_iterations"] == 3

    def test_transition_records_attempt(self):
        """Transitions record the attempt number."""
        obs = LoopObserver()
        obs.record_transition("RED:FIX", "GENERATE", attempt=2)
        obs.finalize()
        assert obs.summary()["iterations"][0]["attempt"] == 2

    def test_state_change_callback_called(self):
        """Registered callback is called on transition."""
        called_with = []

        def callback(from_s, to_s, attempt, meta):
            called_with.append((from_s, to_s, attempt))

        obs = LoopObserver()
        obs.on_state_change = callback
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        assert len(called_with) == 1
        assert called_with[0] == ("PLAN", "GENERATE", 0)

    def test_callback_error_does_not_crash(self):
        """Callback exception is caught, doesn't crash observer."""
        def bad_callback(f, t, a, m):
            raise RuntimeError("callback error")

        obs = LoopObserver()
        obs.on_state_change = bad_callback
        # Should not raise
        obs.record_transition("PLAN", "GENERATE", attempt=0)

    def test_transition_with_metadata(self):
        """Metadata is passed to callback."""
        received = []

        def callback(f, t, a, meta):
            received.append(meta)

        obs = LoopObserver()
        obs.on_state_change = callback
        obs.record_transition("PLAN", "GENERATE", attempt=0, metadata={"key": "val"})
        assert received[0] == {"key": "val"}


# ============================================================================
# Cost and Latency Tracking (5 tests)
# ============================================================================


class TestCostTracking:
    """LLM cost and latency tracking."""

    def test_record_llm_call(self):
        """LLM calls are counted per iteration."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.record_llm_call(tokens=500, cost_usd=0.001)
        obs.record_llm_call(tokens=300, cost_usd=0.0005)
        obs.finalize()
        summary = obs.summary()
        assert summary["total_llm_calls"] == 2

    def test_total_cost_accumulated(self):
        """Total cost sums across iterations."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.record_llm_call(tokens=1000, cost_usd=0.01)
        obs.record_transition("GENERATE", "WRITE", attempt=0)
        obs.record_llm_call(tokens=500, cost_usd=0.005)
        obs.finalize()
        assert obs.total_cost_usd == pytest.approx(0.015)

    def test_zero_cost_when_no_calls(self):
        """No LLM calls means zero cost."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.finalize()
        assert obs.total_cost_usd == 0.0

    def test_duration_tracked(self):
        """Duration per iteration is tracked."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        time.sleep(0.01)  # tiny delay
        obs.finalize()
        assert obs.total_duration_seconds > 0

    def test_test_result_recorded(self):
        """Test results are captured per iteration."""
        obs = LoopObserver()
        obs.record_transition("WRITE", "TEST", attempt=0)
        obs.record_test_result(tests_run=10, tests_passed=8, tests_failed=2)
        obs.finalize()
        it = obs.summary()["iterations"][0]
        assert it["tests_run"] == 10
        assert it["tests_passed"] == 8
        assert it["tests_failed"] == 2


# ============================================================================
# Violation Tracking (8 tests)
# ============================================================================


class TestViolationTracking:
    """Governance violation detection and self-correction."""

    def test_record_violation(self):
        """Record a single violation."""
        obs = LoopObserver()
        v = obs.record_violation(
            ViolationType.SKIPPED_PREFLIGHT,
            "Preflight was skipped for speed",
        )
        assert v.violation_type == ViolationType.SKIPPED_PREFLIGHT
        assert len(obs.violations) == 1

    def test_violation_auto_corrected(self):
        """Auto-corrected violation is marked."""
        obs = LoopObserver()
        v = obs.record_violation(
            ViolationType.EXCEEDED_BUDGET,
            "Budget exceeded by $0.05",
            auto_corrected=True,
            correction_action="Reduced max_rounds from 5 to 3",
        )
        assert v.auto_corrected is True
        assert v.correction_action != ""

    def test_violation_severity_levels(self):
        """Violations support WARN, ERROR, CRITICAL severity."""
        obs = LoopObserver()
        obs.record_violation(ViolationType.STALE_KG, "KG stale", severity="WARN")
        obs.record_violation(ViolationType.BYPASSED_GATE, "Gate bypassed", severity="ERROR")
        obs.record_violation(ViolationType.MODIFIED_PROTECTED_FILE, "IP file", severity="CRITICAL")
        assert len(obs.violations) == 3
        assert obs.violations[0].severity == "WARN"
        assert obs.violations[1].severity == "ERROR"
        assert obs.violations[2].severity == "CRITICAL"

    def test_violations_list_is_copy(self):
        """violations property returns a copy."""
        obs = LoopObserver()
        obs.record_violation(ViolationType.STALE_KG, "test")
        v = obs.violations
        v.clear()
        assert len(obs.violations) == 1  # internal not affected

    def test_violation_to_dict(self):
        """Violation.to_dict() is JSON-serializable."""
        v = Violation(
            violation_type=ViolationType.EXCEEDED_TIMEOUT,
            description="Test timed out after 300s",
            auto_corrected=True,
            correction_action="Reduced timeout to 120s",
        )
        d = v.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        assert d["type"] == "EXCEEDED_TIMEOUT"

    def test_all_violation_types_exist(self):
        """All expected violation types are defined."""
        expected = {
            "SKIPPED_PREFLIGHT", "SKIPPED_REVIEW", "EXCEEDED_BUDGET",
            "EXCEEDED_TIMEOUT", "MODIFIED_PROTECTED_FILE", "BYPASSED_GATE",
            "STALE_KG",
        }
        actual = {v.value for v in ViolationType}
        assert actual == expected

    def test_no_violations_summary(self):
        """Summary with no violations shows clean state."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GREEN:DONE", attempt=0)
        obs.finalize()
        summary = obs.summary()
        assert summary["violations"]["total"] == 0
        assert summary["violations"]["uncorrected"] == 0

    def test_mixed_violations_counted(self):
        """Auto-corrected and uncorrected are counted separately."""
        obs = LoopObserver()
        obs.record_violation(ViolationType.STALE_KG, "stale", auto_corrected=True)
        obs.record_violation(ViolationType.EXCEEDED_BUDGET, "over", auto_corrected=False)
        obs.record_violation(ViolationType.SKIPPED_REVIEW, "skip", auto_corrected=True)
        summary = obs.summary()
        assert summary["violations"]["total"] == 3
        assert summary["violations"]["auto_corrected"] == 2
        assert summary["violations"]["uncorrected"] == 1


# ============================================================================
# Governance Score (5 tests)
# ============================================================================


class TestGovernanceScore:
    """Governance compliance scoring."""

    def test_perfect_score_no_violations(self):
        """No violations = 100% governance score."""
        obs = LoopObserver()
        obs.finalize()
        assert obs.summary()["governance_score"] == 100.0

    def test_warn_deducts_10(self):
        """WARN violation deducts 10 points."""
        obs = LoopObserver()
        obs.record_violation(ViolationType.STALE_KG, "stale", severity="WARN")
        score = obs.summary()["governance_score"]
        assert score == 90.0

    def test_error_deducts_25(self):
        """ERROR violation deducts 25 points."""
        obs = LoopObserver()
        obs.record_violation(ViolationType.BYPASSED_GATE, "bypassed", severity="ERROR")
        score = obs.summary()["governance_score"]
        assert score == 75.0

    def test_auto_corrected_half_deduction(self):
        """Auto-corrected violation gets 50% reduction in deduction."""
        obs = LoopObserver()
        obs.record_violation(
            ViolationType.STALE_KG, "stale", severity="WARN",
            auto_corrected=True,
        )
        score = obs.summary()["governance_score"]
        assert score == 95.0  # 100 - (10 * 0.5)

    def test_score_never_below_zero(self):
        """Score is clamped at 0, never negative."""
        obs = LoopObserver()
        for _ in range(20):
            obs.record_violation(
                ViolationType.MODIFIED_PROTECTED_FILE, "ip file",
                severity="CRITICAL",
            )
        score = obs.summary()["governance_score"]
        assert score == 0.0


# ============================================================================
# Summary and Progress (4 tests)
# ============================================================================


class TestSummaryAndProgress:
    """Summary report and progress formatting."""

    def test_summary_json_serializable(self):
        """Full summary is JSON-serializable."""
        obs = LoopObserver()
        obs.record_transition("PLAN", "GENERATE", attempt=0)
        obs.record_llm_call(tokens=100, cost_usd=0.001)
        obs.record_violation(ViolationType.STALE_KG, "test")
        obs.finalize()
        serialized = json.dumps(obs.summary())
        assert isinstance(serialized, str)

    def test_summary_has_session_duration(self):
        """Summary includes total session duration."""
        obs = LoopObserver()
        obs.finalize()
        assert "session_duration_seconds" in obs.summary()
        assert obs.summary()["session_duration_seconds"] >= 0

    def test_format_progress(self):
        """format_progress returns a readable string."""
        obs = LoopObserver()
        line = obs.format_progress("TEST", attempt=2)
        assert "TEST" in line
        assert "2" in line

    def test_empty_observer_summary(self):
        """Empty observer produces valid summary."""
        obs = LoopObserver()
        summary = obs.summary()
        assert summary["total_iterations"] == 0
        assert summary["total_cost_usd"] == 0
        assert summary["governance_score"] == 100.0


# ============================================================================
# IterationMetrics (2 tests)
# ============================================================================


class TestIterationMetrics:
    """IterationMetrics dataclass."""

    def test_to_dict_keys(self):
        """to_dict has all expected fields."""
        m = IterationMetrics(
            attempt=1, state_from="GENERATE", state_to="WRITE",
            duration_seconds=1.5, llm_calls=2, tokens_used=1000,
        )
        d = m.to_dict()
        assert "transition" in d
        assert d["transition"] == "GENERATE -> WRITE"
        assert d["llm_calls"] == 2

    def test_to_dict_json_serializable(self):
        """IterationMetrics.to_dict() is JSON-serializable."""
        m = IterationMetrics(attempt=0, state_from="A", state_to="B")
        serialized = json.dumps(m.to_dict())
        assert isinstance(serialized, str)
