"""CHAT-02 Intent Hint tests (Wave 2 Phase 5).

Fast-path short-circuit on known intent_hint values:
  - echo   → echoes user message
  - status → session_id + loop count
  - clarify → clarification prompt

Unknown or non-string intent_hint values fall through to full pipeline
(back-compat). Fast-path emits NO LLM calls, NO tool executions, NO
turn_store writes. Response envelope shares canonical keys with full turn.

Covers:
  - Schema (2)
  - Fast-path response shapes (3 parametrized, per hint)
  - Payload correctness (3)
  - Back-compat fallthrough (5, parametrized on unknown/empty/non-string)
  - No-call assertions via mocks (3)
  - Contract parity (1)
  - Combined CHAT-01 + CHAT-02 (3)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from graqle.chat.mcp_handlers import (
    ChatHandlerContext,
    _KNOWN_INTENT_HINTS,
    _TURN_RESPONSE_KEYS,
    handle_chat_turn,
)


# ─────────────────────────────────────────────────────────────────────────
# Schema (2)
# ─────────────────────────────────────────────────────────────────────────


def test_schema_has_intent_hint_without_enum():
    """intent_hint is future-extensible: no enum restriction on values."""
    import graqle.plugins.mcp_dev_server as m

    tool = next(t for t in m.TOOL_DEFINITIONS if t["name"] == "graq_chat_turn")
    props = tool["inputSchema"]["properties"]
    assert "intent_hint" in props
    assert props["intent_hint"]["type"] == "string"
    assert "enum" not in props["intent_hint"]  # no enum → extensible


def test_known_intent_hints_module_constant():
    assert _KNOWN_INTENT_HINTS == ("echo", "status", "clarify")


# ─────────────────────────────────────────────────────────────────────────
# Fast-path response shapes (3 parametrized)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", ["echo", "status", "clarify"])
async def test_fast_path_response_shape(hint):
    """All known hints return envelope with canonical keys."""
    ctx = ChatHandlerContext(session_id="session-1")
    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hello",
        intent_hint=hint,
    )
    assert result["status"] == "ok"
    assert result["turn_id"] == "t1"
    assert result["state"] == "COMPLETED"
    assert result["done"] is True
    assert result["tool_executions"] == []
    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == f"chat.intent.{hint}"
    assert result["fast_path"] == hint


# ─────────────────────────────────────────────────────────────────────────
# Payload correctness (3)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_echo_payload_reflects_message():
    ctx = ChatHandlerContext(session_id="s")
    result = await handle_chat_turn(
        ctx, turn_id="t", message="hello world",
        intent_hint="echo",
    )
    assert result["events"][0]["payload"] == {"echo": "hello world"}


@pytest.mark.asyncio
async def test_status_payload_has_session_id_and_loop_count():
    ctx = ChatHandlerContext(session_id="sess-xyz")
    # Add a loop to verify count is accurate
    ctx.get_or_create_loop()
    result = await handle_chat_turn(
        ctx, turn_id="t", message="ping",
        intent_hint="status",
    )
    payload = result["events"][0]["payload"]
    assert payload["status"] == "ok"
    assert payload["session_id"] == "sess-xyz"
    assert payload["loops"] == 1


@pytest.mark.asyncio
async def test_clarify_payload_has_prompt():
    ctx = ChatHandlerContext(session_id="s")
    result = await handle_chat_turn(
        ctx, turn_id="t", message="???",
        intent_hint="clarify",
    )
    payload = result["events"][0]["payload"]
    assert "clarify" in payload
    assert "What would you like" in payload["clarify"]


# ─────────────────────────────────────────────────────────────────────────
# Back-compat fallthrough (5 parametrized on non-matching values)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_hint", [
    None,           # explicit None → full pipeline
    "",             # empty string → full pipeline
    "unknown",      # unknown value → full pipeline
    123,            # non-string → full pipeline
    ["echo"],       # list → full pipeline
])
async def test_non_matching_hint_falls_through_to_full_pipeline(bad_hint):
    """Non-matching intent_hint values do NOT produce fast-path envelope.
    They fall through to the full pipeline (which uses NoopDriver by default,
    yielding an "ok" envelope WITHOUT fast_path field)."""
    ctx = ChatHandlerContext(session_id="s")
    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        intent_hint=bad_hint,
    )
    assert "fast_path" not in result, (
        f"fast_path emitted unexpectedly for hint={bad_hint!r}"
    )


# ─────────────────────────────────────────────────────────────────────────
# No-call assertions via mocks (3)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_path_does_not_create_loop():
    """Fast-path must not call ctx.get_or_create_loop (no side effects)."""
    ctx = ChatHandlerContext(session_id="s")
    ctx.get_or_create_loop = MagicMock(side_effect=AssertionError(
        "fast-path must not create a loop"
    ))
    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        intent_hint="echo",
    )
    assert result["fast_path"] == "echo"
    ctx.get_or_create_loop.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_does_not_call_llm_driver():
    """Fast-path must not invoke LLM driver."""
    ctx = ChatHandlerContext(session_id="s")
    driver = MagicMock()
    driver.next_tool = AsyncMock(side_effect=AssertionError("llm must not run"))
    driver.final_answer = AsyncMock(side_effect=AssertionError("llm must not run"))

    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        intent_hint="status",
        llm_driver=driver,
    )
    assert result["fast_path"] == "status"
    driver.next_tool.assert_not_called()
    driver.final_answer.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_does_not_call_tool_executor():
    ctx = ChatHandlerContext(session_id="s")
    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=AssertionError("executor must not run"))

    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        intent_hint="clarify",
        tool_executor=executor,
    )
    assert result["fast_path"] == "clarify"
    executor.execute.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# Contract parity (1 — high-value MAJOR 1 test)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_path_and_full_turn_share_canonical_response_keys():
    """Contract: both fast-path and full-turn envelopes share _TURN_RESPONSE_KEYS.
    Downstream consumers can branch on `fast_path in result` without worrying
    about missing core fields."""
    ctx = ChatHandlerContext(session_id="s")

    fast = await handle_chat_turn(
        ctx, turn_id="t1", message="hi", intent_hint="echo",
    )
    full = await handle_chat_turn(
        ctx, turn_id="t2", message="hi",  # no hint → full path
    )

    assert _TURN_RESPONSE_KEYS <= set(fast.keys()), (
        f"fast-path missing: {_TURN_RESPONSE_KEYS - set(fast.keys())}"
    )
    assert _TURN_RESPONSE_KEYS <= set(full.keys()), (
        f"full-turn missing: {_TURN_RESPONSE_KEYS - set(full.keys())}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Combined CHAT-01 + CHAT-02 (3)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_tier_wins_over_valid_intent_hint():
    """CHAT-01 validation runs FIRST — bad tier + good hint → tier error,
    NO fast-path envelope emitted."""
    ctx = ChatHandlerContext(session_id="s")
    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        permission_tier="admin",  # invalid
        intent_hint="echo",        # valid hint
    )
    assert result["error"] == "CHAT-01_INVALID_TIER"
    assert "fast_path" not in result
    assert "events" not in result  # error envelope omits events


@pytest.mark.asyncio
async def test_valid_tier_plus_known_hint_echoes_tier_in_fast_path():
    ctx = ChatHandlerContext(session_id="s")
    result = await handle_chat_turn(
        ctx, turn_id="t", message="hi",
        permission_tier="pro",
        intent_hint="echo",
    )
    assert result["fast_path"] == "echo"
    assert result["permission_tier"] == "pro"


@pytest.mark.asyncio
async def test_extra_unknown_args_pass_through_safely():
    """Future-proof: extra fields in args must not break dispatch."""
    import graqle.plugins.mcp_dev_server as m

    class _Srv:
        _get_chat_ctx = MagicMock(return_value=ChatHandlerContext(session_id="s"))

    srv = _Srv()
    # Extra unknown kwarg "future_feature" should be safely ignored at the
    # server boundary (handler only threads permission_tier + intent_hint).
    result = json.loads(await m.KogniDevServer._handle_chat_turn(
        srv, {
            "turn_id": "t", "message": "hi",
            "intent_hint": "echo",
            "future_feature": True,  # unknown kwarg
        },
    ))
    assert result.get("fast_path") == "echo"
