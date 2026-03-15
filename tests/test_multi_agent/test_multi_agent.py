"""Tests for Multi-Agent Graph Access features (P1).

Covers:
1. graq context --json output
2. Read-only MCP server
3. File locking on concurrent writes
4. Caller parameter in metrics
"""

# ── graqle:intelligence ──
# module: tests.test_multi_agent.test_multi_agent
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, os, tempfile, threading +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers: create a minimal graph for testing
# ---------------------------------------------------------------------------

def _make_test_graph(tmp_path: Path) -> tuple:
    """Create a minimal Graqle graph for testing."""
    from graqle.core.edge import CogniEdge
    from graqle.core.graph import Graqle
    from graqle.core.node import CogniNode

    graph = Graqle()
    # Add nodes
    node_a = CogniNode(
        id="auth-service",
        label="Auth Service",
        entity_type="SERVICE",
        description="Handles authentication and JWT tokens",
        properties={"language": "python", "framework": "fastapi"},
    )
    node_b = CogniNode(
        id="user-db",
        label="User Database",
        entity_type="DATABASE",
        description="PostgreSQL database for user data",
        properties={"engine": "postgresql", "region": "eu-central-1"},
    )
    node_c = CogniNode(
        id="api-gateway",
        label="API Gateway",
        entity_type="SERVICE",
        description="Entry point for all API requests",
        properties={
            "api_style": "REST",
            # Simulate an embedding vector that should be filtered
            "_embedding_cache": [0.1] * 100,
        },
    )

    graph.nodes["auth-service"] = node_a
    graph.nodes["user-db"] = node_b
    graph.nodes["api-gateway"] = node_c

    edge = CogniEdge(
        id="e1",
        source_id="auth-service",
        target_id="user-db",
        relationship="READS_FROM",
        weight=1.0,
    )
    graph.edges["e1"] = edge
    node_a.outgoing_edges.append("e1")
    node_b.incoming_edges.append("e1")

    edge2 = CogniEdge(
        id="e2",
        source_id="api-gateway",
        target_id="auth-service",
        relationship="CALLS",
        weight=1.0,
    )
    graph.edges["e2"] = edge2
    node_c.outgoing_edges.append("e2")
    node_a.incoming_edges.append("e2")

    # Save to JSON
    graph_path = str(tmp_path / "graqle.json")
    graph.to_json(graph_path)

    return graph, graph_path


# ===========================================================================
# 1. graq context --json
# ===========================================================================


