"""Tests for graq_plan Phase 6 — goal decomposition + governance-gated DAG plans.

# ── graqle:intelligence ──
# module: tests.test_generation.test_phase_plan
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, json, unittest.mock, graqle.core.plan, graqle.plugins.mcp_dev_server
# constraints: none
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.core.plan import ExecutionPlan, GovernanceCheckpoint, PlanStep
from graqle.ontology.domains.coding import (
    CODING_ENTITY_SHAPES,
    CODING_OUTPUT_GATES,
    CODING_RELATIONSHIP_SHAPES,
    CODING_SKILL_MAP,
    CODING_SKILLS,
    register_coding_domain,
)
from graqle.ontology.domain_registry import DomainRegistry
from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# Plan Types Tests
# ---------------------------------------------------------------------------

class TestPlanStep:
    def test_plan_step_to_dict_required_fields(self) -> None:
        step = PlanStep(step_id="s1", tool="graq_impact", description="Run impact")
        d = step.to_dict()
        assert d["step_id"] == "s1"
        assert d["tool"] == "graq_impact"
        assert d["description"] == "Run impact"
        assert d["risk_level"] == "LOW"
        assert d["requires_approval"] is False
        assert d["depends_on"] == []

    def test_plan_step_depends_on_and_risk(self) -> None:
        step = PlanStep(
            step_id="s2",
            tool="graq_edit",
            description="Apply diff",
            depends_on=["s1"],
            risk_level="HIGH",
            requires_approval=True,
            gate_name="validate_diff_format",
            estimated_cost_usd=0.01,
        )
        d = step.to_dict()
        assert d["depends_on"] == ["s1"]
        assert d["risk_level"] == "HIGH"
        assert d["requires_approval"] is True
        assert d["gate_name"] == "validate_diff_format"
        assert d["estimated_cost_usd"] == 0.01


class TestGovernanceCheckpoint:
    def test_checkpoint_to_dict(self) -> None:
        cp = GovernanceCheckpoint(
            checkpoint_id="cp_1",
            before_step_id="s3",
            check_type="approval",
            description="Review diff before applying",
            blocking=True,
        )
        d = cp.to_dict()
        assert d["checkpoint_id"] == "cp_1"
        assert d["before_step_id"] == "s3"
        assert d["check_type"] == "approval"
        assert d["blocking"] is True

    def test_checkpoint_non_blocking(self) -> None:
        cp = GovernanceCheckpoint(
            checkpoint_id="cp_2",
            before_step_id="s4",
            check_type="preflight",
            description="Advisory preflight",
            blocking=False,
        )
        assert cp.blocking is False
        assert cp.to_dict()["blocking"] is False


class TestExecutionPlan:
    def test_execution_plan_to_dict_empty(self) -> None:
        plan = ExecutionPlan(goal="Refactor X", plan_id="plan_abc123")
        d = plan.to_dict()
        assert d["goal"] == "Refactor X"
        assert d["plan_id"] == "plan_abc123"
        assert d["steps"] == []
        assert d["checkpoints"] == []
        assert d["total_steps"] == 0
        assert d["high_risk_steps"] == 0
        assert d["approval_required_steps"] == 0

    def test_execution_plan_counts_high_risk_steps(self) -> None:
        plan = ExecutionPlan(
            goal="Big refactor",
            plan_id="plan_xyz",
            steps=[
                PlanStep("s1", "graq_impact", "Impact", risk_level="LOW"),
                PlanStep("s2", "graq_edit", "Edit", risk_level="HIGH", requires_approval=True),
                PlanStep("s3", "graq_edit", "Edit 2", risk_level="CRITICAL", requires_approval=True),
                PlanStep("s4", "graq_test", "Test", risk_level="LOW"),
            ],
        )
        d = plan.to_dict()
        assert d["total_steps"] == 4
        assert d["high_risk_steps"] == 2  # HIGH + CRITICAL
        assert d["approval_required_steps"] == 2

    def test_execution_plan_with_checkpoints(self) -> None:
        cp = GovernanceCheckpoint("cp1", "s2", "approval", "Review before apply")
        plan = ExecutionPlan(
            goal="Generate tests",
            plan_id="plan_001",
            steps=[PlanStep("s1", "graq_generate", "Generate")],
            checkpoints=[cp],
        )
        d = plan.to_dict()
        assert len(d["checkpoints"]) == 1
        assert d["checkpoints"][0]["checkpoint_id"] == "cp1"


# ---------------------------------------------------------------------------
# Ontology Phase 6 Tests
# ---------------------------------------------------------------------------

class TestCodingOntologyPhase6:
    def test_goal_decomposition_skill_exists(self) -> None:
        assert "GOAL_DECOMPOSITION" in CODING_SKILLS

    def test_skill_count_is_13(self) -> None:
        # Phase 7 adds PERFORMANCE_PROFILING: 13 → 14
        assert len(CODING_SKILLS) == 14

    def test_execution_plan_entity_exists(self) -> None:
        assert "ExecutionPlan" in CODING_ENTITY_SHAPES
        shape = CODING_ENTITY_SHAPES["ExecutionPlan"]
        assert "required" in shape
        assert "goal" in shape["required"]
        assert "plan_id" in shape["required"]

    def test_planned_by_relationship_exists(self) -> None:
        assert "PLANNED_BY" in CODING_RELATIONSHIP_SHAPES
        rel = CODING_RELATIONSHIP_SHAPES["PLANNED_BY"]
        assert "ExecutionPlan" in rel["range"]

    def test_validate_plan_format_gate_exists(self) -> None:
        assert "validate_plan_format" in CODING_OUTPUT_GATES
        gate = CODING_OUTPUT_GATES["validate_plan_format"]
        assert "plan_id" in gate["required"]
        assert "goal" in gate["required"]
        assert "steps" in gate["required"]

    def test_output_gate_count_is_11(self) -> None:
        # Phase 7 adds validate_profile_output: 11 → 12
        assert len(CODING_OUTPUT_GATES) == 12

    def test_execution_plan_in_skill_map(self) -> None:
        assert "ExecutionPlan" in CODING_SKILL_MAP
        assert "GOAL_DECOMPOSITION" in CODING_SKILL_MAP["ExecutionPlan"]

    def test_register_coding_domain_phase6(self) -> None:
        registry = DomainRegistry()
        register_coding_domain(registry)
        domain = registry.get_domain("coding")
        assert domain is not None
        assert "ExecutionPlan" in domain.valid_entity_types


# ---------------------------------------------------------------------------
# graq_plan Tool Definition Tests
# ---------------------------------------------------------------------------

class TestGraqPlanToolDefinition:
    def test_graq_plan_in_tool_definitions(self) -> None:
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_plan" in names
        assert "kogni_plan" in names

    def test_graq_plan_schema_has_required_goal(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_plan")
        schema = tool["inputSchema"]
        assert "goal" in schema["properties"]
        assert schema["required"] == ["goal"]

    def test_graq_plan_schema_has_optional_params(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_plan")
        props = tool["inputSchema"]["properties"]
        assert "scope" in props
        assert "max_steps" in props
        assert "include_tests" in props
        assert "require_approval_threshold" in props
        assert "dry_run" in props

    def test_tool_count_is_110(self) -> None:
        # Phase 7: +graq_profile + kogni_profile = 110 → 112
        assert len(TOOL_DEFINITIONS) == 112

    def test_graq_plan_not_in_write_tools(self) -> None:
        """graq_plan is read-only — must NOT be in _WRITE_TOOLS."""
        from graqle.plugins.mcp_dev_server import _WRITE_TOOLS
        assert "graq_plan" not in _WRITE_TOOLS
        assert "kogni_plan" not in _WRITE_TOOLS


# ---------------------------------------------------------------------------
# graq_plan Handler Tests
# ---------------------------------------------------------------------------

def _build_mock_server(preloaded_graph=None) -> object:
    """Build a minimal KogniDevServer instance for handler testing."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    server = KogniDevServer.__new__(KogniDevServer)
    server._graph = preloaded_graph
    server._graph_file = "graqle.json" if preloaded_graph else None
    server._graph_mtime = 9999999999.0
    server._config = None
    server._config_path = "graqle.yaml"
    server._read_only = False
    return server


