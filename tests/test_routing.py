"""Tests for graqle.routing — task-based model routing."""

# ── graqle:intelligence ──
# module: tests.test_routing
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, os, mock, pytest, routing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
from unittest.mock import patch

from graqle.routing import (
    MCP_TOOL_TO_TASK,
    TASK_RECOMMENDATIONS,
    RoutingRule,
    TaskRouter,
)


class TestTaskRecommendations:
    def test_all_task_types_have_required_keys(self):
        required = {"description", "recommended_traits", "suggested_providers", "suggested_reason"}
        for task, rec in TASK_RECOMMENDATIONS.items():
            missing = required - set(rec.keys())
            assert not missing, f"Task '{task}' missing keys: {missing}"

    def test_known_task_types_exist(self):
        # v0.38.0 Phase 7: +profile = 20 total
        expected = {
            "context", "reason", "preflight", "impact", "lessons", "learn",
            "code", "docs", "predict",
            "generate", "edit", "read", "write", "grep", "glob", "bash", "git",
            "test", "plan", "profile",
        }
        assert expected == set(TASK_RECOMMENDATIONS.keys())

    def test_all_have_suggested_providers(self):
        for task, rec in TASK_RECOMMENDATIONS.items():
            assert len(rec["suggested_providers"]) > 0, f"Task '{task}' has no providers"


class TestMCPToolToTask:
    def test_graq_tools_mapped(self):
        assert MCP_TOOL_TO_TASK["graq_reason"] == "reason"
        assert MCP_TOOL_TO_TASK["graq_context"] == "context"
        assert MCP_TOOL_TO_TASK["graq_preflight"] == "preflight"
        # graq_predict added in v0.35.0
        assert MCP_TOOL_TO_TASK["graq_predict"] == "predict"

    def test_kogni_tools_mapped(self):
        assert MCP_TOOL_TO_TASK["kogni_reason"] == "reason"
        assert MCP_TOOL_TO_TASK["kogni_learn"] == "learn"
        # kogni_predict added in v0.35.0
        assert MCP_TOOL_TO_TASK["kogni_predict"] == "predict"


class TestRoutingRule:
    def test_to_dict_minimal(self):
        rule = RoutingRule(task="reason", provider="groq")
        d = rule.to_dict()
        assert d["task"] == "reason"
        assert d["provider"] == "groq"
        assert "model" not in d
        assert "reason" not in d

    def test_to_dict_full(self):
        rule = RoutingRule(task="context", provider="gemini", model="gemini-2.0-flash", reason="fast")
        d = rule.to_dict()
        assert d["model"] == "gemini-2.0-flash"
        assert d["reason"] == "fast"

    def test_from_dict(self):
        rule = RoutingRule.from_dict({"task": "learn", "provider": "anthropic", "model": "claude-haiku-4-5-20251001"})
        assert rule.task == "learn"
        assert rule.provider == "anthropic"
        assert rule.model == "claude-haiku-4-5-20251001"

    def test_from_dict_minimal(self):
        rule = RoutingRule.from_dict({"task": "impact", "provider": "groq"})
        assert rule.model is None
        assert rule.reason == ""


class TestTaskRouter:
    def test_empty_router(self):
        router = TaskRouter()
        assert router.get_rule_for_task("reason") is None
        assert router.get_backend_for_task("reason") is None

    def test_from_config_none(self):
        router = TaskRouter.from_config(None)
        assert len(router.rules) == 0

    def test_from_config_with_rules(self):
        config = {
            "default_provider": "groq",
            "default_model": "llama-3.1-8b-instant",
            "rules": [
                {"task": "reason", "provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
                {"task": "context", "provider": "groq"},
            ],
        }
        router = TaskRouter.from_config(config)
        assert router.default_provider == "groq"
        assert router.default_model == "llama-3.1-8b-instant"
        assert len(router.rules) == 2
        assert router.get_rule_for_task("reason").provider == "anthropic"
        assert router.get_rule_for_task("context").provider == "groq"

    def test_add_rule(self):
        router = TaskRouter()
        rule = RoutingRule(task="code", provider="deepseek", model="deepseek-chat")
        router.add_rule(rule)
        assert router.get_rule_for_task("code") is rule

    def test_get_task_from_mcp_tool(self):
        router = TaskRouter()
        assert router.get_task_from_mcp_tool("graq_reason") == "reason"
        assert router.get_task_from_mcp_tool("kogni_context") == "context"
        assert router.get_task_from_mcp_tool("unknown_tool") == "reason"  # default

    def test_recommend_known_task(self):
        router = TaskRouter()
        rec = router.recommend("reason")
        assert rec is not None
        assert rec["task"] == "reason"
        assert "suggested_providers" in rec
        assert rec["current_rule"] is None

    def test_recommend_with_existing_rule(self):
        router = TaskRouter()
        router.add_rule(RoutingRule(task="reason", provider="anthropic"))
        rec = router.recommend("reason")
        assert rec["current_rule"] is not None
        assert rec["current_rule"]["provider"] == "anthropic"

    def test_recommend_unknown_task(self):
        router = TaskRouter()
        assert router.recommend("nonexistent") is None

    def test_recommend_all(self):
        router = TaskRouter()
        recs = router.recommend_all()
        assert len(recs) == 20  # v0.38.0 Phase 7: 19 + profile = 20

    def test_recommend_shows_available_providers(self):
        router = TaskRouter()
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False):
            rec = router.recommend("context")
        available_providers = [p["provider"] for p in rec["available_providers"]]
        assert "groq" in available_providers

    def test_to_config_empty(self):
        router = TaskRouter()
        assert router.to_config() == {}

    def test_to_config_with_rules(self):
        router = TaskRouter(default_provider="groq")
        router.add_rule(RoutingRule(task="reason", provider="anthropic"))
        config = router.to_config()
        assert config["default_provider"] == "groq"
        assert len(config["rules"]) == 1
        assert config["rules"][0]["task"] == "reason"

    def test_get_backend_for_task_with_default_provider(self):
        """When no specific rule exists but default_provider is set,
        the router should try creating a backend from the default provider."""
        router = TaskRouter(default_provider="groq", default_model="llama-3.1-8b-instant")
        # Will fail because no API key, but validates the code path
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False):
            backend = router.get_backend_for_task("docs")
        # Should return a CustomBackend from the default provider
        assert backend is not None

    def test_get_backend_gemini_rule(self):
        """Gemini rules should create a GeminiBackend."""
        router = TaskRouter()
        router.add_rule(RoutingRule(task="docs", provider="gemini", model="gemini-2.0-flash"))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            backend = router.get_backend_for_task("docs")
        assert backend is not None
        assert "gemini" in backend.name

    def test_get_backend_native_provider_returns_none(self):
        """Anthropic returns None when no ANTHROPIC_API_KEY is set."""
        router = TaskRouter()
        router.add_rule(RoutingRule(task="reason", provider="anthropic"))
        # Use patch.dict to reliably remove the key for this test
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            backend = router.get_backend_for_task("reason")
        assert backend is None


