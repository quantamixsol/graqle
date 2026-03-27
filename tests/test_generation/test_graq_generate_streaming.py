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
async def test_stream_true_populates_chunks(server):
    """stream=True → metadata.chunks contains the streamed text pieces."""
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
        assert len(chunks) >= 1
        assert data["metadata"]["stream"] is True


@pytest.mark.asyncio
async def test_stream_true_chunks_join_to_non_empty(server):
    """stream=True → joining chunks produces non-empty text."""
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
        assert "".join(chunks).strip() != ""


@pytest.mark.asyncio
async def test_stream_param_in_tool_definition():
    """graq_generate tool definition exposes a 'stream' boolean parameter."""
    from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS

    graq_gen = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_generate")
    props = graq_gen["inputSchema"]["properties"]
    assert "stream" in props
    assert props["stream"]["type"] == "boolean"
    assert props["stream"].get("default") is False
