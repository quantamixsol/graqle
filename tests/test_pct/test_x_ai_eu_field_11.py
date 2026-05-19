"""Unit tests for cr-017 ``XAiEuExtension.policy_version`` (field 11).

Layer 1 of the cr-017 test plan. Targets the 11th field added to the
:class:`graqle.pct.extensions.x_ai_eu.XAiEuExtension` frozen dataclass:

  - ``policy_version: str | None`` (default ``None``)

This file pins the 11-field namespace contract per Research-Team v0.58.x
directive item #2 + OPSF PCT comment 4 alignment. The companion test
file :mod:`tests.test_pct.test_extension_x_ai_eu` covers the pre-cr-017
10-field surface and continues to pass; this file ADDS the 11th-field
verification.
"""

# ── graqle:intelligence ──
# module: tests.test_pct.test_x_ai_eu_field_11
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, dataclasses, graqle.pct.extensions.x_ai_eu
# constraints: pin cr-017 11-field contract
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import fields

import pytest

from graqle.pct.extensions.x_ai_eu import (
    X_AI_EU_NAMESPACE,
    XAiEuExtension,
)


# -------------------------------------------------------------------------
# LAYER 1A — field count + ordering contract
# -------------------------------------------------------------------------


class TestFieldCountAndOrdering:
    """Pin the 11-field namespace contract. Any future field addition
    must update this test count; any field removal/rename will fail it."""

    def test_field_count_is_11(self):
        assert len(fields(XAiEuExtension)) == 11

    def test_field_11_is_policy_version(self):
        fs = fields(XAiEuExtension)
        assert fs[10].name == "policy_version"

    def test_field_11_type_is_optional_str(self):
        fs = fields(XAiEuExtension)
        assert fs[10].type in ("str | None", "Optional[str]")

    def test_full_field_name_order(self):
        # Pin the EXACT field ordering. The PCT spec relies on order for
        # canonical serialisation, so a reordering is a wire-format break.
        expected = [
            "article_6_classification",
            "article_9_risk_management_ref",
            "article_12_audit_log_pointer",
            "article_13_transparency_doc_ref",
            "article_14_human_oversight_mode",
            "article_50_disclosure_mode",
            "articles_covered",
            "gpai_provider_flag",
            "annex_iii_category",
            "cr_lookup_id",
            "policy_version",
        ]
        actual = [f.name for f in fields(XAiEuExtension)]
        assert actual == expected


# -------------------------------------------------------------------------
# LAYER 1B — policy_version default + assignment behaviour
# -------------------------------------------------------------------------


class TestPolicyVersionDefaults:
    def test_default_is_none(self):
        ext = XAiEuExtension()
        assert ext.policy_version is None

    def test_explicit_sha256_value_accepted(self):
        ext = XAiEuExtension(policy_version="sha256:abc123")
        assert ext.policy_version == "sha256:abc123"

    def test_arbitrary_string_accepted(self):
        # The dataclass does not enforce the sha256: prefix at construction
        # time. Validator-side enforcement is the issuer's responsibility.
        ext = XAiEuExtension(policy_version="opaque-policy-id")
        assert ext.policy_version == "opaque-policy-id"

    def test_empty_string_stored_as_is(self):
        # Empty string is technically allowed at the dataclass layer
        # (matches the same behaviour for cr_lookup_id and other str fields).
        # Downstream serialisation MAY emit empty string; documented
        # behaviour, not a bug.
        ext = XAiEuExtension(policy_version="")
        assert ext.policy_version == ""


# -------------------------------------------------------------------------
# LAYER 1C — to_pct_extension_dict serialisation behaviour
# -------------------------------------------------------------------------


