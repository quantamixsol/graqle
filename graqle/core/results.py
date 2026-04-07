"""Fault-isolated, clearance-aware result types for GraQle node reasoning.

Implements ADR-145: every node call returns a ToolResult instead of raising.
Provides Promise.allSettled semantics so no single failure kills a round.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from graqle.core.types import ClearanceLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fault codes — safe to expose at any clearance tier
# ---------------------------------------------------------------------------
FAULT_TIMEOUT = "FAULT_TIMEOUT"
FAULT_NETWORK = "FAULT_NETWORK"
FAULT_PARSE = "FAULT_PARSE"
FAULT_ACCESS = "FAULT_ACCESS"
FAULT_UNKNOWN = "FAULT_UNKNOWN"


def _classify_fault(error: Exception) -> str:
    """Map an exception to a generic, clearance-safe fault code."""
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return FAULT_TIMEOUT
    if isinstance(error, ConnectionError):
        return FAULT_NETWORK
    if isinstance(error, (ValueError, KeyError)):
        return FAULT_PARSE
    if isinstance(error, PermissionError):
        return FAULT_ACCESS
    return FAULT_UNKNOWN


# ---------------------------------------------------------------------------
# ToolResult — frozen, fault-isolated, clearance-aware result envelope
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolResult:
    """Immutable, clearance-aware result from a single tool or LLM call."""

    data: str
    is_error: bool = False
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC
    source_node_id: str | None = None
    round_num: int | None = None
    agent_id: str | None = None
    fault_code: str | None = None

    # -- factory methods ----------------------------------------------------

    @staticmethod
    def success(
        data: str,
        *,
        clearance: ClearanceLevel = ClearanceLevel.PUBLIC,
        source_node_id: str | None = None,
        round_num: int | None = None,
        agent_id: str | None = None,
    ) -> ToolResult:
        """Create a successful result."""
        return ToolResult(
            data=data,
            is_error=False,
            clearance=clearance,
            source_node_id=source_node_id,
            round_num=round_num,
            agent_id=agent_id,
            fault_code=None,
        )

    @staticmethod
    def failure(
        data: str,
        *,
        fault_code: str = FAULT_UNKNOWN,
        clearance: ClearanceLevel = ClearanceLevel.PUBLIC,
        source_node_id: str | None = None,
        round_num: int | None = None,
        agent_id: str | None = None,
    ) -> ToolResult:
        """Create a failed result with a fault code."""
        return ToolResult(
            data=data,
            is_error=True,
            clearance=clearance,
            source_node_id=source_node_id,
            round_num=round_num,
            agent_id=agent_id,
            fault_code=fault_code,
        )

    # -- instance methods ---------------------------------------------------

    def redacted_for(self, viewer_clearance: ClearanceLevel) -> ToolResult:
        """Return a clearance-appropriate view of this result.

        If the viewer's clearance is lower than the result's clearance the
        data payload is replaced with a generic redaction notice.
        """
        if viewer_clearance.value >= self.clearance.value:
            return self
        return ToolResult(
            data="[REDACTED — insufficient clearance]",
            is_error=self.is_error,
            clearance=self.clearance,
            source_node_id=self.source_node_id,
            round_num=self.round_num,
            agent_id=self.agent_id,
            fault_code=self.fault_code,
        )

    def to_audit_event(self) -> dict[str, Any]:
        """Return a structured dict suitable for graph persistence."""
        return {
            "source_node_id": self.source_node_id,
            "round_num": self.round_num,
            "agent_id": self.agent_id,
            "is_error": self.is_error,
            "fault_code": self.fault_code,
            "clearance": self.clearance.name,
            "data_length": len(self.data),
        }


# ---------------------------------------------------------------------------
# safe_node_reason — async wrapper that NEVER raises
# ---------------------------------------------------------------------------
async def safe_node_reason(
    node_id: str,
    prompt: str,
    llm_fn: Callable[[str], Awaitable[str]],
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC,
    round_num: int | None = None,
    agent_id: str | None = None,
    timeout_seconds: float = 30.0,
) -> ToolResult:
    """Call *llm_fn* with timeout; return a ToolResult — **never raises**."""
    try:
        raw = await asyncio.wait_for(llm_fn(prompt), timeout=timeout_seconds)
        return ToolResult.success(
            data=str(raw),
            clearance=clearance,
            source_node_id=node_id,
            round_num=round_num,
            agent_id=agent_id,
        )
    except Exception as exc:  # noqa: BLE001
        fault = _classify_fault(exc)
        logger.error("FAULT_AUDIT node=%s fault=%s error=%s", node_id, fault, exc)
        return ToolResult.failure(
            data=str(exc),
            fault_code=fault,
            clearance=clearance,
            source_node_id=node_id,
            round_num=round_num,
            agent_id=agent_id,
        )


# ---------------------------------------------------------------------------
# gather_settled — Promise.allSettled equivalent
# ---------------------------------------------------------------------------
async def gather_settled(tasks: Sequence[Awaitable[Any]]) -> list[ToolResult]:
    """Await all *tasks*; convert each outcome to a ToolResult. None lost."""
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    settled: list[ToolResult] = []
    for outcome in outcomes:
        if isinstance(outcome, ToolResult):
            settled.append(outcome)
        elif isinstance(outcome, Exception):
            settled.append(ToolResult.failure(data=str(outcome), fault_code=_classify_fault(outcome)))
        else:
            settled.append(ToolResult.success(data=str(outcome)))
    return settled
