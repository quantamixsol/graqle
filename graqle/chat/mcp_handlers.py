"""ChatAgentLoop v4 MCP handlers — .

Four handler functions plus a ``ChatHandlerContext`` that owns the
shared per-process state (``ChatAgentLoop``, ``TurnStore``,
``PermissionManager``). The MCP server registration code in
``graqle/plugins/mcp_dev_server.py`` will instantiate one
``ChatHandlerContext`` at startup and dispatch the four ``graq_chat_*``
tools to these functions.

Why a separate module
---------------------
``mcp_dev_server.py`` is a CRITICAL hub file (8609 lines, impact
radius 491 modules). Per / the safest pattern is
to keep new logic in its own module and add the SMALLEST possible
edit to the hub: a few lines that import + dispatch. This module is
the "few lines" target — wiring in mcp_dev_server.py is just
``from graqle.chat.mcp_handlers import handle_chat_*`` plus the
registration block.

Tools registered
----------------

  - ``graq_chat_turn`` — start a new turn, return the first event batch
  - ``graq_chat_poll`` — long-poll events since a cursor
  - ``graq_chat_resume`` — apply a permission decision and resume
  - ``graq_chat_cancel`` — cancel an in-flight turn

Each handler returns a JSON-serializable dict that the MCP layer
passes through unchanged.

CGI-compatibility note seed)
-------------------------------------
The ``ChatHandlerContext`` already owns a ``TurnStore`` whose
``TurnCheckpoint`` carries the fields a future CGI ``Session`` /
``Checkpoint`` node would need. When ships, the only thing
that needs to change is the terminal-transition hook in
``handle_chat_turn`` and ``handle_chat_resume`` to also write the
checkpoint into a persistent CGI graph. The handler signature stays
the same.
"""

# ── graqle:intelligence ──
# module: graqle.chat.mcp_handlers
# risk: MEDIUM (process-level shared state)
# consumers: graqle.plugins.mcp_dev_server registration)
# dependencies: __future__, asyncio, typing, graqle.chat.*
# constraints: every handler returns JSON-serializable dict
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from graqle.chat.agent_loop import (
    ChatAgentLoop,
    LLMDriver,
    ToolExecutor,
    ToolPlan,
)
from graqle.chat.backend_router import BackendProfile, BackendRouter
from graqle.chat.permission_manager import (
    PermissionDecision,
    PermissionManager,
    TurnState,
    TurnStore,
)
from graqle.chat.rcag import RuntimeChatActionGraph
from graqle.chat.streaming import poll_events
from graqle.chat.tool_capability_graph import ToolCapabilityGraph

logger = logging.getLogger("graqle.chat.mcp_handlers")


# ──────────────────────────────────────────────────────────────────────
# Default driver / executor stubs (replaced by production wiring)
# ──────────────────────────────────────────────────────────────────────


class _NoopDriver:
    """Default LLM driver: returns no tools, empty answer.

    The production code injects a real driver that wraps an MCP
    backend with native tool-use. This default keeps unit tests
    against the handler API working without backend setup.
    """

    async def next_tool(
        self, *, user_message, candidates, prior_results, partial_text,
    ):
        return None

    async def final_answer(self, *, user_message, results):
        return ""


class _NoopExecutor:
    """Default tool executor: should never be called when driver is no-op."""

    async def execute(self, plan: ToolPlan):
        from graqle.chat.agent_loop import ToolExecution
        return ToolExecution(
            tool_name=plan.tool_name, status="success",
            payload_summary="noop", latency_ms=0.0,
        )