class TestGraqPlanHandler:
    @pytest.mark.asyncio
    async def test_plan_requires_goal(self) -> None:
        server = _build_mock_server()
        result = json.loads(await server._handle_plan({}))
        assert "error" in result
        assert "goal" in result["error"]

    @pytest.mark.asyncio
    async def test_dry_run_returns_plan_without_graph(self) -> None:
        server = _build_mock_server()
        result = json.loads(await server._handle_plan({
            "goal": "Add error handling to SyncEngine.push()",
            "dry_run": True,
        }))
        assert result["dry_run"] is True
        assert "plan" in result
        plan = result["plan"]
        assert plan["goal"] == "Add error handling to SyncEngine.push()"
        assert len(plan["plan_id"]) > 0
        assert plan["total_steps"] >= 2

    @pytest.mark.asyncio
    async def test_dry_run_plan_includes_test_step_by_default(self) -> None:
        server = _build_mock_server()
        result = json.loads(await server._handle_plan({
            "goal": "Refactor data model",
            "dry_run": True,
            "include_tests": True,
        }))
        steps = result["plan"]["steps"]
        tools = [s["tool"] for s in steps]
        assert "graq_test" in tools

    @pytest.mark.asyncio
    async def test_dry_run_no_test_step_when_disabled(self) -> None:
        server = _build_mock_server()
        result = json.loads(await server._handle_plan({
            "goal": "Quick analysis",
            "dry_run": True,
            "include_tests": False,
        }))
        steps = result["plan"]["steps"]
        tools = [s["tool"] for s in steps]
        assert "graq_test" not in tools

    @pytest.mark.asyncio
    async def test_dry_run_plan_has_valid_step_structure(self) -> None:
        server = _build_mock_server()
        result = json.loads(await server._handle_plan({
            "goal": "Fix bug in payment handler",
            "dry_run": True,
        }))
        for step in result["plan"]["steps"]:
            assert "step_id" in step
            assert "tool" in step
            assert "description" in step
            assert "risk_level" in step
            assert step["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    @pytest.mark.asyncio
    async def test_full_plan_with_graph_loaded(self) -> None:
        """Full plan: preloaded mock graph + mocked impact handler."""
        import networkx as nx
        from graqle.core.graph import Graqle

        G = nx.Graph()
        G.add_node("sync_engine", label="SyncEngine", type="Module", description="Sync engine module")
        G.add_node("push", label="push()", type="Function", description="Push method")
        G.add_edge("sync_engine", "push", relationship="CONTAINS")
        mock_graph = Graqle.from_networkx(G)

        server = _build_mock_server(preloaded_graph=mock_graph)

        # Mock _handle_impact to return a simple impact result
        async def _mock_impact(args: dict) -> str:
            return json.dumps({"modules": ["sync_engine", "push"], "files": ["graqle/cloud/sync_engine.py"]})

        server._handle_impact = _mock_impact  # type: ignore[attr-defined]

        result = json.loads(await server._handle_plan({
            "goal": "Add retry logic to SyncEngine.push()",
            "dry_run": False,
        }))

        assert "plan" in result
        plan = result["plan"]
        assert plan["total_steps"] >= 1
        assert "plan_id" in plan
        assert len(plan["plan_id"]) > 0

    @pytest.mark.asyncio
    async def test_plan_id_is_unique_across_calls(self) -> None:
        server = _build_mock_server()
        r1 = json.loads(await server._handle_plan({"goal": "Task A", "dry_run": True}))
        r2 = json.loads(await server._handle_plan({"goal": "Task B", "dry_run": True}))
        assert r1["plan"]["plan_id"] != r2["plan"]["plan_id"]

    @pytest.mark.asyncio
    async def test_analysis_goal_produces_review_step(self) -> None:
        """Analysis goals (review/audit) should produce graq_review step, not graq_edit."""
        import networkx as nx
        from graqle.core.graph import Graqle
        G = nx.Graph()
        G.add_node("app", label="App", type="Module", description="Application module")
        mock_graph = Graqle.from_networkx(G)
        server = _build_mock_server(preloaded_graph=mock_graph)

        async def _mock_impact(args: dict) -> str:
            return json.dumps({})

        server._handle_impact = _mock_impact  # type: ignore[attr-defined]

        result = json.loads(await server._handle_plan({
            "goal": "Review all authentication code for security issues",
            "dry_run": False,
        }))
        plan = result["plan"]
        tools = [s["tool"] for s in plan["steps"]]
        # Analysis goals should not trigger graq_edit
        assert "graq_edit" not in tools


# ---------------------------------------------------------------------------
# Routing Tests
# ---------------------------------------------------------------------------

class TestGraqPlanRouting:
    def test_graq_plan_mapped_to_plan_task(self) -> None:
        from graqle.routing import MCP_TOOL_TO_TASK
        assert MCP_TOOL_TO_TASK["graq_plan"] == "plan"
        assert MCP_TOOL_TO_TASK["kogni_plan"] == "plan"

    def test_plan_task_type_in_recommendations(self) -> None:
        from graqle.routing import TASK_RECOMMENDATIONS
        assert "plan" in TASK_RECOMMENDATIONS
        rec = TASK_RECOMMENDATIONS["plan"]
        assert "description" in rec
        assert "suggested_providers" in rec
        assert len(rec["suggested_providers"]) > 0

    def test_task_count_is_19(self) -> None:
        from graqle.routing import TASK_RECOMMENDATIONS
        # Phase 7: +profile = 19 → 20
        assert len(TASK_RECOMMENDATIONS) == 20
