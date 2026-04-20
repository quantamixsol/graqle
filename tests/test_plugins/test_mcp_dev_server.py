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
        }
        # v0.52.0: 77 graq_* + 77 kogni_* = 154 total (CG-17 +2, G2 +2, G3 +2)
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
        # v0.52.0: 148 -> 154 (CG-17 +2 graq_memory; G2 +2 graq_release_gate; G3 +2 graq_vsce_check)
        assert len(tools) == 154


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
        with patch.object(server, "_read_active_branch", return_value=None):
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

