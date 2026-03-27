"""Task-based model routing — match tasks to the right model.

Users teach GraQle routing rules that map task types and entity types
to specific backends. The router recommends models based on user
preferences, never auto-switches without explicit configuration.

Task types correspond to MCP tool names and reasoning patterns:
    - "context"    — fast lookups, entity summaries
    - "reason"     — multi-hop reasoning, deep analysis
    - "preflight"  — safety checks, lesson retrieval
    - "impact"     — dependency tracing, blast radius
    - "lessons"    — mistake patterns, past failures
    - "learn"      — knowledge ingestion, graph updates
    - "code"       — code analysis, function understanding
    - "docs"       — document understanding, spec reading

Usage:
    from graqle.routing import TaskRouter

    router = TaskRouter.from_config(config.routing)
    backend = router.get_backend_for_task("reason")
    recommendations = router.recommend("What depends on auth?")
"""

# ── graqle:intelligence ──
# module: graqle.routing
# risk: LOW (impact radius: 1 modules)
# consumers: test_routing
# dependencies: __future__, logging, os, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.routing")

# ---------------------------------------------------------------------------
# Default recommendations — sensible starting point, user can override
# ---------------------------------------------------------------------------

TASK_RECOMMENDATIONS: dict[str, dict[str, Any]] = {
    "context": {
        "description": "Fast entity lookups and summaries",
        "recommended_traits": ["fast", "cheap"],
        "suggested_providers": ["groq", "gemini", "deepseek"],
        "suggested_reason": "Context queries are simple lookups — fast and cheap models work great.",
    },
    "reason": {
        "description": "Multi-hop reasoning across graph nodes",
        "recommended_traits": ["smart", "thorough"],
        "suggested_providers": ["anthropic", "openai", "deepseek"],
        "suggested_reason": "Reasoning requires strong multi-step logic — use your best model.",
    },
    "preflight": {
        "description": "Safety checks and lesson retrieval",
        "recommended_traits": ["reliable", "thorough"],
        "suggested_providers": ["anthropic", "mistral", "deepseek"],
        "suggested_reason": "Preflight checks catch mistakes — reliability matters more than speed.",
    },
    "impact": {
        "description": "Dependency tracing and blast radius analysis",
        "recommended_traits": ["fast", "structured"],
        "suggested_providers": ["groq", "together", "fireworks"],
        "suggested_reason": "Impact analysis is structured traversal — fast models are fine.",
    },
    "lessons": {
        "description": "Past mistake patterns and failure retrieval",
        "recommended_traits": ["cheap", "fast"],
        "suggested_providers": ["groq", "gemini", "deepseek"],
        "suggested_reason": "Lesson lookups are simple retrieval — save expensive models for reasoning.",
    },
    "learn": {
        "description": "Knowledge ingestion and entity extraction",
        "recommended_traits": ["smart", "structured"],
        "suggested_providers": ["anthropic", "deepseek", "mistral"],
        "suggested_reason": "Learning requires accurate entity extraction — use a capable model.",
    },
    "code": {
        "description": "Code analysis and function understanding",
        "recommended_traits": ["code-aware", "fast"],
        "suggested_providers": ["deepseek", "groq", "fireworks"],
        "suggested_reason": "Code tasks benefit from code-trained models at fast inference.",
    },
    "docs": {
        "description": "Document understanding and spec reading",
        "recommended_traits": ["long-context", "thorough"],
        "suggested_providers": ["gemini", "anthropic", "together"],
        "suggested_reason": "Document tasks need long context windows — Gemini and Claude excel here.",
    },
    "predict": {
        "description": "Governed prediction with confidence-gated graph write-back",
        "recommended_traits": ["smart", "thorough"],
        "suggested_providers": ["anthropic", "openai", "deepseek"],
        "suggested_reason": "Predictions require strong reasoning to meet confidence threshold before writing to graph.",
    },
    # v0.38.0: coding assistant task types
    "generate": {
        "description": "Governed code generation — unified diff via graph context",
        "recommended_traits": ["code-aware", "smart"],
        "suggested_providers": ["anthropic", "deepseek", "openai"],
        "suggested_reason": "Code generation requires strong reasoning + code understanding — use best available model.",
    },
    "edit": {
        "description": "Apply a code diff to a file with safety checks",
        "recommended_traits": ["code-aware", "reliable"],
        "suggested_providers": ["anthropic", "deepseek", "openai"],
        "suggested_reason": "Edit operations mutate files — reliability and code awareness are critical.",
    },
    "read": {
        "description": "Read file contents with optional line range",
        "recommended_traits": ["fast", "cheap"],
        "suggested_providers": ["groq", "gemini", "deepseek"],
        "suggested_reason": "File reads are deterministic I/O — any model can handle them.",
    },
    "write": {
        "description": "Atomically write or overwrite a file",
        "recommended_traits": ["reliable"],
        "suggested_providers": ["anthropic", "deepseek"],
        "suggested_reason": "File writes are destructive — prefer reliable models for content generation.",
    },
    "grep": {
        "description": "Search file contents by regex pattern across the codebase",
        "recommended_traits": ["fast", "cheap"],
        "suggested_providers": ["groq", "gemini", "deepseek"],
        "suggested_reason": "Grep is deterministic pattern matching — no LLM needed, any model works for wrapping.",
    },
    "glob": {
        "description": "Find files by glob pattern",
        "recommended_traits": ["fast", "cheap"],
        "suggested_providers": ["groq", "gemini", "deepseek"],
        "suggested_reason": "Glob is deterministic filesystem traversal — fast and cheap.",
    },
    "bash": {
        "description": "Execute a governed shell command with allowlist and timeout",
        "recommended_traits": ["reliable", "safe"],
        "suggested_providers": ["anthropic", "deepseek"],
        "suggested_reason": "Shell execution is high-risk — use reliable models for command construction.",
    },
    "git": {
        "description": "Git workflow operations (status, diff, log, commit, branch)",
        "recommended_traits": ["reliable", "code-aware"],
        "suggested_providers": ["anthropic", "deepseek", "openai"],
        "suggested_reason": "Git operations affect version history — use reliable, code-aware models.",
    },
    # v0.38.0 Phase 5
    "test": {
        "description": "Test execution, result parsing, and coverage metrics collection",
        "recommended_traits": ["fast", "reliable"],
        "suggested_providers": ["groq", "deepseek", "anthropic"],
        "suggested_reason": "Test execution is deterministic subprocess I/O — fast models work for orchestration.",
    },
    # v0.38.0 Phase 6
    "plan": {
        "description": "Goal decomposition into governance-gated DAG execution plans with impact analysis",
        "recommended_traits": ["reasoning", "code-aware", "reliable"],
        "suggested_providers": ["anthropic", "openai", "deepseek"],
        "suggested_reason": "Planning requires deep graph reasoning and dependency understanding — use strong reasoning models.",
    },
    # v0.38.0 Phase 7
    "profile": {
        "description": "Reasoning performance profiling: per-step latency, token cost, confidence measurement",
        "recommended_traits": ["fast", "reliable"],
        "suggested_providers": ["groq", "anthropic", "deepseek"],
        "suggested_reason": "Profiling runs the reasoning pipeline — fast models reduce profiling overhead.",
    },
}

