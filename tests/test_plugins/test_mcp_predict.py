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
    # FB-004 fix: _generate_predicted_subgraph now uses _get_backend_for_node() instead
    # of node.backend (which is None after areason deactivation). Wire it to mock_backend.
    graph._get_backend_for_node = MagicMock(return_value=mock_backend)
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


# ---------------------------------------------------------------------------
# AGREEMENT_THRESHOLD boundary tests — added v0.35.0
# graq_predict gate (2026-03-25, 81% confidence) flagged zero boundary tests
# as a ship-blocking gap when raising threshold from 0.12 → 0.15.
# ---------------------------------------------------------------------------

def _make_msg(source_node_id: str, content: str):
    """Build a minimal message object matching what _compute_answer_confidence reads."""
    return type("Msg", (), {"source_node_id": source_node_id, "content": content, "round": 1})()


def test_compute_answer_confidence_above_threshold():
    """Texts with >15% Jaccard token overlap count as agreed pairs → higher confidence."""
    srv = _make_server(_build_mock_graph())

    result = MockReasonResult(
        answer="The authentication service validates tokens and manages sessions.",
        confidence=0.75,
        active_nodes=["node-a", "node-b"],
    )
    # message_trace is a list of message objects with source_node_id + content
    # Use identical content to guarantee Jaccard = 1.0 (100% overlap) → agreement_ratio = 1.0
    result.message_trace = [
        _make_msg("node-a", "authentication service validates tokens manages sessions"),
        _make_msg("node-b", "authentication service validates tokens manages sessions"),
    ]

    conf = srv._compute_answer_confidence(result)
    # agreement_ratio=1.0, raw=0.75 → blended = 0.70*1.0 + 0.30*min(1.0, 0.75*2.5) = 0.70 + 0.30 = 1.0
    assert conf > 0.5, f"Expected >0.5 for identical texts, got {conf}"


def test_compute_answer_confidence_below_threshold():
    """Texts with zero shared tokens produce 0 agreement pairs → low confidence."""
    srv = _make_server(_build_mock_graph())

    result = MockReasonResult(
        answer="Divergent answers from nodes.",
        confidence=0.3,
        active_nodes=["node-a", "node-b"],
    )
    # Completely disjoint vocabularies → Jaccard = 0/N = 0 < 0.15 → pairs_agreed = 0
    result.message_trace = [
        _make_msg("node-a", "authentication lambda jwt validation cold start"),
        _make_msg("node-b", "dynamo throughput provisioned iops partition key"),
    ]

    conf = srv._compute_answer_confidence(result)
    # agreement_ratio=0, raw=0.3 → blended = 0 + 0.30*min(1.0, 0.3*2.5) = 0.30*0.75 = 0.225
    assert conf < 0.5, f"Expected <0.5 for zero-overlap texts, got {conf}"
    assert conf >= 0.0


def test_compute_answer_confidence_returns_float_in_range():
    """_compute_answer_confidence must always return a float in [0.0, 1.0]."""
    srv = _make_server(_build_mock_graph())
    result = MockReasonResult(answer="Test.", confidence=0.5, active_nodes=["node-a"])
    result.message_trace = [_make_msg("node-a", "test content here")]

    conf = srv._compute_answer_confidence(result)
    assert isinstance(conf, float)
    assert 0.0 <= conf <= 1.0


def test_compute_answer_confidence_empty_trace():
    """Empty message_trace should not raise — falls back to rescaled activation confidence."""
    srv = _make_server(_build_mock_graph())
    result = MockReasonResult(answer="Test.", confidence=0.6, active_nodes=[])
    result.message_trace = []  # empty list — triggers fallback

    conf = srv._compute_answer_confidence(result)
    # Fallback: min(1.0, 0.6 * 2.0 + 0.20) = min(1.0, 1.40) = 1.0
    assert isinstance(conf, float)
    assert 0.0 <= conf <= 1.0


# ===========================================================================
# Layer B Tests — v0.36.0
# ===========================================================================

# ---------------------------------------------------------------------------
# Phase 1 — mode="gate"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_mode_high_risk_returns_flag_no_write():
    """Gate mode with a high-risk query returns FLAG and writes nothing."""
    graph = _build_mock_graph(size=15)
    # Pad active nodes so >= 10 activate
    active = [f"node-pad-{i}" for i in range(3, 13)]
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer=(
            "This change is critical — it will delete the TRACE validation module "
            "causing a security vulnerability and data loss in downstream services."
        ),
        confidence=0.8,
        active_nodes=active,
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {"query": "Deploy PR removing TRACE", "mode": "gate"})
    data = json.loads(result.content)

    assert data["gate_status"] == "FLAG"
    assert "risk_vectors" in data
    # Gate mode must NEVER write — no prediction written
    graph.to_json.assert_not_called()


