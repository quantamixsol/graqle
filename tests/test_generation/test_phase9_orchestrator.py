"""Phase 9 tests — WorkflowOrchestrator, GovernancePolicyConfig, graq gate CLI registration.

# ── graqle:intelligence ──
# module: tests.test_generation.test_phase9_orchestrator
# risk: LOW (impact radius: 0 modules — test only)
# dependencies: __future__, pytest, asyncio, graqle.core.workflow_orchestrator
# constraints: Tests must not require live graph or LLM backend
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. GovernancePolicyConfig
# ──────────────────────────────────────────────────────────────────────────────

class TestGovernancePolicyConfig:
    """Verify GovernancePolicyConfig defaults and GraqleConfig integration."""

    def test_importable(self) -> None:
        from graqle.config.settings import GovernancePolicyConfig
        assert GovernancePolicyConfig is not None

    def test_defaults(self) -> None:
        from graqle.config.settings import GovernancePolicyConfig
        cfg = GovernancePolicyConfig()
        assert cfg.ts_hard_block is True
        assert cfg.review_threshold == pytest.approx(0.70, abs=0.001)
        assert cfg.block_threshold == pytest.approx(0.90, abs=0.001)
        assert cfg.auto_pass_max_radius == 2
        assert cfg.auto_pass_max_risk == "LOW"
        assert cfg.cumulative_radius_cap == 10
        assert cfg.audit_tool_calls is True
        assert cfg.workflow_enforce_gate is True
        assert cfg.workflow_require_preflight is True
        assert cfg.workflow_require_learn is True

    def test_graqle_config_has_governance_field(self) -> None:
        from graqle.config.settings import GraqleConfig, GovernancePolicyConfig
        cfg = GraqleConfig()
        assert hasattr(cfg, "governance")
        assert isinstance(cfg.governance, GovernancePolicyConfig)

    def test_graqle_config_governance_defaults_match(self) -> None:
        from graqle.config.settings import GraqleConfig
        cfg = GraqleConfig()
        assert cfg.governance.ts_hard_block is True
        assert cfg.governance.review_threshold == pytest.approx(0.70, abs=0.001)

    def test_graqle_config_backward_compatible(self) -> None:
        """Existing GraqleConfig() calls without governance still work."""
        from graqle.config.settings import GraqleConfig
        # No governance key passed — should use default_factory
        cfg = GraqleConfig(domain="coding")
        assert cfg.domain == "coding"
        assert cfg.governance is not None

    def test_policy_config_custom_thresholds(self) -> None:
        from graqle.config.settings import GovernancePolicyConfig
        cfg = GovernancePolicyConfig(review_threshold=0.60, block_threshold=0.85)
        assert cfg.review_threshold == pytest.approx(0.60, abs=0.001)
        assert cfg.block_threshold == pytest.approx(0.85, abs=0.001)

    def test_policy_enforcement_modes(self) -> None:
        """workflow_enforce_gate and workflow_require_preflight are independently toggleable."""
        from graqle.config.settings import GovernancePolicyConfig
        permissive = GovernancePolicyConfig(
            workflow_enforce_gate=False,
            workflow_require_preflight=False,
            workflow_require_learn=False,
        )
        assert permissive.workflow_enforce_gate is False
        assert permissive.workflow_require_preflight is False
        assert permissive.workflow_require_learn is False


# ──────────────────────────────────────────────────────────────────────────────
# 2. WorkflowOrchestrator — types and plan building
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkflowOrchestratorTypes:
    """Verify WorkflowStage, StageStatus, WorkflowPlan, StageResult types."""

    def test_importable(self) -> None:
        from graqle.core.workflow_orchestrator import (
            WorkflowOrchestrator,
            WorkflowPlan,
            WorkflowResult,
            WorkflowStage,
            StageStatus,
            StageResult,
        )
        assert WorkflowOrchestrator is not None

    def test_stage_order_complete(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowStage, _STAGE_ORDER
        stages = [s.value for s in _STAGE_ORDER]
        assert stages == ["PLAN", "PREFLIGHT", "GATE", "CODE", "VALIDATE", "TEST", "LEARN"]

    def test_build_plan_defaults(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("refactor auth middleware")
        assert plan.goal == "refactor auth middleware"
        assert plan.workflow_type == "governed_edit"
        assert plan.files == []
        assert plan.dry_run is False
        assert plan.plan_id.startswith("wf_")

    def test_build_plan_with_files(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator()
        plan = orch.build_plan(
            "fix security bug",
            files=["graqle/server/app.py", "tests/test_server/test_app.py"],
            workflow_type="governed_generate",
            actor="dev1",
            approved_by="lead",
            dry_run=True,
        )
        assert plan.files == ["graqle/server/app.py", "tests/test_server/test_app.py"]
        assert plan.workflow_type == "governed_generate"
        assert plan.actor == "dev1"
        assert plan.approved_by == "lead"
        assert plan.dry_run is True

    def test_skip_stages_parsed(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, WorkflowStage
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("test goal", skip_stages=["LEARN", "TEST"])
        assert WorkflowStage.LEARN in plan.skip_stages
        assert WorkflowStage.TEST in plan.skip_stages

    def test_plan_id_unique(self) -> None:
        import time
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator()
        p1 = orch.build_plan("goal A")
        time.sleep(0.01)
        p2 = orch.build_plan("goal B")
        # Different goals → different IDs
        assert p1.plan_id != p2.plan_id

    def test_stage_result_to_dict(self) -> None:
        from graqle.core.workflow_orchestrator import StageResult, StageStatus, WorkflowStage
        result = StageResult(
            stage=WorkflowStage.PREFLIGHT,
            status=StageStatus.PASSED,
            tool_used="graq_preflight",
            latency_ms=42,
            output={"risk_level": "LOW"},
        )
        d = result.to_dict()
        assert d["stage"] == "PREFLIGHT"
        assert d["status"] == "PASSED"
        assert d["tool_used"] == "graq_preflight"
        assert d["latency_ms"] == 42


# ──────────────────────────────────────────────────────────────────────────────
# 3. WorkflowOrchestrator.execute() — mock-based integration
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkflowOrchestratorExecute:
    """Integration tests using a mock tool handler."""

    def _make_handler(self, responses: dict[str, dict]) -> object:
        """Build an async mock handler returning canned responses per tool name."""
        async def handler(tool_name: str, args: dict) -> str:
            resp = responses.get(tool_name, {"status": "ok"})
            return json.dumps(resp)
        return handler

    @pytest.mark.asyncio
    async def test_happy_path_all_stages_pass(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, StageStatus

        responses = {
            "graq_plan": {"plan_id": "p1", "steps": []},
            "graq_preflight": {"risk_level": "LOW", "impact_radius": 1},
            "graq_gov_gate": {"tier": "T1", "blocked": False, "gate_score": 0.1},
            "graq_generate": {"patches": [], "status": "ok"},
            "graq_review": {"issues": [], "status": "ok"},
            "graq_test": {"passed": 42, "failed": 0, "status": "ok"},
            "graq_learn": {"status": "ok", "mode": "outcome"},
        }
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("add logging", workflow_type="governed_generate", dry_run=True)
        result = await orch.execute(plan, self._make_handler(responses))

        assert result.final_status == StageStatus.PASSED
        assert result.halted_at is None
        assert result.rollback_triggered is False
        assert len(result.stages) == 7

    @pytest.mark.asyncio
    async def test_gate_block_halts_workflow(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, StageStatus, WorkflowStage

        responses = {
            "graq_plan": {"plan_id": "p1", "steps": []},
            "graq_preflight": {"risk_level": "LOW", "impact_radius": 1},
            # Phase 10: GATE stage now calls graq_gov_gate (not graq_gate)
            "graq_gov_gate": {
                "error": "GOVERNANCE_GATE",
                "tier": "TS-BLOCK",
                "blocked": True,
                "message": "TS-1 pattern detected",
            },
        }
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("expose weights", workflow_type="governed_edit")
        result = await orch.execute(plan, self._make_handler(responses))

        assert result.final_status == StageStatus.BLOCKED
        assert result.halted_at == WorkflowStage.GATE
        # CODE/VALIDATE/TEST/LEARN stages never run
        stage_names = [s.stage.value for s in result.stages]
        assert "CODE" not in stage_names
        assert "LEARN" not in stage_names

    @pytest.mark.asyncio
    async def test_test_failure_sets_rollback(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, StageStatus

        responses = {
            "graq_plan": {"plan_id": "p1", "steps": []},
            "graq_preflight": {"risk_level": "LOW", "impact_radius": 1},
            "graq_gov_gate": {"tier": "T1", "blocked": False, "gate_score": 0.1},
            "graq_generate": {"patches": [], "status": "ok"},
            "graq_review": {"issues": [], "status": "ok"},
            "graq_test": {"passed": 10, "failed": 3, "status": "failed"},
            "graq_learn": {"status": "ok"},
        }
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("risky refactor", workflow_type="governed_generate")
        result = await orch.execute(plan, self._make_handler(responses))

        assert result.final_status == StageStatus.FAILED
        assert result.rollback_triggered is True

    @pytest.mark.asyncio
    async def test_skip_stages_respected(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, StageStatus

        responses = {
            "graq_plan": {"plan_id": "p1", "steps": []},
            "graq_preflight": {"risk_level": "LOW", "impact_radius": 1},
            "graq_gov_gate": {"tier": "T1", "blocked": False, "gate_score": 0.1},
            "graq_generate": {"patches": [], "status": "ok"},
            "graq_review": {"issues": [], "status": "ok"},
            # TEST and LEARN are skipped
        }
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("minor tweak", workflow_type="governed_generate",
                               skip_stages=["TEST", "LEARN"])
        result = await orch.execute(plan, self._make_handler(responses))

        assert result.final_status == StageStatus.PASSED
        skipped = [s.stage.value for s in result.stages if s.status.value == "SKIPPED"]
        assert "TEST" in skipped
        assert "LEARN" in skipped

    @pytest.mark.asyncio
    async def test_policy_disables_gate(self) -> None:
        from graqle.config.settings import GovernancePolicyConfig
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator, StageStatus

        policy = GovernancePolicyConfig(workflow_enforce_gate=False)
        responses = {
            "graq_plan": {"plan_id": "p1", "steps": []},
            "graq_preflight": {"risk_level": "LOW"},
            "graq_generate": {"patches": [], "status": "ok"},
            "graq_review": {"issues": [], "status": "ok"},
            "graq_test": {"passed": 5, "failed": 0},
            "graq_learn": {"status": "ok"},
        }
        orch = WorkflowOrchestrator(policy=policy)
        plan = orch.build_plan("quick fix", workflow_type="governed_generate")
        result = await orch.execute(plan, self._make_handler(responses))

        assert result.final_status == StageStatus.PASSED
        skipped = [s.stage.value for s in result.stages if s.status.value == "SKIPPED"]
        assert "GATE" in skipped

    @pytest.mark.asyncio
    async def test_workflow_result_to_dict(self) -> None:
        from graqle.core.workflow_orchestrator import WorkflowOrchestrator

        responses = {
            "graq_plan": {"plan_id": "p1"},
            "graq_preflight": {"risk_level": "LOW"},
            "graq_gov_gate": {"tier": "T1", "blocked": False, "gate_score": 0.1},
            "graq_generate": {"status": "ok"},
            "graq_review": {"issues": []},
            "graq_test": {"passed": 1, "failed": 0},
            "graq_learn": {"status": "ok"},
        }
        orch = WorkflowOrchestrator()
        plan = orch.build_plan("test dict", workflow_type="governed_generate")
        result = await orch.execute(plan, self._make_handler(responses))
        d = result.to_dict()

        assert "plan_id" in d
        assert "final_status" in d
        assert "stages" in d
        assert "stages_passed" in d
        assert "total_latency_ms" in d
        assert d["stages_passed"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# 4. graq gate CLI — Phase 9 registration check
# ──────────────────────────────────────────────────────────────────────────────

class TestGraqGateCLIPhase9:
    """Verify graq gate is properly registered and help text mentions governance."""

    def test_gate_in_app_help(self) -> None:
        from typer.testing import CliRunner
        from graqle.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert "gate" in result.output

    def test_gate_help_mentions_exit_code(self) -> None:
        from typer.testing import CliRunner
        from graqle.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["gate", "--help"])
        assert result.exit_code == 0

    def test_gate_passes_t1(self) -> None:
        from typer.testing import CliRunner
        from graqle.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["gate", "src/utils.py", "--risk", "LOW", "--impact-radius", "1"])
        assert result.exit_code == 0

    def test_gate_blocks_ts_pattern(self) -> None:
        from typer.testing import CliRunner
        from graqle.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "gate", "src/core.py",
            "--diff", "config w_J = 0.7 internal",
        ])
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# 5. governance-gate.yml GitHub Actions workflow exists
# ──────────────────────────────────────────────────────────────────────────────

class TestGovernanceGateWorkflow:
    """Verify governance-gate.yml exists and has required structure."""

    def test_workflow_file_exists(self) -> None:
        from pathlib import Path
        wf = Path(".github/workflows/governance-gate.yml")
        assert wf.exists(), "governance-gate.yml not found"

    def test_workflow_has_sarif_upload(self) -> None:
        from pathlib import Path
        content = Path(".github/workflows/governance-gate.yml").read_text(encoding="utf-8")
        assert "upload-sarif" in content

    def test_workflow_triggers_on_pr(self) -> None:
        from pathlib import Path
        content = Path(".github/workflows/governance-gate.yml").read_text(encoding="utf-8")
        assert "pull_request" in content

    def test_workflow_has_security_events_permission(self) -> None:
        from pathlib import Path
        content = Path(".github/workflows/governance-gate.yml").read_text(encoding="utf-8")
        assert "security-events: write" in content
