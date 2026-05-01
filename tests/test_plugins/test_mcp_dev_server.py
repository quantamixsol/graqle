"""Tests for graqle.plugins.mcp_dev_server — KogniDevServer (7-tool MCP server)."""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_mcp_dev_server
# risk: HIGH (impact radius: 0 modules)
# dependencies: __future__, json, dataclasses, typing, mock +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import (
    _SENSITIVE_KEYS,
    TOOL_DEFINITIONS,
    KogniDevServer,
)

# ---------------------------------------------------------------------------
# Mock graph objects (same pattern as test_mcp_server.py)
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    degree: int = 2
    status: str = "ACTIVE"


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float = 1.0


@dataclass
class MockStats:
    total_nodes: int = 3
    total_edges: int = 2
    avg_degree: float = 1.33
    density: float = 0.67
    connected_components: int = 1
    hub_nodes: list = field(default_factory=lambda: ["auth-lambda"])


def _build_mock_graph() -> MagicMock:
    """Build a small mock knowledge graph."""
    nodes = {
        "auth-lambda": MockNode(
            id="auth-lambda",
            label="Auth Lambda",
            entity_type="service",
            description="JWT verification and user authentication for the EU region.",
            properties={"runtime": "python3.11", "password": "secret123"},
        ),
        "users-table": MockNode(
            id="users-table",
            label="Users Table",
            entity_type="database",
            description="DynamoDB table storing user profiles and workspace membership.",
            properties={"table": "users-eu"},
        ),
        "lesson-cors": MockNode(
            id="lesson-cors",
            label="CORS Double-Header Bug",
            entity_type="LESSON",
            description="Duplicate CORS headers cause browser rejection. Severity: CRITICAL.",
            properties={"severity": "CRITICAL", "hits": 5},
        ),
    }

    edges = {
        "e1": MockEdge(source_id="auth-lambda", target_id="users-table", relationship="READS_FROM"),
        "e2": MockEdge(source_id="auth-lambda", target_id="lesson-cors", relationship="HAS_LESSON"),
    }

    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    graph.stats = MockStats()
    return graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graph():
    return _build_mock_graph()


@pytest.fixture
def server(mock_graph):
    """KogniDevServer with graph pre-injected."""
    import threading
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = mock_graph
    srv._config = None
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0  # Far future — prevent hot-reload in tests
    # v0.46.8: lazy KG load state (bypassed by __new__)
    srv._kg_load_lock = threading.Lock()
    srv._kg_loaded = threading.Event()
    srv._kg_load_error = None
    srv._kg_load_state = "LOADED"  # Pre-injected graph = already loaded
    return srv


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_tools_defined(self):
        assert len(TOOL_DEFINITIONS) >= 130  # floor check: 130 is the minimum expected count; additive tool growth is allowed (CG-04 phase 0)

    def test_expected_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected_graq = {
            "graq_context",
            "graq_inspect",
            "graq_reason",
            "graq_reason_batch",
            "graq_preflight",
            "graq_lessons",
            "graq_impact",
            "graq_safety_check",
            "graq_learn",
            "graq_predict",
            "graq_reload",
            "graq_audit",
            "graq_runtime",
            "graq_route",
            "graq_lifecycle",
            "graq_drace",
            "graq_gate",
            "graq_scorch_audit",
            "graq_scorch_behavioral",
            "graq_scorch_report",
            "graq_scorch_a11y",
            "graq_scorch_perf",
            "graq_scorch_seo",
            "graq_scorch_mobile",
            "graq_scorch_i18n",
            "graq_scorch_security",
            "graq_scorch_conversion",
            "graq_scorch_brand",
            "graq_scorch_auth_flow",
            "graq_scorch_diff",
            "graq_phantom_browse",
            "graq_phantom_click",
            "graq_phantom_type",
            "graq_phantom_screenshot",
            "graq_phantom_audit",
            "graq_phantom_flow",
            "graq_phantom_discover",
            "graq_phantom_session",
            "graq_generate",    # v0.38.0
            "graq_edit",        # v0.38.0
            # Phase 3.5: file system + git tools
            "graq_read",
            "graq_write",
            "graq_grep",
            "graq_glob",
            "graq_bash",
            "graq_git_status",
            "graq_git_diff",
            "graq_git_log",
            "graq_git_commit",
            "graq_git_branch",
            # HFCI-001+002: GitHub PR tools
            "graq_github_pr",
            "graq_github_diff",
            # Phase 4: compound workflow tools
            "graq_review",
            "graq_debug",
            "graq_scaffold",
            "graq_workflow",
            # Phase 5: test execution
            "graq_test",
            # Phase 6: agent planning
            "graq_plan",
            # Phase 7: performance profiling
            "graq_profile",
            # Phase 10: governance gate MCP tool
            "graq_gov_gate",
            # R6: correction tool
            "graq_correct",
            # v0.44.1: autonomous loop
            "graq_auto",
            # v0.45.1: capability gap hotfixes
            "graq_vendor",
            "graq_web_search",
            "graq_gcc_status",
            "graq_gate_status",
            "graq_gate_install",
            "graq_ingest",
            # v0.46.4: governed todo list
            "graq_todo",
            # v0.47.0: deterministic insertion engine (CG-DIF-02)
            "graq_apply",
            # v0.51.6: T04 write-race diagnostic
            "graq_kg_diag",
            # v0.51.6: T03 chat surface (unblocks VS Code v0.4.9)
            "graq_chat_turn",
            "graq_chat_poll",
            "graq_chat_resume",
            "graq_chat_cancel",
            # CG-17 / G1 (v0.52.0): governed memory-file I/O
            "graq_memory",
            # G2 (v0.52.0): pre-publish governance gate
            "graq_release_gate",
            # G3 (v0.52.0): VS Code Marketplace version check
            "graq_vsce_check",
            # Wave 2 (0.52.0b1): CG-14 config drift + CG-13 deps gate + NS-07 session list
            "graq_config_audit",
            "graq_deps_install",
            "graq_session_list",
            # R20 AGGC (ADR-203): governance score calibration
            "graq_calibrate_governance",
            # NS-08/NS-09 (Wave 3 / 0.52.0): session compact + resume
            "graq_session_compact",
            "graq_session_resume",
            # ADR-208 (0.53.0): graph health check + rebuild MCP tool
            "graq_graph_health",
        }
        expected_kogni = {
            "kogni_context",
            "kogni_inspect",
            "kogni_reason",
            "kogni_reason_batch",
            "kogni_preflight",
            "kogni_lessons",
            "kogni_impact",
            "kogni_safety_check",
            "kogni_learn",
            "kogni_predict",
            "kogni_runtime",
            "kogni_route",
            "kogni_lifecycle",
            "kogni_drace",
            "kogni_gate",
            "kogni_scorch_audit",
            "kogni_scorch_behavioral",
            "kogni_scorch_report",
            "kogni_scorch_a11y",
            "kogni_scorch_perf",
            "kogni_scorch_seo",
            "kogni_scorch_mobile",
            "kogni_scorch_i18n",
            "kogni_scorch_security",
            "kogni_scorch_conversion",
            "kogni_scorch_brand",
            "kogni_scorch_auth_flow",
            "kogni_scorch_diff",
            "kogni_phantom_browse",
            "kogni_phantom_click",
            "kogni_phantom_type",
            "kogni_phantom_screenshot",
            "kogni_phantom_audit",
            "kogni_phantom_flow",
            "kogni_phantom_discover",
            "kogni_phantom_session",
            "kogni_generate",    # v0.38.0
            "kogni_edit",        # v0.38.0
            # Phase 3.5: file system + git tools
            "kogni_read",
            "kogni_write",
            "kogni_grep",
            "kogni_glob",
            "kogni_bash",
            "kogni_git_status",
            "kogni_git_diff",
            "kogni_git_log",
            "kogni_git_commit",
            "kogni_git_branch",
            # HFCI-001+002: GitHub PR tools
            "kogni_github_pr",
            "kogni_github_diff",
            # Phase 4: compound workflow tools
            "kogni_review",
            "kogni_debug",
            "kogni_scaffold",
            "kogni_workflow",
            # Phase 5: test execution
            "kogni_test",
            # Phase 6: agent planning
            "kogni_plan",
            # Phase 7: performance profiling
            "kogni_profile",
            # Phase 10: governance gate MCP tool
            "kogni_gov_gate",
            # R6: correction tool
            "kogni_correct",
            # v0.44.1: autonomous loop
            "kogni_auto",
            # v0.45.1: capability gap hotfixes
            "kogni_vendor",
            "kogni_web_search",
            "kogni_gcc_status",
            "kogni_gate_status",
            "kogni_gate_install",
            "kogni_ingest",
            # v0.46.4: governed todo list
            "kogni_todo",
            # v0.47.0: deterministic insertion engine (CG-DIF-02)
            "kogni_apply",
            # v0.51.6: T04 diagnostic + T03 chat surface aliases
            "kogni_kg_diag",
            "kogni_chat_turn",
            "kogni_chat_poll",
            "kogni_chat_resume",
            "kogni_chat_cancel",
            # CG-17 / G1 (v0.52.0): governed memory-file I/O alias
            "kogni_memory",
            # G2 (v0.52.0): pre-publish governance gate alias
            "kogni_release_gate",
            # G3 (v0.52.0): VS Code Marketplace version check alias
            "kogni_vsce_check",
            # Wave 2 (0.52.0b1): CG-14 config drift + CG-13 deps gate + NS-07 session list aliases
            "kogni_config_audit",
            "kogni_deps_install",
            "kogni_session_list",
            # R20 AGGC (ADR-203): governance score calibration alias
            "kogni_calibrate_governance",
            # NS-08/NS-09 (Wave 3 / 0.52.0): session compact + resume aliases
            "kogni_session_compact",
            "kogni_session_resume",
            # ADR-208 (0.53.0): graph health check + rebuild MCP tool alias
            "kogni_graph_health",
        }
        # 0.53.0: +2 tools (graq_graph_health + kogni_graph_health) = 168 total
        assert expected_graq | expected_kogni == names

    def test_all_tools_have_schema(self):
        for tool in TOOL_DEFINITIONS:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"
            assert "properties" in tool["inputSchema"]

    def test_all_tools_have_description(self):
        for tool in TOOL_DEFINITIONS:
            assert "description" in tool
            assert len(tool["description"]) > 10

    def test_all_tools_are_free(self):
        """All MCP tools are ungated since v0.7.5."""
        tool_names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_preflight" in tool_names
        assert "graq_lessons" in tool_names
        assert "graq_impact" in tool_names
        assert "graq_learn" in tool_names


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------