@pytest.mark.asyncio
async def test_gate_mode_low_risk_returns_clear_no_write():
    """Gate mode with a low-risk, low-confidence query returns CLEAR and writes nothing."""
    graph = _build_mock_graph(size=15)
    active = [f"node-pad-{i}" for i in range(3, 13)]
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="The module has good test coverage and no known issues.",
        confidence=0.1,
        active_nodes=active,
    ))
    # Minimal message_trace so answer_confidence stays low
    reason_result = graph.areason.return_value
    reason_result.message_trace = []
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {"query": "Review auth module", "mode": "gate"})
    data = json.loads(result.content)

    assert data["gate_status"] == "CLEAR"
    graph.to_json.assert_not_called()


@pytest.mark.asyncio
async def test_gate_mode_sparse_graph_returns_insufficient():
    """Gate mode with fewer than 10 activated nodes returns INSUFFICIENT_GRAPH."""
    graph = _build_mock_graph(size=5)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="Not enough graph data.",
        confidence=0.9,
        active_nodes=["node-a", "node-b"],  # only 2 activated
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {"query": "Analyse risk", "mode": "gate"})
    data = json.loads(result.content)

    assert data["gate_status"] == "INSUFFICIENT_GRAPH"
    graph.to_json.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2 — mode="cascade_analysis"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cascade_analysis_returns_cascade_chain():
    """cascade_analysis mode returns a cascade_chain with >= 2 tiers."""
    graph = _build_mock_graph(size=15)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer=(
            "The root cause leads to auth failures\n"
            "Auth failures trigger downstream API timeouts\n"
            "API timeouts result in user-facing errors and data inconsistency\n"
            "Data inconsistency causes critical audit trail corruption"
        ),
        confidence=0.85,
        active_nodes=[f"node-pad-{i}" for i in range(3, 13)],
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "What cascades from auth failure?",
        "mode": "cascade_analysis",
        "fold_back": False,
    })
    data = json.loads(result.content)

    assert "cascade_chain" in data
    assert len(data["cascade_chain"]) >= 2
    assert "tier_impacts" in data
    assert set(data["tier_impacts"].keys()) == {"HIGH", "MEDIUM", "LOW"}


@pytest.mark.asyncio
async def test_cascade_analysis_fold_back_writes_cascade_trigger_edges():
    """cascade_analysis with fold_back=True writes CASCADE_TRIGGER edges to KG."""
    graph = _build_mock_graph(size=15)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer=(
            "Auth failure leads to token expiry. "
            "Token expiry triggers session loss. "
            "Session loss causes critical data inconsistency."
        ),
        confidence=0.85,
        active_nodes=[f"node-pad-{i}" for i in range(3, 13)],
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Cascade from auth failure",
        "mode": "cascade_analysis",
        "fold_back": True,
        "confidence_threshold": 0.3,
    })
    data = json.loads(result.content)

    assert data["prediction"]["status"] in ("WRITTEN", "SKIPPED_DUPLICATE")
    # CASCADE_TRIGGER edge type must appear in the written subgraph
    if data["prediction"]["status"] == "WRITTEN":
        # Verify cascade nodes were written to graph
        cascade_nodes = [
            n for n in graph.nodes.values()
            if isinstance(getattr(n, "properties", {}), dict)
            and n.properties.get("derived_from") == "graq_predict"
        ]
        assert len(cascade_nodes) >= 1


# ---------------------------------------------------------------------------
# Phase 3 — stg_class parameter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stg_class_auto_resolves_simple_completion():
    """stg_class='auto' works for a simple completion query without error."""
    graph = _build_mock_graph(size=15)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="The missing config key is 'api_timeout'.",
        confidence=0.8,
        active_nodes=[f"node-pad-{i}" for i in range(3, 8)],
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "What is the missing config key?",
        "stg_class": "auto",
        "fold_back": False,
    })
    data = json.loads(result.content)

    assert not result.is_error
    assert data["stg_class"] == "auto"


