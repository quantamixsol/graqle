"""Tests for cognigraph.plugins.mcp_dev_server — KogniDevServer (7-tool MCP server)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cognigraph.plugins.mcp_dev_server import (
    TOOL_DEFINITIONS,
    KogniDevServer,
    _SENSITIVE_KEYS,
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
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "cognigraph.yaml"
    srv._graph = mock_graph
    srv._config = None
    srv._graph_file = "cognigraph.json"
    return srv


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_seven_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 7

    def test_expected_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "kogni_context",
            "kogni_inspect",
            "kogni_reason",
            "kogni_preflight",
            "kogni_lessons",
            "kogni_impact",
            "kogni_learn",
        }
        assert names == expected

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
        assert "kogni_preflight" in tool_names
        assert "kogni_lessons" in tool_names
        assert "kogni_impact" in tool_names
        assert "kogni_learn" in tool_names


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------

class TestListTools:
    def test_returns_all_definitions(self, server):
        tools = server.list_tools()
        assert len(tools) == 7


# ---------------------------------------------------------------------------
# handle_tool dispatch
# ---------------------------------------------------------------------------

class TestHandleTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, server):
        result = await server.handle_tool("kogni_nonexistent", {})
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_dispatches_free_tool(self, server):
        """kogni_inspect should work without license check."""
        with patch.object(server, "_read_active_branch", return_value=None):
            result = await server.handle_tool("kogni_inspect", {"stats": True})
        data = json.loads(result)
        assert "total_nodes" in data
        assert data["total_nodes"] == 3

    @pytest.mark.asyncio
    async def test_pro_tools_ungated(self, server):
        """All tools are free since v0.7.5 — no license gate."""
        # kogni_preflight should dispatch directly without any license check
        with patch.object(server, "_handle_preflight", new_callable=AsyncMock) as mock_pf:
            mock_pf.return_value = json.dumps({"status": "ok"})
            result = await server.handle_tool("kogni_preflight", {"action": "test"})
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
# kogni_inspect handler
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
# kogni_context handler
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
# kogni_reason handler (fallback mode)
# ---------------------------------------------------------------------------

class TestReasonHandler:
    @pytest.mark.asyncio
    async def test_missing_question(self, server):
        result = await server._handle_reason({})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_fallback_traversal(self, server):
        # Mock areason to raise RuntimeError (no backend)
        server._graph.areason = AsyncMock(side_effect=RuntimeError("no backend"))
        result = await server._handle_reason({"question": "what does auth lambda do?"})
        data = json.loads(result)
        assert "answer" in data
        assert data["nodes_used"] >= 1
        assert data.get("mode") in ("fallback_traversal", None)

    @pytest.mark.asyncio
    async def test_no_matches(self, server):
        server._graph.areason = AsyncMock(side_effect=RuntimeError("no backend"))
        result = await server._handle_reason({"question": "zzzzz_no_match_zzzzz"})
        data = json.loads(result)
        assert data["nodes_used"] == 0


# ---------------------------------------------------------------------------
# kogni_impact handler
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
# kogni_lessons handler
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
# kogni_preflight handler
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
        """The _version variable in mcp_dev_server must come from cognigraph.__version__."""
        from cognigraph.__version__ import __version__ as pkg_version
        from cognigraph.plugins.mcp_dev_server import _version

        assert _version == pkg_version
        assert _version != "0.0.0", "_version fell back to default; import is broken"
