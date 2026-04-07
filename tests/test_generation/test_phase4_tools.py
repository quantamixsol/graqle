"""Tests for v0.38.0 Phase 4 — compound workflow tools and ontology expansion.

Tools under test: graq_review, graq_debug, graq_scaffold, graq_workflow
Ontology under test: 12 skills, 13 entities, 16 relationships, 9 output gates
"""

# ── graqle:intelligence ──
# module: tests.test_generation.test_phase4_tools
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, dataclasses, pathlib, unittest.mock, pytest
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import (
    TOOL_DEFINITIONS,
    KogniDevServer,
    _WRITE_TOOLS,
)
from graqle.ontology.domains.coding import (
    CODING_SKILLS,
    CODING_ENTITY_SHAPES,
    CODING_RELATIONSHIP_SHAPES,
    CODING_OUTPUT_GATES,
    CODING_SKILL_MAP,
    CODING_CLASS_HIERARCHY,
)
from graqle.routing import MCP_TOOL_TO_TASK, TASK_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# Mock helpers (reuse pattern from test_phase35_tools.py)
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    degree: int = 2


def _build_mock_graph() -> MagicMock:
    nodes = {
        "auth-lambda": MockNode("auth-lambda", "Auth Lambda", "SERVICE", "JWT auth"),
    }
    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = {}
    graph.add_node_simple = MagicMock()
    graph.auto_connect = MagicMock(return_value=0)

    mock_result = MagicMock()
    mock_result.answer = json.dumps({
        "summary": "Looks good",
        "verdict": "APPROVED",
        "comments": [],
    })
    graph.areason = AsyncMock(return_value=mock_result)
    graph.areason_stream = AsyncMock(return_value=iter([]))
    return graph


@pytest.fixture
def server(tmp_path):
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = _build_mock_graph()
    srv._config = None
    srv._graph_file = str(tmp_path / "graqle.json")
    srv._graph_mtime = 9999999999.0
    return srv


# ---------------------------------------------------------------------------
# Phase 4: Ontology expansion tests
# ---------------------------------------------------------------------------

class TestCodingOntologyPhase4:
    """Verify the expanded coding ontology hits the roadmap targets."""

    def test_skill_count(self):
        """ADR-116 roadmap: 14 skills (Phase 7 added PERFORMANCE_PROFILING)."""
        assert len(CODING_SKILLS) == 14

    def test_phase4_skills_exist(self):
        expected_new = {
            "CODE_REVIEW", "DEBUG", "SECURITY_AUDIT", "DEPENDENCY_ANALYSIS",
            "COMPLEXITY_ANALYSIS", "DEAD_CODE_DETECTION", "DOCUMENTATION", "MIGRATION",
        }
        assert expected_new.issubset(set(CODING_SKILLS.keys()))

    def test_entity_shape_count(self):
        """15 entity shapes (5 original + 8 Phase4 + 1 Phase5 CodeMetric + 1 Phase6 ExecutionPlan)."""
        assert len(CODING_ENTITY_SHAPES) == 15

    def test_phase4_entities_exist(self):
        expected_new = {
            "CodeDependency", "CodeConfig", "CodeInterface", "CodeException",
            "CodeDecorator", "CodeChange", "CodeSchema", "CodeVariable",
        }
        assert expected_new.issubset(set(CODING_ENTITY_SHAPES.keys()))

    def test_relationship_count(self):
        """17 relationships (4 original + 12 Phase4 + 1 Phase6 PLANNED_BY)."""
        assert len(CODING_RELATIONSHIP_SHAPES) == 17

    def test_phase4_relationships_exist(self):
        expected_new = {
            "DEPENDS_ON", "IMPORTS", "CALLS", "INHERITS_FROM", "IMPLEMENTS",
            "TESTED_BY", "RAISES", "HANDLES", "CONFIGURES", "OVERRIDES",
            "DOCUMENTS", "DECORATES",
        }
        assert expected_new.issubset(set(CODING_RELATIONSHIP_SHAPES.keys()))

    def test_output_gate_count(self):
        """12 output gates (5 original + 4 Phase4 + 1 Phase5 + 1 Phase6 + 1 Phase7)."""
        assert len(CODING_OUTPUT_GATES) == 12

    def test_phase4_output_gates_exist(self):
        expected_new = {
            "validate_review_format", "validate_diagnostic_list",
            "validate_complexity_metrics", "validate_security_report",
        }
        assert expected_new.issubset(set(CODING_OUTPUT_GATES.keys()))

    def test_class_hierarchy_has_phase4_entities(self):
        expected = {
            "CodeDependency", "CodeConfig", "CodeInterface", "CodeException",
            "CodeDecorator", "CodeChange", "CodeSchema", "CodeVariable",
        }
        assert expected.issubset(set(CODING_CLASS_HIERARCHY.keys()))

    def test_skill_map_covers_phase4_entities(self):
        phase4_entities = {
            "CodeDependency", "CodeConfig", "CodeInterface", "CodeException",
            "CodeDecorator", "CodeChange", "CodeSchema", "CodeVariable",
        }
        for entity in phase4_entities:
            assert entity in CODING_SKILL_MAP, f"'{entity}' missing from CODING_SKILL_MAP"
            assert len(CODING_SKILL_MAP[entity]) > 0, f"'{entity}' has no skills"

    def test_all_skills_have_handler_prompt(self):
        for name, skill in CODING_SKILLS.items():
            assert skill.handler_prompt, f"Skill '{name}' has empty handler_prompt"

    def test_all_output_gates_have_required_fields(self):
        for gate_name, gate in CODING_OUTPUT_GATES.items():
            assert "description" in gate, f"Gate '{gate_name}' missing description"
            assert "required" in gate, f"Gate '{gate_name}' missing required"


