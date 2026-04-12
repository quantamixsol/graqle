"""ChatAgentLoop — the core integration point for ChatAgentLoop v4. of ChatAgentLoop v4 . Wires together:

  - GRAQ.md system prompt bundle graq_md_loader)
  - .graqle/settings.json policy settings_loader)
  - ChatEvent emission + per-turn ledger streaming + turn_ledger)
  - TCG tool ranking tool_capability_graph)
  - RCAG ephemeral memory rcag)
  - TurnStore CAS state machine + permissions permission_manager)
  - Debate debate)
  - Backend router backend_router)

The 10-step turn flow (from §Decision)
----------------------------------------------

  1. begin_turn (RCAG) + create TurnCheckpoint (TurnStore) + ledger open
  2. activate TCG → ranked candidates with governance tiers
  3. emit governance_chip events upfront (pre-disclosed consent)
  4. drive the LLM tool-use loop:
     a. propose tool call (LLM is RANKER over the TCG subgraph)
     b. permission check (PermissionManager) — pause if PROMPT
     c. (optional) debate before HIGH/CRITICAL actions
     d. execute tool, capture result
     e. record ToolCall + ToolResult + GovernanceCheckpoint in RCAG
     f. ledger.append every event
     g. reinforce TCG sequence on success/failure
  5. on hard error → ErrorNode in RCAG, synthetic tool_result, continue
  6. on budget exhaustion → soft chip + burst override decision
  7. on PAUSED state → emit permission_requested, return next_seq
  8. on completion → final tool_ended + turn_complete
  9. mine_workflow_patterns (probationary) from this turn's sequence
 10. end_turn (RCAG rolling summary) + transition to terminal state

CGI-compatibility seed)
--------------------------------
Every event emitted by the loop carries the structural fields a future
CGI Task / Session / Decision / Review node would need:

  - turn_id, session_id, parent_id (Task lineage)
  - tool_name, status, latency_ms (Artifact provenance)
  - debate verdict + reason (Decision rationale)
  - governance tier + decision (Review trail)

The CGI design session (post v0.50.0) can decide whether to fold
terminal turn events into a persistent project-self-memory graph or
keep them ephemeral. The shape is intentionally CGI-compatible TODAY
so the migration is a classification pass, not a rewrite. This is
the single concrete contribution to the build wave.
"""

# ── graqle:intelligence ──
# module: graqle.chat.agent_loop
# risk: HIGH (the integration point)
# consumers: chat.mcp_handlers # dependencies: __future__, asyncio, dataclasses, typing,
#   graqle.chat.{streaming,turn_ledger,settings_loader,graq_md_loader,
#                tool_capability_graph,rcag,permission_manager,
#                debate,backend_router}
# constraints: never block on permissions; CGI-compatible event shape
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from graqle.chat.backend_router import BackendRouter
from graqle.chat.debate import ConcernCheckRecord, ReasonFn, resolve_concern
from graqle.chat.permission_manager import (
    PermissionDecision,
    PermissionManager,
    TurnState,
    TurnStore,
)
from graqle.chat.rcag import RuntimeChatActionGraph
from graqle.chat.streaming import ChatEventBuffer, ChatEventType
from graqle.chat.tool_capability_graph import ToolCandidate, ToolCapabilityGraph
from graqle.chat.turn_ledger import TurnLedger

logger = logging.getLogger("graqle.chat.agent_loop")

# Adaptive budget §Decision)
DEFAULT_TOOL_CALL_BUDGET = 25
BURST_OVERRIDE_CEILING = 100
DEFAULT_PER_TOOL_TIMEOUT_S = 120.0


@dataclass
class ToolPlan:
    """A single tool call the LLM driver wants to execute."""

    tool_name: str
    params: dict[str, Any]
    governance_tier: str
    requires_debate: bool = False
    rationale: str = ""


@dataclass
class ToolExecution:
    """Outcome of executing one tool plan."""

    tool_name: str
    status: str  # success | error | denied
    payload_summary: str
    latency_ms: float
    error: str | None = None


class LLMDriver(Protocol):
    """Pluggable LLM driver for the tool-use loop."""

    async def next_tool(
        self,
        *,
        user_message: str,
        candidates: list[ToolCandidate],
        prior_results: list[ToolExecution],
        partial_text: str,
    ) -> ToolPlan | None: ...

    async def final_answer(
        self,
        *,
        user_message: str,
        results: list[ToolExecution],
    ) -> str: ...