# Map MCP tool names to task types
MCP_TOOL_TO_TASK: dict[str, str] = {
    "graq_context": "context",
    "graq_reason": "reason",
    "graq_preflight": "preflight",
    "graq_impact": "impact",
    "graq_lessons": "lessons",
    "graq_learn": "learn",
    "graq_predict": "predict",
    # v0.38.0: coding assistant tools
    "graq_generate": "generate",
    "graq_edit": "edit",
    "graq_read": "read",
    "graq_write": "write",
    "graq_grep": "grep",
    "graq_glob": "glob",
    "graq_bash": "bash",
    "graq_git_status": "git",
    "graq_git_diff": "git",
    "graq_git_log": "git",
    "graq_git_commit": "git",
    "graq_git_branch": "git",
    # v0.38.0 Phase 4: compound workflow tools
    "graq_review": "code",
    "graq_debug": "code",
    "graq_scaffold": "generate",
    "graq_workflow": "code",
    # v0.38.0 Phase 5: test execution
    "graq_test": "test",
    # kogni_* aliases
    "kogni_context": "context",
    "kogni_reason": "reason",
    "kogni_preflight": "preflight",
    "kogni_impact": "impact",
    "kogni_lessons": "lessons",
    "kogni_learn": "learn",
    "kogni_predict": "predict",
    "kogni_generate": "generate",
    "kogni_edit": "edit",
    "kogni_read": "read",
    "kogni_write": "write",
    "kogni_grep": "grep",
    "kogni_glob": "glob",
    "kogni_bash": "bash",
    "kogni_git_status": "git",
    "kogni_git_diff": "git",
    "kogni_git_log": "git",
    "kogni_git_commit": "git",
    "kogni_git_branch": "git",
    # Phase 4: compound workflow aliases
    "kogni_review": "code",
    "kogni_debug": "code",
    "kogni_scaffold": "generate",
    "kogni_workflow": "code",
    # Phase 5: test execution alias
    "kogni_test": "test",
    # Phase 6: agent planning
    "graq_plan": "plan",
    "kogni_plan": "plan",
    # Phase 7: performance profiling
    "graq_profile": "profile",
    "kogni_profile": "profile",
    # Phase 10: governance gate (writes GOVERNANCE_BYPASS KG nodes)
    "graq_gov_gate": "gate",
    "kogni_gov_gate": "gate",
}


