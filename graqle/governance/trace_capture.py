# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Governed Execution Trace Capture Middleware (R18 ADR-201).

Async context manager that wraps MCP tool handler execution in
KogniDevServer.handle_tool(). Creates a GovernedTrace before execution,
collects governance decisions during execution, finalizes outcome/latency
after execution, and persists to the trace store.

Non-bypassable: every governed tool entrypoint flows through TraceCapture.
Latency target: < 50ms overhead (AC-5).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from graqle.governance.trace_schema import (
    ClearanceLevel,
    Decision,
    GateType,
    GovernanceDecision,
    GovernedTrace,
    Outcome,
    ToolCall,
)

if TYPE_CHECKING:
    from graqle.governance.trace_store import TraceStore

logger = logging.getLogger("graqle.governance.trace_capture")

# Tools that are considered governed entrypoints (emit traces).
# Non-governed tools (internal helpers, aliases) are excluded.
GOVERNED_TOOLS: frozenset[str] = frozenset({
    "graq_context", "graq_inspect", "graq_reason", "graq_reason_batch",
    "graq_preflight", "graq_lessons", "graq_impact", "graq_safety_check",
    "graq_learn", "graq_predict", "graq_reload", "graq_audit",
    "graq_runtime", "graq_route", "graq_correct", "graq_lifecycle",
    "graq_gate", "graq_gov_gate", "graq_drace",
    "graq_edit", "graq_generate", "graq_review", "graq_debug",
    "graq_scaffold", "graq_workflow", "graq_test", "graq_plan",
    "graq_profile", "graq_auto",
    "graq_read", "graq_write", "graq_grep", "graq_glob", "graq_bash",
    "graq_git_status", "graq_git_diff", "graq_git_log",
    "graq_git_commit", "graq_git_branch",
    "graq_github_pr", "graq_github_diff",
    "graq_vendor", "graq_web_search", "graq_gcc_status",
    "graq_ingest", "graq_todo",
    # Scorch plugin
    "graq_scorch_audit", "graq_scorch_behavioral", "graq_scorch_report",
    "graq_scorch_a11y", "graq_scorch_perf", "graq_scorch_seo",
    "graq_scorch_mobile", "graq_scorch_i18n", "graq_scorch_security",
    "graq_scorch_conversion", "graq_scorch_brand", "graq_scorch_auth_flow",
    "graq_scorch_diff",
    # Phantom plugin
    "graq_phantom_browse", "graq_phantom_click", "graq_phantom_type",
    "graq_phantom_screenshot", "graq_phantom_audit", "graq_phantom_flow",
    "graq_phantom_discover", "graq_phantom_session",
})


def _extract_query(arguments: dict[str, Any]) -> str:
    """Extract a query string from tool arguments.

    Tries common argument names in priority order.
    Falls back to a truncated JSON dump of the arguments.
    """
    for key in ("question", "query", "task", "action", "goal", "description", "command"):
        val = arguments.get(key)
        if val and isinstance(val, str):
            return val[:4000]
    # Fallback: serialize arguments
    try:
        return json.dumps(arguments, default=str)[:4000]
    except Exception:
        return "(unable to extract query)"


def _extract_outcome_from_result(result_json: str) -> tuple[Outcome, float, float]:
    """Parse handler result JSON to extract outcome, confidence, cost.

    Returns (outcome, confidence, cost_usd).
    """
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return Outcome.SUCCESS, 0.0, 0.0

    # Check for error indicators
    if isinstance(data, dict):
        if "error" in data:
            return Outcome.FAILURE, 0.0, 0.0
        confidence = 0.0
        cost = 0.0
        # Extract confidence from various field names
        for conf_key in ("confidence", "activation_confidence", "answer_confidence"):
            val = data.get(conf_key)
            if isinstance(val, (int, float)) and 0.0 <= val <= 1.0:
                confidence = float(val)
                break
        # Extract cost
        cost_val = data.get("cost_usd")
        if isinstance(cost_val, (int, float)):
            cost = float(cost_val)
        return Outcome.SUCCESS, confidence, cost

    return Outcome.SUCCESS, 0.0, 0.0


