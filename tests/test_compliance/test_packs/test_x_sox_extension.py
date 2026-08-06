"""Tests for graqle.pct.extensions.x_sox (CR-010.R3).

Covers the typed x-sox bootstrap: round-tripping, the pseudonym discipline,
conditional-field enforcement, and the reporting-period constraints.
"""

from __future__ import annotations

import pytest

from graqle.pct.extensions.x_sox import (
    PSEUDONYM_OMITTED,
    X_SOX_NAMESPACE,
    XSoxExtension,
    is_pseudonym_token,
)

# A valid 64-char lowercase-hex token (HMAC-SHA256 shaped).
TOKEN_A = "a" * 64
TOKEN_B = "b3f1" + "0" * 60


def _minimal(**overrides):
    """Build a minimally-valid extension, with optional overrides."""
    kwargs = {
        "control_id": "FCC-1042",
        "assertion": "completeness",
        "reporting_period_start": "2026-07-01",
        "reporting_period_end": "2026-09-30",
        "management_review_status": "not_required",
    }
    kwargs.update(overrides)
    return XSoxExtension(**kwargs)


class TestNamespace:
    def test_namespace_constant(self):
        assert X_SOX_NAMESPACE == "x-sox"

    def test_emitted_keys_are_all_namespaced(self):
        ext = _minimal()
        emitted = ext.to_pct_extension_dict()
        assert emitted, "expected a non-empty payload"
        for key in emitted:
            assert key.startswith("x-sox:"), key


class TestRoundTrip:
    def test_round_trip_is_lossless(self):
        original = _minimal(
            control_framework="coso_2013",
            fiscal_period_label="FY2026-Q3",
            preparer_token=TOKEN_A,
            reviewer_token=TOKEN_B,
            management_review_status="completed",
            management_review_ref="https://audit.example/reviews/9912",
            control_operating_effectiveness="effective",
            icfr_scope=True,
            policy_version="c" * 64,
        )
        restored = XSoxExtension.from_pct_extension_dict(
            original.to_pct_extension_dict()
        )
        assert restored == original

    def test_minimal_round_trip(self):
        original = _minimal()
        restored = XSoxExtension.from_pct_extension_dict(
            original.to_pct_extension_dict()
        )
        assert restored == original

    def test_none_fields_are_omitted(self):
        emitted = _minimal().to_pct_extension_dict()
        assert "x-sox:control_framework" not in emitted
        assert "x-sox:icfr_scope" not in emitted

    def test_omit_sentinel_is_emitted_not_dropped(self):
        # "the operator chose not to name a preparer" is audit-relevant and
        # must survive serialisation — it is not the same as "absent".
        emitted = _minimal().to_pct_extension_dict()
        assert emitted["x-sox:preparer_token"] == PSEUDONYM_OMITTED

    def test_false_and_zero_are_emitted_not_skipped(self):
        """Sentinel F-2 (REFUTED): only None/empty-list are skipped.

        A falsy-but-present value must survive. `icfr_scope=False` means
        "explicitly out of ICFR scope", which an auditor must be able to
        distinguish from "never assessed". The skip predicate is
        `value is None`, deliberately NOT `if value`.
        """
        emitted = _minimal(icfr_scope=False).to_pct_extension_dict()
        assert emitted["x-sox:icfr_scope"] is False
        restored = XSoxExtension.from_pct_extension_dict(emitted)
        assert restored.icfr_scope is False

    def test_explicit_none_survives_round_trip(self):
        """Sentinel F-4 (REFUTED): from_ filters by key, never by value."""
        payload = _minimal().to_pct_extension_dict()
        payload["x-sox:management_review_ref"] = None
        restored = XSoxExtension.from_pct_extension_dict(payload)
        assert restored.management_review_ref is None

    def test_foreign_and_unknown_keys_ignored(self):
        payload = _minimal().to_pct_extension_dict()
        payload["x-ai-eu:article_6_classification"] = "non_high_risk"
        payload["x-sox:some_future_field"] = "ignored"
        restored = XSoxExtension.from_pct_extension_dict(payload)
        assert restored == _minimal()

    def test_missing_required_field_raises_value_error(self):
        # Callers parsing untrusted payloads get ONE exception type.
        with pytest.raises(ValueError):
            XSoxExtension.from_pct_extension_dict({"x-sox:control_id": "FCC-1"})


class TestControlBinding:
    """AC-2: bind a decision to a named control and a reporting period."""

    def test_binds_named_control_and_period(self):
        emitted = _minimal(control_id="REV-7781").to_pct_extension_dict()
        assert emitted["x-sox:control_id"] == "REV-7781"
        assert emitted["x-sox:reporting_period_start"] == "2026-07-01"
        assert emitted["x-sox:reporting_period_end"] == "2026-09-30"

    @pytest.mark.parametrize("bad", ["", "   ", "\t", "\n"])
    def test_empty_control_id_rejected(self, bad):
        with pytest.raises(ValueError, match="control_id"):
            _minimal(control_id=bad)

    def test_non_string_control_id_rejected(self):
        with pytest.raises(TypeError):
            _minimal(control_id=1042)


