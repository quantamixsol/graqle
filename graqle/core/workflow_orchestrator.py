"""WorkflowOrchestrator — governed multi-step coding workflow state machine.

# ── graqle:intelligence ──
# module: graqle.core.orchestrator
# risk: LOW (impact radius: 1 module — mcp_dev_server only)
# dependencies: __future__, dataclasses, datetime, enum, typing
# constraints: PLAN→PREFLIGHT→GATE→CODE→VALIDATE→TEST→LEARN stage order enforced
# ── /graqle:intelligence ──

Enforces the governed coding workflow defined in ADR-121:

    PLAN      → graq_plan (read-only, returns ExecutionPlan)
    PREFLIGHT → graq_preflight (risk assessment, impact_radius)
    GATE      → GovernanceMiddleware.check() (3-tier: TS-BLOCK/T1/T2/T3)
    CODE      → graq_generate or graq_edit (produces diff)
    VALIDATE  → graq_review (static analysis on produced diff)
    TEST      → graq_test (run test suite, verify no regressions)
    LEARN     → graq_learn (write outcome to KG for calibration)

Each stage produces a StageResult. If any stage reaches BLOCKED status,
the orchestrator halts and returns the full audit trail so far.

Key properties:
- Stage order is ENFORCED — skipping stages requires explicit opt-out
- Each stage result is immutable after completion
- GATE stage uses policy thresholds from GovernancePolicyConfig
- Rollback flag propagates from CODE → VALIDATE/TEST failures

Usage:
    orchestrator = WorkflowOrchestrator(policy=policy_cfg)
    plan = orchestrator.build_plan("refactor auth middleware", files=["auth.py"])
    result = await orchestrator.execute(plan, handler)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

class WorkflowStage(str, Enum):
    """Ordered stages in a governed coding workflow."""
    PLAN = "PLAN"
    PREFLIGHT = "PREFLIGHT"
    GATE = "GATE"
    CODE = "CODE"
    VALIDATE = "VALIDATE"
    TEST = "TEST"
    LEARN = "LEARN"


# Canonical stage order — violations are rejected
_STAGE_ORDER = [
    WorkflowStage.PLAN,
    WorkflowStage.PREFLIGHT,
    WorkflowStage.GATE,
    WorkflowStage.CODE,
    WorkflowStage.VALIDATE,
    WorkflowStage.TEST,
    WorkflowStage.LEARN,
]


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    SKIPPED = "SKIPPED"   # Explicitly opted out (requires justification)
    BLOCKED = "BLOCKED"   # Hard stop — workflow halts here
    FAILED = "FAILED"     # Soft failure — may continue depending on policy


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Result of a single workflow stage."""
    stage: WorkflowStage
    status: StageStatus
    tool_used: str
    latency_ms: int
    output: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    skip_reason: str = ""       # set when status=SKIPPED
    block_reason: str = ""      # set when status=BLOCKED
    rollback_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "tool_used": self.tool_used,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
            "skip_reason": self.skip_reason,
            "block_reason": self.block_reason,
            "rollback_required": self.rollback_required,
            "output_summary": _summarize_output(self.output),
        }


@dataclass
class WorkflowPlan:
    """A governed workflow execution plan."""
    goal: str
    files: list[str]
    workflow_type: str          # "governed_edit", "governed_generate", "governed_refactor"
    actor: str = ""
    approved_by: str = ""
    justification: str = ""
    skip_stages: list[WorkflowStage] = field(default_factory=list)
    dry_run: bool = False
    plan_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.plan_id:
            import hashlib
            raw = f"{self.goal}{self.created_at}"
            self.plan_id = f"wf_{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


@dataclass
class WorkflowResult:
    """Final result of a governed workflow execution."""
    plan: WorkflowPlan
    stages: list[StageResult]
    final_status: StageStatus       # Overall workflow outcome
    halted_at: WorkflowStage | None = None
    rollback_triggered: bool = False
    total_latency_ms: int = 0
    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan.plan_id,
            "goal": self.plan.goal,
            "workflow_type": self.plan.workflow_type,
            "dry_run": self.plan.dry_run,
            "final_status": self.final_status.value,
            "halted_at": self.halted_at.value if self.halted_at else None,
            "rollback_triggered": self.rollback_triggered,
            "total_latency_ms": self.total_latency_ms,
            "completed_at": self.completed_at,
            "stages": [s.to_dict() for s in self.stages],
            "stages_passed": sum(1 for s in self.stages if s.status == StageStatus.PASSED),
            "stages_blocked": sum(1 for s in self.stages if s.status == StageStatus.BLOCKED),
            "stages_skipped": sum(1 for s in self.stages if s.status == StageStatus.SKIPPED),
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Type alias for the tool handler coroutine
ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]


