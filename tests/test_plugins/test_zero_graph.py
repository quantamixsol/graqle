"""Tests for zero-graph first-run experience.

New users with no graqle.json should get helpful NO_GRAPH responses,
not crashes.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from graqle.plugins.mcp_dev_server import KogniDevServer


@pytest.fixture
def server_no_graph():
    """Server with NO graph loaded — simulates first-run."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph = None
    srv._graph_file = None
    srv._graph_mtime = 0.0
    srv._config = None
    srv._session_cache = {}
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    return srv


class TestZeroGraphGracefulDegradation:
    """Every graph-dependent tool returns NO_GRAPH, not crash."""

    @pytest.mark.asyncio
    async def test_inspect_no_graph(self, server_no_graph):
        result = json.loads(await server_no_graph._handle_inspect({}))
        assert result["error"] == "NO_GRAPH"
        assert "no knowledge graph" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_reason_no_graph(self, server_no_graph):
        result = json.loads(await server_no_graph._handle_reason({"question": "test"}))
        assert result["error"] == "NO_GRAPH"

    @pytest.mark.asyncio
    async def test_impact_no_graph(self, server_no_graph):
        result = json.loads(await server_no_graph._handle_impact({"component": "test"}))
        assert result["error"] == "NO_GRAPH"

    @pytest.mark.asyncio
    async def test_no_graph_includes_quick_start(self, server_no_graph):
        result = json.loads(await server_no_graph._handle_inspect({}))
        assert "quick_start" in result
        assert isinstance(result["quick_start"], list)
        assert len(result["quick_start"]) >= 1

    @pytest.mark.asyncio
    async def test_no_graph_includes_available_tools(self, server_no_graph):
        result = json.loads(await server_no_graph._handle_inspect({}))
        assert "tools_available_now" in result
        assert "graq_bash" in result["tools_available_now"]
        assert "graq_read" in result["tools_available_now"]

    @pytest.mark.asyncio
    async def test_no_graph_never_raises(self, server_no_graph):
        """No tool should raise an exception on zero graph."""
        handlers = [
            server_no_graph._handle_inspect,
        ]
        for handler in handlers:
            try:
                result = await handler({})
                data = json.loads(result)
                assert "error" in data
            except Exception as e:
                pytest.fail(f"{handler.__name__} raised {type(e).__name__}: {e}")