@dataclass
class RoutingRule:
    """A user-defined routing rule mapping a task type to a backend."""

    task: str
    provider: str
    model: str | None = None
    reason: str = ""
    region: str | None = None
    profile: str | None = None

    def __post_init__(self) -> None:
        """FB-006: Bedrock rules must specify region and profile.

        Fails at rule creation time so misconfiguration is caught before any
        API call is made — not silently mid-request.
        """
        if self.provider == "bedrock":
            if not self.region:
                raise ValueError(
                    f"Bedrock routing rule for task '{self.task}' requires 'region'. "
                    "Set the AWS region (e.g. 'eu-central-1')."
                )
            if not self.profile:
                raise ValueError(
                    f"Bedrock routing rule for task '{self.task}' requires 'profile'. "
                    "Set the AWS profile name (e.g. 'default')."
                )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"task": self.task, "provider": self.provider}
        if self.model:
            d["model"] = self.model
        if self.reason:
            d["reason"] = self.reason
        if self.region:
            d["region"] = self.region
        if self.profile:
            d["profile"] = self.profile
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingRule:
        return cls(
            task=data["task"],
            provider=data["provider"],
            model=data.get("model"),
            reason=data.get("reason", ""),
            region=data.get("region"),
            profile=data.get("profile"),
        )


