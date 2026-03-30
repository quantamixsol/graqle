"""
tests/test_analysis/test_mcp_impact.py
Phase 5 (ADR-128) — MCP-aware blast radius analysis tests.
Verifies cross-domain impact tracing for schema, server, and tool changes.
"""
from __future__ import annotations

import networkx as nx
import pytest

from graqle.analysis.mcp_impact import MCPImpactAnalyzer, MCPImpactReport


def _make_mcp_graph() -> nx.DiGraph:
    """Create a minimal MCP protocol graph for testing."""
    G = nx.DiGraph()

    # Nodes
    G.add_node("server1", entity_type="MCP_SERVER", label="graq_server")
    G.add_node("tool1", entity_type="MCP_TOOL", label="graq_reason")
    G.add_node("tool2", entity_type="MCP_TOOL", label="graq_inspect")
    G.add_node("alias1", entity_type="MCP_TOOL", label="kogni_reason")
    G.add_node("schema1", entity_type="MCP_SCHEMA", label="graq_reason.question")
    G.add_node("client1", entity_type="MCP_CLIENT", label="vscode_extension")
    G.add_node("client2", entity_type="MCP_CLIENT", label="claude_code")
    G.add_node("handler1", entity_type="Function", label="handle_reason")
    G.add_node("code1", entity_type="PythonModule", label="graqle/core/graph.py")

    # Edges
    G.add_edge("server1", "tool1", edge_type="EXPOSES_TOOL")
    G.add_edge("server1", "tool2", edge_type="EXPOSES_TOOL")
    G.add_edge("client1", "tool1", edge_type="CALLS_TOOL")
    G.add_edge("client2", "tool1", edge_type="CALLS_TOOL")
    G.add_edge("client1", "tool2", edge_type="CALLS_TOOL")
    G.add_edge("tool1", "schema1", edge_type="HAS_PARAM_SCHEMA")
    G.add_edge("tool1", "handler1", edge_type="HANDLES_REQUEST")
    G.add_edge("alias1", "tool1", edge_type="ALIASES")
    G.add_edge("server1", "code1", edge_type="IMPLEMENTS")

    return G


class TestToolSchemaChange:
    def test_traces_to_owning_tool(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_schema_change("schema1")
        tool_entries = [e for e in report.entries if e.severity == "DIRECT"]
        assert len(tool_entries) == 1
        assert tool_entries[0].node_id == "tool1"

    def test_traces_to_calling_clients(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_schema_change("schema1")
        client_entries = [e for e in report.entries if e.severity == "INDIRECT"]
        assert len(client_entries) == 2  # client1 + client2

    def test_breaking_change_severity(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_schema_change("schema1", change_type="breaking")
        breaking = [e for e in report.entries if e.severity == "BREAKING"]
        assert len(breaking) == 2
        assert report.breaking_count == 2


class TestServerChange:
    def test_traces_to_exposed_tools(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_server_change("server1")
        direct = [e for e in report.entries if e.severity == "DIRECT"]
        assert len(direct) == 2  # tool1 + tool2

    def test_traces_cross_domain(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_server_change("server1")
        cross = [e for e in report.entries if e.severity == "CROSS_DOMAIN"]
        assert len(cross) == 1
        assert cross[0].node_id == "code1"
        assert report.cross_domain_count == 1

    def test_traces_to_clients_via_tools(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_server_change("server1")
        indirect = [e for e in report.entries if e.severity == "INDIRECT"]
        # client1 calls tool1 + tool2 but is deduplicated, client2 calls tool1 = 2 unique clients
        assert len(indirect) == 2
        client_ids = {e.node_id for e in indirect}
        assert client_ids == {"client1", "client2"}


class TestToolChange:
    def test_traces_to_schema(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_change("tool1")
        schema_entries = [e for e in report.entries if e.node_type == "MCP_SCHEMA"]
        assert len(schema_entries) == 1

    def test_traces_to_handler(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_change("tool1")
        handler_entries = [e for e in report.entries if e.reason == "handler"]
        assert len(handler_entries) == 1

    def test_traces_to_aliases(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_change("tool1")
        alias_entries = [e for e in report.entries if e.reason == "alias_of_changed_tool"]
        assert len(alias_entries) == 1
        assert alias_entries[0].node_id == "alias1"


class TestEdgeCases:
    def test_no_impact_for_non_mcp_nodes(self) -> None:
        G = _make_mcp_graph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_tool_schema_change("nonexistent_node")
        assert report.affected_count == 0

    def test_empty_graph_returns_empty_report(self) -> None:
        G = nx.DiGraph()
        analyzer = MCPImpactAnalyzer(G)
        report = analyzer.analyze_server_change("anything")
        assert report.affected_count == 0
        assert report.cross_domain_count == 0
        assert report.breaking_count == 0

    def test_graqle_instance_accepted(self) -> None:
        """MCPImpactAnalyzer accepts Graqle instance (not just raw DiGraph)."""
        G = _make_mcp_graph()

        class FakeGraqle:
            _graph = G

        analyzer = MCPImpactAnalyzer(FakeGraqle())
        report = analyzer.analyze_tool_change("tool1")
        assert report.affected_count > 0
