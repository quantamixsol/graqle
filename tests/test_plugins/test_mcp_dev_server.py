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

