"""Tests for graqle.compliance.article_14_gate (PR-010c CG-MKT-01)."""

from __future__ import annotations

import os

import pytest

from graqle.compliance.article_14_gate import (
    ARTICLE_14_CLAUSES,
    Article14GateResult,
    DEFAULT_HUMAN_REVIEW_THRESHOLD,
    THRESHOLD_STATUS_CALIBRATED,
    THRESHOLD_STATUS_PLACEHOLDER,
    check_article_14_human_review,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Each test starts with EU AI Act mode OFF."""
    monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)


class TestConstants:
    def test_default_threshold_is_placeholder(self):
        assert DEFAULT_HUMAN_REVIEW_THRESHOLD == 0.75

    def test_clauses_are_14_4_c_and_d(self):
        assert ARTICLE_14_CLAUSES == ("14(4)(c)", "14(4)(d)")

    def test_threshold_status_constants(self):
        assert THRESHOLD_STATUS_PLACEHOLDER == "placeholder"
        assert THRESHOLD_STATUS_CALIBRATED == "calibrated"


class TestDisarmedGate:
    def test_disarmed_allows_low_confidence(self):
        """When EU AI Act mode is off and human_review_required is None/False, gate is disarmed."""
        result = check_article_14_human_review(
            confidence=0.1,  # very low — but gate is disarmed
            human_review_required=False,
        )
        assert result.allowed is True

    def test_disarmed_with_none_flag(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=None,
        )
        assert result.allowed is True

    def test_disarmed_with_empty_string_flag(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required="",
        )
        assert result.allowed is True


class TestArmedByEnvVar:
    def test_env_var_on_arms_gate(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=False,
        )
        assert result.allowed is False
        assert "14(4)(c)" in result.reason

    @pytest.mark.parametrize("val", ["on", "true", "1", "yes", "TRUE", "On"])
    def test_env_var_truthy_values_all_arm(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
        result = check_article_14_human_review(
            confidence=0.1, human_review_required=False,
        )
        assert result.allowed is False

    @pytest.mark.parametrize("val", ["off", "false", "0", "no", ""])
    def test_env_var_falsy_values_leave_disarmed(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
        result = check_article_14_human_review(
            confidence=0.1, human_review_required=False,
        )
        assert result.allowed is True


class TestArmedByFlag:
    def test_flag_true_arms_gate(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=True,
        )
        assert result.allowed is False

    @pytest.mark.parametrize("val", [True, "true", "on", "1", "yes"])
    def test_flag_truthy_values_arm(self, val):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=val,
        )
        assert result.allowed is False


class TestThresholdComparison:
    def test_at_threshold_allows(self):
        result = check_article_14_human_review(
            confidence=0.75,
            human_review_required=True,
            threshold=0.75,
        )
        assert result.allowed is True

    def test_just_below_threshold_refuses(self):
        result = check_article_14_human_review(
            confidence=0.749,
            human_review_required=True,
            threshold=0.75,
        )
        assert result.allowed is False

    def test_above_threshold_allows(self):
        result = check_article_14_human_review(
            confidence=0.95,
            human_review_required=True,
        )
        assert result.allowed is True

    def test_custom_threshold_respected(self):
        result = check_article_14_human_review(
            confidence=0.5,
            human_review_required=True,
            threshold=0.4,
        )
        assert result.allowed is True

    def test_threshold_none_falls_back_to_default(self):
        result = check_article_14_human_review(
            confidence=0.5,
            human_review_required=True,
            threshold=None,
        )
        # 0.5 < 0.75 default — refuses
        assert result.allowed is False
        assert result.threshold == DEFAULT_HUMAN_REVIEW_THRESHOLD


class TestRefusalEnvelope:
    def test_refusal_envelope_has_required_fields(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=True,
        )
        env = result.to_refusal_envelope()
        assert env["success"] is False
        assert env["error_code"] == "ARTICLE_14_HUMAN_REVIEW_REQUIRED"
        assert env["article_14_clauses"] == ["14(4)(c)", "14(4)(d)"]
        assert env["confidence"] == 0.1
        assert env["threshold"] == 0.75
        assert env["threshold_status"] == "placeholder"
        assert env["next_action"] == "present_diff_to_human_reviewer"

    def test_refusal_envelope_on_allowed_raises(self):
        result = check_article_14_human_review(
            confidence=0.9,
            human_review_required=True,
        )
        with pytest.raises(RuntimeError, match="allowed gate result"):
            result.to_refusal_envelope()

    def test_action_label_in_reason(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=True,
            action_label="auto",
        )
        assert "auto" in result.reason

    def test_calibrated_status_passed_through(self):
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=True,
            threshold_status="calibrated",
        )
        env = result.to_refusal_envelope()
        assert env["threshold_status"] == "calibrated"


class TestEdgeCases:
    def test_confidence_zero_below_any_threshold(self):
        result = check_article_14_human_review(
            confidence=0.0,
            human_review_required=True,
        )
        assert result.allowed is False

    def test_confidence_one_above_any_threshold(self):
        result = check_article_14_human_review(
            confidence=1.0,
            human_review_required=True,
        )
        assert result.allowed is True

    def test_env_var_and_flag_both_set(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        result = check_article_14_human_review(
            confidence=0.1,
            human_review_required=True,
        )
        # Either path arms the gate; outcome identical
        assert result.allowed is False


class TestInputValidationPass1:
    """Sentinel pass 1 MAJOR-2: NaN/inf/range validation on confidence + threshold."""

    def test_nan_confidence_raises(self):
        with pytest.raises(ValueError, match="finite"):
            check_article_14_human_review(
                confidence=float("nan"),
                human_review_required=True,
            )

    def test_pos_inf_confidence_raises(self):
        with pytest.raises(ValueError, match="finite"):
            check_article_14_human_review(
                confidence=float("inf"),
                human_review_required=True,
            )

    def test_neg_inf_confidence_raises(self):
        with pytest.raises(ValueError, match="finite"):
            check_article_14_human_review(
                confidence=float("-inf"),
                human_review_required=True,
            )

    def test_negative_confidence_raises(self):
        with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
            check_article_14_human_review(
                confidence=-0.1,
                human_review_required=True,
            )

    def test_above_one_confidence_raises(self):
        with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
            check_article_14_human_review(
                confidence=1.5,
                human_review_required=True,
            )

    def test_non_numeric_confidence_raises_typeerror(self):
        with pytest.raises(TypeError, match="real number"):
            check_article_14_human_review(
                confidence="not_a_number",  # type: ignore[arg-type]
                human_review_required=True,
            )

    def test_nan_threshold_raises(self):
        with pytest.raises(ValueError, match="finite"):
            check_article_14_human_review(
                confidence=0.5,
                human_review_required=True,
                threshold=float("nan"),
            )

    def test_negative_threshold_raises(self):
        with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
            check_article_14_human_review(
                confidence=0.5,
                human_review_required=True,
                threshold=-0.1,
            )

    def test_above_one_threshold_raises(self):
        with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
            check_article_14_human_review(
                confidence=0.5,
                human_review_required=True,
                threshold=1.5,
            )

    def test_validation_runs_before_armed_check(self):
        # Even when disarmed (no env var, no flag), invalid inputs raise.
        # This is intentional: callers should never pass NaN/inf, even on
        # the disarmed path, because the value flows into the result.
        with pytest.raises(ValueError):
            check_article_14_human_review(
                confidence=float("nan"),
                human_review_required=False,
            )


class TestIsEuAiActModeOnSharesAllowlistWithCoerceBool:
    """Sentinel pass 1 MINOR: shared truthy allowlist."""

    def test_is_eu_ai_act_mode_uses_coerce_bool_semantics(self, monkeypatch):
        from graqle.compliance.article_14_gate import (
            _coerce_bool,
            _is_eu_ai_act_mode_on,
        )
        # The allowlist {"1","true","yes","on"} is shared.
        for val in ["1", "true", "yes", "on", "TRUE", "  On  "]:
            monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
            assert _is_eu_ai_act_mode_on() is True
            assert _coerce_bool(val) is True
        for val in ["0", "false", "no", "off", ""]:
            monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
            assert _is_eu_ai_act_mode_on() is False
            assert _coerce_bool(val) is False
