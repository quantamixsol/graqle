"""Tests for graqle.cloud.plans — plan limits and monetization gating."""

from __future__ import annotations

import pytest

from graqle.cloud.plans import (
    PLAN_LIMITS,
    PLAN_PRICING,
    PlanLimits,
    check_node_limit,
    check_doc_limit,
    check_feature,
    check_team_member_limit,
    get_plan_limits,
    get_usage_summary,
)


class TestPlanLimits:
    def test_free_limits(self):
        limits = get_plan_limits("free")
        assert limits.max_nodes == 500
        assert limits.max_docs == 10
        assert not limits.cloud_sync
        assert not limits.shared_graph

    def test_pro_limits(self):
        limits = get_plan_limits("pro")
        assert limits.max_nodes == 5_000
        assert limits.max_docs == -1
        assert not limits.cloud_sync
        assert limits.semantic_linking

    def test_team_limits(self):
        limits = get_plan_limits("team")
        assert limits.max_nodes == 50_000
        assert limits.cloud_sync
        assert limits.cloud_observability
        assert limits.shared_graph
        assert limits.cross_repo

    def test_enterprise_limits(self):
        limits = get_plan_limits("enterprise")
        assert limits.max_nodes == -1  # unlimited
        assert limits.cloud_sync

    def test_unknown_plan_defaults_to_free(self):
        limits = get_plan_limits("nonexistent")
        assert limits.max_nodes == 500


class TestNodeLimitCheck:
    def test_free_under_limit(self):
        result = check_node_limit("free", 100)
        assert result.allowed

    def test_free_at_limit(self):
        result = check_node_limit("free", 500)
        assert not result.allowed
        assert result.required_plan == "pro"

    def test_pro_at_limit(self):
        result = check_node_limit("pro", 5000)
        assert not result.allowed
        assert result.required_plan == "team"

    def test_team_large_graph(self):
        result = check_node_limit("team", 30_000)
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
        assert result.required_plan == "team"

    def test_cloud_sync_team(self):
        result = check_feature("team", "cloud_sync")
        assert result.allowed

    def test_semantic_linking_free(self):
        result = check_feature("free", "semantic_linking")
        assert not result.allowed
        assert result.required_plan == "pro"

    def test_semantic_linking_pro(self):
        result = check_feature("pro", "semantic_linking")
        assert result.allowed

    def test_unknown_feature_allowed(self):
        result = check_feature("free", "nonexistent_feature")
        assert result.allowed

    def test_upgrade_hint(self):
        result = check_feature("free", "cloud_sync")
        hint = result.upgrade_hint
        assert "Team" in hint
        assert "$29/dev/mo" in hint


class TestTeamMemberLimit:
    def test_free_single_member(self):
        result = check_team_member_limit("free", 0)
        assert result.allowed

    def test_free_exceeds_limit(self):
        result = check_team_member_limit("free", 1)
        assert not result.allowed

    def test_team_unlimited(self):
        result = check_team_member_limit("team", 100)
        assert result.allowed


class TestUsageSummary:
    def test_free_summary(self):
        summary = get_usage_summary("free", {
            "node_count": 300,
            "query_count": 50,
            "doc_count": 5,
        })
        assert summary["plan"] == "free"
        assert summary["usage"]["nodes"]["current"] == 300
        assert summary["usage"]["nodes"]["limit"] == 500
        assert len(summary["upgrade_benefits"]) > 0

    def test_team_summary_no_upgrades(self):
        summary = get_usage_summary("team", {
            "node_count": 1000,
            "query_count": 100,
        })
        assert len(summary["upgrade_benefits"]) == 0

    def test_value_delivered(self):
        summary = get_usage_summary("free", {"query_count": 100})
        assert summary["value_delivered"]["queries_answered_by_graph"] == 100
        assert summary["value_delivered"]["estimated_tokens_saved"] > 0


class TestPlanPricing:
    def test_all_plans_have_pricing(self):
        for plan in PLAN_LIMITS:
            assert plan in PLAN_PRICING
            assert "price" in PLAN_PRICING[plan]
            assert "tagline" in PLAN_PRICING[plan]