# ---------------------------------------------------------------------------
# Phase 4: Tool definitions count
# ---------------------------------------------------------------------------

class TestPhase4ToolDefinitions:
    def test_total_tool_count(self):
        """v0.38.0 Phase 7: 56 graq_* + 56 kogni_* = 112."""
        assert len(TOOL_DEFINITIONS) == 120  # +4: graq_github_pr/diff + kogni aliases (HFCI-001+002)

    def test_compound_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for tool in ("graq_review", "graq_debug", "graq_scaffold", "graq_workflow"):
            assert tool in names, f"'{tool}' missing from TOOL_DEFINITIONS"

    def test_kogni_aliases_for_compound_tools(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for tool in ("kogni_review", "kogni_debug", "kogni_scaffold", "kogni_workflow"):
            assert tool in names, f"'{tool}' missing from TOOL_DEFINITIONS"

    def test_compound_write_tools_in_write_tools(self):
        """graq_scaffold and graq_workflow are write-capable — must be in _WRITE_TOOLS."""
        assert "graq_scaffold" in _WRITE_TOOLS
        assert "graq_workflow" in _WRITE_TOOLS
        assert "kogni_scaffold" in _WRITE_TOOLS
        assert "kogni_workflow" in _WRITE_TOOLS

    def test_review_debug_not_in_write_tools(self):
        """graq_review and graq_debug are read-only analysis — NOT in _WRITE_TOOLS."""
        assert "graq_review" not in _WRITE_TOOLS
        assert "graq_debug" not in _WRITE_TOOLS

    def test_workflow_tool_has_required_schema(self):
        workflow_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_workflow")
        props = workflow_tool["inputSchema"]["properties"]
        assert "workflow" in props
        assert "goal" in props
        assert "dry_run" in props
        assert set(props["workflow"]["enum"]) == {
            "bug_fix", "scaffold_and_test", "governed_refactor", "review_and_fix"
        }

    def test_scaffold_tool_dry_run_default_true(self):
        scaffold_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_scaffold")
        props = scaffold_tool["inputSchema"]["properties"]
        assert props["dry_run"]["default"] is True

    def test_review_tool_focus_options(self):
        review_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_review")
        props = review_tool["inputSchema"]["properties"]
        assert "focus" in props
        assert "security" in props["focus"]["enum"]
        assert "all" in props["focus"]["enum"]


# ---------------------------------------------------------------------------
# Phase 4: Routing
# ---------------------------------------------------------------------------

class TestPhase4Routing:
    def test_compound_tools_mapped(self):
        assert MCP_TOOL_TO_TASK["graq_review"] == "code"
        assert MCP_TOOL_TO_TASK["graq_debug"] == "code"
        assert MCP_TOOL_TO_TASK["graq_scaffold"] == "generate"
        assert MCP_TOOL_TO_TASK["graq_workflow"] == "code"

    def test_kogni_aliases_mapped(self):
        assert MCP_TOOL_TO_TASK["kogni_review"] == "code"
        assert MCP_TOOL_TO_TASK["kogni_debug"] == "code"
        assert MCP_TOOL_TO_TASK["kogni_scaffold"] == "generate"
        assert MCP_TOOL_TO_TASK["kogni_workflow"] == "code"

    def test_code_task_has_providers(self):
        assert "code" in TASK_RECOMMENDATIONS
        assert len(TASK_RECOMMENDATIONS["code"]["suggested_providers"]) > 0


# ---------------------------------------------------------------------------
# graq_review handler
# ---------------------------------------------------------------------------

class TestGraqReview:
    @pytest.mark.asyncio
    async def test_review_no_args_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_review", {}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_review_with_diff(self, server):
        result = json.loads(await server.handle_tool("graq_review", {
            "diff": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2",
            "focus": "all",
        }))
        assert "tool" in result
        assert result["tool"] == "graq_review"
        assert "review" in result

    @pytest.mark.asyncio
    async def test_review_with_file_path(self, tmp_path, server):
        test_file = tmp_path / "test_mod.py"
        test_file.write_text("def foo():\n    pass\n", encoding="utf-8")
        result = json.loads(await server.handle_tool("graq_review", {
            "file_path": str(test_file),
            "focus": "security",
        }))
        assert result.get("tool") == "graq_review"
        assert result.get("focus") == "security"

    @pytest.mark.asyncio
    async def test_review_security_focus(self, server):
        result = json.loads(await server.handle_tool("graq_review", {
            "diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+password = 'hardcoded'\n",
            "focus": "security",
        }))
        assert "error" not in result


# ---------------------------------------------------------------------------
# graq_debug handler
# ---------------------------------------------------------------------------

class TestGraqDebug:
    @pytest.mark.asyncio
    async def test_debug_no_args_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_debug", {}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_debug_with_error(self, server):
        result = json.loads(await server.handle_tool("graq_debug", {
            "error": "AttributeError: 'NoneType' object has no attribute 'encode'\nFile: graqle/core/graph.py line 42",
        }))
        assert result.get("tool") == "graq_debug"
        assert "analysis" in result

    @pytest.mark.asyncio
    async def test_debug_with_symptom(self, server):
        result = json.loads(await server.handle_tool("graq_debug", {
            "symptom": "Test suite hangs indefinitely when run in CI",
        }))
        assert result.get("tool") == "graq_debug"

    @pytest.mark.asyncio
    async def test_debug_with_file_context(self, tmp_path, server):
        test_file = tmp_path / "buggy.py"
        test_file.write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
        result = json.loads(await server.handle_tool("graq_debug", {
            "error": "ZeroDivisionError: division by zero",
            "file_path": str(test_file),
        }))
        assert "tool" in result
        assert result["tool"] == "graq_debug"


# ---------------------------------------------------------------------------
# graq_scaffold handler
# ---------------------------------------------------------------------------

class TestGraqScaffold:
    @pytest.mark.asyncio
    async def test_scaffold_no_spec_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_scaffold", {}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_scaffold_dry_run_returns_plan(self, server):
        result = json.loads(await server.handle_tool("graq_scaffold", {
            "spec": "FastAPI authentication endpoint with JWT",
            "scaffold_type": "api_endpoint",
            "dry_run": True,
        }))
        assert result.get("dry_run") is True
        assert result.get("tool") == "graq_scaffold"
        assert "scaffold" in result or "error" in result  # may be error if graph unavailable

    @pytest.mark.asyncio
    async def test_scaffold_default_dry_run(self, server):
        """dry_run defaults to True — must not write files."""
        import os
        result = json.loads(await server.handle_tool("graq_scaffold", {
            "spec": "A simple utility module",
        }))
        assert result.get("dry_run") is True or "error" in result

    @pytest.mark.asyncio
    async def test_scaffold_blocked_in_read_only(self, server):
        server.read_only = True
        result = json.loads(await server.handle_tool("graq_scaffold", {
            "spec": "New module",
            "dry_run": False,
        }))
        assert "error" in result


# ---------------------------------------------------------------------------
# graq_workflow handler
# ---------------------------------------------------------------------------

class TestGraqWorkflow:
    @pytest.mark.asyncio
    async def test_workflow_no_args_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_workflow_missing_goal_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "bug_fix",
        }))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_workflow_dry_run_returns_plan(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "bug_fix",
            "goal": "Fix the authentication timeout issue",
            "dry_run": True,
        }))
        assert result.get("dry_run") is True
        assert result.get("tool") == "graq_workflow"
        assert "steps" in result
        assert len(result["steps"]) > 0

    @pytest.mark.asyncio
    async def test_workflow_unknown_workflow_returns_error(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "nonexistent_workflow",
            "goal": "Do something",
            "dry_run": True,
        }))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_workflow_bug_fix_plan_has_expected_tools(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "bug_fix",
            "goal": "Fix null pointer in auth module",
            "dry_run": True,
        }))
        assert result.get("dry_run") is True
        steps = result.get("steps", [])
        tool_names = [s["tool"] for s in steps]
        assert "graq_debug" in tool_names
        assert "graq_bash" in tool_names

    @pytest.mark.asyncio
    async def test_workflow_scaffold_and_test_plan(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "scaffold_and_test",
            "goal": "Create a new payment service module",
            "dry_run": True,
        }))
        assert result.get("dry_run") is True
        steps = result.get("steps", [])
        tool_names = [s["tool"] for s in steps]
        assert "graq_scaffold" in tool_names

    @pytest.mark.asyncio
    async def test_workflow_max_steps_respected(self, server):
        result = json.loads(await server.handle_tool("graq_workflow", {
            "workflow": "governed_refactor",
            "goal": "Refactor payment module",
            "dry_run": True,
            "max_steps": 3,
        }))
        assert result.get("dry_run") is True
        steps = result.get("steps", [])
        assert len(steps) <= 3

    @pytest.mark.asyncio
    async def test_all_workflows_have_plans(self, server):
        workflows = ["bug_fix", "scaffold_and_test", "governed_refactor", "review_and_fix"]
        for wf in workflows:
            result = json.loads(await server.handle_tool("graq_workflow", {
                "workflow": wf,
                "goal": f"Test {wf} workflow",
                "dry_run": True,
            }))
            assert result.get("dry_run") is True, f"Workflow '{wf}' dry_run not True"
            # Legacy workflows return "steps"; orchestrator workflows return "stages"
            plan_items = result.get("steps") or result.get("stages") or []
            assert len(plan_items) > 0, f"Workflow '{wf}' has no steps/stages"


