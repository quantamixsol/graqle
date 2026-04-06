"""Standard governance gate definitions for the reasoning pipeline.

Reference: ADR-147 — Governance gates run in Wave 0 with no dependencies,
ensuring policy checks complete before any downstream reasoning tasks execute.
"""

from __future__ import annotations

from graqle.core.types import ClearanceLevel
from graqle.reasoning.task_queue import ReasoningTask


def create_governance_gates() -> list[ReasoningTask]:
    """Return the three standard governance gate tasks (Wave 0, no dependencies)."""
    return [
        ReasoningTask(
            id="gate_git_governance",
            node_id="governance:git",
            depends_on=[],
            task_type="governance_gate",
            clearance=ClearanceLevel.INTERNAL,
        ),
        ReasoningTask(
            id="gate_ip_trade_secret",
            node_id="governance:ip",
            depends_on=[],
            task_type="ip_check",
            clearance=ClearanceLevel.CONFIDENTIAL,
        ),
        ReasoningTask(
            id="gate_clearance_verification",
            node_id="governance:clearance",
            depends_on=[],
            task_type="clearance_check",
            clearance=ClearanceLevel.INTERNAL,
        ),
    ]