def is_governed(tool_name: str) -> bool:
    """Check if a tool name is a governed entrypoint.

    Kogni aliases (kogni_*) are mapped to their graq_* equivalents.
    """
    canonical = tool_name.replace("kogni_", "graq_", 1) if tool_name.startswith("kogni_") else tool_name
    return canonical in GOVERNED_TOOLS


class TraceCapture:
    """Async context manager for governed execution trace capture.

    Usage in handle_tool()::

        if is_governed(name):
            async with TraceCapture(name, arguments, trace_store) as tc:
                # governance gates fire here, call tc.record_gate_decision()
                result = await handler(arguments)
                tc.set_result(result)
            return tc.result
        else:
            result = await handler(arguments)
            return result

    Attributes:
        trace: The GovernedTrace being built.
        result: The handler result string (set via set_result).
    """

    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        store: TraceStore | None = None,
    ) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._store = store
        self._start_time: float = 0.0
        self.trace: GovernedTrace | None = None
        self.result: str = ""

    async def __aenter__(self) -> TraceCapture:
        self._start_time = time.monotonic()
        query = _extract_query(self._arguments)
        self.trace = GovernedTrace(
            tool_name=self._tool_name,
            query=query,
            outcome=Outcome.SUCCESS,  # default, updated in __aexit__
            confidence=0.0,
            clearance_level=ClearanceLevel.INTERNAL,
        )
        return self

    def record_gate_decision(
        self,
        gate_id: str,
        gate_type: GateType,
        decision: Decision,
        reason: str = "",
        auto_corrected: bool = False,
    ) -> None:
        """Record a governance gate decision during tool execution."""
        if self.trace is None:
            return
        self.trace.governance_decisions.append(
            GovernanceDecision(
                gate_id=gate_id,
                gate_type=gate_type,
                decision=decision,
                reason=reason[:200],
                auto_corrected=auto_corrected,
            )
        )

    def set_result(self, result: str) -> None:
        """Store the handler result for post-processing in __aexit__."""
        self.result = result

    def set_context_nodes(self, nodes: list[str]) -> None:
        """Record which KG nodes were activated for this call."""
        if self.trace is not None:
            self.trace.context_nodes = nodes

    def add_tool_call(self, tool: str, args: dict[str, Any] | None = None, summary: str | None = None) -> None:
        """Record a nested tool invocation."""
        if self.trace is not None:
            self.trace.tool_calls.append(
                ToolCall(tool=tool, args=args or {}, result_summary=summary)
            )

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        elapsed_ms = (time.monotonic() - self._start_time) * 1000

        if self.trace is None:
            return False

        self.trace.latency_ms = elapsed_ms

        if exc_val is not None:
            # Exception during handler execution
            self.trace.outcome = Outcome.FAILURE
            self.trace.error = str(exc_val)[:1000]
            self.trace.confidence = 0.0
        elif self.result:
            # Parse result for outcome/confidence/cost
            outcome, confidence, cost = _extract_outcome_from_result(self.result)
            self.trace.outcome = outcome
            self.trace.confidence = confidence
            self.trace.cost_usd = cost
        # else: keep defaults (SUCCESS, 0.0, 0.0)

        # Check if any governance decision was BLOCK
        if any(gd.decision == Decision.BLOCK for gd in self.trace.governance_decisions):
            self.trace.outcome = Outcome.BLOCKED

        # Persist trace (non-blocking, best-effort)
        if self._store is not None:
            try:
                await self._store.append(self.trace)
            except Exception:
                logger.warning("Failed to persist trace for %s", self._tool_name, exc_info=True)

        return False  # Never suppress exceptions