class TestRoutingConfig:
    def test_default_routing_config(self):
        from graqle.config.settings import RoutingConfig
        config = RoutingConfig()
        assert config.default_provider is None
        assert config.default_model is None
        assert config.rules == []

    def test_routing_config_with_rules(self):
        from graqle.config.settings import RoutingConfig, RoutingRuleConfig
        config = RoutingConfig(
            default_provider="groq",
            rules=[
                RoutingRuleConfig(task="reason", provider="anthropic", model="claude-haiku-4-5-20251001"),
            ],
        )
        assert config.default_provider == "groq"
        assert len(config.rules) == 1
        assert config.rules[0].task == "reason"

    def test_routing_in_graqle_config(self):
        from graqle.config.settings import GraqleConfig
        config = GraqleConfig()
        assert config.routing is not None
        assert config.routing.default_provider is None
        assert config.routing.rules == []

    def test_routing_from_yaml_dict(self):
        from graqle.config.settings import GraqleConfig
        config = GraqleConfig.model_validate({
            "routing": {
                "default_provider": "deepseek",
                "rules": [
                    {"task": "context", "provider": "groq", "model": "llama-3.1-8b-instant"},
                ],
            },
        })
        assert config.routing.default_provider == "deepseek"
        assert len(config.routing.rules) == 1
        assert config.routing.rules[0].provider == "groq"


# ---------------------------------------------------------------------------
# Phase 6 — Bedrock routing validation (FB-006)
# ---------------------------------------------------------------------------

class TestBedrockRoutingValidation:
    """FB-006: Bedrock routing rules must specify region and profile.

    Without these fields, routing silently sends requests to the wrong AWS
    account with no error. Validation must fail at config load time.
    """

    def test_bedrock_rule_without_region_raises(self):
        """RoutingRule with provider=bedrock and no region raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="region"):
            RoutingRule(task="predict", provider="bedrock", profile="default")

    def test_bedrock_rule_without_profile_raises(self):
        """RoutingRule with provider=bedrock and no profile raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="profile"):
            RoutingRule(task="predict", provider="bedrock", region="eu-central-1")

    def test_bedrock_rule_with_both_fields_succeeds(self):
        """RoutingRule with provider=bedrock, region, and profile is valid."""
        rule = RoutingRule(
            task="predict",
            provider="bedrock",
            region="eu-central-1",
            profile="default",
        )
        assert rule.region == "eu-central-1"
        assert rule.profile == "default"

    def test_non_bedrock_rule_without_region_succeeds(self):
        """Non-Bedrock rules don't require region or profile."""
        rule = RoutingRule(task="reason", provider="anthropic", model="claude-sonnet-4-6")
        assert rule.region is None
        assert rule.profile is None

    def test_bedrock_routing_rule_config_without_region_raises(self):
        """RoutingRuleConfig (Pydantic) with provider=bedrock and no region raises."""
        import pytest
        from pydantic import ValidationError
        from graqle.config.settings import RoutingRuleConfig
        with pytest.raises(ValidationError):
            RoutingRuleConfig(task="predict", provider="bedrock", profile="default")

    def test_bedrock_routing_rule_config_with_both_fields_succeeds(self):
        """RoutingRuleConfig with all required Bedrock fields is valid."""
        from graqle.config.settings import RoutingRuleConfig
        rule = RoutingRuleConfig(
            task="predict",
            provider="bedrock",
            region="eu-central-1",
            profile="default",
        )
        assert rule.region == "eu-central-1"