class TestListTools:
    def test_returns_all_definitions(self, server):
        tools = server.list_tools()
        # 0.53.0: 166 -> 168 (ADR-208: +graq_graph_health + kogni_graph_health)
        assert len(tools) == 168


# ---------------------------------------------------------------------------
# handle_tool dispatch
# ---------------------------------------------------------------------------

class TestHandleTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, server):
        result = await server.handle_tool("graq_nonexistent", {})
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_dispatches_free_tool(self, server):
        """graq_inspect should work without license check."""
        import graqle.plugins.mcp_dev_server as _mds
        with patch.object(server, "_read_active_branch", return_value=None), \
             patch.object(_mds, "_SHACL_GATE_ENABLED", False):
            result = await server.handle_tool("graq_inspect", {"stats": True})
        data = json.loads(result)
        assert "total_nodes" in data
        assert data["total_nodes"] == 3

    @pytest.mark.asyncio
    async def test_pro_tools_ungated(self, server):
        """All tools are free since v0.7.5 — no license gate."""
        # graq_preflight should dispatch directly without any license check
        with patch.object(server, "_handle_preflight", new_callable=AsyncMock) as mock_pf:
            mock_pf.return_value = json.dumps({"status": "ok"})
            result = await server.handle_tool("graq_preflight", {"action": "test"})
        data = json.loads(result)
        assert "error" not in data or "Unknown" not in data.get("error", "")


# ---------------------------------------------------------------------------
# _redact
# ---------------------------------------------------------------------------

class TestRedact:
    def test_removes_sensitive_keys(self, server):
        props = {
            "runtime": "python3.11",
            "password": "secret",
            "api_key": "ak_123",
            "secret": "shh",
            "token": "tok_abc",
            "credential": "cred_xyz",
            "region": "eu-central-1",
        }
        clean = server._redact(props)
        assert "runtime" in clean
        assert "region" in clean
        assert "password" not in clean
        assert "api_key" not in clean
        assert "secret" not in clean
        assert "token" not in clean
        assert "credential" not in clean

    def test_removes_chunks_key(self, server):
        props = {"chunks": [1, 2, 3], "name": "test"}
        clean = server._redact(props)
        assert "chunks" not in clean
        assert "name" in clean


# ---------------------------------------------------------------------------
# _find_node
# ---------------------------------------------------------------------------

class TestFindNode:
    def test_exact_id(self, server):
        node = server._find_node("auth-lambda")
        assert node is not None
        assert node.id == "auth-lambda"

    def test_case_insensitive_label(self, server):
        node = server._find_node("auth lambda")
        assert node is not None
        assert node.label == "Auth Lambda"

    def test_substring_match(self, server):
        node = server._find_node("users")
        assert node is not None
        assert node.id == "users-table"

    def test_no_match(self, server):
        node = server._find_node("nonexistent-xyz-12345")
        assert node is None

    def test_empty_name(self, server):
        node = server._find_node("")
        assert node is None


# ---------------------------------------------------------------------------
# _find_nodes_matching
# ---------------------------------------------------------------------------

class TestFindNodesMatching:
    def test_finds_by_keyword(self, server):
        matches = server._find_nodes_matching("auth")
        assert len(matches) >= 1
        assert any(m.id == "auth-lambda" for m in matches)

    def test_respects_limit(self, server):
        matches = server._find_nodes_matching("table auth lambda", limit=1)
        assert len(matches) <= 1

    def test_no_match(self, server):
        matches = server._find_nodes_matching("zzzzzzzzzzz")
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# graq_inspect handler
# ---------------------------------------------------------------------------

