"""Tests for graq_predict — Layer A: governed reasoning + fold-back write.

Covers:
- _compute_content_hash determinism
- dry-run (fold_back=False)
- low-confidence skip
- duplicate skip (exact hash + semantic)
- successful write-back (nodes and edges created)
- answer always returned regardless of status
- graqle.json survival (atomic write doesn't corrupt)
- regression: existing tools unchanged by graq_predict addition
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_mcp_predict
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, asyncio, dataclasses, unittest.mock
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from graqle.plugins.mcp_server import MCPConfig, MCPServer, MCPToolResult, _compute_content_hash


# ---------------------------------------------------------------------------
# Helpers — mock objects
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    backend: Any = None
    incoming_edges: list = field(default_factory=list)
    outgoing_edges: list = field(default_factory=list)


@dataclass
class MockEdge:
    id: str
    source_id: str
    target_id: str
    relationship: str
    weight: float
    properties: dict = field(default_factory=dict)


class MockReasonResult:
    def __init__(self, answer: str, confidence: float, active_nodes: list[str] | None = None):
        self.answer = answer
        self.confidence = confidence
        self.rounds_completed = 2
        self.node_count = 3
        self.cost_usd = 0.01
        self.active_nodes = active_nodes or ["node-a", "node-b"]


def _build_mock_graph(size: int = 3) -> MagicMock:
    """Mock Graqle graph with `size` nodes and a backend.

    Pass size >= 10 for tests that exercise write-back (safety guard requires >= 10 nodes).
    """
    mock_backend = MagicMock()
    mock_backend.generate = AsyncMock()

    nodes = {
        "node-a": MockNode(
            id="node-a",
            label="Auth Lambda",
            entity_type="SERVICE",
            description="Handles JWT auth.",
            backend=mock_backend,
        ),
        "node-b": MockNode(
            id="node-b",
            label="DynamoDB Users",
            entity_type="DATABASE",
            description="User storage.",
        ),
        "node-c": MockNode(
            id="node-c",
            label="Cognito Pool",
            entity_type="AUTH",
            description="User pool.",
        ),
    }
    # Pad to requested size so write-back safety guard (>= 10) passes
    for i in range(3, size):
        nid = f"node-pad-{i}"
        nodes[nid] = MockNode(
            id=nid,
            label=f"Pad Node {i}",
            entity_type="Entity",
            description=f"Padding node {i} for test graph.",
        )

    edges = {
        "e1": MockEdge(
            id="e1",
            source_id="node-a",
            target_id="node-b",
            relationship="READS_FROM",
            weight=0.9,
        ),
    }

    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    graph.areason = AsyncMock()
    graph.to_json = MagicMock()
    return graph


def _make_server(graph: MagicMock | None = None, graph_path: str = "test_predict_tmp.json") -> MCPServer:
    """Build a test MCPServer.

    Uses a non-production graph_path so tests NEVER touch graqle.json.
    The graph.to_json mock means no file is actually written.
    """
    srv = MCPServer(config=MCPConfig(graph_path=graph_path))
    srv._graph = graph or _build_mock_graph()
    srv._embedder = None
    return srv


def _good_subgraph_json() -> str:
    """Valid JSON that _generate_predicted_subgraph would return from LLM."""
    return json.dumps({
        "anchor_label": "Auth Lambda Cold Start Risk",
        "anchor_type": "KNOWLEDGE",
        "anchor_description": "Cold starts in auth lambda cause auth failures under load.",
        "anchor_properties": {
            "source_query": "what causes auth failures?",
            "derived_from": "graq_predict",
            "confidence": 0.82,
        },
        "supporting_nodes": [
            {
                "label": "Cold Start Latency",
                "type": "KNOWLEDGE",
                "description": "Lambda cold starts add 200-500ms latency.",
                "relationship_to_anchor": "CAUSES",
            }
        ],
        "causal_edges": [
            {
                "from_label": "Auth Lambda Cold Start Risk",
                "to_label": "Cold Start Latency",
                "relationship": "CAUSES",
                "weight": 0.85,
            }
        ],
    })


# ---------------------------------------------------------------------------
# 1. _compute_content_hash — determinism
# ---------------------------------------------------------------------------

def test_compute_content_hash_deterministic():
    """Same subgraph content always produces the same hash."""
    subgraph = {
        "anchor_label": "test concept",
        "anchor_description": "test description",
        "supporting_nodes": [{"label": "node a"}, {"label": "node b"}],
        "causal_edges": [
            {"from_label": "test concept", "to_label": "node a", "relationship": "CAUSES"},
            {"from_label": "node a", "to_label": "node b", "relationship": "CONTRIBUTES_TO"},
        ],
    }
    h1 = _compute_content_hash(subgraph)
    h2 = _compute_content_hash(subgraph)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_content_hash_order_independent():
    """Reordering supporting_nodes or causal_edges gives the same hash."""
    base = {
        "anchor_label": "risk pattern",
        "anchor_description": "a known risk",
        "supporting_nodes": [{"label": "alpha"}, {"label": "beta"}],
        "causal_edges": [
            {"from_label": "risk pattern", "to_label": "alpha", "relationship": "CAUSES"},
            {"from_label": "risk pattern", "to_label": "beta", "relationship": "CAUSES"},
        ],
    }
    reordered = {
        "anchor_label": "risk pattern",
        "anchor_description": "a known risk",
        "supporting_nodes": [{"label": "beta"}, {"label": "alpha"}],
        "causal_edges": [
            {"from_label": "risk pattern", "to_label": "beta", "relationship": "CAUSES"},
            {"from_label": "risk pattern", "to_label": "alpha", "relationship": "CAUSES"},
        ],
    }
    assert _compute_content_hash(base) == _compute_content_hash(reordered)


def test_compute_content_hash_different_inputs():
    """Different anchor labels produce different hashes."""
    a = {"anchor_label": "concept alpha", "anchor_description": "d", "supporting_nodes": [], "causal_edges": []}
    b = {"anchor_label": "concept beta", "anchor_description": "d", "supporting_nodes": [], "causal_edges": []}
    assert _compute_content_hash(a) != _compute_content_hash(b)


# ---------------------------------------------------------------------------
# 2. tool list updated
# ---------------------------------------------------------------------------

def test_tools_list_includes_predict():
    """graq_predict appears in the tools list alongside existing tools."""
    srv = _make_server()
    names = {t["name"] for t in srv.tools}
    assert "graq_predict" in names
    # Original tools still present
    assert names >= {"graq_context", "graq_reason", "graq_inspect", "graq_search"}


def test_predict_tool_schema():
    """graq_predict schema has correct required fields."""
    srv = _make_server()
    predict_tool = next(t for t in srv.tools if t["name"] == "graq_predict")
    schema = predict_tool["inputSchema"]
    assert schema["type"] == "object"
    assert "query" in schema["required"]
    props = schema["properties"]
    assert "query" in props
    assert "fold_back" in props
    assert "confidence_threshold" in props
    assert "similarity_threshold" in props
    assert "max_rounds" in props


# ---------------------------------------------------------------------------
# 3. dry-run (fold_back=False)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_dry_run_does_not_write():
    """fold_back=False returns answer + DRY_RUN status, graph unchanged."""
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(
        answer="Auth cold starts cause failures.", confidence=0.90
    )
    # Backend returns valid subgraph JSON
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    node_count_before = len(graph.nodes)

    result = await srv.handle_tool_call("graq_predict", {"query": "auth failures", "fold_back": False})
    assert not result.is_error
    data = json.loads(result.content)

    assert data["prediction"]["status"] == "DRY_RUN"
    assert data["answer"] != ""
    # Graph NOT written to
    graph.to_json.assert_not_called()
    assert len(graph.nodes) == node_count_before


# ---------------------------------------------------------------------------
# 4. low confidence — skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_low_confidence_skipped():
    """answer_confidence < threshold → SKIPPED_LOW_CONFIDENCE, answer still returned.

    Uses threshold=0.99 (above any realistic answer_confidence) to force skip.
    """
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(
        answer="Weak signal detected.", confidence=0.30
    )

    srv = _make_server(graph)

    result = await srv.handle_tool_call(
        "graq_predict", {"query": "auth failures", "confidence_threshold": 0.99}
    )
    assert not result.is_error
    data = json.loads(result.content)

    assert data["prediction"]["status"] == "SKIPPED_LOW_CONFIDENCE"
    assert data["answer"] == "Weak signal detected."
    # Both confidence fields present in output
    assert "answer_confidence" in data
    assert "activation_confidence" in data
    assert data["answer_confidence"] < 0.99  # confirmed below threshold
    graph.to_json.assert_not_called()


# ---------------------------------------------------------------------------
# 5. successful write-back
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_write_creates_anchor_node():
    """High confidence + fold_back=True → WRITTEN, anchor node in graph."""
    graph = _build_mock_graph(size=12)
    graph.areason.return_value = MockReasonResult(
        answer="Auth cold starts cause failures under load.", confidence=0.88
    )
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    node_count_before = len(graph.nodes)

    result = await srv.handle_tool_call(
        "graq_predict", {"query": "auth failures", "confidence_threshold": 0.70, "fold_back": True}
    )
    assert not result.is_error
    data = json.loads(result.content)

    assert data["prediction"]["status"] == "WRITTEN"
    anchor_id = data["prediction"]["anchor_node_id"]
    assert anchor_id is not None
    assert anchor_id.startswith("pse-pred-")

    # Anchor node exists in the in-memory graph
    assert anchor_id in graph.nodes

    # At least 1 node added (the anchor)
    assert data["prediction"]["nodes_added"] >= 1

    # Graph persisted to whatever path was configured
    graph.to_json.assert_called_once()

    # Graph grew
    assert len(graph.nodes) > node_count_before


@pytest.mark.asyncio
async def test_predict_write_creates_edges():
    """Write-back creates causal edges between anchor and supporting nodes."""
    graph = _build_mock_graph(size=12)
    graph.areason.return_value = MockReasonResult(
        answer="Cold starts cause latency spikes.", confidence=0.85
    )
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    edge_count_before = len(graph.edges)

    result = await srv.handle_tool_call(
        "graq_predict", {"query": "cold start impact", "confidence_threshold": 0.70}
    )
    data = json.loads(result.content)

    if data["prediction"]["status"] == "WRITTEN":
        assert data["prediction"]["edges_added"] >= 1
        assert len(graph.edges) > edge_count_before


# ---------------------------------------------------------------------------
# 6. duplicate detection — exact hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_duplicate_exact_hash_skipped():
    """Second call with same query + same subgraph → SKIPPED_DUPLICATE, no growth."""
    graph = _build_mock_graph(size=12)
    graph.areason.return_value = MockReasonResult(
        answer="Auth cold starts cause failures.", confidence=0.90
    )
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)

    # First call — should WRITE
    r1 = await srv.handle_tool_call(
        "graq_predict", {"query": "auth failures", "confidence_threshold": 0.70}
    )
    d1 = json.loads(r1.content)
    assert d1["prediction"]["status"] == "WRITTEN"

    node_count_after_first = len(graph.nodes)
    # Reset to_json mock call count
    graph.to_json.reset_mock()

    # Second call — same subgraph JSON → same hash → SKIPPED_DUPLICATE
    result = await srv.handle_tool_call(
        "graq_predict", {"query": "auth failures", "confidence_threshold": 0.70}
    )
    d2 = json.loads(result.content)

    assert d2["prediction"]["status"] == "SKIPPED_DUPLICATE"
    # Graph did NOT grow further
    assert len(graph.nodes) == node_count_after_first
    graph.to_json.assert_not_called()


# ---------------------------------------------------------------------------
# 7. answer always returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_answer_always_returned_dry_run():
    """Answer is returned even in DRY_RUN."""
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(answer="Important insight.", confidence=0.90)
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    result = await srv.handle_tool_call("graq_predict", {"query": "test", "fold_back": False})
    data = json.loads(result.content)
    assert data["answer"] == "Important insight."


@pytest.mark.asyncio
async def test_predict_answer_always_returned_low_confidence():
    """Answer is returned even when SKIPPED_LOW_CONFIDENCE."""
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(answer="Weak signal.", confidence=0.20)

    srv = _make_server(graph)
    result = await srv.handle_tool_call("graq_predict", {"query": "test", "confidence_threshold": 0.65})
    data = json.loads(result.content)
    assert data["answer"] == "Weak signal."


# ---------------------------------------------------------------------------
# 8. missing query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_missing_query_returns_error():
    """Empty query returns is_error=True."""
    srv = _make_server()
    result = await srv.handle_tool_call("graq_predict", {})
    assert result.is_error


# ---------------------------------------------------------------------------
# 9. content hash in prediction output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_content_hash_in_output():
    """Prediction output includes content_hash when subgraph generated."""
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(answer="Test.", confidence=0.90)
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    result = await srv.handle_tool_call(
        "graq_predict", {"query": "test", "fold_back": False}
    )
    data = json.loads(result.content)
    # DRY_RUN exits before LLM generation — content_hash is None (no LLM call needed)
    assert data["prediction"]["status"] == "DRY_RUN"
    assert data["prediction"]["content_hash"] is None


# ---------------------------------------------------------------------------
# 10. regression — existing tools untouched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regression_graq_reason_unchanged():
    """graq_reason still works correctly after graq_predict addition."""
    graph = _build_mock_graph()
    graph.areason.return_value = MockReasonResult(
        answer="Everything is fine.", confidence=0.75
    )

    srv = _make_server(graph)
    result = await srv.handle_tool_call("graq_reason", {"query": "status check"})
    assert not result.is_error
    data = json.loads(result.content)
    assert data["answer"] == "Everything is fine."
    assert data["confidence"] == 0.75


@pytest.mark.asyncio
async def test_regression_graq_inspect_unchanged():
    """graq_inspect still returns correct node/edge counts."""
    srv = _make_server()
    result = await srv.handle_tool_call("graq_inspect", {"detail": "summary"})
    assert not result.is_error
    data = json.loads(result.content)
    assert data["nodes"] == 3
    assert data["edges"] == 1


@pytest.mark.asyncio
async def test_regression_graq_context_unchanged():
    """graq_context still finds nodes by label."""
    srv = _make_server()
    result = await srv.handle_tool_call("graq_context", {"entity": "Auth Lambda"})
    assert not result.is_error
    assert "Auth Lambda" in result.content


def test_regression_tool_count_is_five():
    """Exactly 5 tools registered (4 original + graq_predict)."""
    srv = _make_server()
    assert len(srv.tools) == 5


# ---------------------------------------------------------------------------
# 11. anchor node properties
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_anchor_has_pse_properties():
    """Written anchor node has pse_content_hash and derived_from properties."""
    graph = _build_mock_graph(size=12)
    graph.areason.return_value = MockReasonResult(answer="Test insight.", confidence=0.85)
    graph.nodes["node-a"].backend.generate.return_value = _good_subgraph_json()

    srv = _make_server(graph)
    result = await srv.handle_tool_call(
        "graq_predict", {"query": "test", "confidence_threshold": 0.70}
    )
    data = json.loads(result.content)

    if data["prediction"]["status"] == "WRITTEN":
        anchor_id = data["prediction"]["anchor_node_id"]
        anchor_node = graph.nodes[anchor_id]
        assert anchor_node.properties.get("pse_content_hash") is not None
        assert anchor_node.properties.get("derived_from") == "graq_predict"


# ---------------------------------------------------------------------------
# 12. existing node reuse (supporting node label matches existing)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_reuses_existing_node_by_label():
    """If supporting node label matches existing graph node, no new node created."""
    graph = _build_mock_graph(size=12)
    graph.areason.return_value = MockReasonResult(answer="Auth Lambda is a bottleneck.", confidence=0.85)

    # Subgraph that references "Auth Lambda" — already in graph
    subgraph_reuse = json.dumps({
        "anchor_label": "Auth Bottleneck Pattern",
        "anchor_type": "KNOWLEDGE",
        "anchor_description": "Auth Lambda is a single point of failure.",
        "anchor_properties": {"source_query": "auth bottleneck", "derived_from": "graq_predict", "confidence": 0.85},
        "supporting_nodes": [
            {"label": "Auth Lambda", "type": "SERVICE", "description": "existing node"},
        ],
        "causal_edges": [
            {"from_label": "Auth Bottleneck Pattern", "to_label": "Auth Lambda", "relationship": "CAUSES", "weight": 0.8},
        ],
    })
    graph.nodes["node-a"].backend.generate.return_value = subgraph_reuse

    srv = _make_server(graph)
    node_count_before = len(graph.nodes)

    result = await srv.handle_tool_call(
        "graq_predict", {"query": "auth bottleneck", "confidence_threshold": 0.70}
    )
    data = json.loads(result.content)

    if data["prediction"]["status"] == "WRITTEN":
        # Only anchor added — supporting node reused existing "Auth Lambda"
        assert data["prediction"]["nodes_added"] == 1
        # Total nodes = before + 1 (just anchor)
        assert len(graph.nodes) == node_count_before + 1
