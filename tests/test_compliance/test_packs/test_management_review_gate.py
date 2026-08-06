"""Tests for graqle.compliance.management_review_gate (CR-010.R3).

Two jobs:
  1. Verify the new SOX-vocabulary gate behaves correctly.
  2. Verify — as regression — that the live Article 14 EU AI Act surface is
     completely UNCHANGED (AC-5). That second job is the point of the CR's
     additive design and must fail loudly if anyone later "unifies" the two.
"""

from __future__ import annotations

import dataclasses

import pytest

from graqle.compliance.article_14_gate import (
    ARTICLE_14_CLAUSES,
    Article14GateResult,
    DEFAULT_HUMAN_REVIEW_THRESHOLD,
    THRESHOLD_STATUS_CALIBRATED,
    THRESHOLD_STATUS_PLACEHOLDER,
    check_article_14_human_review,
)
from graqle.compliance.management_review_gate import (
    DEFAULT_MANAGEMENT_REVIEW_THRESHOLD,
    MANAGEMENT_REVIEW_ERROR_CODE,
    ManagementReviewGateResult,
    check_management_review,
)


class TestArming:
    def test_disarmed_allows_regardless_of_confidence(self):
        result = check_management_review(confidence=0.01)
        assert result.allowed is True
        assert result.reason == ""

    def test_armed_below_threshold_refuses(self):
        result = check_management_review(
            confidence=0.10, management_review_required=True
        )
        assert result.allowed is False
        assert "below threshold" in result.reason

    def test_armed_above_threshold_allows(self):
        result = check_management_review(
            confidence=0.99, management_review_required=True
        )
        assert result.allowed is True

    def test_confidence_exactly_at_threshold_allows(self):
        # Matches the Article 14 rule: refusal fires strictly below.
        result = check_management_review(
            confidence=0.75, management_review_required=True, threshold=0.75
        )
        assert result.allowed is True

    def test_just_below_threshold_refuses(self):
        result = check_management_review(
            confidence=0.749, management_review_required=True, threshold=0.75
        )
        assert result.allowed is False

    def test_no_env_var_arming_path(self, monkeypatch):
        # SOX applicability is a property of the control, not of a global
        # deployment mode — the EU env var must NOT arm this gate.
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "1")
        result = check_management_review(confidence=0.01)
        assert result.allowed is True


class TestRefusalEnvelope:
    def test_envelope_shape(self):
        result = check_management_review(
            confidence=0.10,
            management_review_required=True,
            control_id="FCC-1042",
        )
        env = result.to_refusal_envelope()
        assert env["success"] is False
        assert env["error_code"] == MANAGEMENT_REVIEW_ERROR_CODE
        assert env["error_code"] == "MANAGEMENT_REVIEW_REQUIRED"
        assert env["control_id"] == "FCC-1042"
        assert env["control_vocabulary"] == "management_review"
        assert env["next_action"] == "present_to_management_reviewer"
        assert env["threshold_status"] == THRESHOLD_STATUS_PLACEHOLDER

    def test_control_id_omitted_when_absent(self):
        result = check_management_review(
            confidence=0.10, management_review_required=True
        )
        assert "control_id" not in result.to_refusal_envelope()

    def test_envelope_on_allowed_result_raises(self):
        result = check_management_review(confidence=0.99)
        with pytest.raises(RuntimeError, match="allowed gate result"):
            result.to_refusal_envelope()

    def test_control_id_appears_in_reason(self):
        result = check_management_review(
            confidence=0.10,
            management_review_required=True,
            control_id="REV-7781",
        )
        assert "REV-7781" in result.reason


class TestValidation:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
    def test_invalid_confidence_raises(self, bad):
        with pytest.raises(ValueError):
            check_management_review(confidence=bad, management_review_required=True)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
    def test_invalid_threshold_raises(self, bad):
        with pytest.raises(ValueError):
            check_management_review(
                confidence=0.5, management_review_required=True, threshold=bad
            )


class TestThresholdStatus:
    def test_default_is_placeholder(self):
        # Assert the MARKER, never the float — so wiring calibration later
        # cannot silently pass a stale expectation.
        result = check_management_review(confidence=0.9)
        assert result.threshold_status == THRESHOLD_STATUS_PLACEHOLDER

    def test_calibrated_marker_propagates(self):
        result = check_management_review(
            confidence=0.9, threshold_status=THRESHOLD_STATUS_CALIBRATED
        )
        assert result.threshold_status == THRESHOLD_STATUS_CALIBRATED

    def test_default_threshold_aliases_article_14(self):
        # One placeholder value, one place to replace.
        assert DEFAULT_MANAGEMENT_REVIEW_THRESHOLD == DEFAULT_HUMAN_REVIEW_THRESHOLD