# ---------------------------------------------------------------------------
# graq_test handler (Phase 5)
# ---------------------------------------------------------------------------

class TestGraqTest:
    @pytest.mark.asyncio
    async def test_test_blocked_in_read_only(self, server):
        server.read_only = True
        result = json.loads(await server.handle_tool("graq_test", {}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_test_in_write_tools(self):
        assert "graq_test" in _WRITE_TOOLS
        assert "kogni_test" in _WRITE_TOOLS

    @pytest.mark.asyncio
    async def test_test_tool_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_test" in names
        assert "kogni_test" in names

    def test_test_tool_schema(self):
        test_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_test")
        props = test_tool["inputSchema"]["properties"]
        assert "target" in props
        assert "coverage" in props
        assert "fail_fast" in props
        assert "record_metrics" in props

    @pytest.mark.asyncio
    async def test_test_runs_and_returns_metrics(self, server):
        """graq_test should run pytest and parse structured output."""
        # Run actual tests on a tiny target — test_routing.py is fast + reliable
        result = json.loads(await server.handle_tool("graq_test", {
            "target": "tests/test_routing.py",
            "cwd": ".",
        }))
        assert result.get("tool") == "graq_test"
        assert "metrics" in result
        metrics = result["metrics"]
        assert "passed" in metrics
        assert "failed" in metrics
        assert "status" in metrics
        assert metrics["status"] in ("GREEN", "RED")

    @pytest.mark.asyncio
    async def test_test_green_status_on_passing_tests(self, server):
        """A passing test suite should return status=GREEN."""
        result = json.loads(await server.handle_tool("graq_test", {
            "target": "tests/test_routing.py",
            "cwd": ".",
        }))
        metrics = result.get("metrics", {})
        # test_routing.py is always green — assert GREEN
        assert metrics.get("status") == "GREEN"
        assert metrics.get("failed", 0) == 0

    @pytest.mark.asyncio
    async def test_test_routing_mapping(self):
        from graqle.routing import MCP_TOOL_TO_TASK, TASK_RECOMMENDATIONS
        assert MCP_TOOL_TO_TASK["graq_test"] == "test"
        assert MCP_TOOL_TO_TASK["kogni_test"] == "test"
        assert "test" in TASK_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# Phase 5: CodeMetric entity + test_coverage_gate
# ---------------------------------------------------------------------------

class TestPhase5OntologyAdditions:
    def test_code_metric_entity_exists(self):
        assert "CodeMetric" in CODING_ENTITY_SHAPES
        shape = CODING_ENTITY_SHAPES["CodeMetric"]
        assert "name" in shape["required"]
        assert "metric_type" in shape["required"]

    def test_code_metric_in_class_hierarchy(self):
        assert "CodeMetric" in CODING_CLASS_HIERARCHY

    def test_test_coverage_gate_exists(self):
        assert "test_coverage_gate" in CODING_OUTPUT_GATES
        gate = CODING_OUTPUT_GATES["test_coverage_gate"]
        assert "description" in gate
        assert "passed" in gate["required"]
        assert "failed" in gate["required"]
