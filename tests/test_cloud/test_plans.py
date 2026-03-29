"""Tests for graqle.cloud.plans — plan limits and monetization gating (ADR-126: 3 tiers)."""

# ── graqle:intelligence ──
# module: tests.test_cloud.test_plans
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pytest, plans
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.cloud.plans import (
    PLAN_LIMITS,
    PLAN_PRICING,
    check_doc_limit,
    check_feature,
    check_node_limit,
    check_team_member_limit,
    get_plan_limits,
    get_usage_summary,
)


class TestPlanLimits:
    def test_free_limits(self):
        limits = get_plan_limits("free")
        assert limits.max_nodes == 1_500
        assert limits.max_docs == 10
        assert not limits.cloud_sync
        assert not limits.shared_graph

    def test_pro_limits(self):
        limits = get_plan_limits("pro")
        assert limits.max_nodes == 15_000
        assert limits.max_docs == -1
        assert limits.cloud_sync           # ADR-126 override: Pro gets cloud sync
        assert limits.shared_graph         # ADR-126 override: Pro gets shared graph
        assert limits.semantic_linking
        assert limits.cloud_observability
        assert limits.cloud_metrics
        assert limits.cross_repo
        assert limits.custom_extractors
        assert limits.priority_support

    def test_enterprise_limits(self):
        limits = get_plan_limits("enterprise")
        assert limits.max_nodes == -1  # unlimited
        assert limits.cloud_sync
        assert limits.shared_graph
        assert limits.cloud_observability
        assert limits.cross_repo

    def test_unknown_plan_defaults_to_free(self):
        limits = get_plan_limits("nonexistent")
        assert limits.max_nodes == 1_500

    def test_only_three_tiers(self):
        assert set(PLAN_LIMITS.keys()) == {"free", "pro", "enterprise"}

    def test_team_tier_does_not_exist(self):
        assert "team" not in PLAN_LIMITS
        assert "team" not in PLAN_PRICING


class TestNodeLimitCheck:
    def test_free_under_limit(self):
        result = check_node_limit("free", 100)
        assert result.allowed

    def test_free_at_limit(self):
        result = check_node_limit("free", 1_500)
        assert not result.allowed
        assert result.required_plan == "pro"

    def test_pro_at_limit(self):
        result = check_node_limit("pro", 15_000)
        assert not result.allowed
        assert result.required_plan == "enterprise"

    def test_pro_under_limit(self):
        result = check_node_limit("pro", 10_000)
        assert result.allowed

    def test_enterprise_unlimited(self):
        result = check_node_limit("enterprise", 100_000)
        assert result.allowed


class TestDocLimitCheck:
    def test_free_under_limit(self):
        result = check_doc_limit("free", 5)
        assert result.allowed

    def test_free_at_limit(self):
        result = check_doc_limit("free", 10)
        assert not result.allowed

    def test_pro_unlimited(self):
        result = check_doc_limit("pro", 1000)
        assert result.allowed


class TestFeatureCheck:
    def test_cloud_sync_free(self):
        result = check_feature("free", "cloud_sync")
        assert not result.allowed
        assert result.required_plan == "pro"

    def test_cloud_sync_pro(self):
        result = check_feature("pro", "cloud_sync")
        assert result.allowed

    def test_cloud_sync_enterprise(self):
        result = check_feature("enterprise", "cloud_sync")
        assert result.allowed

    def test_semantic_linking_free(self):
        result = check_feature("free", "semantic_linking")
        assert not result.allowed
        assert result.required_plan == "pro"

    def test_semantic_linking_pro(self):
        result = check_feature("pro", "semantic_linking")
        assert result.allowed

    def test_shared_graph_requires_enterprise(self):
        result = check_feature("pro", "shared_graph")
        assert result.allowed  # ADR-126 override: Pro gets shared graph

    def test_cloud_observability_pro(self):
        result = check_feature("pro", "cloud_observability")
        assert result.allowed

    def test_cross_repo_pro(self):
        result = check_feature("pro", "cross_repo")
        assert result.allowed

    def test_unknown_feature_allowed(self):
        result = check_feature("free", "nonexistent_feature")
        assert result.allowed

    def test_upgrade_hint(self):
        result = check_feature("free", "cloud_sync")
        hint = result.upgrade_hint
        assert "Pro" in hint  # ADR-126: cloud_sync is now a Pro feature
        assert "$19/mo" in hint


class TestTeamMemberLimit:
    def test_free_single_member(self):
        result = check_team_member_limit("free", 0)
        assert result.allowed

    def test_free_exceeds_limit(self):
        result = check_team_member_limit("free", 1)
        assert not result.allowed
        assert result.required_plan == "enterprise"

    def test_enterprise_unlimited(self):
        result = check_team_member_limit("enterprise", 100)
        assert result.allowed

    def test_pro_single_member_only(self):
        result = check_team_member_limit("pro", 1)
        assert not result.allowed
        assert result.required_plan == "enterprise"


class TestUsageSummary:
    def test_free_summary(self):
        summary = get_usage_summary("free", {
            "node_count": 1200,
            "query_count": 50,
            "doc_count": 5,
        })
        assert summary["plan"] == "free"
        assert summary["usage"]["nodes"]["current"] == 1200
        assert summary["usage"]["nodes"]["limit"] == 1_500
        assert len(summary["upgrade_benefits"]) > 0

    def test_enterprise_summary_no_upgrades(self):
        summary = get_usage_summary("enterprise", {
            "node_count": 1000,
            "query_count": 100,
        })
        assert len(summary["upgrade_benefits"]) == 0

    def test_value_delivered(self):
        summary = get_usage_summary("free", {"query_count": 100})
        assert summary["value_delivered"]["queries_answered_by_graph"] == 100
        assert summary["value_delivered"]["estimated_context_saved"] > 0


class TestPlanPricing:
    def test_all_plans_have_pricing(self):
        for plan in PLAN_LIMITS:
            assert plan in PLAN_PRICING
            assert "price" in PLAN_PRICING[plan]
            assert "tagline" in PLAN_PRICING[plan]

    def test_exactly_three_pricing_tiers(self):
        assert len(PLAN_PRICING) == 3
