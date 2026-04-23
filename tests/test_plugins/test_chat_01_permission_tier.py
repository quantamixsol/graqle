"""CHAT-01 Permission Tier tests (Wave 2 Phase 5).

Advisory tier gate on graq_chat_turn: enum {free, pro, enterprise}.
- Validated at turn boundary BEFORE any loop creation or LLM side-effect
- Omitted → defaults to "free" (sentinel-distinguished from explicit None)
- Invalid (type, value, case) → CHAT-01_INVALID_TIER envelope, no side-effects
- Echoed in success envelope for observability

Covers:
  - Schema (2)
  - Valid tier values (4, parametrized)
  - Invalid tier values (8, parametrized)
  - Server-boundary required-field validation (3)
  - Side-effect assertions via mocks (2)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from graqle.chat.mcp_handlers import (
    ChatHandlerContext,
    _VALID_PERMISSION_TIERS,
    handle_chat_turn,
)


# ─────────────────────────────────────────────────────────────────────────
# Schema (2)
# ─────────────────────────────────────────────────────────────────────────


def test_schema_has_permission_tier_enum_with_default():
    import graqle.plugins.mcp_dev_server as m

    tool = next(t for t in m.TOOL_DEFINITIONS if t["name"] == "graq_chat_turn")
    props = tool["inputSchema"]["properties"]
    assert "permission_tier" in props
    assert props["permission_tier"]["enum"] == ["free", "pro", "enterprise"]
    assert props["permission_tier"]["default"] == "free"


def test_valid_permission_tiers_module_constant():
    assert _VALID_PERMISSION_TIERS == ("free", "pro", "enterprise")


# ─────────────────────────────────────────────────────────────────────────
# Valid tiers (4 parametrized — 1 omit + 3 explicit)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_omitted_tier_defaults_to_free():
    """Omitted permission_tier → no error, falls through to full pipeline
    with tier='free'. Back-compat guaranteed."""
    ctx = ChatHandlerContext(session_id="test")
    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hi",
        # permission_tier intentionally omitted
    )
    # Not an invalid-tier envelope
    assert result.get("error") != "CHAT-01_INVALID_TIER"
    # Success envelope echoes the default
    assert result.get("permission_tier") == "free"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["free", "pro", "enterprise"])
async def test_valid_tier_values_pass(tier):
    ctx = ChatHandlerContext(session_id="test")
    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hi",
        permission_tier=tier,
    )
    assert result.get("error") != "CHAT-01_INVALID_TIER"
    assert result.get("permission_tier") == tier


# ─────────────────────────────────────────────────────────────────────────
# Invalid tiers (8 parametrized)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_tier", [
    "admin",         # invalid value
    "FREE",          # case-sensitive (must be lowercase)
    "Pro",           # mixed-case
    "",              # empty string
    "   ",           # whitespace
    None,            # explicit None (distinct from omitted)
    1,               # non-string (int)
    ["free"],        # non-string (list)
])
async def test_invalid_tier_returns_error_envelope(bad_tier):
    ctx = ChatHandlerContext(session_id="test")
    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hi",
        permission_tier=bad_tier,
    )
    assert result["error"] == "CHAT-01_INVALID_TIER"
    assert result["status"] == "invalid_permission_tier"
    assert result["turn_id"] == "t1"
    # permission_tier is None in error envelope (not echoed back)
    assert result["permission_tier"] is None


# ─────────────────────────────────────────────────────────────────────────
# Server-boundary validation — no KeyError on missing fields (3)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_chat_turn_rejects_missing_turn_id():
    """Server-boundary defensive validation: missing turn_id → structured
    envelope, NOT KeyError."""
    import graqle.plugins.mcp_dev_server as m

    class _Srv:
        async def _get_chat_ctx(self):
            return None  # never reached
        _get_chat_ctx = MagicMock(return_value=ChatHandlerContext(session_id="x"))

    srv = _Srv()
    result = json.loads(await m.KogniDevServer._handle_chat_turn(
        srv, {"message": "hi"},  # missing turn_id
    ))
    assert result["error"] == "CHAT_MISSING_TURN_ID"


@pytest.mark.asyncio
async def test_handle_chat_turn_rejects_missing_message():
    import graqle.plugins.mcp_dev_server as m

    class _Srv:
        _get_chat_ctx = MagicMock(return_value=ChatHandlerContext(session_id="x"))

    srv = _Srv()
    result = json.loads(await m.KogniDevServer._handle_chat_turn(
        srv, {"turn_id": "t1"},  # missing message
    ))
    assert result["error"] == "CHAT_MISSING_MESSAGE"


@pytest.mark.asyncio
async def test_handle_chat_turn_rejects_non_dict_args():
    import graqle.plugins.mcp_dev_server as m

    class _Srv:
        _get_chat_ctx = MagicMock(return_value=ChatHandlerContext(session_id="x"))

    srv = _Srv()
    result = json.loads(await m.KogniDevServer._handle_chat_turn(
        srv, "not_a_dict",
    ))
    assert result["error"] == "CHAT_INVALID_ARGS"


# ─────────────────────────────────────────────────────────────────────────
# Side-effect assertions via mocks (2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_tier_does_not_create_loop():
    """Critical: invalid tier short-circuits BEFORE loop creation.
    Prevents any LLM/tool/side-effect execution on bad input."""
    ctx = ChatHandlerContext(session_id="test")
    # Spy on get_or_create_loop
    ctx.get_or_create_loop = MagicMock(side_effect=AssertionError(
        "loop must not be created on invalid tier"
    ))

    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hi",
        permission_tier="admin",  # invalid
    )
    assert result["error"] == "CHAT-01_INVALID_TIER"
    ctx.get_or_create_loop.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_tier_does_not_call_llm_driver():
    """Invalid tier must not reach the LLM driver."""
    ctx = ChatHandlerContext(session_id="test")
    driver = MagicMock()
    driver.next_tool = AsyncMock(side_effect=AssertionError("llm must not be called"))
    driver.final_answer = AsyncMock(side_effect=AssertionError("llm must not be called"))

    result = await handle_chat_turn(
        ctx, turn_id="t1", message="hi",
        permission_tier="admin",  # invalid
        llm_driver=driver,
    )
    assert result["error"] == "CHAT-01_INVALID_TIER"
    driver.next_tool.assert_not_called()
    driver.final_answer.assert_not_called()