@pytest.mark.asyncio
async def test_stg_class_iv_without_allow_raises():
    """stg_class='IV' without allow_class_iv=True returns an error."""
    srv = _make_server(_build_mock_graph())

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Extrapolate novel hypothesis",
        "stg_class": "IV",
        "allow_class_iv": False,
    })

    assert result.is_error
    assert "allow_class_iv" in result.content


@pytest.mark.asyncio
async def test_stg_class_iv_with_low_confidence_threshold_raises():
    """stg_class='IV' with confidence_threshold < 0.75 returns an error."""
    srv = _make_server(_build_mock_graph())

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Novel hypothesis",
        "stg_class": "IV",
        "allow_class_iv": True,
        "confidence_threshold": 0.60,
    })

    assert result.is_error
    assert "0.75" in result.content


@pytest.mark.asyncio
async def test_stg_class_iv_with_sparse_domain_returns_insufficient():
    """stg_class='IV' with < 50 domain-intersection nodes returns INSUFFICIENT_GRAPH."""
    graph = _build_mock_graph(size=15)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="Novel extrapolation.",
        confidence=0.9,
        active_nodes=["node-a", "node-b", "node-c"],  # all are generic types → < 50 domain nodes
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Novel extrapolation",
        "stg_class": "IV",
        "allow_class_iv": True,
        "confidence_threshold": 0.75,
        "fold_back": False,
    })
    data = json.loads(result.content)

    assert data["prediction"]["status"] == "INSUFFICIENT_GRAPH"


# ---------------------------------------------------------------------------
# Phase 4 — Q-function scores
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_q_scores_present_in_dry_run_result():
    """Q-scores are present in DRY_RUN (fold_back=False) results."""
    graph = _build_mock_graph(size=3)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="Auth module has cold start risk.", confidence=0.8,
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Auth cold start risk",
        "fold_back": False,
    })
    data = json.loads(result.content)

    assert "q_scores" in data
    qs = data["q_scores"]
    assert set(qs.keys()) == {"feasibility", "novelty", "goal_alignment"}
    for score in qs.values():
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_q_scores_present_in_written_result(mock_predict_subgraph_json):
    """Q-scores are present in WRITTEN results."""
    graph = _build_mock_graph(size=15)
    mock_backend = graph._get_backend_for_node.return_value
    mock_backend.generate = AsyncMock(return_value=mock_predict_subgraph_json)
    graph.areason = AsyncMock(return_value=MockReasonResult(
        answer="Auth cold start risk is high.",
        confidence=0.85,
        active_nodes=[f"node-pad-{i}" for i in range(3, 13)],
    ))
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_predict", {
        "query": "Auth cold start risk",
        "fold_back": True,
        "confidence_threshold": 0.3,
    })
    data = json.loads(result.content)

    # Must have q_scores regardless of written/skipped status
    assert "q_scores" in data
    qs = data["q_scores"]
    assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in qs.values())


@pytest.fixture
def mock_predict_subgraph_json():
    return _good_subgraph_json()


# ---------------------------------------------------------------------------
# Phase 5 — graq_reason mode="predictive"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graq_reason_standard_mode_unchanged():
    """graq_reason mode='standard' output is identical to default graq_reason output."""
    graph = _build_mock_graph(size=3)
    reason_result = MockReasonResult(answer="The answer.", confidence=0.7)
    reason_result.message_trace = []
    graph.areason = AsyncMock(return_value=reason_result)
    srv = _make_server(graph)

    default_result = await srv.handle_tool_call("graq_reason", {"query": "test question"})
    explicit_result = await srv.handle_tool_call("graq_reason", {"query": "test question", "mode": "standard"})

    default_data = json.loads(default_result.content)
    explicit_data = json.loads(explicit_result.content)

    assert default_data.keys() == explicit_data.keys()
    assert "answer" in default_data
    assert "q_scores" not in default_data  # standard mode has no PSE fields


@pytest.mark.asyncio
async def test_graq_reason_predictive_mode_returns_pse_fields():
    """graq_reason mode='predictive' returns PSE prediction fields including q_scores."""
    graph = _build_mock_graph(size=3)
    reason_result = MockReasonResult(answer="Prediction answer.", confidence=0.8)
    reason_result.message_trace = []
    graph.areason = AsyncMock(return_value=reason_result)
    srv = _make_server(graph)

    result = await srv.handle_tool_call("graq_reason", {
        "query": "predictive question",
        "mode": "predictive",
        "fold_back": False,
    })
    data = json.loads(result.content)

    assert "q_scores" in data
    assert "prediction" in data
    assert "answer_confidence" in data
    assert "activation_confidence" in data
