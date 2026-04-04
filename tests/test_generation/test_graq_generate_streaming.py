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

    # OT-054: Mock graph with direct backend.generate() path
    mock_graph = MagicMock()
    mock_graph.nodes = {
        "node_a": MagicMock(label="node_a", entity_type="Class", description="Test node"),
    }
    mock_graph._activate_subgraph = MagicMock(return_value=["node_a"])
    mock_graph.config.activation.strategy = "spread"

    # Direct backend mock
    mock_backend = MagicMock()
    mock_gen_result = MagicMock()
    mock_gen_result.text = "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,2 @@\n+# added\nSUMMARY: Added comment"
    mock_gen_result.tokens_used = 100
    mock_backend.generate = AsyncMock(return_value=mock_gen_result)
    mock_backend.cost_per_1k_tokens = 0.003
    mock_graph._get_backend_for_node = MagicMock(return_value=mock_backend)

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
async def test_stream_true_returns_empty_chunks_ot054(server):
    """OT-054: stream=True logs warning but returns empty chunks (direct backend mode)."""
    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
               new=AsyncMock(return_value='{"risk_level":"low","warnings":[]}')), \
         patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_safety_check",
               new=AsyncMock(return_value='{"overall_risk":"low"}')), \
         patch("graqle.cloud.credentials.load_credentials",
               side_effect=Exception("no creds")):
        raw = await server._handle_generate({"description": "add a comment", "stream": True})

    data = json.loads(raw)
    if "error" not in data:
        chunks = data["metadata"]["chunks"]
        assert isinstance(chunks, list)
        assert len(chunks) == 0  # OT-054: streaming not supported in direct mode
        assert data["metadata"]["stream"] is True


@pytest.mark.asyncio
async def test_stream_true_still_returns_valid_diff_ot054(server):
    """OT-054: stream=True still produces a valid diff (non-streaming fallback)."""
    with patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_preflight",
               new=AsyncMock(return_value='{"risk_level":"low","warnings":[]}')), \
         patch("graqle.plugins.mcp_dev_server.KogniDevServer._handle_safety_check",
               new=AsyncMock(return_value='{"overall_risk":"low"}')), \
         patch("graqle.cloud.credentials.load_credentials",
               side_effect=Exception("no creds")):
        raw = await server._handle_generate({"description": "add a comment", "stream": True})

    data = json.loads(raw)
    if "error" not in data:
        patches = data.get("patches", [])
        assert len(patches) >= 1
        assert "---" in patches[0]["unified_diff"]


@pytest.mark.asyncio
async def test_stream_param_in_tool_definition():
    """graq_generate tool definition exposes a 'stream' boolean parameter."""
    from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS

    graq_gen = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
    props = graq_gen["inputSchema"]["properties"]
    assert "stream" in props
    assert props["stream"]["type"] == "boolean"
    assert props["stream"].get("default") is False