class TestInspectHandler:
    @pytest.mark.asyncio
    async def test_stats_mode(self, server):
        result = await server._handle_inspect({"stats": True})
        data = json.loads(result)
        assert data["total_nodes"] == 3
        assert data["total_edges"] == 2
        assert "entity_types" in data
        assert data["entity_types"]["service"] == 1

    @pytest.mark.asyncio
    async def test_node_inspection(self, server):
        result = await server._handle_inspect({"node_id": "auth-lambda"})
        data = json.loads(result)
        assert data["id"] == "auth-lambda"
        assert data["label"] == "Auth Lambda"
        assert data["type"] == "service"
        assert "neighbors" in data
        # Password should be redacted from properties
        assert "password" not in data.get("properties", {})

    @pytest.mark.asyncio
    async def test_node_not_found(self, server):
        result = await server._handle_inspect({"node_id": "no-such-node"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_default_listing(self, server):
        result = await server._handle_inspect({})
        data = json.loads(result)
        assert "nodes" in data
        assert data["total"] == 3


# ---------------------------------------------------------------------------
# graq_context handler
# ---------------------------------------------------------------------------

class TestContextHandler:
    @pytest.mark.asyncio
    async def test_returns_context(self, server):
        with patch.object(server, "_read_active_branch", return_value="main (ACTIVE)"):
            result = await server._handle_context({"task": "fix auth lambda"})
        data = json.loads(result)
        assert "context" in data
        assert data["graph_loaded"] is True
        assert data["nodes_matched"] >= 1

    @pytest.mark.asyncio
    async def test_missing_task(self, server):
        with patch.object(server, "_read_active_branch", return_value=None):
            result = await server._handle_context({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_level_parameter(self, server):
        with patch.object(server, "_read_active_branch", return_value=None):
            result = await server._handle_context({"task": "auth", "level": "deep"})
        data = json.loads(result)
        assert data["level"] == "deep"


# ---------------------------------------------------------------------------
# graq_reason handler (fallback mode)
# ---------------------------------------------------------------------------

class TestReasonHandler:
    @pytest.mark.asyncio
    async def test_missing_question(self, server):
        result = await server._handle_reason({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_fallback_traversal(self, server):
        # ADR-112: graq_reason has NO silent fallback. When backend fails,
        # returns a hard error so the user knows to fix their config.
        server._graph.areason = AsyncMock(side_effect=RuntimeError("no backend"))
        result = await server._handle_reason({"question": "what does auth lambda do?"})
        data = json.loads(result)
        assert data["error"] == "REASONING_BACKEND_UNAVAILABLE"
        assert data["mode"] == "error"
        assert data["confidence"] == 0.0
        assert "backend_error" in data

    @pytest.mark.asyncio
    async def test_no_matches(self, server):
        # ADR-112: no fallback — backend error returns error dict, not nodes_used
        server._graph.areason = AsyncMock(side_effect=RuntimeError("no backend"))
        result = await server._handle_reason({"question": "zzzzz_no_match_zzzzz"})
        data = json.loads(result)
        assert data["error"] == "REASONING_BACKEND_UNAVAILABLE"
        assert data["confidence"] == 0.0


# ---------------------------------------------------------------------------
# graq_impact handler
# ---------------------------------------------------------------------------

class TestImpactHandler:
    @pytest.mark.asyncio
    async def test_missing_component(self, server):
        result = await server._handle_impact({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_component_not_found(self, server):
        result = await server._handle_impact({"component": "zzzzz_nonexistent"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_impact_found(self, server):
        with patch.object(server, "_bfs_impact", return_value=[
            {"id": "users-table", "label": "Users Table", "depth": 1, "risk": "medium"},
        ]):
            result = await server._handle_impact({"component": "auth-lambda"})
        data = json.loads(result)
        assert data["component"] == "Auth Lambda"
        assert data["affected_count"] >= 1
        assert "overall_risk" in data


# ---------------------------------------------------------------------------
# graq_lessons handler
# ---------------------------------------------------------------------------

class TestLessonsHandler:
    @pytest.mark.asyncio
    async def test_missing_operation(self, server):
        result = await server._handle_lessons({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_lessons(self, server):
        with patch.object(server, "_find_lesson_nodes", return_value=[
            {"label": "CORS Bug", "severity": "CRITICAL", "description": "Duplicate headers", "entity_type": "LESSON"},
        ]):
            result = await server._handle_lessons({"operation": "deployment"})
        data = json.loads(result)
        assert data["count"] == 1
        assert len(data["lessons"]) == 1


# ---------------------------------------------------------------------------
# graq_preflight handler
# ---------------------------------------------------------------------------

class TestPreflightHandler:
    @pytest.mark.asyncio
    async def test_missing_action(self, server):
        result = await server._handle_preflight({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_report(self, server):
        with patch.object(server, "_find_lesson_nodes", return_value=[]):
            result = await server._handle_preflight({"action": "modify auth handler"})
        data = json.loads(result)
        assert "action" in data
        assert "risk_level" in data
        assert "warnings" in data
        assert "lessons" in data

    @pytest.mark.asyncio
    async def test_detects_high_risk(self, server):
        with patch.object(server, "_find_lesson_nodes", return_value=[
            {"label": "CORS", "severity": "CRITICAL", "description": "Bad", "entity_type": "LESSON"},
        ]):
            result = await server._handle_preflight({"action": "deploy lambda"})
        data = json.loads(result)
        assert data["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Sensitive keys constant
# ---------------------------------------------------------------------------

class TestSensitiveKeys:
    def test_contains_expected(self):
        assert "api_key" in _SENSITIVE_KEYS
        assert "secret" in _SENSITIVE_KEYS
        assert "password" in _SENSITIVE_KEYS
        assert "token" in _SENSITIVE_KEYS
        assert "credential" in _SENSITIVE_KEYS


# ---------------------------------------------------------------------------
# Bug 13 — MCP version must match package version (not hardcoded)
# ---------------------------------------------------------------------------

class TestMcpVersion:
    def test_version_matches_package(self):
        """The _version variable in mcp_dev_server must come from graqle.__version__."""
        from graqle.__version__ import __version__ as pkg_version
        from graqle.plugins.mcp_dev_server import _version

        assert _version == pkg_version
        assert _version != "0.0.0", "_version fell back to default; import is broken"


# ---------------------------------------------------------------------------
# Phase 7 — graq_reason_batch predictive mode
# ---------------------------------------------------------------------------

@dataclass
class MockBatchReasonResult:
    answer: str
    confidence: float
    node_count: int = 5
    cost_usd: float = 0.01
    reasoning_mode: str = "full"
    active_nodes: list = field(default_factory=lambda: ["node-a", "node-b"])
    message_trace: list = field(default_factory=list)
    rounds_completed: int = 2


class TestReasonBatchPredictiveMode:
    """Phase 7: graq_reason_batch mode='predictive'."""

    def _make_server(self) -> KogniDevServer:
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._graph = None
        srv._embedder = None
        srv._graph_path = "graqle.json"
        return srv

    @pytest.mark.asyncio
    async def test_batch_predictive_returns_independent_results(self):
        """Batch of 3 queries in predictive mode returns 3 independent results."""
        srv = self._make_server()

        # Patch _handle_predict to return distinct results per query
        call_count = 0

        async def _fake_predict(args: dict) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({
                "answer": f"Answer for: {args['query']}",
                "answer_confidence": 0.8,
                "activation_confidence": 0.5,
                "q_scores": {"feasibility": 0.7, "novelty": 0.5, "goal_alignment": 0.6},
                "stg_class": "auto",
                "embedding_model": "test",
                "rounds": 2,
                "nodes_used": 5,
                "cost_usd": 0.01,
                "active_nodes": [],
                "prediction": {"status": "DRY_RUN", "nodes_added": 0, "edges_added": 0,
                               "anchor_node_id": None, "content_hash": None, "subgraph": None},
            })

        srv._handle_predict = _fake_predict

        result = await srv._handle_reason_batch({
            "questions": ["Q1", "Q2", "Q3"],
            "mode": "predictive",
            "fold_back": False,
        })
        data = json.loads(result)

        assert data["batch_size"] == 3
        assert data["mode"] == "predictive"
        assert len(data["results"]) == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_batch_predictive_fold_back_skips_low_confidence(self):
        """fold_back=True with mixed confidence: only WRITTEN + SKIPPED results, none crash."""
        srv = self._make_server()

        statuses = ["WRITTEN", "SKIPPED_LOW_CONFIDENCE", "WRITTEN"]
        idx = 0

        async def _fake_predict(args: dict) -> str:
            nonlocal idx
            status = statuses[idx % len(statuses)]
            idx += 1
            nodes_added = 2 if status == "WRITTEN" else 0
            return json.dumps({
                "answer": "answer",
                "answer_confidence": 0.8 if status == "WRITTEN" else 0.2,
                "activation_confidence": 0.5,
                "q_scores": {"feasibility": 0.7, "novelty": 0.5, "goal_alignment": 0.6},
                "stg_class": "auto",
                "embedding_model": "test",
                "rounds": 2,
                "nodes_used": 5,
                "cost_usd": 0.01,
                "active_nodes": [],
                "prediction": {"status": status, "nodes_added": nodes_added,
                               "edges_added": nodes_added, "anchor_node_id": "x" if nodes_added else None,
                               "content_hash": None, "subgraph": None},
            })

        srv._handle_predict = _fake_predict

        result = await srv._handle_reason_batch({
            "questions": ["Q1", "Q2", "Q3"],
            "mode": "predictive",
            "fold_back": True,
            "confidence_threshold": 0.65,
        })
        data = json.loads(result)

        assert len(data["results"]) == 3
        statuses_returned = [r.get("prediction", {}).get("status") for r in data["results"]]
        assert "WRITTEN" in statuses_returned
        assert "SKIPPED_LOW_CONFIDENCE" in statuses_returned


class TestInitializeClientInfoBypass:
    """OT-062: Initialize handler detects clientInfo.name == "graqle-vscode"
    and sets per-MCP-session bypass flags for CG-01/02/03 gates.
    Default is fail-closed: missing or unrecognized clientInfo → gates ON.
    """

    def _make_server(self):
        """Build a fresh KogniDevServer without invoking __init__ heavy load."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._mcp_client_name = None
        srv._cg01_bypass = False
        srv._cg02_bypass = False
        srv._cg03_bypass = False
        srv._session_started = False
        srv._plan_active = False
        srv._start_kg_load_background = lambda: None
        return srv

    @pytest.mark.asyncio
    async def test_initialize_with_graqle_vscode_client_sets_all_bypasses(self):
        """When clientInfo.name == "graqle-vscode", all three CG bypasses are set."""
        srv = self._make_server()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "graqle-vscode", "version": "0.1.0"},
                "capabilities": {},
            },
        }
        response = await srv._handle_jsonrpc(request)
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert srv._mcp_client_name == "graqle-vscode"
        assert srv._cg01_bypass is True
        assert srv._cg02_bypass is True
        assert srv._cg03_bypass is True

    @pytest.mark.asyncio
    async def test_initialize_with_unknown_client_keeps_gates_on(self):
        """Unknown clientInfo.name leaves all bypasses False (fail-closed)."""
        srv = self._make_server()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "claude-code", "version": "2.0"},
            },
        }
        await srv._handle_jsonrpc(request)
        assert srv._mcp_client_name == "claude-code"
        assert srv._cg01_bypass is False
        assert srv._cg02_bypass is False
        assert srv._cg03_bypass is False

    @pytest.mark.asyncio
    async def test_initialize_with_missing_clientInfo_keeps_gates_on(self):
        """Missing clientInfo entirely → fail-closed (gates remain on)."""
        srv = self._make_server()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
        await srv._handle_jsonrpc(request)
        assert srv._mcp_client_name is None
        assert srv._cg01_bypass is False
        assert srv._cg02_bypass is False
        assert srv._cg03_bypass is False

    @pytest.mark.asyncio
    async def test_initialize_with_malformed_clientInfo_keeps_gates_on(self):
        """Malformed clientInfo (string instead of dict) → fail-closed."""
        srv = self._make_server()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": "not-a-dict"},
        }
        await srv._handle_jsonrpc(request)
        assert srv._cg01_bypass is False
        assert srv._cg02_bypass is False
        assert srv._cg03_bypass is False

    @pytest.mark.asyncio
    async def test_two_independent_servers_have_independent_bypass_state(self):
        """Two KogniDevServer instances on the same process have independent state.
        Proves the bypass flags are session-scoped, not global.
        """
        srv_vscode = self._make_server()
        srv_other = self._make_server()

        vscode_req = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientInfo": {"name": "graqle-vscode"}},
        }
        other_req = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientInfo": {"name": "other-client"}},
        }
        await srv_vscode._handle_jsonrpc(vscode_req)
        await srv_other._handle_jsonrpc(other_req)

        assert srv_vscode._cg01_bypass is True
        assert srv_vscode._cg02_bypass is True
        assert srv_vscode._cg03_bypass is True
        assert srv_other._cg01_bypass is False
        assert srv_other._cg02_bypass is False
        assert srv_other._cg03_bypass is False


class TestBug008ReloadCG01Exempt:
    """BUG-008: graq_reload and kogni_reload must be exempt from CG-01_SESSION_GATE.
    graq_lifecycle(session_start) must call _load_graph_impl() unconditionally.
    """

    def _make_governed_server(self):
        """Build a server with governance enabled and session NOT started."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        from unittest.mock import MagicMock
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._session_started = False
        srv._plan_active = False
        srv._cg01_bypass = False
        srv._cg02_bypass = False
        srv._cg03_bypass = False
        srv._graph = None
        srv._graph_file = None
        srv._graph_mtime = 0.0
        srv._start_kg_load_background = lambda: None
        # Governance config with session gate enabled
        gov = MagicMock()
        gov.session_gate_enabled = True
        gov.plan_mandatory = False
        gov.edit_enforcement = False
        gov.edit_batch_max = 10
        gov.ts_hard_block = False
        config = MagicMock()
        config.governance = gov
        srv._config = config
        return srv

    @pytest.mark.asyncio
    async def test_reload_before_session_start_not_blocked(self):
        """graq_reload must NOT be blocked by CG-01 before session_start."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        from unittest.mock import AsyncMock, patch
        srv = self._make_governed_server()
        # Patch _handle_reload to avoid actual graph loading
        srv._handle_reload = AsyncMock(return_value='{"reloaded": true}')
        srv._inject_tool_hints = lambda name, result: result

        request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "graq_reload", "arguments": {}},
        }
        with patch.object(srv, "_load_graph", return_value=None):
            response = await srv._handle_jsonrpc(request)

        result_text = response.get("result", {}).get("content", [{}])[0].get("text", "")
        assert "CG-01_SESSION_GATE" not in result_text, (
            "graq_reload must be exempt from CG-01 — got blocked before session_start"
        )

    @pytest.mark.asyncio
    async def test_kogni_reload_before_session_start_not_blocked(self):
        """kogni_reload alias must also be exempt from CG-01."""
        from unittest.mock import AsyncMock, patch
        srv = self._make_governed_server()
        srv._handle_reload = AsyncMock(return_value='{"reloaded": true}')
        srv._inject_tool_hints = lambda name, result: result

        request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "kogni_reload", "arguments": {}},
        }
        with patch.object(srv, "_load_graph", return_value=None):
            response = await srv._handle_jsonrpc(request)

        result_text = response.get("result", {}).get("content", [{}])[0].get("text", "")
        assert "CG-01_SESSION_GATE" not in result_text, (
            "kogni_reload must be exempt from CG-01 — got blocked before session_start"
        )

    @pytest.mark.asyncio
    async def test_session_start_calls_load_graph_impl(self):
        """graq_lifecycle(session_start) must call _load_graph_impl(), not _load_graph()."""
        from graqle.plugins.mcp_dev_server import KogniDevServer
        from unittest.mock import MagicMock, patch
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._session_started = False
        srv._cg01_bypass = False
        srv._config = MagicMock()
        srv._config.governance = MagicMock()
        srv._config.governance.session_gate_enabled = False

        mock_graph = MagicMock()
        mock_graph.stats.total_nodes = 100
        mock_graph.stats.total_edges = 200
        mock_graph.stats.connected_components = 5
        mock_graph.stats.hub_nodes = []

        impl_called = []

        def fake_impl():
            impl_called.append(True)
            return mock_graph

        srv._load_graph_impl = fake_impl
        srv._load_graph = lambda: mock_graph
        srv._check_backend_status = lambda g: {"status": "ok"}
        srv._read_active_branch = lambda: None
        srv._find_lesson_nodes = lambda *a, **kw: []

        result_json = await srv._handle_lifecycle({"event": "session_start", "context": "", "files": []})
        import json as _json
        result = _json.loads(result_json)

        assert impl_called, "session_start must call _load_graph_impl() for unconditional fresh load"
        assert result["graph_loaded"] is True
        assert srv._session_started is True


# ---------------------------------------------------------------------------
# BUG-006: Orphan node detection
# ---------------------------------------------------------------------------

class TestBug006OrphanDetection:
    """BUG-006: graq_inspect(orphans=True) and graq_reason activation_warning for orphan seeds."""

    def _make_server_with_orphans(self):
        import threading
        from unittest.mock import MagicMock
        srv = KogniDevServer.__new__(KogniDevServer)
        srv.config_path = "graqle.yaml"
        srv.read_only = False
        srv._config = None
        srv._graph_file = "graqle.json"
        srv._graph_mtime = 9999999999.0
        srv._kg_load_lock = threading.Lock()
        srv._kg_loaded = threading.Event()
        srv._kg_load_error = None
        srv._kg_load_state = "LOADED"
        srv._gov = None
        nodes = {
            "orphan-lesson": MockNode(id="orphan-lesson", label="Orphan Lesson Node", entity_type="LESSON", description="isolated lesson", degree=0),
            "orphan-knowledge": MockNode(id="orphan-knowledge", label="Orphan Knowledge Node", entity_type="KNOWLEDGE", description="A" * 250, degree=0),
            "connected-lesson": MockNode(id="connected-lesson", label="Connected Lesson Node", entity_type="LESSON", description="connected", degree=2),
            "connected-service": MockNode(id="connected-service", label="Connected Service Node", entity_type="service", description="service", degree=3),
            "no-entity-type": MockNode(id="no-entity-type", label="No Entity Type", entity_type="", description="missing type", degree=0),
            "none-description": MockNode(id="none-description", label="None Description Node", entity_type="LESSON", description=None, degree=0),
        }
        graph = MagicMock()
        graph.nodes = nodes
        srv._graph = graph
        return srv

    def _make_server_no_orphans(self):
        import threading
        from unittest.mock import MagicMock
        srv = KogniDevServer.__new__(KogniDevServer)
        srv.config_path = "graqle.yaml"
        srv.read_only = False
        srv._config = None
        srv._graph_file = "graqle.json"
        srv._graph_mtime = 9999999999.0
        srv._kg_load_lock = threading.Lock()
        srv._kg_loaded = threading.Event()
        srv._kg_load_error = None
        srv._kg_load_state = "LOADED"
        srv._gov = None
        nodes = {
            "connected-1": MockNode(id="connected-1", label="Connected One", entity_type="LESSON", description="connected", degree=2),
            "connected-2": MockNode(id="connected-2", label="Connected Two", entity_type="KNOWLEDGE", description="connected", degree=1),
        }
        graph = MagicMock()
        graph.nodes = nodes
        srv._graph = graph
        return srv

    def _make_server_empty_graph(self):
        import threading
        from unittest.mock import MagicMock
        srv = KogniDevServer.__new__(KogniDevServer)
        srv.config_path = "graqle.yaml"
        srv.read_only = False
        srv._config = None
        srv._graph_file = "graqle.json"
        srv._graph_mtime = 9999999999.0
        srv._kg_load_lock = threading.Lock()
        srv._kg_loaded = threading.Event()
        srv._kg_load_error = None
        srv._kg_load_state = "LOADED"
        srv._gov = None
        graph = MagicMock()
        graph.nodes = {}
        srv._graph = graph
        return srv

    # --- _handle_inspect(orphans=True) ---

    @pytest.mark.asyncio
    async def test_inspect_orphans_returns_lesson_node(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert any(n["id"] == "orphan-lesson" for n in data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_returns_knowledge_node(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert any(n["id"] == "orphan-knowledge" for n in data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_excludes_connected_lesson(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert not any(n["id"] == "connected-lesson" for n in data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_excludes_connected_service(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert not any(n["id"] == "connected-service" for n in data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_excludes_non_kg_entity_type(self):
        """Nodes with entity_type not in (KNOWLEDGE, LESSON) must be excluded."""
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert not any(n["id"] == "no-entity-type" for n in data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_sorted_by_label(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        labels = [n["label"] for n in data["orphans"]]
        assert labels == sorted(labels)

    @pytest.mark.asyncio
    async def test_inspect_orphans_count_matches_list(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert data["orphan_count"] == len(data["orphans"])

    @pytest.mark.asyncio
    async def test_inspect_orphans_hint_present(self):
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert "hint" in data
        assert len(data["hint"]) > 0

    @pytest.mark.asyncio
    async def test_inspect_orphans_empty_graph_returns_empty(self):
        srv = self._make_server_empty_graph()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert data["orphans"] == []
        assert data["orphan_count"] == 0

    @pytest.mark.asyncio
    async def test_inspect_orphans_no_orphans_returns_empty(self):
        srv = self._make_server_no_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        assert data["orphans"] == []
        assert data["orphan_count"] == 0

    @pytest.mark.asyncio
    async def test_inspect_orphans_description_truncated_to_200(self):
        """Description longer than 200 chars must be truncated — no ellipsis added."""
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        knowledge = next(n for n in data["orphans"] if n["id"] == "orphan-knowledge")
        assert len(knowledge["description"]) == 200

    @pytest.mark.asyncio
    async def test_inspect_orphans_none_description_safe(self):
        """None description must not raise — must return empty string."""
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": True}))
        none_desc = next(n for n in data["orphans"] if n["id"] == "none-description")
        assert none_desc["description"] == ""

    @pytest.mark.asyncio
    async def test_inspect_orphans_false_does_not_return_orphan_keys(self):
        """orphans=False must fall through to normal inspect — no orphan_count key."""
        srv = self._make_server_with_orphans()
        data = json.loads(await srv._handle_inspect({"orphans": False}))
        assert "orphan_count" not in data

    # --- _handle_reason activation_warning ---

    def _make_reasoning_result(self, active_nodes, **kwargs):
        from graqle.core.types import ReasoningResult
        defaults = dict(
            query="q", answer="a", confidence=0.8, rounds_completed=2,
            message_trace=[], cost_usd=0.01, latency_ms=100.0,
            backend_status="ok", backend_error=None, reasoning_mode="full",
        )
        defaults.update(kwargs)
        return ReasoningResult(active_nodes=active_nodes, **defaults)

    @pytest.mark.asyncio
    async def test_reason_single_orphan_adds_activation_warning(self):
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["orphan-lesson"]))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" in data
        assert "orphan-lesson" in data["activation_warning"]
        assert "orphan" in data["activation_warning"].lower()

    @pytest.mark.asyncio
    async def test_reason_single_connected_seed_no_warning(self):
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["connected-service"]))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" not in data

    @pytest.mark.asyncio
    async def test_reason_multiple_active_nodes_no_warning(self):
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["orphan-lesson", "connected-service"]))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" not in data

    @pytest.mark.asyncio
    async def test_reason_env_fallback_disabled_suppresses_warning(self):
        from unittest.mock import AsyncMock, patch
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["orphan-lesson"]))
        with patch.dict("os.environ", {"GRAQLE_ORPHAN_FALLBACK": "0"}):
            data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" not in data

    @pytest.mark.asyncio
    async def test_reason_env_fallback_unset_defaults_enabled(self):
        from unittest.mock import AsyncMock, patch
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["orphan-lesson"]))
        env = {k: v for k, v in __import__("os").environ.items() if k != "GRAQLE_ORPHAN_FALLBACK"}
        with patch.dict("os.environ", env, clear=True):
            data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" in data

    @pytest.mark.asyncio
    async def test_reason_node_id_not_in_graph_no_keyerror(self):
        """Node ID returned by areason but absent from graph.nodes must not raise."""
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["nonexistent-node-xyz"]))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert "activation_warning" not in data

    @pytest.mark.asyncio
    async def test_reason_existing_result_fields_preserved(self):
        """Orphan check must not mutate existing result_dict fields."""
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(return_value=self._make_reasoning_result(["orphan-lesson"], answer="exact answer", confidence=0.77))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert data["answer"] == "exact answer"
        assert data["confidence"] == 0.77
        assert data["nodes_used"] == 1

    @pytest.mark.asyncio
    async def test_reason_backend_error_path_unaffected(self):
        """Backend error response must not contain activation_warning."""
        from unittest.mock import AsyncMock
        srv = self._make_server_with_orphans()
        srv._graph.areason = AsyncMock(side_effect=RuntimeError("backend down"))
        data = json.loads(await srv._handle_reason({"question": "q"}))
        assert data["error"] == "REASONING_BACKEND_UNAVAILABLE"
        assert data["confidence"] == 0.0
        assert "activation_warning" not in data


class TestBug003CG02BashExempt:
    """BUG-003: graq_bash dry_run carve-out + graq_reload exempt from CG-02."""

    def _make_server(self, *, plan_mandatory=True, plan_active=False, cg02_bypass=False):
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._gov = None
        srv.read_only = False
        srv._kg_load_state = "LOADED"
        # CG-02 gate reads: getattr(getattr(self, "_config", None), "governance", None)
        srv._config = MagicMock()
        srv._config.governance = MagicMock()
        srv._config.governance.plan_mandatory = plan_mandatory
        srv._config.governance.session_gate_enabled = True
        srv._config.governance.edit_enforcement = False
        # Simulate session already started so CG-01 doesn't fire before CG-02
        srv._session_started = True
        srv._cg01_bypass = False
        srv._plan_active = plan_active
        srv._cg02_bypass = cg02_bypass
        return srv

    # ── graq_bash dry_run carve-out ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_graq_bash_dry_run_true_passes_cg02(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_bash", return_value='{"ok": true}'):
            result = await srv.handle_tool("graq_bash", {"command": "git log", "dry_run": True})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_graq_bash_dry_run_false_blocked_by_cg02(self):
        srv = self._make_server()
        # Use a non-git command to avoid CG-11 gate intercepting before CG-02
        result = await srv.handle_tool("graq_bash", {"command": "echo hello", "dry_run": False})
        assert "CG-02_PLAN_GATE" in result

    @pytest.mark.asyncio
    async def test_kogni_bash_dry_run_true_passes_cg02(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_bash", return_value='{"ok": true}'):
            result = await srv.handle_tool("kogni_bash", {"command": "echo hello", "dry_run": True})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_kogni_bash_dry_run_false_blocked_by_cg02(self):
        srv = self._make_server()
        # Use a non-git command to avoid CG-11 gate intercepting before CG-02
        result = await srv.handle_tool("kogni_bash", {"command": "echo hello", "dry_run": False})
        assert "CG-02_PLAN_GATE" in result

    # ── dry_run edge cases ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_graq_bash_dry_run_key_absent_blocked(self):
        """Missing dry_run key defaults to False — must be blocked."""
        srv = self._make_server()
        result = await srv.handle_tool("graq_bash", {"command": "echo hello"})
        assert "CG-02_PLAN_GATE" in result

    @pytest.mark.asyncio
    async def test_graq_bash_dry_run_string_true_blocked(self):
        """dry_run='true' (string) is not `is True` — must be blocked."""
        srv = self._make_server()
        result = await srv.handle_tool("graq_bash", {"command": "echo hello", "dry_run": "true"})
        assert "CG-02_PLAN_GATE" in result

    # ── graq_reload / kogni_reload exempt ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_graq_reload_exempt_from_cg02(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_reload", return_value='{"status": "reloaded"}'):
            result = await srv.handle_tool("graq_reload", {})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_kogni_reload_exempt_from_cg02(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_reload", return_value='{"status": "reloaded"}'):
            result = await srv.handle_tool("kogni_reload", {})
        assert "CG-02_PLAN_GATE" not in result

    # ── gate inactive paths ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cg02_bypass_allows_bash_dry_run_false(self):
        """When _cg02_bypass=True the gate is skipped entirely."""
        srv = self._make_server(cg02_bypass=True)
        with patch.object(srv, "_handle_bash", return_value='{"ok": true}'):
            result = await srv.handle_tool("graq_bash", {"command": "echo hello", "dry_run": False})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_plan_mandatory_false_gate_not_triggered(self):
        """When plan_mandatory=False the CG-02 gate is entirely inactive."""
        srv = self._make_server(plan_mandatory=False)
        with patch.object(srv, "_handle_bash", return_value='{"ok": true}'):
            result = await srv.handle_tool("graq_bash", {"command": "echo hello", "dry_run": False})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_plan_active_allows_bash_dry_run_false(self):
        """With an active plan, graq_bash(dry_run=False) is allowed through."""
        srv = self._make_server(plan_active=True)
        with patch.object(srv, "_handle_bash", return_value='{"ok": true}'):
            result = await srv.handle_tool("graq_bash", {"command": "echo hello", "dry_run": False})
        assert "CG-02_PLAN_GATE" not in result

    # ── regression: other write tools still blocked ────────────────────────

    @pytest.mark.asyncio
    async def test_graq_edit_still_blocked_without_plan(self):
        srv = self._make_server()
        result = await srv.handle_tool("graq_edit", {"file_path": "test.py", "description": "test"})
        assert "CG-02_PLAN_GATE" in result

    @pytest.mark.asyncio
    async def test_graq_generate_still_blocked_without_plan(self):
        srv = self._make_server()
        result = await srv.handle_tool("graq_generate", {"description": "test"})
        assert "CG-02_PLAN_GATE" in result

    # ── regression: existing exemptions preserved ──────────────────────────

    @pytest.mark.asyncio
    async def test_graq_plan_still_exempt(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_plan", return_value='{"status": "planned"}'):
            result = await srv.handle_tool("graq_plan", {"goal": "test"})
        assert "CG-02_PLAN_GATE" not in result

    @pytest.mark.asyncio
    async def test_graq_learn_still_exempt(self):
        srv = self._make_server()
        with patch.object(srv, "_handle_learn", return_value='{"status": "learned"}'):
            result = await srv.handle_tool("graq_learn", {"action": "test"})
        assert "CG-02_PLAN_GATE" not in result


class TestBug004PipInstallVenvGate:
    """BUG-004: pip install blocked outside venv, allowed inside venv."""

    def _make_server(self):
        import threading
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._gov = None
        srv.read_only = False
        srv._kg_load_state = "LOADED"
        srv._config = MagicMock()
        srv._config.governance = MagicMock()
        srv._config.governance.plan_mandatory = False
        srv._config.governance.session_gate_enabled = False
        srv._config.governance.edit_enforcement = False
        srv._session_started = True
        srv._cg01_bypass = False
        srv._plan_active = True  # plan_mandatory=False so CG-02 inactive
        srv._cg02_bypass = True
        srv._graph = None
        srv._lock = threading.Lock()
        return srv

    @pytest.mark.asyncio
    async def test_pip_install_blocked_outside_venv(self):
        """pip install is blocked when no venv signals are present."""
        import sys
        import os
        srv = self._make_server()
        env_patch = {k: "" for k in ("VIRTUAL_ENV", "CONDA_DEFAULT_ENV") if k in os.environ}
        with patch.object(sys, "prefix", sys.base_prefix), \
             patch.dict(os.environ, env_patch, clear=False):
            for key in ("VIRTUAL_ENV", "CONDA_DEFAULT_ENV"):
                os.environ.pop(key, None)
            result = await srv._handle_bash({"command": "pip install requests", "dry_run": False})
        data = json.loads(result)
        assert data.get("error") == "BLOCKED_COMMAND"
        assert "no active virtualenv" in data.get("message", "")

    @pytest.mark.asyncio
    async def test_pip_install_allowed_inside_venv(self):
        """pip install is allowed when sys.prefix != sys.base_prefix (inside venv)."""
        import sys
        import subprocess
        srv = self._make_server()
        fake_prefix = sys.base_prefix + "_venv"
        with patch.object(sys, "prefix", fake_prefix), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Successfully installed", stderr="", returncode=0)
            result = await srv._handle_bash({"command": "pip install requests", "dry_run": False})
        data = json.loads(result)
        assert data.get("error") is None
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_pip_install_dry_run_skips_venv_check(self):
        """dry_run=True returns before the venv check — always safe."""
        import sys
        srv = self._make_server()
        with patch.object(sys, "prefix", sys.base_prefix):
            result = await srv._handle_bash({"command": "pip install requests", "dry_run": True})
        data = json.loads(result)
        assert data.get("dry_run") is True
        assert data.get("error") is None

    @pytest.mark.asyncio
    async def test_non_pip_command_unaffected(self):
        """Commands without 'pip install' are not subject to the venv gate."""
        import sys
        import subprocess
        srv = self._make_server()
        with patch.object(sys, "prefix", sys.base_prefix), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
            result = await srv._handle_bash({"command": "echo hello", "dry_run": False})
        data = json.loads(result)
        assert data.get("error") is None

    @pytest.mark.asyncio
    async def test_pip_install_upgrade_blocked_outside_venv(self):
        """pip install --upgrade variant also blocked outside venv."""
        import sys
        import os
        srv = self._make_server()
        with patch.object(sys, "prefix", sys.base_prefix):
            for key in ("VIRTUAL_ENV", "CONDA_DEFAULT_ENV"):
                os.environ.pop(key, None)
            result = await srv._handle_bash({"command": "pip install --upgrade graqle", "dry_run": False})
        data = json.loads(result)
        assert data.get("error") == "BLOCKED_COMMAND"
        assert "no active virtualenv" in data.get("message", "")

    @pytest.mark.asyncio
    async def test_pip_install_allowed_via_virtual_env_envvar(self):
        """pip install allowed when VIRTUAL_ENV env var is set even if sys.prefix == base_prefix."""
        import sys
        import subprocess
        import os
        srv = self._make_server()
        with patch.object(sys, "prefix", sys.base_prefix), \
             patch.dict(os.environ, {"VIRTUAL_ENV": "/home/user/.venv"}), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Successfully installed", stderr="", returncode=0)
            result = await srv._handle_bash({"command": "pip install requests", "dry_run": False})
        data = json.loads(result)
        assert data.get("error") is None
        assert data.get("success") is True


class TestBug001WritePathAlias:
    """BUG-001: graq_write accepts 'path' as alias for 'file_path'.

    Covers:
    - _handle_write direct: path alias → file_path (1)
    - _handle_write direct: file_path wins when both given (2)
    - _handle_write direct: neither given → hint in error message (3)
    - _handle_write direct: file_path only (no alias) still works (4)
    - _handle_write direct: kogni_write same logic (5)
    - handle_tool integration: path alias normalised before CG-03 (6)
    - handle_tool integration: file_path wins over path before CG-03 (7)
    - handle_tool integration: non-write tools unaffected by normalisation (8)
    - handle_tool integration: path alias passed through to _handle_write (9)
    - _handle_write: path alias with dry_run=True returns file_path in response (10)
    """

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make_write_server(self):
        """Minimal server with no CG gates active, no real graph."""
        import threading
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._gov = None
        srv.read_only = False
        srv._kg_load_state = "LOADED"
        srv._config = MagicMock()
        srv._config.governance = MagicMock()
        srv._config.governance.plan_mandatory = False
        srv._config.governance.session_gate_enabled = False
        srv._config.governance.edit_enforcement = False
        srv._session_started = True
        srv._cg01_bypass = False
        srv._plan_active = True
        srv._cg02_bypass = True
        srv._cg03_bypass = True
        srv._graph = None
        srv._graph_file = None   # no real graph file → project_root = CWD
        srv._lock = threading.Lock()
        return srv

    def _kg_gate_passthrough(self):
        """Context manager: mock CG-15 + G4 to always allow."""
        from unittest.mock import patch as _patch
        return _patch(
            "graqle.governance.kg_write_gate.check_kg_block",
            return_value=(True, None),
        ), _patch(
            "graqle.governance.kg_write_gate.check_protected_path",
            return_value=(True, None),
        )

    # ── 1. path alias → file_path in _handle_write ───────────────────────────

    @pytest.mark.asyncio
    async def test_path_alias_accepted_by_handle_write(self, tmp_path):
        """Passing 'path' instead of 'file_path' is normalised and accepted."""
        srv = self._make_write_server()
        target = str(tmp_path / "out.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = await srv._handle_write({
                "path": target, "content": "hello", "dry_run": True,
            })
        data = json.loads(result)
        assert data.get("error") is None
        assert data.get("dry_run") is True
        assert target in data.get("file_path", "")

    # ── 2. file_path wins when both given ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_file_path_wins_over_path(self, tmp_path):
        """When both 'path' and 'file_path' given, 'file_path' is used."""
        srv = self._make_write_server()
        winner = str(tmp_path / "winner.txt")
        loser = str(tmp_path / "loser.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = await srv._handle_write({
                "path": loser, "file_path": winner,
                "content": "x", "dry_run": True,
            })
        data = json.loads(result)
        assert data.get("error") is None
        assert winner in data.get("file_path", "")
        assert loser not in data.get("file_path", "")

    # ── 3. neither given → error with hint ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_missing_file_path_gives_hint(self):
        """Missing file_path (and no 'path') → hint about 'file_path' in error."""
        srv = self._make_write_server()
        result = await srv._handle_write({"content": "x"})
        data = json.loads(result)
        assert data.get("error") is not None
        assert "file_path" in data["error"]
        assert "Did you mean" in data["error"]

    # ── 4. file_path only (no alias) still works ─────────────────────────────

    @pytest.mark.asyncio
    async def test_file_path_only_still_works(self, tmp_path):
        """Original 'file_path' param continues to work unchanged."""
        srv = self._make_write_server()
        target = str(tmp_path / "normal.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = await srv._handle_write({
                "file_path": target, "content": "ok", "dry_run": True,
            })
        data = json.loads(result)
        assert data.get("error") is None
        assert data.get("dry_run") is True

    # ── 5. empty path alias → still gets error (not silent) ──────────────────

    @pytest.mark.asyncio
    async def test_empty_path_alias_gives_error(self):
        """path='' (empty) is treated same as missing — returns an error."""
        srv = self._make_write_server()
        result = await srv._handle_write({"path": "", "content": "x"})
        data = json.loads(result)
        assert data.get("error") is not None

    # ── 6. handle_tool integration: path alias normalised before CG-03 ───────

    @pytest.mark.asyncio
    async def test_handle_tool_path_alias_normalised_before_cg03(self, tmp_path):
        """handle_tool normalises 'path' → 'file_path' so CG-03 sees the right value."""
        srv = self._make_write_server()
        srv._config.governance.edit_enforcement = True   # activate CG-03
        srv._cg03_bypass = False
        target = str(tmp_path / "non_code_file.txt")   # .txt → CG-03 does NOT block
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2, \
             patch.object(srv, "_handle_write", return_value='{"dry_run": true}') as mock_w:
            await srv.handle_tool("graq_write", {"path": target, "content": "x", "dry_run": True})
        # _handle_write must have been called with file_path, not path
        called_args = mock_w.call_args[0][0]
        assert "file_path" in called_args
        assert called_args["file_path"] == target
        assert "path" not in called_args

    # ── 7. handle_tool: file_path wins over path before CG-03 ────────────────

    @pytest.mark.asyncio
    async def test_handle_tool_file_path_wins_over_path(self, tmp_path):
        """When both given to handle_tool, file_path wins after normalisation."""
        srv = self._make_write_server()
        winner = str(tmp_path / "winner.txt")
        loser = str(tmp_path / "loser.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2, \
             patch.object(srv, "_handle_write", return_value='{"dry_run": true}') as mock_w:
            await srv.handle_tool("graq_write", {
                "path": loser, "file_path": winner, "content": "x", "dry_run": True,
            })
        called_args = mock_w.call_args[0][0]
        assert called_args.get("file_path") == winner
        assert "path" not in called_args

    # ── 8. non-write tools unaffected ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_non_write_tool_path_not_normalised(self):
        """Non-write tools (graq_read) are not subject to path normalisation."""
        srv = self._make_write_server()
        with patch.object(srv, "_handle_read", return_value='{"ok": true}') as mock_r:
            await srv.handle_tool("graq_read", {"path": "some_file.txt"})
        # _handle_read must receive the original 'path' key unchanged
        called_args = mock_r.call_args[0][0]
        assert "path" in called_args
        assert "file_path" not in called_args

    # ── 9. kogni_write alias also normalised ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_kogni_write_path_alias_normalised(self, tmp_path):
        """kogni_write receives the same path→file_path normalisation."""
        srv = self._make_write_server()
        target = str(tmp_path / "kogni_out.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2, \
             patch.object(srv, "_handle_write", return_value='{"dry_run": true}') as mock_w:
            await srv.handle_tool("kogni_write", {"path": target, "content": "x", "dry_run": True})
        called_args = mock_w.call_args[0][0]
        assert called_args.get("file_path") == target
        assert "path" not in called_args

    # ── 10. path alias with dry_run=True returns file_path in response ────────

    @pytest.mark.asyncio
    async def test_path_alias_dry_run_returns_resolved_file_path(self, tmp_path):
        """dry_run=True response contains 'file_path' derived from the 'path' alias."""
        srv = self._make_write_server()
        target = str(tmp_path / "dryrun.txt")
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = await srv._handle_write({
                "path": target, "content": "data", "dry_run": True,
            })
        data = json.loads(result)
        assert data.get("dry_run") is True
        assert data.get("error") is None
        # resolved path ends with the file name
        assert "dryrun.txt" in data.get("file_path", "")


# ──────────────────────────────────────────────────────────────────────────────
# BUG-002 — graq_write CG-03 blocks full-file rewrites; force_overwrite bypasses
# ──────────────────────────────────────────────────────────────────────────────

class TestBug002ForceOverwrite:
    """BUG-002: graq_write accepts force_overwrite=True to bypass CG-03 edit gate.

    Covers:
    - CG-03 blocks existing code file without force_overwrite (1)
    - force_overwrite=True bypasses CG-03 for existing code file (2)
    - force_overwrite=False is same as default blocked behaviour (3)
    - force_overwrite does not affect new files (already allowed) (4)
    - force_overwrite does not affect scratch/test paths (already allowed) (5)
    - force_overwrite logs governance warning (6)
    - CG-03 error message now mentions force_overwrite hint (7)
    - _handle_write reads force_overwrite from args without error (8)
    - kogni_write schema alias: force_overwrite propagates through handle_tool (9)
    - dry_run + force_overwrite: preview returned, no write attempted (10)
    """

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make_cg03_server(self, tmp_path):
        """Server with CG-03 enforcement ACTIVE. No real graph."""
        import threading
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._gov = None
        srv.read_only = False
        srv._kg_load_state = "LOADED"
        srv._config = MagicMock()
        gov = MagicMock()
        gov.edit_enforcement = True      # CG-03 ON
        gov.plan_mandatory = False
        gov.session_gate_enabled = False
        srv._config.governance = gov
        srv._session_started = True
        srv._cg01_bypass = False
        srv._cg02_bypass = True
        srv._cg03_bypass = False         # NOT bypassed — CG-03 active
        srv._plan_active = True
        srv._graph = None
        srv._graph_file = None
        srv._lock = threading.Lock()
        # Give it a real _inject_tool_hints stub
        srv._inject_tool_hints = lambda name, err: err
        return srv

    def _make_write_server(self):
        """Minimal server with all CG gates off — for _handle_write direct tests."""
        import threading
        srv = KogniDevServer.__new__(KogniDevServer)
        srv._gov = None
        srv.read_only = False
        srv._kg_load_state = "LOADED"
        srv._config = MagicMock()
        srv._config.governance = MagicMock()
        srv._config.governance.plan_mandatory = False
        srv._config.governance.session_gate_enabled = False
        srv._config.governance.edit_enforcement = False
        srv._session_started = True
        srv._cg01_bypass = False
        srv._plan_active = True
        srv._cg02_bypass = True
        srv._cg03_bypass = True
        srv._graph = None
        srv._graph_file = None
        srv._lock = threading.Lock()
        return srv

    def _kg_gate_passthrough(self):
        from unittest.mock import patch as _patch
        return _patch(
            "graqle.governance.kg_write_gate.check_kg_block",
            return_value=(True, None),
        ), _patch(
            "graqle.governance.kg_write_gate.check_protected_path",
            return_value=(True, None),
        )

    # ── 1. CG-03 blocks without force_overwrite ───────────────────────────────

    @pytest.mark.asyncio
    async def test_cg03_blocks_existing_code_file_without_force_overwrite(self, tmp_path):
        """CG-03 must block graq_write on an existing .py file when edit_enforcement=True."""
        target = tmp_path / "module.py"
        target.write_text("# existing")
        srv = self._make_cg03_server(tmp_path)
        result = json.loads(await srv.handle_tool("graq_write", {
            "file_path": str(target), "content": "new content",
        }))
        assert result.get("error") == "CG-03_EDIT_GATE"

    # ── 2. force_overwrite=True bypasses CG-03 ───────────────────────────────

    @pytest.mark.asyncio
    async def test_force_overwrite_bypasses_cg03_for_existing_code_file(self, tmp_path):
        """force_overwrite=True must bypass CG-03 gate."""
        target = tmp_path / "module.py"
        target.write_text("# existing")
        srv = self._make_cg03_server(tmp_path)
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv.handle_tool("graq_write", {
                "file_path": str(target),
                "content": "new content",
                "force_overwrite": True,
                "dry_run": True,
            }))
        assert result.get("error") != "CG-03_EDIT_GATE"

    # ── 3. force_overwrite=False same as default ──────────────────────────────

    @pytest.mark.asyncio
    async def test_force_overwrite_false_still_blocked_by_cg03(self, tmp_path):
        """force_overwrite=False must behave identically to omitting the parameter."""
        target = tmp_path / "module.py"
        target.write_text("# existing")
        srv = self._make_cg03_server(tmp_path)
        result = json.loads(await srv.handle_tool("graq_write", {
            "file_path": str(target), "content": "x", "force_overwrite": False,
        }))
        assert result.get("error") == "CG-03_EDIT_GATE"

    # ── 4. force_overwrite does not affect new files ──────────────────────────

    @pytest.mark.asyncio
    async def test_new_code_file_always_allowed_regardless_of_force_overwrite(self, tmp_path):
        """New (non-existent) code files bypass CG-03 regardless of force_overwrite."""
        target = tmp_path / "newfile.py"    # does NOT exist on disk
        srv = self._make_cg03_server(tmp_path)
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv.handle_tool("graq_write", {
                "file_path": str(target), "content": "print('hello')", "dry_run": True,
            }))
        assert result.get("error") != "CG-03_EDIT_GATE"

    # ── 5. scratch paths already allowed ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_tests_path_already_allowed_without_force_overwrite(self, tmp_path):
        """Files under tests/ bypass CG-03 without force_overwrite."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        target = tests_dir / "test_foo.py"
        target.write_text("# test file")
        srv = self._make_cg03_server(tmp_path)
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv.handle_tool("graq_write", {
                "file_path": str(target), "content": "# updated", "dry_run": True,
            }))
        assert result.get("error") != "CG-03_EDIT_GATE"

    # ── 6. governance log warning emitted ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_force_overwrite_emits_governance_warning(self, tmp_path, caplog):
        """force_overwrite=True must emit a WARNING governance log entry."""
        import logging
        srv = self._make_write_server()
        target = tmp_path / "src.py"
        p1, p2 = self._kg_gate_passthrough()
        with caplog.at_level(logging.WARNING):
            with p1, p2:
                await srv._handle_write({
                    "file_path": str(target),
                    "content": "print('hi')",
                    "force_overwrite": True,
                    "dry_run": True,
                })
        assert any("BUG-002-GATE" in r.message for r in caplog.records)

    # ── 7. CG-03 error message mentions force_overwrite ───────────────────────

    @pytest.mark.asyncio
    async def test_cg03_error_message_hints_force_overwrite(self, tmp_path):
        """CG-03 error message must include the force_overwrite hint."""
        target = tmp_path / "module.py"
        target.write_text("# existing")
        srv = self._make_cg03_server(tmp_path)
        result = json.loads(await srv.handle_tool("graq_write", {
            "file_path": str(target), "content": "x",
        }))
        assert result.get("error") == "CG-03_EDIT_GATE"
        assert "force_overwrite" in result.get("message", "")

    # ── 8. _handle_write reads force_overwrite without error ─────────────────

    @pytest.mark.asyncio
    async def test_handle_write_accepts_force_overwrite_arg_without_error(self, tmp_path):
        """_handle_write must not error when force_overwrite is passed."""
        srv = self._make_write_server()
        target = tmp_path / "out.txt"
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv._handle_write({
                "file_path": str(target),
                "content": "hello",
                "force_overwrite": True,
                "dry_run": True,
            }))
        assert "error" not in result or result.get("error") is None

    # ── 9. kogni_write alias propagates force_overwrite ──────────────────────

    @pytest.mark.asyncio
    async def test_kogni_write_force_overwrite_bypasses_cg03(self, tmp_path):
        """kogni_write must also accept and honour force_overwrite."""
        target = tmp_path / "module.py"
        target.write_text("# existing")
        srv = self._make_cg03_server(tmp_path)
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv.handle_tool("kogni_write", {
                "file_path": str(target),
                "content": "new",
                "force_overwrite": True,
                "dry_run": True,
            }))
        assert result.get("error") != "CG-03_EDIT_GATE"

    # ── 10. dry_run + force_overwrite: preview, no write ─────────────────────

    @pytest.mark.asyncio
    async def test_dry_run_with_force_overwrite_previews_without_writing(self, tmp_path):
        """dry_run=True + force_overwrite=True must return dry_run=True, not write."""
        target = tmp_path / "module.py"
        target.write_text("# original")
        srv = self._make_write_server()
        p1, p2 = self._kg_gate_passthrough()
        with p1, p2:
            result = json.loads(await srv._handle_write({
                "file_path": str(target),
                "content": "# replacement",
                "force_overwrite": True,
                "dry_run": True,
            }))
        assert result.get("dry_run") is True
        assert target.read_text() == "# original"  # file unchanged


# ---------------------------------------------------------------------------
# BUG-007 — graq_learn(mode="outcome") orphan-skip + create_lesson=False
# ---------------------------------------------------------------------------

class TestBug007LearnOrphanSkip:
    """BUG-007: _handle_learn_outcome skips LEARNED_FROM edges to orphan nodes
    (degree==0) and supports create_lesson=False to suppress lesson node entirely."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make_learn_server(self, nodes: dict | None = None):
        """Build a minimal KogniDevServer for _handle_learn_outcome tests.

        The graph has _save_graph mocked to always succeed (returns (True, 0)),
        get_edges_between returns [], and add_node/add_edge are recorded.
        """
        import threading
        srv = KogniDevServer.__new__(KogniDevServer)
        srv.read_only = False
        srv._config = None
        srv._graph_file = "graqle.json"
        srv._graph_mtime = 9999999999.0
        srv._kg_load_lock = threading.Lock()
        srv._kg_loaded = threading.Event()
        srv._kg_load_error = None
        srv._kg_load_state = "LOADED"
        srv._gov = None

        graph = MagicMock()
        graph.get_edges_between.return_value = []
        graph.add_node = MagicMock()
        graph.add_edge = MagicMock()

        if nodes is None:
            nodes = {
                "comp-connected": MockNode(id="comp-connected", label="Connected Comp", entity_type="service", description="has edges", degree=3),
                "comp-orphan": MockNode(id="comp-orphan", label="Orphan Comp", entity_type="service", description="no edges", degree=0),
            }
        graph.nodes = nodes
        srv._graph = graph

        # _find_node: look up by id in graph.nodes
        def _find_node(name):
            return graph.nodes.get(name)

        srv._find_node = _find_node
        srv._save_graph = MagicMock(return_value=(True, 0))
        srv._load_graph = MagicMock(return_value=graph)
        return srv, graph

    # ── 1. Baseline: normal call with connected nodes, no orphans ─────────────

    @pytest.mark.asyncio
    async def test_outcome_normal_connected_no_orphan_skips(self):
        """All connected nodes → orphan_targets_skipped is empty."""
        nodes = {
            "comp-a": MockNode(id="comp-a", label="A", entity_type="service", description="d", degree=5),
            "comp-b": MockNode(id="comp-b", label="B", entity_type="service", description="d", degree=2),
        }
        srv, graph = self._make_learn_server(nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "deploy",
            "outcome": "success",
            "components": ["comp-a", "comp-b"],
            "lesson": "Deploy succeeded without rollback.",
        }))
        assert result["recorded"] is True
        assert result["orphan_targets_skipped"] == []
        assert graph.add_edge.call_count == 2  # one LEARNED_FROM per connected node

    # ── 2. Orphan component → LEARNED_FROM edge skipped ──────────────────────

    @pytest.mark.asyncio
    async def test_outcome_skips_learned_from_to_orphan_node(self):
        """A component with degree==0 must NOT get a LEARNED_FROM edge."""
        srv, graph = self._make_learn_server()
        result = json.loads(await srv._handle_learn_outcome({
            "action": "deploy",
            "outcome": "success",
            "components": ["comp-connected", "comp-orphan"],
            "lesson": "Mixed-degree components.",
        }))
        assert result["recorded"] is True
        assert "comp-orphan" in result["orphan_targets_skipped"]
        # Only one LEARNED_FROM edge — to comp-connected only
        edge_calls = [c for c in graph.add_edge.call_args_list]
        targets = [c.args[0].target_id for c in edge_calls if hasattr(c.args[0], "target_id")]
        assert "comp-orphan" not in targets
        assert "comp-connected" in targets

    # ── 3. All orphans → no LEARNED_FROM edges, but lesson node still created ─

    @pytest.mark.asyncio
    async def test_outcome_all_orphans_lesson_node_created_no_edges(self):
        """When all components are orphans, lesson node is created but no edges added."""
        nodes = {
            "orphan-a": MockNode(id="orphan-a", label="Orphan A", entity_type="service", description="d", degree=0),
            "orphan-b": MockNode(id="orphan-b", label="Orphan B", entity_type="service", description="d", degree=0),
        }
        srv, graph = self._make_learn_server(nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "refactor",
            "outcome": "failure",
            "components": ["orphan-a", "orphan-b"],
            "lesson": "All orphans triggered.",
        }))
        assert result["recorded"] is True
        assert set(result["orphan_targets_skipped"]) == {"orphan-a", "orphan-b"}
        assert graph.add_node.call_count == 1  # lesson node created
        assert graph.add_edge.call_count == 0  # no edges

    # ── 4. orphan_targets_skipped in envelope when no orphans ────────────────

    @pytest.mark.asyncio
    async def test_outcome_envelope_always_has_orphan_targets_skipped_key(self):
        """orphan_targets_skipped key must always be present in the response envelope."""
        nodes = {
            "comp-a": MockNode(id="comp-a", label="A", entity_type="service", description="d", degree=1),
        }
        srv, _ = self._make_learn_server(nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "test",
            "outcome": "success",
            "components": ["comp-a"],
        }))
        assert "orphan_targets_skipped" in result
        assert isinstance(result["orphan_targets_skipped"], list)

    # ── 5. create_lesson=False skips lesson node and all edges ───────────────

    @pytest.mark.asyncio
    async def test_create_lesson_false_no_lesson_node_no_edges(self):
        """create_lesson=False must suppress lesson node creation and all LEARNED_FROM edges."""
        srv, graph = self._make_learn_server()
        result = json.loads(await srv._handle_learn_outcome({
            "action": "deploy",
            "outcome": "success",
            "components": ["comp-connected", "comp-orphan"],
            "lesson": "Should be suppressed.",
            "create_lesson": False,
        }))
        assert result["recorded"] is True
        assert result["lesson_node_id"] is None
        assert graph.add_node.call_count == 0
        assert graph.add_edge.call_count == 0

    # ── 6. create_lesson=False: orphan_targets_skipped still empty ───────────

    @pytest.mark.asyncio
    async def test_create_lesson_false_orphan_targets_skipped_empty(self):
        """When create_lesson=False, no edges attempted → orphan_targets_skipped is []."""
        srv, _ = self._make_learn_server()
        result = json.loads(await srv._handle_learn_outcome({
            "action": "deploy",
            "outcome": "success",
            "components": ["comp-connected", "comp-orphan"],
            "lesson": "Suppressed.",
            "create_lesson": False,
        }))
        assert result["orphan_targets_skipped"] == []

    # ── 7. create_lesson=True (explicit default) behaves same as omitted ─────

    @pytest.mark.asyncio
    async def test_create_lesson_true_explicit_behaves_as_default(self):
        """Explicit create_lesson=True produces same result as not passing it."""
        nodes = {
            "comp-a": MockNode(id="comp-a", label="A", entity_type="service", description="d", degree=2),
        }
        srv_explicit, graph_explicit = self._make_learn_server(nodes)
        srv_implicit, graph_implicit = self._make_learn_server(nodes)

        args_explicit = {"action": "test", "outcome": "success", "components": ["comp-a"], "lesson": "Lesson text.", "create_lesson": True}
        args_implicit = {"action": "test", "outcome": "success", "components": ["comp-a"], "lesson": "Lesson text."}

        r_explicit = json.loads(await srv_explicit._handle_learn_outcome(args_explicit))
        r_implicit = json.loads(await srv_implicit._handle_learn_outcome(args_implicit))

        assert r_explicit["recorded"] is True
        assert r_implicit["recorded"] is True
        assert graph_explicit.add_node.call_count == graph_implicit.add_node.call_count == 1
        assert graph_explicit.add_edge.call_count == graph_implicit.add_edge.call_count == 1

    # ── 8. lesson=None with connected node: no edges, lesson_node_id is None ─

    @pytest.mark.asyncio
    async def test_no_lesson_text_no_edges_created(self):
        """When lesson text is omitted, no lesson node or LEARNED_FROM edges created."""
        nodes = {
            "comp-a": MockNode(id="comp-a", label="A", entity_type="service", description="d", degree=2),
        }
        srv, graph = self._make_learn_server(nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "refactor",
            "outcome": "partial",
            "components": ["comp-a"],
        }))
        assert result["recorded"] is True
        assert result["lesson_node_id"] is None
        assert graph.add_node.call_count == 0
        assert graph.add_edge.call_count == 0

    # ── 9. degree=None node: treated as not orphan (degree absent ≠ degree==0) ─

    @pytest.mark.asyncio
    async def test_node_with_no_degree_attr_not_treated_as_orphan(self):
        """A node with no degree attribute (getattr returns None) must NOT be treated as orphan."""
        nodes = {
            "nodegree-comp": MockNode(id="nodegree-comp", label="No Degree", entity_type="service", description="d"),
        }
        # Remove degree attribute entirely from the node dataclass instance
        import dataclasses
        node = nodes["nodegree-comp"]
        # Simulate absence by using an object without degree attr
        class _NodeNoDegree:
            id = "nodegree-comp"
        graph_nodes = {"nodegree-comp": _NodeNoDegree()}
        srv, graph = self._make_learn_server(graph_nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "test",
            "outcome": "success",
            "components": ["nodegree-comp"],
            "lesson": "Lesson for no-degree node.",
        }))
        # degree is None (via getattr default) → not 0 → not skipped
        assert "nodegree-comp" not in result["orphan_targets_skipped"]
        assert graph.add_edge.call_count == 1

    # ── 10. Mixed: multiple components, partial orphans ────────────────────

    @pytest.mark.asyncio
    async def test_outcome_partial_orphans_mixed_components(self):
        """With 3 components (2 connected, 1 orphan), 2 edges written, 1 skipped."""
        nodes = {
            "comp-1": MockNode(id="comp-1", label="C1", entity_type="service", description="d", degree=5),
            "comp-2": MockNode(id="comp-2", label="C2", entity_type="service", description="d", degree=1),
            "comp-orphan": MockNode(id="comp-orphan", label="Orphan", entity_type="service", description="d", degree=0),
        }
        srv, graph = self._make_learn_server(nodes)
        result = json.loads(await srv._handle_learn_outcome({
            "action": "migrate",
            "outcome": "success",
            "components": ["comp-1", "comp-2", "comp-orphan"],
            "lesson": "Partial orphan lesson.",
        }))
        assert result["recorded"] is True
        assert result["orphan_targets_skipped"] == ["comp-orphan"]
        edge_calls = graph.add_edge.call_args_list
        targets = [c.args[0].target_id for c in edge_calls if hasattr(c.args[0], "target_id")]
        assert "comp-1" in targets
        assert "comp-2" in targets
        assert "comp-orphan" not in targets

    # ── 11. Schema: create_lesson parameter present in graq_learn definition ─

    def test_schema_has_create_lesson_parameter(self):
        """graq_learn MCP schema must expose create_lesson parameter."""
        learn_def = next((t for t in TOOL_DEFINITIONS if t["name"] in ("graq_learn", "kogni_learn")), None)
        assert learn_def is not None, "graq_learn not found in TOOL_DEFINITIONS"
        props = learn_def["inputSchema"]["properties"]
        assert "create_lesson" in props, "create_lesson missing from graq_learn schema"
        assert props["create_lesson"]["type"] == "boolean"
        assert props["create_lesson"]["default"] is True


# ---------------------------------------------------------------------------
# BUG-005 — graq_bash Windows multi-line python -c swallows stdout
# ---------------------------------------------------------------------------

class TestBug005WindowsPythonC:
    """graq_bash must route multi-line python -c through a temp .py file on Windows."""

    # ── helpers ─────────────────────────────────────────────────────────────

    def _make_bash_server(self):
        """Minimal KogniDevServer with _load_graph mocked out."""
        server = KogniDevServer.__new__(KogniDevServer)
        server._graph_path = "graqle.json"
        server._session_active = True
        server._plan_approved = True
        server._plan_goal = "test"
        server._graph = MagicMock()
        server._logger = MagicMock()
        server._cg01_session_gate_active = False
        return server

    def _make_subprocess_result(self, stdout="", stderr="", returncode=0):
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    # ── 1. Non-Windows: no temp file, command unchanged ─────────────────────

    @pytest.mark.asyncio
    async def test_non_windows_single_line_no_rewrite(self):
        """On non-Windows platforms, single-line python -c must NOT be rewritten."""
        server = self._make_bash_server()
        command = "python -c 'print(42)'"
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._make_subprocess_result(stdout="42\n")

        with patch("sys.platform", "linux"), \
             patch("subprocess.run", side_effect=fake_run):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0
        assert captured["cmd"] == command, "Command must not be rewritten on non-Windows"

    # ── 2. Windows + single-line -c: no temp file (no newline in code) ──────

    @pytest.mark.asyncio
    async def test_windows_single_line_no_rewrite(self):
        """Windows single-line python -c (no embedded newline) must NOT be rewritten."""
        server = self._make_bash_server()
        command = 'python -c "print(42)"'
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._make_subprocess_result(stdout="42\n")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0
        assert captured["cmd"] == command, "Single-line command must not be rewritten"

    # ── 3. Windows + multi-line double-quoted: rewrite to temp file ──────────

    @pytest.mark.asyncio
    async def test_windows_multiline_double_quoted_rewrites(self):
        """Windows multi-line python -c with double quotes must be rewritten to temp .py."""
        server = self._make_bash_server()
        multiline_code = "x = 1\nprint(x)\n"
        command = f'python -c "{multiline_code}"'
        captured = {}
        written_content = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            # Simulate reading the temp file to verify its contents
            if cmd.startswith("python "):
                tmp_path = cmd.split('"')[1]
                try:
                    with open(tmp_path, encoding="utf-8") as f:
                        written_content["body"] = f.read()
                except FileNotFoundError:
                    pass
            return self._make_subprocess_result(stdout="1\n")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0
        assert captured["cmd"] != command, "Command must be rewritten to temp file path"
        assert captured["cmd"].startswith("python "), "Rewritten command starts with python"
        assert captured["cmd"].endswith('.py"'), "Rewritten command ends with .py\""
        assert written_content.get("body") == multiline_code, \
            "Temp file must contain the extracted multi-line code"

    # ── 4. Windows + multi-line single-quoted: rewrite to temp file ──────────

    @pytest.mark.asyncio
    async def test_windows_multiline_single_quoted_rewrites(self):
        """Windows multi-line python -c with single quotes must also be rewritten."""
        server = self._make_bash_server()
        multiline_code = "import os\nprint(os.getcwd())\n"
        command = f"python -c '{multiline_code}'"
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._make_subprocess_result(stdout="/some/path\n")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0
        assert ".py" in captured["cmd"], "Rewritten command must reference a .py file"

    # ── 5. Windows + no -c: no rewrite ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_windows_no_c_flag_no_rewrite(self):
        """Windows command without -c must not be rewritten."""
        server = self._make_bash_server()
        command = "python myscript.py"
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._make_subprocess_result(stdout="done\n")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            await server._handle_bash({"command": command})

        assert captured["cmd"] == command

    # ── 6. Windows + multi-line but no quote wrapper: safe no-op ─────────────

    @pytest.mark.asyncio
    async def test_windows_multiline_no_quotes_no_rewrite(self):
        """If regex can't extract quoted -c body, command must NOT be rewritten (safe fallback)."""
        server = self._make_bash_server()
        # No quotes around the -c argument — regex won't match
        command = "python -c import sys; print(sys.version)"
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._make_subprocess_result(stdout="3.10\n")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            await server._handle_bash({"command": command})

        assert captured["cmd"] == command, "Unquoted -c must not be rewritten"

    # ── 7. Temp file deleted after success ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_temp_file_deleted_after_success(self):
        """Temp .py file must be deleted in finally block after successful run."""
        server = self._make_bash_server()
        multiline_code = "x = 2\nprint(x)\n"
        command = f'python -c "{multiline_code}"'
        deleted_paths = []
        created_paths = []

        original_unlink = __import__("os").unlink

        def fake_run(cmd, **kwargs):
            # Capture the temp file path from the rewritten command
            if '"' in cmd:
                path = cmd.split('"')[1]
                created_paths.append(path)
            return self._make_subprocess_result(stdout="2\n")

        def fake_unlink(path):
            deleted_paths.append(path)

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.unlink", side_effect=fake_unlink):
            await server._handle_bash({"command": command})

        assert len(created_paths) == 1, "One temp file path must be captured"
        assert created_paths[0] in deleted_paths, "Temp file must be deleted after success"

    # ── 8. Temp file deleted after TimeoutExpired ─────────────────────────────

    @pytest.mark.asyncio
    async def test_temp_file_deleted_after_timeout(self):
        """Temp .py file must be deleted even when subprocess times out."""
        import subprocess as _subprocess
        server = self._make_bash_server()
        multiline_code = "import time\ntime.sleep(999)\n"
        command = f'python -c "{multiline_code}"'
        deleted_paths = []

        def fake_run(cmd, **kwargs):
            raise _subprocess.TimeoutExpired(cmd, 30)

        def fake_unlink(path):
            deleted_paths.append(path)

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.unlink", side_effect=fake_unlink):
            result = json.loads(await server._handle_bash({"command": command}))

        assert "timed out" in result.get("error", "").lower(), \
            "TimeoutExpired must produce timeout error"
        assert len(deleted_paths) == 1, "Temp file must be deleted after timeout"

    # ── 9. Temp file deleted after general exception ──────────────────────────

    @pytest.mark.asyncio
    async def test_temp_file_deleted_after_exception(self):
        """Temp .py file must be deleted even when subprocess raises a general exception."""
        server = self._make_bash_server()
        multiline_code = "raise ValueError('boom')\n"
        command = f'python -c "{multiline_code}"'
        deleted_paths = []

        def fake_run(cmd, **kwargs):
            raise RuntimeError("subprocess failed hard")

        def fake_unlink(path):
            deleted_paths.append(path)

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.unlink", side_effect=fake_unlink):
            result = json.loads(await server._handle_bash({"command": command}))

        assert "Bash failed" in result.get("error", ""), \
            "General exception must produce Bash failed error"
        assert len(deleted_paths) == 1, "Temp file must be deleted after exception"

    # ── 10. No temp file created when rewrite does not trigger ───────────────

    @pytest.mark.asyncio
    async def test_no_temp_file_when_no_rewrite(self):
        """When no rewrite is triggered, os.unlink must never be called."""
        server = self._make_bash_server()
        command = "echo hello"
        unlink_calls = []

        def fake_run(cmd, **kwargs):
            return self._make_subprocess_result(stdout="hello\n")

        def fake_unlink(path):
            unlink_calls.append(path)

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.unlink", side_effect=fake_unlink):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0
        assert len(unlink_calls) == 0, "os.unlink must NOT be called when no temp file created"

    # ── 11. Stdout is correctly captured via temp file path ──────────────────

    @pytest.mark.asyncio
    async def test_stdout_captured_from_temp_file_run(self):
        """stdout from the rewritten temp-file command must appear in the response."""
        server = self._make_bash_server()
        multiline_code = "x = 99\nprint(x)\n"
        command = f'python -c "{multiline_code}"'

        def fake_run(cmd, **kwargs):
            return self._make_subprocess_result(stdout="99\n", returncode=0)

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run):
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["stdout"] == "99\n"
        assert result["exit_code"] == 0
        assert result["success"] is True

    # ── 12. OSError during unlink is swallowed ────────────────────────────────

    @pytest.mark.asyncio
    async def test_oserror_during_unlink_is_swallowed(self):
        """If os.unlink raises OSError (e.g. file already gone), it must be silently swallowed."""
        server = self._make_bash_server()
        multiline_code = "print('hello')\nprint('world')\n"
        command = f'python -c "{multiline_code}"'

        def fake_run(cmd, **kwargs):
            return self._make_subprocess_result(stdout="hello\nworld\n")

        def failing_unlink(path):
            raise OSError("already deleted")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.unlink", side_effect=failing_unlink):
            # Must not raise — OSError is caught in finally block
            result = json.loads(await server._handle_bash({"command": command}))

        assert result["exit_code"] == 0, "OSError in unlink must not surface to caller"