class TestReportingPeriod:
    @pytest.mark.parametrize(
        "bad",
        [
            "2026-7-1",          # not zero-padded
            "07/01/2026",        # wrong format
            "2026-07-01T00:00Z", # timestamp, not a date
            "",
            "not-a-date",
            "20260701",
        ],
    )
    def test_malformed_dates_rejected(self, bad):
        with pytest.raises(ValueError, match="ISO-8601"):
            _minimal(reporting_period_start=bad)

    @pytest.mark.parametrize(
        "bad",
        [
            "2026-13-45",  # month 13, day 45
            "2026-99-99",
            "2026-00-10",  # month 0
            "2026-02-30",  # Feb 30 never exists
            "2025-02-29",  # 2025 is not a leap year
            "2026-04-31",  # April has 30 days
        ],
    )
    def test_calendar_impossible_dates_rejected(self, bad):
        """Sentinel F-3 (CONFIRMED): the regex checks shape, not calendar.

        Without date.fromisoformat() these pass validation and get signed
        into an audit record carrying a nonsensical reporting period.
        """
        with pytest.raises(ValueError, match="not a real calendar date"):
            _minimal(reporting_period_start=bad, reporting_period_end="2026-12-31")

    def test_leap_day_accepted_in_leap_year(self):
        ext = _minimal(
            reporting_period_start="2028-02-29",
            reporting_period_end="2028-03-31",
        )
        assert ext.reporting_period_start == "2028-02-29"

    def test_inverted_period_rejected(self):
        with pytest.raises(ValueError, match="must not precede"):
            _minimal(
                reporting_period_start="2026-09-30",
                reporting_period_end="2026-07-01",
            )

    def test_single_day_period_allowed(self):
        ext = _minimal(
            reporting_period_start="2026-07-01",
            reporting_period_end="2026-07-01",
        )
        assert ext.reporting_period_end == "2026-07-01"


class TestPseudonymDiscipline:
    """AC-4: raw identifiers must never reach an audit artifact."""

    def test_valid_token_accepted(self):
        assert is_pseudonym_token(TOKEN_A)
        assert is_pseudonym_token(PSEUDONYM_OMITTED)

    @pytest.mark.parametrize(
        "raw",
        [
            "jane.doe@example.com",       # email
            "Jane Doe",                   # display name
            "EMP-00417",                  # employee ID
            "550e8400-e29b-41d4-a716-446655440000",  # UUID
            "a" * 63,                     # one char short
            "a" * 65,                     # one char long
            "A" * 64,                     # uppercase hex
            "g" * 64,                     # non-hex chars
            "",                           # empty
            "   ",                        # whitespace
            "omitted",                    # near-miss on the sentinel
            "OMIT",                       # wrong case sentinel
        ],
    )
    def test_raw_identifiers_rejected(self, raw):
        assert is_pseudonym_token(raw) is False
        with pytest.raises(ValueError, match="prohibited|HMAC-SHA256"):
            _minimal(preparer_token=raw)
        with pytest.raises(ValueError, match="prohibited|HMAC-SHA256"):
            _minimal(reviewer_token=raw)

    def test_non_string_token_rejected(self):
        with pytest.raises(TypeError):
            is_pseudonym_token(12345)
        with pytest.raises(TypeError):
            _minimal(preparer_token=None)

    def test_segregation_of_duties_checkable_without_identities(self):
        # An auditor can compare tokens without learning who they are.
        ext = _minimal(preparer_token=TOKEN_A, reviewer_token=TOKEN_B)
        assert ext.preparer_token != ext.reviewer_token


class TestManagementReviewLinkage:
    @pytest.mark.parametrize("status", ["completed", "waived_with_reason"])
    def test_ref_required_when_review_asserted(self, status):
        with pytest.raises(ValueError, match="management_review_ref"):
            _minimal(management_review_status=status)

    @pytest.mark.parametrize("status", ["completed", "waived_with_reason"])
    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_blank_ref_treated_as_missing(self, status, blank):
        with pytest.raises(ValueError, match="management_review_ref"):
            _minimal(management_review_status=status, management_review_ref=blank)

    @pytest.mark.parametrize("status", ["not_required", "pending"])
    def test_ref_not_required_otherwise(self, status):
        ext = _minimal(management_review_status=status)
        assert ext.management_review_ref is None

    def test_ref_accepted_when_provided(self):
        ext = _minimal(
            management_review_status="completed",
            management_review_ref="https://audit.example/r/1",
        )
        assert ext.management_review_ref == "https://audit.example/r/1"


class TestImmutability:
    def test_frozen(self):
        ext = _minimal()
        with pytest.raises(Exception):
            ext.control_id = "OTHER"  # type: ignore[misc]
