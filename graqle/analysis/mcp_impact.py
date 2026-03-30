"""MCP-aware blast radius analysis — traces cross-domain impact for MCP protocol changes.

ADR-128 Phase 5: Composable enrichment for graq_impact. Does NOT replace _bfs_impact,
enriches its results with protocol-boundary awareness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.analysis.mcp_impact")


@dataclass
class ImpactEntry:
    """A single entry in the impact report."""

    node_id: str
    node_type: str
    severity: str  # DIRECT, INDIRECT, BREAKING, CROSS_DOMAIN
    reason: str
    depth: int = 0


@dataclass
class MCPImpactReport:
    """Result of MCP-aware impact analysis."""

    trigger_node_id: str
    change_type: str  # "schema_change", "server_change", "tool_change"
    entries: list[ImpactEntry] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set, repr=False)

    def add_impact(
        self,
        node_id: str,
        node_type: str,
        severity: str,
        reason: str,
        depth: int = 0,
    ) -> None:
        """Add an impact entry. Deduplicates by node_id."""
        if node_id in self._seen:
            return
        self._seen.add(node_id)
        self.entries.append(
            ImpactEntry(
                node_id=node_id,
                node_type=node_type,
                severity=severity,
                reason=reason,
                depth=depth,
            )
        )

    @property
    def cross_domain_count(self) -> int:
        return sum(1 for e in self.entries if e.severity == "CROSS_DOMAIN")

    @property
    def breaking_count(self) -> int:
        return sum(1 for e in self.entries if e.severity == "BREAKING")

    @property
    def affected_count(self) -> int:
        return len(self.entries)


class MCPImpactAnalyzer:
    """Analyzes blast radius for MCP protocol changes.

    Traces: schema changes -> owning tools -> calling clients (reverse traversal).
    Traces: server changes -> exposed tools -> calling clients + code domain (cross-domain).
    """

    def __init__(self, graph: Any) -> None:
        """graph: a NetworkX DiGraph or Graqle instance with a ._graph attribute."""
        self._graph = graph._graph if hasattr(graph, "_graph") else graph

    def _get_neighbors(
        self, node_id: str, edge_type: str, direction: str = "outbound",
    ) -> list[str]:
        """Get neighbors filtered by edge type. Returns empty list for missing nodes."""
        if node_id not in self._graph.nodes:
            return []
        result: list[str] = []
        if direction == "outbound":
            for _, target, data in self._graph.out_edges(node_id, data=True):
                if data.get("edge_type") == edge_type or data.get("relationship") == edge_type:
                    result.append(target)
        else:  # inbound
            for source, _, data in self._graph.in_edges(node_id, data=True):
                if data.get("edge_type") == edge_type or data.get("relationship") == edge_type:
                    result.append(source)
        return result

    def _get_node_type(self, node_id: str) -> str:
        if node_id in self._graph.nodes:
            return self._graph.nodes[node_id].get("entity_type", "unknown")
        return "unknown"

    def analyze_tool_schema_change(
        self, schema_node_id: str, change_type: str = "modify",
    ) -> MCPImpactReport:
        """When a tool's parameter schema changes, trace to all calling clients."""
        report = MCPImpactReport(trigger_node_id=schema_node_id, change_type="schema_change")

        owning_tools = self._get_neighbors(schema_node_id, "HAS_PARAM_SCHEMA", "inbound")
        for tool_id in owning_tools:
            report.add_impact(tool_id, self._get_node_type(tool_id), "DIRECT", "owns_schema", depth=1)

            clients = self._get_neighbors(tool_id, "CALLS_TOOL", "inbound")
            severity = "BREAKING" if change_type == "breaking" else "INDIRECT"
            for client_id in clients:
                report.add_impact(
                    client_id, self._get_node_type(client_id), severity,
                    f"calls_tool:{tool_id}", depth=2,
                )

        return report

    def analyze_server_change(
        self, server_node_id: str, change_type: str = "modify",
    ) -> MCPImpactReport:
        """When a server changes, trace to all exposed tools and their clients."""
        report = MCPImpactReport(trigger_node_id=server_node_id, change_type="server_change")

        exposed_tools = self._get_neighbors(server_node_id, "EXPOSES_TOOL", "outbound")
        for tool_id in exposed_tools:
            report.add_impact(tool_id, self._get_node_type(tool_id), "DIRECT", "exposed_by_server", depth=1)

            clients = self._get_neighbors(tool_id, "CALLS_TOOL", "inbound")
            client_severity = "BREAKING" if change_type == "breaking" else "INDIRECT"
            for client_id in clients:
                report.add_impact(
                    client_id, self._get_node_type(client_id), client_severity,
                    f"calls_tool:{tool_id}", depth=2,
                )

        code_nodes = self._get_neighbors(server_node_id, "IMPLEMENTS", "outbound")
        for code_id in code_nodes:
            report.add_impact(
                code_id, self._get_node_type(code_id), "CROSS_DOMAIN",
                "mcp_to_code_boundary", depth=1,
            )

        return report

    def analyze_tool_change(
        self, tool_node_id: str, change_type: str = "modify",
    ) -> MCPImpactReport:
        """When a tool changes, trace to schema, handler, and clients."""
        report = MCPImpactReport(trigger_node_id=tool_node_id, change_type="tool_change")

        for schema_id in self._get_neighbors(tool_node_id, "HAS_PARAM_SCHEMA", "outbound"):
            report.add_impact(schema_id, "MCP_SCHEMA", "DIRECT", "param_schema", depth=1)

        for handler_id in self._get_neighbors(tool_node_id, "HANDLES_REQUEST", "outbound"):
            report.add_impact(handler_id, self._get_node_type(handler_id), "DIRECT", "handler", depth=1)

        severity = "BREAKING" if change_type == "breaking" else "INDIRECT"
        for client_id in self._get_neighbors(tool_node_id, "CALLS_TOOL", "inbound"):
            report.add_impact(client_id, self._get_node_type(client_id), severity, "calls_tool", depth=1)

        for alias_id in self._get_neighbors(tool_node_id, "ALIASES", "inbound"):
            report.add_impact(alias_id, "MCP_TOOL", "INDIRECT", "alias_of_changed_tool", depth=1)

        return report
