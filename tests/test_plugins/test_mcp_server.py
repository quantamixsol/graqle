"""Tests for GraQle MCP Server plugin."""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_mcp_server
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, math, dataclasses, typing +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import numpy as np
import pytest

from graqle.plugins.mcp_server import MCPConfig, MCPServer, MCPToolResult

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


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float


def _build_mock_graph() -> MagicMock:
    """Build a small mock knowledge graph with 3 nodes and 2 edges."""
    nodes = {
        "lambda-auth": MockNode(
            id="lambda-auth",
            label="Auth Lambda",
            entity_type="service",
            description="Handles JWT verification and user authentication for the EU region.",
            properties={"runtime": "python3.11", "region": "eu-central-1", "password": "s3cret"},
        ),
        "dynamodb-users": MockNode(
            id="dynamodb-users",
            label="Users Table",
            entity_type="database",
            description="DynamoDB table storing user profiles and workspace membership.",
            properties={"table_name": "users-eu", "api_key": "ak_12345"},
        ),
        "cognito-pool": MockNode(
            id="cognito-pool",
            label="EU Cognito Pool",
            entity_type="auth",
            description="Cognito user pool for the EU region. Manages sign-up, sign-in, MFA.",
            properties={"pool_id": "eu-central-1_Z0rehiDtA"},
        ),
    }

    edges = {
        "e1": MockEdge(source_id="lambda-auth", target_id="dynamodb-users", relationship="READS_FROM", weight=0.9),
        "e2": MockEdge(source_id="lambda-auth", target_id="cognito-pool", relationship="AUTHENTICATES_VIA", weight=0.95),
    }

    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    return graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graph():
    return _build_mock_graph()


@pytest.fixture
def server(mock_graph):
    """MCPServer with graph pre-injected (bypasses lazy loading)."""
    srv = MCPServer(config=MCPConfig())
    srv._graph = mock_graph
    return srv


# ---------------------------------------------------------------------------
# 1. test_tool_definitions
# ---------------------------------------------------------------------------

def test_tool_definitions(server: MCPServer):
    """Verify 5 tools returned with correct schema (4 original + graq_predict)."""
    tools = server.tools
    assert len(tools) == 5

    names = {t["name"] for t in tools}
    assert names == {"graq_context", "graq_reason", "graq_inspect", "graq_search", "graq_predict"}

    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


# ---------------------------------------------------------------------------
# 2. test_context_text_format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_text_format(server: MCPServer):
    """Get text context and verify sections present."""
    result = await server.handle_tool_call("graq_context", {"entity": "Auth Lambda"})
    assert not result.is_error
    text = result.content

    # Header with label and type
    assert "Auth Lambda" in text
    assert "service" in text
    # Connections section
    assert "## Connections" in text
    assert "READS_FROM" in text
    assert "Users Table" in text
    assert "AUTHENTICATES_VIA" in text
    # Properties section (should NOT contain redacted 'password')
    assert "## Properties" in text
    assert "runtime" in text
    assert "password" not in text


# ---------------------------------------------------------------------------
# 3. test_context_json_format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_json_format(server: MCPServer):
    """Verify JSON output has required fields."""
    result = await server.handle_tool_call("graq_context", {"entity": "lambda-auth", "format": "json"})
    assert not result.is_error
    data = json.loads(result.content)

    assert data["entity"] == "Auth Lambda"
    assert data["type"] == "service"
    assert "description" in data
    assert "properties" in data
    assert "neighbors" in data
    assert len(data["neighbors"]) == 2
    # Redacted
    assert "password" not in data["properties"]


# ---------------------------------------------------------------------------
# 4. test_context_entity_not_found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_entity_not_found(server: MCPServer):
    """Verify error result for missing entity."""
    result = await server.handle_tool_call("graq_context", {"entity": "nonexistent-service"})
    assert result.is_error
    assert "Entity not found" in result.content


# ---------------------------------------------------------------------------
# 5. test_inspect_summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inspect_summary(server: MCPServer):
    """Verify node/edge counts in summary."""
    result = await server.handle_tool_call("graq_inspect", {"detail": "summary"})
    assert not result.is_error
    data = json.loads(result.content)

    assert data["nodes"] == 3
    assert data["edges"] == 2
    assert "service" in data["entity_types"]
    assert data["entity_types"]["service"] == 1
    assert data["entity_types"]["database"] == 1
    assert data["entity_types"]["auth"] == 1


# ---------------------------------------------------------------------------
# 6. test_inspect_types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inspect_types(server: MCPServer):
    """Verify entity type grouping."""
    result = await server.handle_tool_call("graq_inspect", {"detail": "types"})
    assert not result.is_error
    data = json.loads(result.content)

    assert "service" in data
    assert "Auth Lambda" in data["service"]
    assert "database" in data
    assert "Users Table" in data["database"]
    assert "auth" in data
    assert "EU Cognito Pool" in data["auth"]


