"""TB-F8 tests for graqle.chat.mcp_handlers.

Verifies the four handler functions work end-to-end with the default
no-op driver and the stub driver/executor injected from the test.
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_mcp_handlers
# risk: LOW
# dependencies: pytest, asyncio, graqle.chat.mcp_handlers
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.chat.agent_loop import ToolExecution, ToolPlan
from graqle.chat.mcp_handlers import (
    ChatHandlerContext,
    handle_chat_cancel,
    handle_chat_poll,
    handle_chat_resume,
    handle_chat_turn,
)
from graqle.chat.permission_manager import PermissionDecision


class _StubDriver:
    def __init__(self, plans: list[ToolPlan], final_text: str = "done") -> None:
        self._plans = list(plans)
        self._final = final_text
        self._idx = 0

    async def next_tool(
        self, *, user_message, candidates, prior_results, partial_text,
    ):
        if self._idx >= len(self._plans):
            return None
        plan = self._plans[self._idx]
        self._idx += 1
        return plan

    async def final_answer(self, *, user_message, results):
        return self._final


class _StubExecutor:
    async def execute(self, plan: ToolPlan) -> ToolExecution:
        return ToolExecution(
            tool_name=plan.tool_name, status="success",
            payload_summary="ok", latency_ms=1.0,
        )


# ──────────────────────────────────────────────────────────────────────
# handle_chat_turn
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_chat_turn_noop_driver_completes() -> None:
    ctx = ChatHandlerContext(session_id="s1")
    out = await handle_chat_turn(ctx, turn_id="t1", message="hello")
    assert out["status"] == "ok"
    assert out["turn_id"] == "t1"
    assert out["state"] == "completed"
    assert isinstance(out["events"], list)
    assert len(out["events"]) >= 1
    assert out["done"] is True


@pytest.mark.asyncio
async def test_handle_chat_turn_with_stub_executes_tools() -> None:
    ctx = ChatHandlerContext(session_id="s2")
    plans = [
        ToolPlan("graq_read", {"file_path": "x.py"}, governance_tier="GREEN"),
    ]
    out = await handle_chat_turn(
        ctx, turn_id="t1", message="read x",
        llm_driver=_StubDriver(plans, "x read"),
        tool_executor=_StubExecutor(),
    )
    assert out["status"] == "ok"
    assert len(out["tool_executions"]) == 1
    assert out["tool_executions"][0]["tool"] == "graq_read"


# ──────────────────────────────────────────────────────────────────────
# handle_chat_poll
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_chat_poll_returns_events_since_cursor() -> None:
    ctx = ChatHandlerContext(session_id="s3")
    await handle_chat_turn(ctx, turn_id="t1", message="hi")
    poll1 = await handle_chat_poll(ctx, turn_id="t1", since_seq=0)
    assert poll1["status"] == "ok"
    assert len(poll1["events"]) >= 1
    cursor = poll1["next_seq"]
    poll2 = await handle_chat_poll(ctx, turn_id="t1", since_seq=cursor)
    # No new events past the end-of-turn cursor.
    assert poll2["events"] == []


@pytest.mark.asyncio
async def test_handle_chat_poll_unknown_turn() -> None:
    ctx = ChatHandlerContext(session_id="s4")
    out = await handle_chat_poll(ctx, turn_id="missing", since_seq=0)
    assert out["status"] == "unknown_turn"


# ──────────────────────────────────────────────────────────────────────
# handle_chat_resume
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_chat_resume_after_pause() -> None:
    ctx = ChatHandlerContext(session_id="s5")
    plans = [
        ToolPlan("graq_write", {"file_path": "out.py"}, governance_tier="YELLOW"),
    ]
    out = await handle_chat_turn(
        ctx, turn_id="t1", message="write x",
        llm_driver=_StubDriver(plans, "ok"),
        tool_executor=_StubExecutor(),
    )
    assert out["state"] == "paused"
    # Pull the pending_id from the permission_requested event.
    perm = next(
        e for e in out["events"]
        if e["type"] == "permission_requested"
    )
    pending_id = perm["data"]["pending_id"]
    resume_out = await handle_chat_resume(
        ctx, turn_id="t1", pending_id=pending_id, decision="approve",
    )
    assert resume_out["status"] == "ok"
    assert resume_out["state"] == "active"


@pytest.mark.asyncio
async def test_handle_chat_resume_invalid_decision() -> None:
    ctx = ChatHandlerContext(session_id="s6")
    await handle_chat_turn(ctx, turn_id="t1", message="hi")
    out = await handle_chat_resume(
        ctx, turn_id="t1", pending_id="x", decision="totally_invalid",
    )
    assert out["status"] == "invalid_decision"


@pytest.mark.asyncio
async def test_handle_chat_resume_unknown_session() -> None:
    ctx = ChatHandlerContext(session_id="s7")
    out = await handle_chat_resume(
        ctx, turn_id="t1", pending_id="x", decision="approve",
    )
    assert out["status"] == "unknown_turn"


# ──────────────────────────────────────────────────────────────────────
# handle_chat_cancel
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_chat_cancel_paused_turn() -> None:
    ctx = ChatHandlerContext(session_id="s8")
    plans = [
        ToolPlan("graq_write", {"file_path": "o.py"}, governance_tier="YELLOW"),
    ]
    await handle_chat_turn(
        ctx, turn_id="t1", message="write",
        llm_driver=_StubDriver(plans, "ok"),
        tool_executor=_StubExecutor(),
    )
    out = await handle_chat_cancel(ctx, turn_id="t1")
    assert out["status"] == "ok"
    assert out["state"] == "cancelled"


@pytest.mark.asyncio
async def test_handle_chat_cancel_unknown_session() -> None:
    ctx = ChatHandlerContext(session_id="s9")
    out = await handle_chat_cancel(ctx, turn_id="t1")
    assert out["status"] == "unknown_turn"
