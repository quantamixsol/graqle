"""Tests for graqle.compliance.claim_limits.taxonomy (PR-010c)."""

from __future__ import annotations

import pytest

from graqle.compliance.claim_limits.taxonomy import (
    CANONICAL_CLAIM_LIMITS,
    CLAIM_LIMITS_TAXONOMY_VERSION,
    COMPLIANCE_SCOPE_CLAIM_LIMITS,
    DATA_SCOPE_CLAIM_LIMITS,
    DECISION_SCOPE_CLAIM_LIMITS,
    LEGACY_BACKFILL_VALUE,
    MODEL_DEPENDENCY_CLAIM_LIMITS,
    TEMPORAL_CLAIM_LIMITS,
    TRUST_BOUNDARY_CLAIM_LIMITS,
    X_PREFIX,
    is_valid_claim_limit,
    validate_claim_limits,
)


class TestVersion:
    def test_version_is_one_zero(self):
        assert CLAIM_LIMITS_TAXONOMY_VERSION == "1.0"

    def test_backfill_sentinel_is_canonical_value(self):
        assert LEGACY_BACKFILL_VALUE == "legacy_pre_R25_EU11"

    def test_x_prefix_constant(self):
        assert X_PREFIX == "x-"


class TestCategoryFrozensets:
    def test_temporal_has_two_values(self):
        assert len(TEMPORAL_CLAIM_LIMITS) == 2
        assert "knowledge_cutoff_apparent" in TEMPORAL_CLAIM_LIMITS
        assert "real_time_data_unavailable" in TEMPORAL_CLAIM_LIMITS

    def test_model_dependency_has_two_values(self):
        assert len(MODEL_DEPENDENCY_CLAIM_LIMITS) == 2

    def test_data_scope_has_four_values(self):
        assert len(DATA_SCOPE_CLAIM_LIMITS) == 4

    def test_decision_scope_has_four_values(self):
        assert len(DECISION_SCOPE_CLAIM_LIMITS) == 4
        assert "human_review_required" in DECISION_SCOPE_CLAIM_LIMITS

    def test_trust_boundary_has_two_values(self):
        assert len(TRUST_BOUNDARY_CLAIM_LIMITS) == 2

    def test_compliance_scope_has_three_values(self):
        assert len(COMPLIANCE_SCOPE_CLAIM_LIMITS) == 3
        assert "eu_ai_act_article_14_oversight" in COMPLIANCE_SCOPE_CLAIM_LIMITS

    def test_canonical_is_union_of_six_categories(self):
        assert len(CANONICAL_CLAIM_LIMITS) == 17
        union = (
            TEMPORAL_CLAIM_LIMITS
            | MODEL_DEPENDENCY_CLAIM_LIMITS
            | DATA_SCOPE_CLAIM_LIMITS
            | DECISION_SCOPE_CLAIM_LIMITS
            | TRUST_BOUNDARY_CLAIM_LIMITS
            | COMPLIANCE_SCOPE_CLAIM_LIMITS
        )
        assert CANONICAL_CLAIM_LIMITS == union

    def test_categories_are_disjoint(self):
        # No value appears in two categories — important for the taxonomy's
        # mutual-exclusivity invariant.
        seen: set[str] = set()
        for cat in (
            TEMPORAL_CLAIM_LIMITS,
            MODEL_DEPENDENCY_CLAIM_LIMITS,
            DATA_SCOPE_CLAIM_LIMITS,
            DECISION_SCOPE_CLAIM_LIMITS,
            TRUST_BOUNDARY_CLAIM_LIMITS,
            COMPLIANCE_SCOPE_CLAIM_LIMITS,
        ):
            for v in cat:
                assert v not in seen, f"{v!r} appears in two categories"
                seen.add(v)

    def test_canonical_values_are_lowercase_snake(self):
        # Auditor-friendly: every value is lowercase_snake_case.
        import re
        pat = re.compile(r"^[a-z][a-z0-9_]*$")
        for v in CANONICAL_CLAIM_LIMITS:
            assert pat.match(v), f"{v!r} is not lowercase_snake_case"


class TestIsValidClaimLimit:
    def test_canonical_value_is_valid(self):
        assert is_valid_claim_limit("not_legal_advice") is True

    def test_unknown_value_is_invalid(self):
        assert is_valid_claim_limit("foo_bar") is False

    def test_backfill_sentinel_is_invalid_for_is_valid_check(self):
        # The sentinel is invalid for new writes — `is_valid_claim_limit`
        # is the "new write" check. Backfill calls go through a separate
        # `allow_legacy_backfill=True` path on the validator.
        assert is_valid_claim_limit(LEGACY_BACKFILL_VALUE) is False

    def test_x_extension_namespace_is_valid(self):
        assert is_valid_claim_limit("x-acme-internal") is True
        assert is_valid_claim_limit("x-prod-only") is True
        assert is_valid_claim_limit("x-eu-region-locked") is True

    def test_x_extension_too_long_is_invalid(self):
        # 64-char body limit on the extension regex.
        assert is_valid_claim_limit("x-" + "a" * 65) is False

    def test_x_extension_uppercase_is_invalid(self):
        assert is_valid_claim_limit("x-AcmeInternal") is False

    def test_x_extension_with_spaces_is_invalid(self):
        assert is_valid_claim_limit("x-acme internal") is False

    def test_bare_x_is_invalid(self):
        assert is_valid_claim_limit("x-") is False

    def test_empty_string_is_invalid(self):
        assert is_valid_claim_limit("") is False

    def test_non_str_raises(self):
        with pytest.raises(TypeError):
            is_valid_claim_limit(42)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            is_valid_claim_limit(None)  # type: ignore[arg-type]


class TestValidateClaimLimits:
    def test_all_canonical_returns_empty_list(self):
        assert validate_claim_limits(["not_legal_advice", "knowledge_cutoff_apparent"]) == []

    def test_canonical_plus_extension_returns_empty(self):
        assert validate_claim_limits(["not_legal_advice", "x-acme-internal"]) == []

    def test_unknown_value_in_list(self):
        invalid = validate_claim_limits(["not_legal_advice", "unknown_value"])
        assert invalid == ["unknown_value"]

    def test_multiple_invalid_preserves_order(self):
        invalid = validate_claim_limits(["bad1", "not_legal_advice", "bad2"])
        assert invalid == ["bad1", "bad2"]

    def test_duplicate_invalid_dedupes(self):
        invalid = validate_claim_limits(["bad", "bad", "bad"])
        assert invalid == ["bad"]

    def test_empty_list_returns_empty(self):
        # validate_claim_limits doesn't enforce non-emptiness — that's
        # the caller's (validator.require_non_empty_claim_limits) job.
        assert validate_claim_limits([]) == []

    def test_non_list_raises(self):
        with pytest.raises(TypeError):
            validate_claim_limits("not_legal_advice")  # type: ignore[arg-type]

    def test_non_str_entry_raises(self):
        with pytest.raises(TypeError):
            validate_claim_limits([1, 2, 3])  # type: ignore[list-item]