# ──────────────────────────────────────────────────────────────────────
# ChatHandlerContext
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ChatHandlerContext:
    """Per-process shared state for the four chat handlers.

    Production code constructs ONE ``ChatHandlerContext`` at MCP server
    startup and reuses it for the lifetime of the process. Tests
    construct fresh contexts per test.
    """

    session_id: str = "default"
    loops: dict[str, ChatAgentLoop] = field(default_factory=dict)

    def get_or_create_loop(
        self,
        *,
        llm_driver: LLMDriver | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> ChatAgentLoop:
        """Return the loop for ``self.session_id``, creating on first call.

        Each call passes the (optional) production driver/executor; the
        first call wins, subsequent calls reuse.
        """
        if self.session_id in self.loops:
            return self.loops[self.session_id]
        tcg = ToolCapabilityGraph.from_seed()
        rcag = RuntimeChatActionGraph(session_id=self.session_id)
        store = TurnStore()
        pm = PermissionManager()
        router = BackendRouter(profiles=[
            BackendProfile.from_name("anthropic:sonnet"),
        ])
        loop = ChatAgentLoop(
            session_id=self.session_id,
            tcg=tcg,
            rcag=rcag,
            turn_store=store,
            permission_manager=pm,
            backend_router=router,
            llm_driver=llm_driver or _NoopDriver(),
            tool_executor=tool_executor or _NoopExecutor(),
        )
        self.loops[self.session_id] = loop
        return loop


# ──────────────────────────────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────────────────────────────


async def handle_chat_turn(
    ctx: ChatHandlerContext,
    *,
    turn_id: str,
    message: str,
    scenario: str | None = None,
    llm_driver: LLMDriver | None = None,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Handle ``graq_chat_turn(message, ...)``.

    Drives one turn through the loop and returns the first batch of
    events plus the next-cursor for the long-poll handler.
    """
    loop = ctx.get_or_create_loop(
        llm_driver=llm_driver, tool_executor=tool_executor,
    )
    result = await loop.run_turn(
        turn_id=turn_id, user_message=message, scenario=scenario,
    )
    buf = loop.buffer_for(turn_id)
    snap = buf.snapshot_since(0)
    return {
        "status": "ok",
        "turn_id": turn_id,
        "state": result.state.value,
        "events": [e.to_dict() for e in snap.events],
        "next_seq": snap.next_seq,
        "done": snap.done,
        "tool_executions": [
            {
                "tool": r.tool_name,
                "status": r.status,
                "summary": r.payload_summary,
                "latency_ms": r.latency_ms,
            }
            for r in result.tool_executions
        ],
    }


async def handle_chat_poll(
    ctx: ChatHandlerContext,
    *,
    turn_id: str,
    since_seq: int,
    timeout: float = 0.0,
) -> dict[str, Any]:
    """Handle ``graq_chat_poll(turn_id, since_seq, timeout)``.

    Long-poll cursor read against the per-turn event buffer.
    """
    loop = ctx.loops.get(ctx.session_id)
    if loop is None or turn_id not in loop._buffers:
        return {
            "status": "unknown_turn",
            "events": [],
            "next_seq": since_seq,
            "done": False,
        }
    buf = loop.buffer_for(turn_id)
    snap = poll_events(buf, since_seq=since_seq, timeout=timeout)
    return {
        "status": "ok",
        "events": [e.to_dict() for e in snap.events],
        "next_seq": snap.next_seq,
        "done": snap.done,
    }


async def handle_chat_resume(
    ctx: ChatHandlerContext,
    *,
    turn_id: str,
    pending_id: str,
    decision: str,
) -> dict[str, Any]:
    """Handle ``graq_chat_resume(turn_id, pending_id, decision)``.

    Apply a user permission decision and transition the turn back to
    ACTIVE so the loop can continue.
    """
    loop = ctx.loops.get(ctx.session_id)
    if loop is None:
        return {"status": "unknown_turn", "turn_id": turn_id}
    try:
        decision_enum = PermissionDecision(decision)
    except ValueError:
        return {
            "status": "invalid_decision",
            "turn_id": turn_id,
            "decision": decision,
        }
    result = await loop.resume_turn(
        turn_id=turn_id,
        pending_id=pending_id,
        decision=decision_enum,
    )
    return {
        "status": "ok",
        "turn_id": turn_id,
        "state": result.state.value,
    }


async def handle_chat_cancel(
    ctx: ChatHandlerContext,
    *,
    turn_id: str,
) -> dict[str, Any]:
    """Handle ``graq_chat_cancel(turn_id)``.

    Move the turn to CANCELLED. Idempotent.
    """
    loop = ctx.loops.get(ctx.session_id)
    if loop is None:
        return {"status": "unknown_turn", "turn_id": turn_id}
    result = await loop.cancel_turn(turn_id)
    return {
        "status": "ok",
        "turn_id": turn_id,
        "state": result.state.value,
    }


__all__ = [
    "ChatHandlerContext",
    "handle_chat_cancel",
    "handle_chat_poll",
    "handle_chat_resume",
    "handle_chat_turn",
]
