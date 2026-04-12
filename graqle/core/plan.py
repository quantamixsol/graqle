"""Plan-as-Graph types for graq_plan: governance-gated DAG execution plans.

# ── graqle:intelligence ──
# module: graqle.core.plan
# risk: LOW (impact radius: 0 modules — new file, zero blast radius)
# dependencies: __future__, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

These types are intentionally separate from types.py (257-module blast radius).
New module = zero regressions. See rationale.

Usage:
    plan = ExecutionPlan(
        goal="Refactor SyncEngine.push() for error handling",
        steps=[PlanStep(...)],
        estimated_cost_usd=0.02,
        risk_level="MEDIUM",
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    """A single step in an execution plan DAG.

    Each step maps to one or more MCP tool calls. Steps are ordered by
    dependency — steps with no ``depends_on`` can run in parallel.
    """

    step_id: str
    tool: str
    description: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    # Governance fields
    risk_level: str = "LOW"          # LOW | MEDIUM | HIGH | CRITICAL
    requires_approval: bool = False   # True if human-in-the-loop required
    gate_name: str = ""               # output gate to validate before proceeding
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "description": self.description,
            "args": self.args,
            "depends_on": self.depends_on,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "gate_name": self.gate_name,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass
class GovernanceCheckpoint:
    """An embedded governance check within an execution plan.

    Checkpoints are placed before high-risk steps. The plan will pause
    and surface the checkpoint result to the caller before proceeding.
    """

    checkpoint_id: str
    before_step_id: str
    check_type: str           # "preflight" | "impact" | "gate" | "approval"
    description: str
    blocking: bool = True     # If True, plan halts if checkpoint fails

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "before_step_id": self.before_step_id,
            "check_type": self.check_type,
            "description": self.description,
            "blocking": self.blocking,
        }


@dataclass
class ExecutionPlan:
    """A governance-gated DAG execution plan produced by graq_plan.

    The plan is emitted BEFORE any tool executes. The caller reviews it,
    then passes ``plan_id`` to graq_workflow to execute.

    Plans are written as ``ExecutionPlan`` nodes into the knowledge graph
    so the reasoning engine can reason *about the plan itself*.
    """

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    checkpoints: list[GovernanceCheckpoint] = field(default_factory=list)
    # Risk summary
    risk_level: str = "LOW"              # overall plan risk
    estimated_cost_usd: float = 0.0
    estimated_steps: int = 0
    affected_files: list[str] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    # Metadata
    plan_id: str = ""
    requires_approval: bool = False
    decomposition_confidence: float = 0.0  # 0.0-1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "risk_level": self.risk_level,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_steps": len(self.steps),
            "affected_files": self.affected_files,
            "affected_modules": self.affected_modules,
            "requires_approval": self.requires_approval,
            "decomposition_confidence": self.decomposition_confidence,
            "total_steps": len(self.steps),
            "high_risk_steps": sum(
                1 for s in self.steps if s.risk_level in ("HIGH", "CRITICAL")
            ),
            "approval_required_steps": sum(
                1 for s in self.steps if s.requires_approval
            ),
        }