class TestContextJsonOutput:
    """Test that `graq context --json` outputs valid, clean JSON."""

    def test_json_output_is_valid_json(self, tmp_path):
        """--json flag produces valid JSON with expected keys."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "auth-service", "--json"])

        assert result.exit_code == 0, f"Exit code: {result.exit_code}, output: {result.output}"
        # Parse JSON from output
        data = json.loads(result.output)
        assert "name" in data
        assert "entity_type" in data
        assert "description" in data
        assert "properties" in data
        assert "relationships" in data
        assert data["name"] == "auth-service"
        assert data["entity_type"] == "SERVICE"

    def test_json_output_no_ansi_codes(self, tmp_path):
        """JSON output must not contain ANSI escape codes."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "auth-service", "--json"])

        assert "\x1b[" not in result.output, "ANSI escape codes found in JSON output"

    def test_json_output_no_embeddings(self, tmp_path):
        """JSON output must not contain embedding vectors or chunks."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "api-gateway", "--json"])

        data = json.loads(result.output)
        props = data.get("properties", {})
        assert "_embedding_cache" not in props
        assert "chunks" not in props
        assert "_chunks" not in props

    def test_json_output_includes_relationships(self, tmp_path):
        """JSON output includes relationship data."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "auth-service", "--json"])

        data = json.loads(result.output)
        rels = data.get("relationships", [])
        assert len(rels) > 0
        # Check relationship structure
        rel = rels[0]
        assert "target" in rel
        assert "relationship" in rel
        assert "target_type" in rel

    def test_json_overrides_format(self, tmp_path):
        """--json flag overrides --format text."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "auth-service", "--format", "text", "--json"])

        # Should still be valid JSON because --json overrides --format
        data = json.loads(result.output)
        assert "name" in data

    def test_json_not_found_error(self, tmp_path):
        """--json with unknown service returns JSON error."""
        from typer.testing import CliRunner

        from graqle.cli.main import app

        graph, graph_path = _make_test_graph(tmp_path)

        runner = CliRunner()
        with patch("graqle.cli.main._load_graph") as mock_load:
            mock_load.return_value = graph
            result = runner.invoke(app, ["context", "nonexistent-xyz", "--json"])

        data = json.loads(result.output)
        assert "error" in data


# ===========================================================================
# 2. Read-only MCP server
# ===========================================================================


class TestReadOnlyMcpServer:
    """Test that --read-only blocks write tools."""

    def test_read_only_blocks_learn(self):
        """graq_learn is blocked in read-only mode."""
        import asyncio

        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer(read_only=True)
        result = asyncio.run(server.handle_tool("graq_learn", {"mode": "outcome"}))
        data = json.loads(result)
        assert "error" in data
        assert "read-only" in data["error"].lower()

    def test_read_only_blocks_reload(self):
        """graq_reload is blocked in read-only mode."""
        import asyncio

        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer(read_only=True)
        result = asyncio.run(server.handle_tool("graq_reload", {}))
        data = json.loads(result)
        assert "error" in data
        assert "read-only" in data["error"].lower()

    def test_read_only_allows_read_tools(self):
        """Read tools are still allowed in read-only mode."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer(read_only=True)
        tools = server.list_tools()
        tool_names = {t["name"] for t in tools}

        # Read tools should be present
        assert "graq_context" in tool_names
        assert "graq_inspect" in tool_names
        assert "graq_reason" in tool_names
        assert "graq_preflight" in tool_names
        assert "graq_lessons" in tool_names
        assert "graq_impact" in tool_names

        # Write tools should NOT be present
        assert "graq_learn" not in tool_names
        assert "graq_reload" not in tool_names

    def test_non_read_only_includes_all_tools(self):
        """Non-read-only mode includes all tools."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer(read_only=False)
        tools = server.list_tools()
        tool_names = {t["name"] for t in tools}

        assert "graq_learn" in tool_names
        assert "graq_reload" in tool_names
        assert "graq_context" in tool_names


# ===========================================================================
# 3. File locking on concurrent writes
# ===========================================================================


class TestFileLocking:
    """Test that concurrent writes don't corrupt the graph file."""

    def test_write_with_lock_basic(self, tmp_path):
        """Basic file write with locking produces correct content."""
        from graqle.core.graph import _write_with_lock

        file_path = str(tmp_path / "test.json")
        content = json.dumps({"test": True, "value": 42}, indent=2)

        _write_with_lock(file_path, content)

        result = Path(file_path).read_text(encoding="utf-8")
        assert json.loads(result) == {"test": True, "value": 42}

    def test_concurrent_writes_no_corruption(self, tmp_path):
        """Multiple concurrent writes produce valid JSON (no corruption)."""
        from graqle.core.graph import _write_with_lock

        file_path = str(tmp_path / "concurrent.json")
        errors: list[str] = []

        def writer(writer_id: int, iterations: int = 20):
            for i in range(iterations):
                content = json.dumps({
                    "writer": writer_id,
                    "iteration": i,
                    "data": f"payload-{writer_id}-{i}",
                }, indent=2)
                try:
                    _write_with_lock(file_path, content)
                except Exception as e:
                    errors.append(f"Writer {writer_id}, iter {i}: {e}")

        # Run multiple writers concurrently
        threads = [
            threading.Thread(target=writer, args=(tid,))
            for tid in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # No errors should have occurred
        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"

        # Final file should be valid JSON
        final = Path(file_path).read_text(encoding="utf-8")
        data = json.loads(final)
        assert "writer" in data
        assert "iteration" in data

    def test_to_json_uses_locking(self, tmp_path):
        """Graqle.to_json() uses file locking internally."""
        graph, _ = _make_test_graph(tmp_path)
        output_path = str(tmp_path / "locked_output.json")

        with patch("graqle.core.graph._write_with_lock") as mock_lock:
            graph.to_json(output_path)
            mock_lock.assert_called_once()
            # Verify the file path argument
            assert mock_lock.call_args[0][0] == output_path

    def test_lock_file_cleanup(self, tmp_path):
        """Lock file is cleaned up after write."""
        from graqle.core.graph import _write_with_lock

        file_path = str(tmp_path / "cleanup_test.json")
        lock_path = file_path + ".lock"

        _write_with_lock(file_path, '{"clean": true}')

        # Lock file should be cleaned up
        assert not Path(lock_path).exists(), "Lock file was not cleaned up"


# ===========================================================================
# 4. Caller parameter in metrics
# ===========================================================================


class TestCallerMetrics:
    """Test that caller parameter is tracked in metrics."""

    def test_record_query_with_caller(self, tmp_path):
        """record_query tracks caller statistics."""
        from graqle.metrics.engine import MetricsEngine

        metrics = MetricsEngine(metrics_dir=tmp_path)
        metrics.record_query("test query", 100, caller="agent-1")
        metrics.record_query("test query 2", 200, caller="agent-1")
        metrics.record_query("test query 3", 150, caller="ci-pipeline")

        assert metrics.queries == 3
        assert "agent-1" in metrics.caller_stats
        assert metrics.caller_stats["agent-1"]["queries"] == 2
        assert "ci-pipeline" in metrics.caller_stats
        assert metrics.caller_stats["ci-pipeline"]["queries"] == 1

    def test_caller_in_summary(self, tmp_path):
        """caller_stats appears in get_summary()."""
        from graqle.metrics.engine import MetricsEngine

        metrics = MetricsEngine(metrics_dir=tmp_path)
        metrics.record_query("q1", 100, caller="agent-1")

        summary = metrics.get_summary()
        assert "caller_stats" in summary
        assert "agent-1" in summary["caller_stats"]

    def test_caller_persists_to_disk(self, tmp_path):
        """caller_stats is persisted and reloaded correctly."""
        from graqle.metrics.engine import MetricsEngine

        # Write
        metrics1 = MetricsEngine(metrics_dir=tmp_path)
        metrics1.record_query("q1", 100, caller="agent-1")
        metrics1.record_query("q2", 200, caller="agent-2")
        metrics1.save()

        # Reload
        metrics2 = MetricsEngine(metrics_dir=tmp_path)
        assert "agent-1" in metrics2.caller_stats
        assert "agent-2" in metrics2.caller_stats
        assert metrics2.caller_stats["agent-1"]["queries"] == 1

    def test_caller_empty_string_no_tracking(self, tmp_path):
        """Empty caller string does not create an entry."""
        from graqle.metrics.engine import MetricsEngine

        metrics = MetricsEngine(metrics_dir=tmp_path)
        metrics.record_query("q1", 100, caller="")

        assert metrics.queries == 1
        assert len(getattr(metrics, "caller_stats", {})) == 0

    def test_caller_reset(self, tmp_path):
        """reset() clears caller_stats."""
        from graqle.metrics.engine import MetricsEngine

        metrics = MetricsEngine(metrics_dir=tmp_path)
        metrics.record_query("q1", 100, caller="agent-1")
        assert len(metrics.caller_stats) == 1

        metrics.reset()
        assert len(metrics.caller_stats) == 0

    def test_mcp_tool_caller_schema(self):
        """MCP tool definitions include caller parameter."""
        from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS

        # Check graq_context has caller
        context_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_context")
        props = context_tool["inputSchema"]["properties"]
        assert "caller" in props
        assert props["caller"]["type"] == "string"

        # Check graq_reason has caller
        reason_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_reason")
        props = reason_tool["inputSchema"]["properties"]
        assert "caller" in props

        # Check graq_preflight has caller
        preflight_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "graq_preflight")
        props = preflight_tool["inputSchema"]["properties"]
        assert "caller" in props