class ToolExecutor(Protocol):
    """Pluggable tool executor."""

    async def execute(self, plan: ToolPlan) -> ToolExecution: ...


@dataclass
class TurnResult:
    turn_id: str
    final_text: str
    state: TurnState
    tool_executions: list[ToolExecution] = field(default_factory=list)
    check_records: list[ConcernCheckRecord] = field(default_factory=list)
    cost_usd: float = 0.0


# ──────────────────────────────────────────────────────────────────────
# ChatAgentLoop
# ──────────────────────────────────────────────────────────────────────


class ChatAgentLoop:
    """The integration point for ChatAgentLoop v4.

    Constructed once per session. ``run_turn`` advances one user turn
    through the 10-step flow. The loop is fully unit-testable through
    stub LLM driver + stub tool executor; production wiring lives in 's MCP handlers.
    """

    def __init__(
        self,
        *,
        session_id: str,
        tcg: ToolCapabilityGraph,
        rcag: RuntimeChatActionGraph,
        turn_store: TurnStore,
        permission_manager: PermissionManager,
        backend_router: BackendRouter,
        llm_driver: LLMDriver,
        tool_executor: ToolExecutor,
        ledger: TurnLedger | None = None,
        reason_fn: ReasonFn | None = None,
        tool_call_budget: int = DEFAULT_TOOL_CALL_BUDGET,
        burst_ceiling: int = BURST_OVERRIDE_CEILING,
    ) -> None:
        self.session_id = session_id
        self.tcg = tcg
        self.rcag = rcag
        self.turn_store = turn_store
        self.permission_manager = permission_manager
        self.backend_router = backend_router
        self.llm_driver = llm_driver
        self.tool_executor = tool_executor
        self.ledger = ledger
        self.reason_fn = reason_fn
        self.tool_call_budget = tool_call_budget
        self.burst_ceiling = burst_ceiling
        self._buffers: dict[str, ChatEventBuffer] = {}

    def buffer_for(self, turn_id: str) -> ChatEventBuffer:
        """Return (creating if needed) the per-turn event buffer."""
        if turn_id not in self._buffers:
            self._buffers[turn_id] = ChatEventBuffer(turn_id)
        return self._buffers[turn_id]

    async def _emit(
        self,
        turn_id: str,
        event_type: ChatEventType,
        data: dict[str, Any],
        *,
        tool_call_id: str | None = None,
    ) -> None:
        buf = self.buffer_for(turn_id)
        evt = buf.append(event_type, data, tool_call_id=tool_call_id)
        if self.ledger is not None:
            await asyncio.to_thread(self.ledger.append, evt.to_dict())

    async def run_turn(
        self,
        *,
        turn_id: str,
        user_message: str,
        scenario: str | None = None,
    ) -> TurnResult:
        """Drive one full turn through the 10-step flow."""
        # Step 1: open turn in store + RCAG + ledger
        await self.turn_store.create(
            turn_id=turn_id, session_id=self.session_id,
            user_message=user_message,
        )
        self.rcag.begin_turn(user_message)
        await self._emit(
            turn_id, ChatEventType.USER_MESSAGE,
            {"text": user_message, "session_id": self.session_id},
        )
        await self.turn_store.transition(turn_id, TurnState.PENDING, TurnState.ACTIVE)

        # Step 2: TCG activation
        activation = self.tcg.activate_for_query(
            user_message, intent_hint=scenario,
        )
        await self._emit(
            turn_id, ChatEventType.ASSISTANT_TEXT_CHUNK,
            {
                "kind": "tools_activated",
                "intent": activation.intent_label or "unknown",
                "intent_id": activation.intent_id,
                "candidates": [c.to_dict() for c in activation.candidates],
            },
        )

        # Step 3: pre-disclose governance tiers upfront
        for c in activation.candidates:
            await self._emit(
                turn_id, ChatEventType.GOVERNANCE_CHIP,
                {
                    "tool": c.label,
                    "tier": c.governance_tier,
                    "decision": "pre_disclose",
                    "rationale": c.rationale,
                },
            )

        # Step 4: tool-use loop
        results: list[ToolExecution] = []
        checks: list[ConcernCheckRecord] = []
        partial_text = ""
        executed = 0
        budget = self.tool_call_budget

        while True:
            if executed >= budget:
                if budget < self.burst_ceiling:
                    budget = self.burst_ceiling
                    await self._emit(
                        turn_id, ChatEventType.GOVERNANCE_CHIP,
                        {
                            "kind": "budget_burst",
                            "message": f"budget expanded to {budget} for this turn",
                        },
                    )
                else:
                    await self._emit(
                        turn_id, ChatEventType.GOVERNANCE_CHIP,
                        {"kind": "budget_ceiling", "message": "hard ceiling reached"},
                    )
                    break

            plan = await self.llm_driver.next_tool(
                user_message=user_message,
                candidates=activation.candidates,
                prior_results=results,
                partial_text=partial_text,
            )
            if plan is None:
                break

            await self._emit(
                turn_id, ChatEventType.TOOL_PLANNED,
                {
                    "tool_name": plan.tool_name,
                    "params": plan.params,
                    "governance_tier": plan.governance_tier,
                    "rationale": plan.rationale,
                },
            )

            # Step 4b: permission gate
            decision, pending_id = await self.permission_manager.check(
                session_id=self.session_id,
                tool_name=plan.tool_name,
                resource_scope=str(plan.params.get("resource_scope", "default")),
                tier=plan.governance_tier,
                rationale=plan.rationale,
            )
            if decision == PermissionDecision.PROMPT:
                await self.turn_store.transition(
                    turn_id, TurnState.ACTIVE, TurnState.PAUSED,
                )
                await self._emit(
                    turn_id, ChatEventType.PERMISSION_REQUESTED,
                    {
                        "pending_id": pending_id or "",
                        "tool": plan.tool_name,
                        "tier": plan.governance_tier,
                        "rationale": plan.rationale,
                    },
                )
                cp_now = await self.turn_store.get(turn_id)
                return TurnResult(
                    turn_id=turn_id,
                    final_text="",
                    state=cp_now.state if cp_now else TurnState.PAUSED,
                    tool_executions=results,
                    check_records=checks,
                )
            if decision == PermissionDecision.DENY:
                exec_result = ToolExecution(
                    tool_name=plan.tool_name, status="denied",
                    payload_summary="permission denied",
                    latency_ms=0.0, error="user denied",
                )
                results.append(exec_result)
                self.rcag.add_governance_checkpoint(
                    self.rcag.add_tool_call(plan.tool_name, plan.params),
                    tier=plan.governance_tier, decision="deny",
                    reason=plan.rationale,
                )
                await self._emit(
                    turn_id, ChatEventType.TOOL_ERROR,
                    {"tool": plan.tool_name, "error": "permission denied"},
                )
                continue

            # Step 4c: debate (optional)
            if plan.requires_debate and self.reason_fn is not None:
                check_record = await resolve_concern(
                    f"{plan.tool_name}({plan.params})",
                    reason_fn=self.reason_fn,
                )
                checks.append(check_record)
                await self._emit(
                    turn_id, ChatEventType.DEBATE_CHIP,
                    {
                        "verdict": check_record.final_decision,
                        "reason": check_record.final_rationale,
                        "rounds": len(debate_record.rounds),
                    },
                )
                if check_record.final_decision == "BLOCK":
                    exec_result = ToolExecution(
                        tool_name=plan.tool_name, status="denied",
                        payload_summary=f"blocked by debate: {check_record.final_rationale}",
                        latency_ms=0.0, error="debate_blocked",
                    )
                    results.append(exec_result)
                    continue

            # Step 4d-f: execute + record
            await self._emit(
                turn_id, ChatEventType.TOOL_STARTED,
                {"tool": plan.tool_name},
            )
            t0 = time.time()
            try:
                exec_result = await self.tool_executor.execute(plan)
            except Exception as exc:
                exec_result = ToolExecution(
                    tool_name=plan.tool_name,
                    status="error",
                    payload_summary=f"tool crashed: {exc}",
                    latency_ms=(time.time() - t0) * 1000,
                    error=str(exc),
                )
                self.rcag.add_error(
                    kind=type(exc).__name__,
                    message=str(exc),
                    related_tool_call_id=self.rcag.add_tool_call(
                        plan.tool_name, plan.params,
                    ),
                    recovered=True,
                )
                logger.warning("tool %s raised %s", plan.tool_name, exc)
                await self._emit(
                    turn_id, ChatEventType.TOOL_ERROR,
                    {"tool": plan.tool_name, "error": str(exc)},
                )
            else:
                call_id = self.rcag.add_tool_call(plan.tool_name, plan.params)
                self.rcag.add_tool_result(
                    call_id,
                    status=exec_result.status,
                    payload_summary=exec_result.payload_summary,
                    latency_ms=exec_result.latency_ms,
                    error=exec_result.error,
                )
                await self._emit(
                    turn_id, ChatEventType.TOOL_ENDED,
                    {
                        "tool": plan.tool_name,
                        "status": exec_result.status,
                        "summary": exec_result.payload_summary,
                        "latency_ms": exec_result.latency_ms,
                    },
                )

            results.append(exec_result)
            executed += 1

            # Step 4g: reinforce TCG
            outcome = "success" if exec_result.status == "success" else "failure"
            self.tcg.reinforce_intent_match(
                activation.intent_id or "",
                f"tool_{plan.tool_name}",
                outcome=outcome,
            )

        # Step 8: produce final answer
        final_text = await self.llm_driver.final_answer(
            user_message=user_message, results=results,
        )

        # Step 9: mine workflow patterns (probationary)
        if results:
            self.tcg.mine_workflow_patterns([{
                "tool_sequence": [f"tool_{r.tool_name}" for r in results],
                "intent_id": activation.intent_id,
                "support_files": [],
                "success": all(r.status == "success" for r in results),
            }])

        # Step 10: close out
        self.rcag.end_turn(final_text, tool_count=len(results))
        await self.turn_store.transition(
            turn_id, TurnState.ACTIVE, TurnState.COMPLETED,
            exit_reason="task_complete",
        )
        await self._emit(
            turn_id, ChatEventType.TURN_COMPLETE,
            {
                "text": final_text,
                "tools_used": len(results),
                "session_id": self.session_id,
            },
        )
        cp_final = await self.turn_store.get(turn_id)
        return TurnResult(
            turn_id=turn_id,
            final_text=final_text,
            state=cp_final.state if cp_final else TurnState.COMPLETED,
            tool_executions=results,
            check_records=checks,
        )

    async def resume_turn(
        self,
        *,
        turn_id: str,
        pending_id: str,
        decision: PermissionDecision,
    ) -> TurnResult:
        """Apply a user permission decision and resume a paused turn."""
        await self.permission_manager.resolve(pending_id, decision)
        cp = await self.turn_store.get(turn_id)
        if cp is None:
            return TurnResult(
                turn_id=turn_id, final_text="",
                state=TurnState.ABANDONED,
            )
        if cp.state != TurnState.PAUSED:
            return TurnResult(
                turn_id=turn_id, final_text="", state=cp.state,
            )
        await self.turn_store.transition(turn_id, TurnState.PAUSED, TurnState.ACTIVE)
        await self._emit(
            turn_id, ChatEventType.GOVERNANCE_CHIP,
            {
                "kind": "turn_resumed",
                "decision": decision.value,
                "pending_id": pending_id,
            },
        )
        cp_now = await self.turn_store.get(turn_id)
        return TurnResult(
            turn_id=turn_id, final_text="",
            state=cp_now.state if cp_now else TurnState.ACTIVE,
        )

    async def cancel_turn(self, turn_id: str) -> TurnResult:
        """Cancel an in-flight turn cleanly."""
        cp = await self.turn_store.get(turn_id)
        if cp is None:
            return TurnResult(
                turn_id=turn_id, final_text="",
                state=TurnState.ABANDONED,
            )
        if cp.is_terminal():
            return TurnResult(
                turn_id=turn_id, final_text="", state=cp.state,
            )
        await self.turn_store.transition(
            turn_id, cp.state, TurnState.CANCELLED,
            exit_reason="user_cancelled",
        )
        await self._emit(
            turn_id, ChatEventType.GOVERNANCE_CHIP,
            {"kind": "turn_cancelled"},
        )
        return TurnResult(
            turn_id=turn_id, final_text="", state=TurnState.CANCELLED,
        )


__all__ = [
    "BURST_OVERRIDE_CEILING",
    "ChatAgentLoop",
    "DEFAULT_PER_TOOL_TIMEOUT_S",
    "DEFAULT_TOOL_CALL_BUDGET",
    "LLMDriver",
    "ToolExecution",
    "ToolExecutor",
    "ToolPlan",
    "TurnResult",
]