class TestImmutability:
    def test_result_is_frozen(self):
        result = check_management_review(confidence=0.9)
        with pytest.raises(Exception):
            result.allowed = False  # type: ignore[misc]


class TestArticle14ContractUnchanged:
    """AC-5 regression: the live EU AI Act surface must not move.

    These tests exist to fail if anyone later "unifies" the two gates by
    renaming fields or generalising the error code. Four production
    consumers pin this contract: mcp_dev_server.py (3 sites) and
    switch_status.py.
    """

    def test_error_code_string_unchanged(self):
        result = check_article_14_human_review(
            confidence=0.10, human_review_required=True
        )
        assert result.to_refusal_envelope()["error_code"] == (
            "ARTICLE_14_HUMAN_REVIEW_REQUIRED"
        )

    def test_default_threshold_value_unchanged(self):
        assert DEFAULT_HUMAN_REVIEW_THRESHOLD == 0.75

    def test_field_names_and_order_unchanged(self):
        names = [f.name for f in dataclasses.fields(Article14GateResult)]
        assert names == [
            "allowed",
            "confidence",
            "threshold",
            "threshold_status",
            "reason",
        ]

    def test_clauses_unchanged(self):
        assert ARTICLE_14_CLAUSES == ("14(4)(c)", "14(4)(d)")

    def test_next_action_unchanged(self):
        result = check_article_14_human_review(
            confidence=0.10, human_review_required=True
        )
        env = result.to_refusal_envelope()
        assert env["next_action"] == "present_diff_to_human_reviewer"

    def test_two_gates_are_distinct_types(self):
        # Not an alias of one another — a SOX refusal must never be mistaken
        # for an EU AI Act refusal by an isinstance check.
        assert ManagementReviewGateResult is not Article14GateResult

    def test_error_codes_are_distinct(self):
        sox = check_management_review(
            confidence=0.10, management_review_required=True
        ).to_refusal_envelope()
        eu = check_article_14_human_review(
            confidence=0.10, human_review_required=True
        ).to_refusal_envelope()
        assert sox["error_code"] != eu["error_code"]

    def test_switch_status_probe_envelope_unchanged(self):
        from graqle.compliance.switch_status import _probe_article_14_gate

        probe = _probe_article_14_gate()
        assert probe["default_threshold"] == 0.75
        assert probe["refusal_error_code"] == "ARTICLE_14_HUMAN_REVIEW_REQUIRED"


class TestGateHelperContract:
    """Sentinel F-1 (PARTIALLY VALID): pin the cross-module helper coupling.

    The SOX gate reuses three validation helpers that live in
    ``article_14_gate`` under underscore-prefixed names, which carry no
    stability contract. ``graqle.compliance._gate_helpers`` re-exports them
    under public names so callers are insulated from the private spelling,
    and these tests make a rename fail HERE — as a named test failure —
    rather than as an ImportError at process start, which was the actual
    problem worth fixing.
    """

    def test_public_helper_names_resolve(self):
        from graqle.compliance import _gate_helpers

        for name in ("coerce_arming_flag", "validate_confidence", "validate_threshold"):
            assert callable(getattr(_gate_helpers, name)), name

    def test_helpers_are_the_article_14_implementations(self):
        # Same objects — shared logic, not a divergent copy that could drift.
        from graqle.compliance import _gate_helpers, article_14_gate

        assert _gate_helpers.coerce_arming_flag is article_14_gate._coerce_bool
        assert _gate_helpers.validate_confidence is article_14_gate._validate_confidence
        assert _gate_helpers.validate_threshold is article_14_gate._validate_threshold

    def test_both_gates_share_validation_behaviour(self):
        # Divergent validation between the two regimes would be a
        # correctness bug, not merely a style difference.
        for bad in (float("nan"), float("inf"), -0.1, 1.1):
            with pytest.raises(ValueError):
                check_article_14_human_review(
                    confidence=bad, human_review_required=True
                )
            with pytest.raises(ValueError):
                check_management_review(
                    confidence=bad, management_review_required=True
                )

    def test_sox_gate_does_not_import_private_names_directly(self):
        import pathlib

        from graqle.compliance import management_review_gate

        text = pathlib.Path(management_review_gate.__file__).read_text(
            encoding="utf-8"
        )
        # The import block must go through _gate_helpers, not reach into
        # article_14_gate's private surface.
        assert "_coerce_bool" not in text
        assert "_validate_confidence" not in text
        assert "_validate_threshold" not in text
