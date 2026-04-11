"""TB-F6 tests for graqle.chat.backend_router."""

# ── graqle:intelligence ──
# module: tests.test_chat.test_backend_router
# risk: LOW
# dependencies: pytest, graqle.chat.backend_router
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.chat.backend_router import (
    CHAT_TASK_TYPES,
    BackendProfile,
    BackendRouter,
    detect_family,
)


def test_detect_family_known_prefixes() -> None:
    assert detect_family("anthropic:claude-sonnet-4-6") == "anthropic"
    assert detect_family("openai:gpt-5.4-mini") == "openai"
    assert detect_family("bedrock:anthropic.claude") == "bedrock"
    assert detect_family("ollama:llama3") == "ollama"
    assert detect_family("gemini:1.5-pro") == "google"
    assert detect_family("groq:llama") == "groq"
    assert detect_family("deepseek:chat") == "deepseek"
    assert detect_family("mistral:large") == "mistral"
    assert detect_family("cohere:command-r") == "cohere"


def test_detect_family_unknown_returns_custom() -> None:
    assert detect_family("totally-novel-llm:xyz") == "custom"


def test_backend_profile_from_name() -> None:
    p = BackendProfile.from_name("anthropic:sonnet")
    assert p.family == "anthropic"
    assert p.supports_tool_use is True


def test_router_requires_at_least_one_profile() -> None:
    with pytest.raises(ValueError):
        BackendRouter(profiles=[])


def test_router_routes_known_task() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
        BackendProfile.from_name("openai:gpt-5.4-mini"),
    ])
    decision = router.route("chat_triage")
    assert decision.task_type == "chat_triage"
    assert decision.selected.name == "anthropic:sonnet"


def test_router_unknown_task_falls_through() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
    ])
    decision = router.route("totally_made_up_task")
    assert decision.selected.name == "anthropic:sonnet"


def test_router_minimal_polyglot_single_backend() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("ollama:llama3", supports_tool_use=False),
    ])
    assert router.is_minimal_polyglot is True
    decision = router.route("chat_reasoning")
    assert decision.minimal_polyglot_mode is True


def test_router_family_separation_with_two_families() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
        BackendProfile.from_name("openai:gpt-5.4-mini"),
    ])
    assert router.family_count == 2
    decision = router.route("chat_debate_adversary", prefer_family="openai")
    assert decision.selected.family == "openai"
    assert decision.family_separation_violated is False


def test_router_family_separation_violated_single_family() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
        BackendProfile.from_name("anthropic:opus"),
    ])
    decision = router.route("chat_debate_adversary", prefer_family="openai")
    assert decision.family_separation_violated is True
    assert "only one family" in decision.warning


def test_adversary_for_picks_different_family() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
        BackendProfile.from_name("openai:gpt-5.4-mini"),
    ])
    decision = router.adversary_for("anthropic")
    assert decision.selected.family == "openai"


def test_adversary_for_falls_back_to_same_family() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
        BackendProfile.from_name("anthropic:opus"),
    ])
    decision = router.adversary_for("anthropic")
    assert decision.selected.family == "anthropic"


def test_router_skips_non_tool_use_for_reasoning_tasks() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("ollama:llama3", supports_tool_use=False),
        BackendProfile.from_name("anthropic:sonnet"),
    ])
    decision = router.route("chat_reasoning")
    assert decision.selected.supports_tool_use is True


def test_router_to_dict() -> None:
    router = BackendRouter(profiles=[
        BackendProfile.from_name("anthropic:sonnet"),
    ])
    d = router.to_dict()
    assert "profiles" in d
    assert "families" in d
    assert d["minimal_polyglot"] is True


def test_chat_task_types_is_six() -> None:
    assert len(CHAT_TASK_TYPES) == 6
    assert "chat_triage" in CHAT_TASK_TYPES
    assert "chat_format" in CHAT_TASK_TYPES