# ---------------------------------------------------------------------------
# 7. test_search_returns_ranked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_ranked(server: MCPServer):
    """Mock embedder, verify results sorted by relevance."""
    # Create a deterministic mock embedder
    call_count = {"n": 0}
    vectors = {
        # query vector
        0: np.array([1.0, 0.0, 0.0]),
        # Auth Lambda — most similar to query
        1: np.array([0.9, 0.1, 0.0]),
        # Users Table — medium similarity
        2: np.array([0.5, 0.5, 0.0]),
        # EU Cognito Pool — least similar
        3: np.array([0.1, 0.9, 0.0]),
    }

    def mock_embed(text: str) -> np.ndarray:
        idx = call_count["n"]
        call_count["n"] += 1
        return vectors[idx]

    embedder = MagicMock()
    embedder.embed = mock_embed
    server._embedder = embedder

    result = await server.handle_tool_call("graq_search", {"query": "authentication", "limit": 3})
    assert not result.is_error
    data = json.loads(result.content)

    assert len(data) == 3
    # Results should be sorted by relevance descending
    relevances = [r["relevance"] for r in data]
    assert relevances == sorted(relevances, reverse=True)
    # Most relevant should be the auth lambda (closest vector)
    assert data[0]["label"] == "Auth Lambda"


# ---------------------------------------------------------------------------
# 8. test_redact_sensitive_props
# ---------------------------------------------------------------------------

def test_redact_sensitive_props(server: MCPServer):
    """Verify passwords/secrets/api_keys removed."""
    props = {
        "runtime": "python3.11",
        "password": "s3cret",
        "api_key": "ak_12345",
        "secret": "very_secret",
        "region": "eu-central-1",
    }
    clean = server._redact(props)

    assert "runtime" in clean
    assert "region" in clean
    assert "password" not in clean
    assert "api_key" not in clean
    assert "secret" not in clean


# ---------------------------------------------------------------------------
# 9. test_find_node_fuzzy
# ---------------------------------------------------------------------------

def test_find_node_fuzzy(server: MCPServer):
    """Verify fuzzy matching works."""
    # Exact ID
    node = server._find_node("lambda-auth")
    assert node is not None
    assert node.id == "lambda-auth"

    # Exact label (case-insensitive)
    node = server._find_node("auth lambda")
    assert node is not None
    assert node.label == "Auth Lambda"

    # Substring match
    node = server._find_node("cognito")
    assert node is not None
    assert node.id == "cognito-pool"

    # No match
    node = server._find_node("zzz-no-match")
    assert node is None


# ---------------------------------------------------------------------------
# 10. test_unknown_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool(server: MCPServer):
    """Verify error for invalid tool name."""
    result = await server.handle_tool_call("graq_nonexistent", {})
    assert result.is_error
    assert "Unknown tool" in result.content


# ---------------------------------------------------------------------------
# Bonus: MCPToolResult.to_dict
# ---------------------------------------------------------------------------

def test_tool_result_to_dict():
    """Verify MCPToolResult serialization."""
    result = MCPToolResult("hello", is_error=False)
    d = result.to_dict()
    assert d["content"][0]["type"] == "text"
    assert d["content"][0]["text"] == "hello"
    assert d["isError"] is False

    err = MCPToolResult("boom", is_error=True)
    d = err.to_dict()
    assert d["isError"] is True


# ---------------------------------------------------------------------------
# _ensure_graph regression test (Group 5 gate — v0.34.0)
# Guards that the _ensure_graph fix (JSONGraphConnector → Graqle.from_json)
# does not break graq_context, graq_reason, graq_inspect, graq_search.
# ---------------------------------------------------------------------------

def test_ensure_graph_loads_graqle_instance(tmp_path):
    """_ensure_graph must produce a Graqle instance via Graqle.from_json.
    All four existing tools depend on this — if the loader changes type they all break."""
    import json
    from graqle.core.graph import Graqle

    # Write a minimal valid graqle.json to a temp path
    minimal = {"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []}
    graph_file = tmp_path / "graqle.json"
    graph_file.write_text(json.dumps(minimal))

    srv = MCPServer(config=MCPConfig(graph_path=str(graph_file)))
    srv._ensure_graph()
    assert isinstance(srv._graph, Graqle), (
        "_ensure_graph must return a Graqle instance (not raw NX or connector). "
        "graq_context/reason/inspect/search all depend on this."
    )


@pytest.mark.asyncio
async def test_ensure_graph_existing_tools_unaffected_after_predict_added(server: MCPServer):
    """graq_context, graq_reason, graq_inspect all still work after graq_predict was added.
    Regression guard: _ensure_graph change must not alter shared tool behaviour."""
    import json

    # graq_inspect
    r = await server.handle_tool_call("graq_inspect", {})
    assert not r.is_error
    data = json.loads(r.content)
    assert "nodes" in data
    assert data["nodes"] == 3

    # graq_context
    r = await server.handle_tool_call("graq_context", {"entity": "Auth Lambda"})
    assert not r.is_error
    assert "Auth Lambda" in r.content

    # graq_search
    r = await server.handle_tool_call("graq_search", {"query": "auth"})
    assert not r.is_error
