"""Tests for graqle.compliance.claim_limits.validator (PR-010c)."""

from __future__ import annotations

import pytest

from graqle.compliance.claim_limits.taxonomy import LEGACY_BACKFILL_VALUE
from graqle.compliance.claim_limits.validator import (
    ClaimLimitsValidationError,
    ClaimLimitsValidationResult,
    require_non_empty_claim_limits,
    validate_for_write,
)


class TestRequireNonEmptyClaimLimits:
    def test_valid_input_returns_copy(self):
        original = ["not_legal_advice", "knowledge_cutoff_apparent"]
        result = require_non_empty_claim_limits(original)
        assert result == original
        assert result is not original  # returns a copy

    def test_none_raises_missing(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits(None)
        assert "claim_limits_missing" in exc.value.reasons

    def test_empty_list_raises_empty(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([])
        assert "claim_limits_empty" in exc.value.reasons

    def test_non_list_raises_wrong_type(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits("not_legal_advice")  # type: ignore[arg-type]
        assert "claim_limits_wrong_type" in exc.value.reasons

    def test_non_str_entry_raises_wrong_type(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([1, 2])  # type: ignore[list-item]
        assert "claim_limits_wrong_type" in exc.value.reasons

    def test_invalid_value_raises_with_invalid_list(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits(["not_legal_advice", "foo_bar"])
        assert "claim_limits_invalid" in exc.value.reasons
        assert "foo_bar" in exc.value.invalid_values

    def test_backfill_sentinel_rejected_by_default(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([LEGACY_BACKFILL_VALUE])
        assert "claim_limits_legacy_backfill_in_new_write" in exc.value.reasons

    def test_backfill_sentinel_allowed_with_flag(self):
        # Backfill migration path: explicit opt-in
        result = require_non_empty_claim_limits(
            [LEGACY_BACKFILL_VALUE],
            allow_legacy_backfill=True,
        )
        assert result == [LEGACY_BACKFILL_VALUE]

    def test_backfill_sentinel_with_other_values_still_rejected(self):
        # Even with allow_legacy_backfill=True, the sentinel should not
        # be MIXED with other canonical values — that's a malformed
        # backfill record. Validation goes through the validate_claim_limits
        # path for the non-sentinel entries.
        with pytest.raises(ClaimLimitsValidationError):
            require_non_empty_claim_limits(
                [LEGACY_BACKFILL_VALUE, "foo_bar"],
                allow_legacy_backfill=True,
            )

    def test_extension_namespace_accepted(self):
        result = require_non_empty_claim_limits(
            ["x-acme-internal", "not_legal_advice"]
        )
        assert "x-acme-internal" in result

    def test_field_name_in_error_message(self):
        with pytest.raises(ClaimLimitsValidationError) as exc:
            require_non_empty_claim_limits([], field_name="my_field")
        assert "my_field" in str(exc.value)


class TestValidateForWrite:
    def test_valid_returns_ok(self):
        result = validate_for_write(["not_legal_advice"])
        assert isinstance(result, ClaimLimitsValidationResult)
        assert result.ok is True
        assert result.reasons == []

    def test_invalid_returns_not_ok(self):
        result = validate_for_write([])
        assert result.ok is False
        assert "claim_limits_empty" in result.reasons

    def test_invalid_values_populated(self):
        result = validate_for_write(["not_legal_advice", "bad_value"])
        assert result.ok is False
        assert "bad_value" in result.invalid_values

    def test_taxonomy_version_present(self):
        result = validate_for_write(["not_legal_advice"])
        assert result.taxonomy_version == "1.0"

    def test_none_input_returns_not_ok(self):
        result = validate_for_write(None)
        assert result.ok is False
        assert "claim_limits_missing" in result.reasons

    def test_non_list_input_returns_not_ok(self):
        result = validate_for_write("not_legal_advice")
        assert result.ok is False
        assert "claim_limits_wrong_type" in result.reasons


class TestErrorAttributes:
    def test_reasons_defaults_to_empty_list(self):
        err = ClaimLimitsValidationError("msg")
        assert err.reasons == []
        assert err.invalid_values == []

    def test_reasons_passed_through(self):
        err = ClaimLimitsValidationError(
            "msg",
            reasons=["claim_limits_empty"],
            invalid_values=["x"],
        )
        assert err.reasons == ["claim_limits_empty"]
        assert err.invalid_values == ["x"]
