"""Tests for graqle.pct.extensions.x_ai_eu (CR-010 PR-010b-1)."""

from __future__ import annotations

import pytest

from graqle.pct.extensions.x_ai_eu import (
    X_AI_EU_NAMESPACE,
    XAiEuExtension,
)


class TestNamespaceConstant:
    def test_namespace_is_canonical(self):
        assert X_AI_EU_NAMESPACE == "x-ai-eu"


class TestEmptyExtensionAllowed:
    def test_all_fields_none_emits_empty_dict(self):
        ext = XAiEuExtension()
        out = ext.to_pct_extension_dict()
        # gpai_provider_flag defaults False (a non-None value);
        # articles_covered defaults [] (empty list — skipped per
        # to_pct_extension_dict()). So the only emitted key is the
        # gpai_provider_flag entry.
        assert out == {"x-ai-eu:gpai_provider_flag": False}


class TestArticlesCoveredEmitted:
    def test_articles_covered_serialised_when_non_empty(self):
        ext = XAiEuExtension(articles_covered=["4", "12", "50"])
        out = ext.to_pct_extension_dict()
        assert out["x-ai-eu:articles_covered"] == ["4", "12", "50"]

    def test_empty_articles_covered_skipped(self):
        ext = XAiEuExtension(articles_covered=[])
        out = ext.to_pct_extension_dict()
        assert "x-ai-eu:articles_covered" not in out


class TestConditionalFieldEnforcement:
    def test_annex_iii_high_risk_requires_article_9_ref(self):
        with pytest.raises(ValueError, match="article_9_risk_management_ref"):
            XAiEuExtension(article_6_classification="annex_iii_high_risk")

    def test_annex_i_high_risk_requires_article_9_ref(self):
        with pytest.raises(ValueError, match="article_9_risk_management_ref"):
            XAiEuExtension(article_6_classification="annex_i_high_risk")

    def test_annex_iii_requires_category_too(self):
        with pytest.raises(ValueError, match="annex_iii_category"):
            XAiEuExtension(
                article_6_classification="annex_iii_high_risk",
                article_9_risk_management_ref="https://example.com/art9.pdf",
            )

    def test_annex_iii_with_all_required_fields_valid(self):
        ext = XAiEuExtension(
            article_6_classification="annex_iii_high_risk",
            article_9_risk_management_ref="https://example.com/art9.pdf",
            annex_iii_category="employment",
        )
        out = ext.to_pct_extension_dict()
        assert out["x-ai-eu:article_6_classification"] == "annex_iii_high_risk"
        assert (
            out["x-ai-eu:article_9_risk_management_ref"]
            == "https://example.com/art9.pdf"
        )
        assert out["x-ai-eu:annex_iii_category"] == "employment"

    def test_non_high_risk_does_not_require_article_9(self):
        # Should NOT raise
        ext = XAiEuExtension(article_6_classification="non_high_risk")
        assert ext.article_6_classification == "non_high_risk"

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n", "  \n  "])
    def test_empty_or_whitespace_article_9_ref_treated_as_missing(self, blank):
        # MINOR-C4 sentinel pass 4 fix — empty/whitespace strings must
        # not pass the conditional-field check for high-risk
        # classification.
        with pytest.raises(ValueError, match="article_9_risk_management_ref"):
            XAiEuExtension(
                article_6_classification="annex_i_high_risk",
                article_9_risk_management_ref=blank,
            )


class TestRoundTrip:
    def test_to_dict_and_from_dict_round_trip(self):
        original = XAiEuExtension(
            article_6_classification="annex_iii_high_risk",
            article_9_risk_management_ref="https://example.com/art9.pdf",
            article_12_audit_log_pointer="https://example.com/audit.jsonl",
            article_13_transparency_doc_ref="https://example.com/transparency.md",
            article_14_human_oversight_mode="gated",
            article_50_disclosure_mode="auto_banner",
            articles_covered=["4", "12", "13", "14", "15", "25", "50"],
            gpai_provider_flag=False,
            annex_iii_category="employment",
            cr_lookup_id="CR-2026-EU-0001",
        )
        ext_dict = original.to_pct_extension_dict()
        recovered = XAiEuExtension.from_pct_extension_dict(ext_dict)
        assert recovered == original

    def test_unknown_keys_ignored(self):
        ext_dict = {
            "x-ai-eu:articles_covered": ["4"],
            "x-ai-eu:unknown_future_field": "ignored_silently",
            "x-other-ns:field": "also_ignored",
        }
        ext = XAiEuExtension.from_pct_extension_dict(ext_dict)
        assert ext.articles_covered == ["4"]


class TestDisclosureModeValues:
    @pytest.mark.parametrize(
        "mode",
        ["auto_banner", "machine_only", "suppress_with_logged_reason"],
    )
    def test_disclosure_mode_accepts_canonical_values(self, mode):
        ext = XAiEuExtension(article_50_disclosure_mode=mode)
        assert ext.article_50_disclosure_mode == mode
