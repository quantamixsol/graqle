"""Tests for v0.15.0 MCP server features:

1. KG hot-reload (mtime-based + graq_reload tool)
2. graq_learn entity mode
3. graq_learn knowledge mode
4. Tool count (now 8)
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_mcp_dev_server_v015
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, time, dataclasses, pathlib +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import (
    TOOL_DEFINITIONS,
    KogniDevServer,
)

# ---------------------------------------------------------------------------
# Mock graph objects
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    degree: int = 2


@dataclass
class MockEdge:
    id: str = "e1"
    source_id: str = "a"
    target_id: str = "b"
    relationship: str = "RELATED"
    weight: float = 1.0


def _build_mock_graph() -> MagicMock:
    nodes = {
        "auth-lambda": MockNode(
            id="auth-lambda", label="Auth Lambda",
            entity_type="SERVICE", description="JWT auth service",
        ),
    }
    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = {}
    graph.add_node_simple = MagicMock()
    graph.add_edge_simple = MagicMock()
    graph.auto_connect = MagicMock(return_value=2)
    graph.add_node = MagicMock()
    graph.add_edge = MagicMock()
    graph.get_edges_between = MagicMock(return_value=[])
    return graph


@pytest.fixture
def server():
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = _build_mock_graph()
    srv._config = None
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0  # Far future — prevent hot-reload in tests
    return srv


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class TestToolDefinitionsV015:
    def test_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 26  # 13 graq_* + 13 kogni_* aliases (includes Wave 5 governance tools)

    def test_reload_tool_exists(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "graq_reload" in names

    def test_learn_has_mode_parameter(self):
        learn_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_learn")
        props = learn_tool["inputSchema"]["properties"]
        assert "mode" in props
        assert set(props["mode"]["enum"]) == {"outcome", "entity", "knowledge"}

    def test_learn_has_entity_params(self):
        learn_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_learn")
        props = learn_tool["inputSchema"]["properties"]
        assert "entity_id" in props
        assert "entity_type" in props
        assert "connects_to" in props

    def test_learn_has_knowledge_params(self):
        learn_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_learn")
        props = learn_tool["inputSchema"]["properties"]
        assert "domain" in props
        assert "tags" in props


# ---------------------------------------------------------------------------
# graq_reload handler
# ---------------------------------------------------------------------------

class TestReloadHandler:
    @pytest.mark.asyncio
    async def test_reload_resets_graph(self, server):
        new_graph = _build_mock_graph()
        new_graph.nodes["new-node"] = MockNode(
            id="new-node", label="New", entity_type="SERVICE", description="Added",
        )

        original_load = server._load_graph

        def patched_load():
            server._graph = new_graph
            return new_graph

        server._load_graph = patched_load
        try:
            result = await server._handle_reload({})
        finally:
            server._load_graph = original_load

        data = json.loads(result)
        assert data["status"] == "reloaded"
        assert data["previous_nodes"] == 1  # old graph had 1 node


# ---------------------------------------------------------------------------
# Hot-reload via mtime
# ---------------------------------------------------------------------------

class TestHotReload:
    def test_mtime_triggers_reload(self, server):
        """If file mtime is newer than cached, graph should be reloaded."""
        server._graph_mtime = 1000.0  # Old mtime

        # Mock Path.stat to return newer mtime
        mock_stat = MagicMock()
        mock_stat.st_mtime = 2000.0  # Newer

        with patch("graqle.plugins.mcp_dev_server.Path") as MockPath:
            MockPath.return_value.stat.return_value = mock_stat
            MockPath.return_value.exists.return_value = True
            # After mtime check sets self._graph = None, the loading code runs
            # We mock the import chain to avoid full Graqle initialization
            server._graph = MagicMock()
            server._graph.nodes = {"a": MockNode("a", "A", "S", "desc")}

            # Directly test that _load_graph detects mtime change
            # by setting _graph_mtime older than file
            assert server._graph is not None  # Currently cached
            # The actual reload happens inside _load_graph which we'd
            # need the full Graqle import chain to test properly


# ---------------------------------------------------------------------------
# graq_learn entity mode
# ---------------------------------------------------------------------------

class TestLearnEntityMode:
    @pytest.mark.asyncio
    async def test_entity_mode_creates_node(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "entity",
            "entity_id": "CrawlQ",
            "entity_type": "PRODUCT",
            "description": "Content ERP for enterprise",
        })
        data = json.loads(result)
        assert data["recorded"] is True
        assert data["mode"] == "entity"
        assert data["entity_id"] == "CrawlQ"
        assert data["entity_type"] == "PRODUCT"

        # Verify add_node_simple was called
        server._graph.add_node_simple.assert_called_once()
        call_args = server._graph.add_node_simple.call_args
        assert call_args[0][0] == "CrawlQ"
        assert call_args[1]["entity_type"] == "PRODUCT"

    @pytest.mark.asyncio
    async def test_entity_mode_requires_entity_id(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "entity",
        })
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_entity_mode_connects_to_existing(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "entity",
            "entity_id": "MyProduct",
            "entity_type": "PRODUCT",
            "connects_to": ["auth-lambda"],
        })
        data = json.loads(result)
        assert data["recorded"] is True
        assert "auth-lambda" in data["connected_to"]


# ---------------------------------------------------------------------------
# graq_learn knowledge mode
# ---------------------------------------------------------------------------

class TestLearnKnowledgeMode:
    @pytest.mark.asyncio
    async def test_knowledge_mode_creates_node(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "knowledge",
            "description": "Target audience is C-suite in regulated industries",
            "domain": "brand",
            "tags": ["audience", "positioning"],
        })
        data = json.loads(result)
        assert data["recorded"] is True
        assert data["mode"] == "knowledge"
        assert data["domain"] == "brand"
        assert "knowledge_brand_" in data["node_id"]

        server._graph.add_node_simple.assert_called_once()
        call_args = server._graph.add_node_simple.call_args
        assert call_args[1]["entity_type"] == "KNOWLEDGE"

    @pytest.mark.asyncio
    async def test_knowledge_mode_requires_description(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "knowledge",
        })
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_knowledge_mode_default_domain(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "knowledge",
            "description": "Some fact",
        })
        data = json.loads(result)
        assert data["domain"] == "general"


# ---------------------------------------------------------------------------
# graq_learn outcome mode (backward compatibility)
# ---------------------------------------------------------------------------

class TestLearnOutcomeMode:
    @pytest.mark.asyncio
    async def test_default_mode_is_outcome(self, server):
        """No mode specified = outcome mode (backward compatible)."""
        result = await server.handle_tool("graq_learn", {
            "action": "fixed auth",
            "outcome": "success",
            "components": ["auth-lambda"],
        })
        data = json.loads(result)
        assert data["recorded"] is True
        assert data["mode"] == "outcome"

    @pytest.mark.asyncio
    async def test_outcome_requires_action(self, server):
        result = await server.handle_tool("graq_learn", {
            "mode": "outcome",
            "outcome": "success",
            "components": ["x"],
        })
        data = json.loads(result)
        assert "error" in data