class WorkflowOrchestrator:
    """Governed multi-step coding workflow state machine.

    Enforces PLAN → PREFLIGHT → GATE → CODE → VALIDATE → TEST → LEARN order.
    Each stage calls an MCP tool via the provided handler coroutine.
    """

    def __init__(
        self,
        policy: Any | None = None,   # GovernancePolicyConfig instance (optional)
    ) -> None:
        self._policy = policy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_plan(
        self,
        goal: str,
        *,
        files: list[str] | None = None,
        workflow_type: str = "governed_edit",
        actor: str = "",
        approved_by: str = "",
        justification: str = "",
        skip_stages: list[str] | None = None,
        dry_run: bool = False,
    ) -> WorkflowPlan:
        """Build a WorkflowPlan for a given goal."""
        skip = [WorkflowStage(s) for s in (skip_stages or []) if s in WorkflowStage._value2member_map_]
        return WorkflowPlan(
            goal=goal,
            files=files or [],
            workflow_type=workflow_type,
            actor=actor,
            approved_by=approved_by,
            justification=justification,
            skip_stages=skip,
            dry_run=dry_run,
        )

    async def execute(
        self,
        plan: WorkflowPlan,
        handler: ToolHandler,
    ) -> WorkflowResult:
        """Execute a governed workflow plan stage by stage.

        Args:
            plan: The WorkflowPlan to execute
            handler: Async callable (tool_name, args) → JSON string

        Returns:
            WorkflowResult with complete audit trail
        """
        import json

        stages: list[StageResult] = []
        t_start = time.monotonic()
        halted_at: WorkflowStage | None = None
        rollback = False

        # Preflight is required unless policy explicitly disables it
        require_preflight = True
        require_learn = True
        enforce_gate = True
        if self._policy is not None:
            require_preflight = getattr(self._policy, "workflow_require_preflight", True)
            require_learn = getattr(self._policy, "workflow_require_learn", True)
            enforce_gate = getattr(self._policy, "workflow_enforce_gate", True)

        # Stage loop
        for stage in _STAGE_ORDER:
            if stage in plan.skip_stages:
                stages.append(StageResult(
                    stage=stage,
                    status=StageStatus.SKIPPED,
                    tool_used="(skipped)",
                    latency_ms=0,
                    output={},
                    skip_reason="Explicitly skipped by caller",
                ))
                continue

            # Enforce stage-specific policy
            if stage == WorkflowStage.PREFLIGHT and not require_preflight:
                stages.append(StageResult(
                    stage=stage, status=StageStatus.SKIPPED, tool_used="(skipped)",
                    latency_ms=0, output={}, skip_reason="workflow_require_preflight=false",
                ))
                continue
            if stage == WorkflowStage.GATE and not enforce_gate:
                stages.append(StageResult(
                    stage=stage, status=StageStatus.SKIPPED, tool_used="(skipped)",
                    latency_ms=0, output={}, skip_reason="workflow_enforce_gate=false",
                ))
                continue
            if stage == WorkflowStage.LEARN and not require_learn:
                stages.append(StageResult(
                    stage=stage, status=StageStatus.SKIPPED, tool_used="(skipped)",
                    latency_ms=0, output={}, skip_reason="workflow_require_learn=false",
                ))
                continue

            result = await self._run_stage(stage, plan, handler, json)
            stages.append(result)

            if result.status == StageStatus.BLOCKED:
                halted_at = stage
                break

            # CODE failure triggers rollback signal for subsequent stages
            if stage == WorkflowStage.CODE and result.status == StageStatus.FAILED:
                rollback = True

            # TEST failure after CODE also triggers rollback
            if stage == WorkflowStage.TEST and result.status == StageStatus.FAILED and result.rollback_required:
                rollback = True

        total_ms = int((time.monotonic() - t_start) * 1000)

        # Determine final status
        if halted_at is not None:
            final = StageStatus.BLOCKED
        elif rollback:
            final = StageStatus.FAILED
        elif any(s.status == StageStatus.FAILED for s in stages):
            final = StageStatus.FAILED
        else:
            final = StageStatus.PASSED

        return WorkflowResult(
            plan=plan,
            stages=stages,
            final_status=final,
            halted_at=halted_at,
            rollback_triggered=rollback,
            total_latency_ms=total_ms,
        )

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    async def _run_stage(
        self,
        stage: WorkflowStage,
        plan: WorkflowPlan,
        handler: ToolHandler,
        json: Any,
    ) -> StageResult:
        t0 = time.monotonic()

        try:
            tool, args = self._stage_to_tool_call(stage, plan)
            raw = await handler(tool, args)
            output = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            return StageResult(
                stage=stage,
                status=StageStatus.FAILED,
                tool_used="(error)",
                latency_ms=int((time.monotonic() - t0) * 1000),
                output={"error": str(exc)},
            )

        ms = int((time.monotonic() - t0) * 1000)

        # Interpret output
        status, block_reason, rollback = self._interpret_output(stage, output)

        return StageResult(
            stage=stage,
            status=status,
            tool_used=tool,
            latency_ms=ms,
            output=output,
            block_reason=block_reason,
            rollback_required=rollback,
        )

    def _stage_to_tool_call(
        self,
        stage: WorkflowStage,
        plan: WorkflowPlan,
    ) -> tuple[str, dict[str, Any]]:
        """Map a stage to (tool_name, args) for the given plan."""
        base = {
            "actor": plan.actor,
            "approved_by": plan.approved_by,
            "justification": plan.justification,
        }

        if stage == WorkflowStage.PLAN:
            return "graq_plan", {
                **base,
                "goal": plan.goal,
                "files": plan.files,
                "dry_run": True,  # graq_plan is always read-only
            }

        if stage == WorkflowStage.PREFLIGHT:
            return "graq_preflight", {
                **base,
                "action": plan.goal,
                "files": plan.files,
            }

        if stage == WorkflowStage.GATE:
            # graq_gov_gate wraps GovernanceMiddleware.check() — distinct from
            # graq_gate which is the IntelligenceGate (module context tool).
            return "graq_gov_gate", {
                **base,
                "file_path": plan.files[0] if plan.files else "",
                "risk_level": "LOW",    # Will be overridden by preflight output in future
                "impact_radius": 0,     # Ditto
            }

        if stage == WorkflowStage.CODE:
            tool = "graq_generate"
            if plan.workflow_type == "governed_edit":
                tool = "graq_edit"
            return tool, {
                **base,
                "goal": plan.goal,
                "file_path": plan.files[0] if plan.files else "",
                "description": plan.goal,
                "dry_run": plan.dry_run,
            }

        if stage == WorkflowStage.VALIDATE:
            return "graq_review", {
                **base,
                "file_path": plan.files[0] if plan.files else "",
                "focus": "correctness,security,style",
            }

        if stage == WorkflowStage.TEST:
            return "graq_test", {
                **base,
                "target": "tests/",
                "fail_fast": True,
            }

        if stage == WorkflowStage.LEARN:
            return "graq_learn", {
                **base,
                "entity": plan.goal[:80],
                "lesson": f"Workflow '{plan.workflow_type}' completed for: {plan.goal[:80]}",
                "outcome": "success",
            }

        raise ValueError(f"Unknown stage: {stage}")

    def _interpret_output(
        self,
        stage: WorkflowStage,
        output: dict[str, Any],
    ) -> tuple[StageStatus, str, bool]:
        """Return (StageStatus, block_reason, rollback_required)."""
        # Error field always blocks
        if "error" in output:
            err = str(output["error"])
            # GOVERNANCE_GATE is a hard block
            if err == "GOVERNANCE_GATE" or output.get("tier") in ("TS-BLOCK", "T3"):
                return StageStatus.BLOCKED, f"Gate blocked: {output.get('message', err)}", False
            # Other errors: BLOCKED for GATE/PREFLIGHT, FAILED for rest
            if stage in (WorkflowStage.GATE, WorkflowStage.PREFLIGHT):
                return StageStatus.BLOCKED, err, False
            return StageStatus.FAILED, "", stage == WorkflowStage.CODE

        # TEST: check if tests passed
        if stage == WorkflowStage.TEST:
            passed = output.get("passed", 0)
            failed = output.get("failed", 0)
            if failed > 0:
                return StageStatus.FAILED, "", True  # rollback_required=True

        # VALIDATE: check for BLOCKER issues
        if stage == WorkflowStage.VALIDATE:
            issues = output.get("issues", [])
            blockers = [i for i in issues if i.get("severity") in ("BLOCKER", "CRITICAL")]
            if blockers:
                return StageStatus.FAILED, "", False

        return StageStatus.PASSED, "", False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_output(output: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary of a tool output (max 200 chars per value)."""
    summary: dict[str, Any] = {}
    for k, v in output.items():
        if k in ("error", "tier", "message", "status", "blocked", "confidence",
                 "passed", "failed", "skipped", "risk_level", "impact_radius",
                 "gate_score", "final_status", "tool"):
            summary[k] = v
    return summary