@dataclass
class TaskRouter:
    """Route tasks to backends based on user-defined rules.

    Rules are explicit — the router never auto-assigns a model
    without the user having configured a rule for that task type.
    """

    rules: dict[str, RoutingRule] = field(default_factory=dict)
    default_provider: str | None = None
    default_model: str | None = None

    @classmethod
    def from_config(cls, routing_config: dict[str, Any] | None) -> TaskRouter:
        """Create a TaskRouter from the routing section of graqle.yaml."""
        if not routing_config:
            return cls()

        rules: dict[str, RoutingRule] = {}
        for rule_data in routing_config.get("rules", []):
            rule = RoutingRule.from_dict(rule_data)
            rules[rule.task] = rule

        return cls(
            rules=rules,
            default_provider=routing_config.get("default_provider"),
            default_model=routing_config.get("default_model"),
        )

    def get_rule_for_task(self, task_type: str) -> RoutingRule | None:
        """Get the routing rule for a task type, if configured."""
        return self.rules.get(task_type)

    def get_backend_for_task(self, task_type: str) -> Any | None:
        """Create a backend instance for a task type.

        Returns None if no rule is configured — the caller should
        fall back to the default backend.
        """
        rule = self.get_rule_for_task(task_type)
        if not rule:
            # Try default provider
            if self.default_provider:
                return self._create_backend(
                    self.default_provider, self.default_model
                )
            return None

        return self._create_backend(
            rule.provider, rule.model,
            region=rule.region, profile=rule.profile,
        )

    def _create_backend(
        self,
        provider: str,
        model: str | None,
        region: str | None = None,
        profile: str | None = None,
    ) -> Any | None:
        """Create a backend from provider name."""
        try:
            if provider == "gemini":
                from graqle.backends.gemini import GeminiBackend
                return GeminiBackend(model=model or "gemini-2.0-flash")

            if provider == "bedrock":
                from graqle.backends.api import BedrockBackend
                import os
                resolved_region = (
                    region
                    or os.environ.get("AWS_DEFAULT_REGION")
                    or os.environ.get("AWS_REGION")
                    or "eu-central-1"
                )
                kwargs: dict[str, Any] = {
                    "model": model or "eu.anthropic.claude-sonnet-4-6",
                    "region": resolved_region,
                }
                if profile:
                    kwargs["profile_name"] = profile
                return BedrockBackend(**kwargs)

            if provider == "anthropic":
                import os
                from graqle.backends.api import AnthropicBackend
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if api_key:
                    return AnthropicBackend(
                        model=model or "claude-sonnet-4-6", api_key=api_key
                    )
                return None  # fall through to _auto_create_backend

            if provider == "openai":
                import os
                from graqle.backends.api import OpenAIBackend
                api_key = os.environ.get("OPENAI_API_KEY")
                if api_key:
                    return OpenAIBackend(
                        model=model or "gpt-4o", api_key=api_key
                    )
                return None

            if provider == "ollama":
                from graqle.backends.api import OllamaBackend
                return OllamaBackend(model=model or "llama3")

            from graqle.backends.providers import PROVIDER_PRESETS
            if provider in PROVIDER_PRESETS:
                from graqle.backends.providers import create_provider_backend
                return create_provider_backend(provider, model=model)

        except (ImportError, ValueError) as e:
            logger.warning("Failed to create backend for %s: %s", provider, e)

        return None

    def get_task_from_mcp_tool(self, tool_name: str) -> str:
        """Map an MCP tool name to a task type."""
        return MCP_TOOL_TO_TASK.get(tool_name, "reason")

    def recommend(self, task_type: str) -> dict[str, Any] | None:
        """Get recommendations for a task type.

        Returns recommendation info including suggested providers
        and reasoning. Does NOT auto-apply — user decides.
        """
        rec = TASK_RECOMMENDATIONS.get(task_type)
        if not rec:
            return None

        # Check which recommended providers have API keys set
        available: list[dict[str, str]] = []
        for provider in rec["suggested_providers"]:
            env_var = self._get_env_var(provider)
            if env_var and os.environ.get(env_var):
                available.append({"provider": provider, "env_var": env_var})

        # Check if user already has a rule
        existing_rule = self.get_rule_for_task(task_type)

        return {
            "task": task_type,
            "description": rec["description"],
            "traits": rec["recommended_traits"],
            "suggested_providers": rec["suggested_providers"],
            "reason": rec["suggested_reason"],
            "available_providers": available,
            "current_rule": existing_rule.to_dict() if existing_rule else None,
        }

    def recommend_all(self) -> list[dict[str, Any]]:
        """Get recommendations for all task types."""
        results = []
        for task_type in TASK_RECOMMENDATIONS:
            rec = self.recommend(task_type)
            if rec:
                results.append(rec)
        return results

    def _get_env_var(self, provider: str) -> str | None:
        """Get the env var for a provider."""
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "bedrock": "AWS_ACCESS_KEY_ID",
            "groq": "GROQ_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "together": "TOGETHER_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
            "cohere": "COHERE_API_KEY",
            "ollama": None,
        }
        return env_map.get(provider)

    def add_rule(self, rule: RoutingRule) -> None:
        """Add or update a routing rule."""
        self.rules[rule.task] = rule
        logger.info(
            "Routing rule: %s → %s%s",
            rule.task,
            rule.provider,
            f" ({rule.model})" if rule.model else "",
        )

    def to_config(self) -> dict[str, Any]:
        """Serialize to graqle.yaml format."""
        config: dict[str, Any] = {}
        if self.rules:
            config["rules"] = [r.to_dict() for r in self.rules.values()]
        if self.default_provider:
            config["default_provider"] = self.default_provider
        if self.default_model:
            config["default_model"] = self.default_model
        return config
