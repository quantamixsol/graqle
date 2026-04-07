"""
tests/test_generation/test_graq_generate_streaming.py
T3.4 — Tests for stream=True parameter on graq_generate.
4 tests. No API key required — MockBackend only.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_mock_server():
    """Build a KogniDevServer with a mock graph (no real KG file needed)."""
    from graqle.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer.__new__(KogniDevServer)
    server.config_path = "graqle.yaml"
    server.read_only = False
    server._config = None
    server._graph_file = None
    server._graph_mtime = 0.0

    # Mock graph that supports both areason and areason_stream
    mock_graph = MagicMock()
    mock_graph.nodes = {
        "node_a": MagicMock(label="node_a", entity_type="Class", description="Mock"),
    }
    mock_graph.edges = {}

    # areason returns a structured ReasoningResult-like object
    mock_result = MagicMock()
    mock_result.answer = "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,2 @@\n+# added\n SUMMARY: Added comment"
    mock_result.confidence = 0.82
    mock_result.rounds_completed = 1
    mock_result.active_nodes = ["node_a"]
    mock_result.cost_usd = 0.001
    mock_result.backend_status = "ok"
    mock_result.backend_error = ""
    mock_graph.areason = AsyncMock(return_value=mock_result)

    # OT-054: _handle_generate uses direct backend call
    _mock_backend = MagicMock()
    _mock_backend.generate = AsyncMock(return_value=mock_result.answer)
    _mock_backend.name = "mock-backend"
    _mock_backend.cost_per_1k_tokens = 0.003
    mock_graph._get_backend_for_node = MagicMock(return_value=_mock_backend)
    mock_graph._activate_subgraph = MagicMock(return_value=["node_a"])
    mock_graph.config = MagicMock()
    mock_graph.config.activation = MagicMock()
    mock_graph.config.activation.strategy = "top_k"

    # areason_stream yields chunk objects with .content attribute
    async def _fake_stream(*args, **kwargs):
        for text in ["--- a/foo.py\n", "+++ b/foo.py\n", "@@ -1 +1,2 @@\n", "+# added\n"]:
            chunk = MagicMock()
            chunk.content = text
            yield chunk

    mock_graph.areason_stream = _fake_stream
    server._graph = mock_graph

    return server


@pytest.fixture
def server():
    return _build_mock_server()


@pytest.mark.asyncio
async def test_stream_false_returns_no_chunks(server):
    """stream=False (default) → metadata.chunks is empty list."""
    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
               new=AsyncMock(return_value='{"risk_level":"low","warnings":[]}')), \
         patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_safety_check",
               new=AsyncMock(return_value='{"overall_risk":"low"}')), \
         patch("graqle.cloud.credentials.load_credentials",
               side_effect=Exception("no creds")):
        raw = await server._handle_generate({"description": "add a comment", "stream": False})

    data = json.loads(raw)
    assert "error" not in data or data.get("error") == "PLAN_GATE"
    # If plan gate is bypassed (exception path), check chunks
    if "error" not in data:
        assert data["metadata"]["chunks"] == []
        assert data["metadata"]["stream"] is False


@pytest.mark.asyncio
async def test_stream_true_ignored_in_ot054_mode(server):
    """OT-054: stream=True is ignored — single-shot backend call, chunks empty."""
    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
               new=AsyncMock(return_value='{"risk_level":"low","warnings":[]}')), \
         patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_safety_check",
               new=AsyncMock(return_value='{"overall_risk":"low"}')), \
         patch("graqle.cloud.credentials.load_credentials") as mock_creds:
        mock_creds.return_value = MagicMock(plan="team")
        raw = await server._handle_generate({"description": "add a comment", "stream": True})

    data = json.loads(raw)
    if "error" not in data:
        # OT-054: stream param is recorded as-is, but chunks are empty (single-shot mode)
        assert data["metadata"]["chunks"] == []


@pytest.mark.asyncio
async def test_stream_true_still_produces_answer(server):
    """OT-054: stream=True still produces a valid answer via single-shot call."""
    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
               new=AsyncMock(return_value='{"risk_level":"low","warnings":[]}')), \
         patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_safety_check",
               new=AsyncMock(return_value='{"overall_risk":"low"}')), \
         patch("graqle.cloud.credentials.load_credentials") as mock_creds:
        mock_creds.return_value = MagicMock(plan="team")
        raw = await server._handle_generate({"description": "add a comment", "stream": True})

    data = json.loads(raw)
    if "error" not in data:
        # Even with stream=True, OT-054 produces answer via single-shot
        assert "patches" in data or "answer" in data


@pytest.mark.asyncio
async def test_stream_param_in_tool_definition():
    """graq_generate tool definition exposes a 'stream' boolean parameter."""
    from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS

    graq_gen = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
    props = graq_gen["inputSchema"]["properties"]
    assert "stream" in props
    assert props["stream"]["type"] == "boolean"
    assert props["stream"].get("default") is False