class TestPolicyVersionPctSerialisation:
    """The PCT extension dict uses ``{"x-ai-eu:<field>": <value>}`` keys.
    Pin how policy_version appears (or doesn't) in the output."""

    def test_emitted_when_value_set(self):
        ext = XAiEuExtension(policy_version="sha256:emitted")
        out = ext.to_pct_extension_dict()
        assert out["x-ai-eu:policy_version"] == "sha256:emitted"

    def test_omitted_when_none(self):
        ext = XAiEuExtension(policy_version=None)
        out = ext.to_pct_extension_dict()
        assert "x-ai-eu:policy_version" not in out

    def test_default_extension_omits_policy_version(self):
        # An XAiEuExtension() with no arguments should NOT emit
        # policy_version (default None -> skipped).
        ext = XAiEuExtension()
        out = ext.to_pct_extension_dict()
        assert "x-ai-eu:policy_version" not in out

    def test_namespace_prefix_correct(self):
        # The key must use the canonical x-ai-eu namespace prefix.
        ext = XAiEuExtension(policy_version="sha256:ns")
        out = ext.to_pct_extension_dict()
        assert any(
            k.startswith(f"{X_AI_EU_NAMESPACE}:policy_version") for k in out
        )


# -------------------------------------------------------------------------
# LAYER 1D — from_pct_extension_dict round-trip
# -------------------------------------------------------------------------


class TestPolicyVersionPctRoundtrip:
    def test_full_roundtrip_preserves_policy_version(self):
        original = XAiEuExtension(policy_version="sha256:roundtrip")
        serialised = original.to_pct_extension_dict()
        reconstructed = XAiEuExtension.from_pct_extension_dict(serialised)
        assert reconstructed.policy_version == original.policy_version

    def test_parse_extension_dict_with_only_policy_version(self):
        ext = XAiEuExtension.from_pct_extension_dict(
            {"x-ai-eu:policy_version": "sha256:standalone"}
        )
        assert ext.policy_version == "sha256:standalone"

    def test_parse_legacy_dict_without_policy_version_defaults_to_none(self):
        # Forward-compat invariant: a PCT issued by a pre-cr-017 SDK has
        # no x-ai-eu:policy_version key. Parsing must return None, not crash.
        ext = XAiEuExtension.from_pct_extension_dict(
            {"x-ai-eu:gpai_provider_flag": False}
        )
        assert ext.policy_version is None

    def test_unknown_keys_ignored_does_not_affect_policy_version(self):
        # Forward-compat: a future PCT might include unknown fields. They
        # must be silently dropped, and policy_version must still parse
        # correctly when present.
        ext = XAiEuExtension.from_pct_extension_dict(
            {
                "x-ai-eu:policy_version": "sha256:withjunk",
                "x-ai-eu:unknown_future_field": "ignored",
                "x-other-namespace:something": "also ignored",
            }
        )
        assert ext.policy_version == "sha256:withjunk"


# -------------------------------------------------------------------------
# LAYER 1E — interaction with conditional-field validators
# -------------------------------------------------------------------------


class TestPolicyVersionDoesNotInterferenceWithConditionalValidators:
    """policy_version is an independent additive field; it must not
    interact with the article_9 / annex_iii_category conditional rules."""

    def test_policy_version_does_not_trigger_high_risk_validation(self):
        # Setting policy_version alone must not require article_9_ref or
        # annex_iii_category (only article_6_classification=high_risk does).
        ext = XAiEuExtension(policy_version="sha256:safe")
        assert ext.policy_version == "sha256:safe"
        # No exception raised → validators are independent.

    def test_high_risk_classification_still_requires_article_9_even_with_policy_version(self):
        # Setting policy_version does NOT exempt high-risk classification
        # from the article_9_risk_management_ref requirement.
        with pytest.raises(ValueError, match="article_9_risk_management_ref"):
            XAiEuExtension(
                article_6_classification="annex_iii_high_risk",
                policy_version="sha256:butstillinvalid",
            )

    def test_policy_version_coexists_with_full_high_risk_setup(self):
        # A fully-specified high-risk extension can also carry policy_version.
        ext = XAiEuExtension(
            article_6_classification="annex_iii_high_risk",
            article_9_risk_management_ref="https://example.com/art9.pdf",
            annex_iii_category="biometric_identification",
            policy_version="sha256:highrisk_policy",
        )
        assert ext.policy_version == "sha256:highrisk_policy"
