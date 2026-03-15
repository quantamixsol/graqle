"""Graqle MCP Server — governed context engineering for Claude Code.

Provides Model Context Protocol tools that Claude Code can call:
1. graq_context — Get focused 500-token context for a service/entity
2. graq_reason — Run governed reasoning query over KG
3. graq_inspect — Inspect graph structure (nodes, edges, stats)
4. graq_search — Semantic search over KG nodes

This replaces brute-force context loading (20-60K tokens) with
governed 500-token focused context per query.

Usage in CLAUDE.md:
    MCP server: graq
    Tools: graq_context, graq_reason, graq_inspect, graq_search

Setup:
    graq mcp serve --graph knowledge_graph.json --port 8765
"""

# ── graqle:intelligence ──
# module: graqle.plugins.mcp_server
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_mcp_server
# dependencies: __future__, json, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.plugins.mcp")


@dataclass
class MCPConfig:
    """Configuration for the MCP server."""
    graph_path: str = "knowledge_graph.json"
    max_context_tokens: int = 500
    max_search_results: int = 5
    host: str = "localhost"
    port: int = 8765
    # Governance
    allowed_entity_types: list[str] = field(default_factory=list)  # empty = all allowed
    redacted_properties: list[str] = field(default_factory=lambda: ["api_key", "secret", "password"])


class MCPToolResult:
    """Standard MCP tool result."""

    def __init__(self, content: str, is_error: bool = False) -> None:
        self.content = content
        self.is_error = is_error

    def to_dict(self) -> dict:
        return {
            "content": [{"type": "text", "text": self.content}],
            "isError": self.is_error,
        }


class MCPServer:
    """Graqle MCP Server for Claude Code integration.

    Exposes 4 tools via Model Context Protocol:
    - graq_context: Focused context for a service/entity
    - graq_reason: Run governed reasoning query
    - graq_inspect: Graph structure inspection
    - graq_search: Semantic node search
    """

    def __init__(self, config: MCPConfig | None = None) -> None:
        self._config = config or MCPConfig()
        self._graph: Any = None  # Graqle, loaded lazily
        self._embedder: Any = None  # EmbeddingEngine, loaded lazily

    @property
    def tools(self) -> list[dict]:
        """MCP tool definitions for Claude Code."""
        return [
            {
                "name": "graq_context",
                "description": (
                    "Get focused ~500-token context for a knowledge graph entity. "
                    "Returns entity description, neighbors, edge relationships, and properties. "
                    "Use instead of loading full KG context (saves 20-60K tokens)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": "Entity name or ID to get context for"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["text", "json", "yaml"],
                            "default": "text",
                            "description": "Output format"
                        }
                    },
                    "required": ["entity"]
                }
            },
            {
                "name": "graq_reason",
                "description": (
                    "Run a governed reasoning query over the knowledge graph. "
                    "Uses PCST activation, convergent message passing, and SemanticSHACL governance. "
                    "Returns answer with confidence, governance score, and provenance."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The reasoning query"
                        },
                        "max_rounds": {
                            "type": "integer",
                            "default": 3,
                            "description": "Maximum message-passing rounds"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "graq_inspect",
                "description": "Inspect knowledge graph structure: node count, edge count, entity types, hub nodes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "enum": ["summary", "nodes", "edges", "types"],
                            "default": "summary"
                        }
                    }
                }
            },
            {
                "name": "graq_search",
                "description": "Semantic search over knowledge graph nodes. Returns top matches by relevance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "limit": {
                            "type": "integer",
                            "default": 5,
                            "description": "Max results"
                        }
                    },
                    "required": ["query"]
                }
            },
        ]

    def _ensure_graph(self) -> None:
        """Lazily load the knowledge graph."""
        if self._graph is not None:
            return

        from graqle.connectors.json_graph import JSONGraphConnector

        connector = JSONGraphConnector()
        self._graph = connector.load(self._config.graph_path)
        logger.info(f"Loaded graph: {len(self._graph.nodes)} nodes, {len(self._graph.edges)} edges")

    def _ensure_embedder(self) -> None:
        """Lazily load the embedding engine."""
        if self._embedder is not None:
            return
        from graqle.activation.embeddings import EmbeddingEngine
        self._embedder = EmbeddingEngine()

    def _redact(self, props: dict) -> dict:
        """Remove sensitive properties."""
        return {
            k: v for k, v in props.items()
            if k not in self._config.redacted_properties
        }

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """Route MCP tool call to handler."""
        handlers = {
            "graq_context": self._handle_context,
            "graq_reason": self._handle_reason,
            "graq_inspect": self._handle_inspect,
            "graq_search": self._handle_search,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return MCPToolResult(f"Unknown tool: {tool_name}", is_error=True)

        try:
            return await handler(arguments)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return MCPToolResult(f"Error: {str(e)}", is_error=True)

    async def _handle_context(self, args: dict) -> MCPToolResult:
        """Get focused context for an entity."""
        self._ensure_graph()
        entity_name = args.get("entity", "")
        fmt = args.get("format", "text")

        # Find node (exact or fuzzy)
        node = self._find_node(entity_name)
        if not node:
            return MCPToolResult(f"Entity not found: '{entity_name}'. Use graq_search to find available entities.", is_error=True)

        # Build context
        neighbors = self._get_neighbors(node.id)
        props = self._redact(node.properties)

        if fmt == "json":
            ctx = {
                "entity": node.label,
                "type": node.entity_type,
                "description": node.description[:300],
                "properties": props,
                "neighbors": neighbors,
            }
            return MCPToolResult(json.dumps(ctx, indent=2))

        elif fmt == "yaml":
            lines = [
                f"entity: {node.label}",
                f"type: {node.entity_type}",
                f"description: {node.description[:300]}",
                "neighbors:",
            ]
            for n in neighbors:
                lines.append(f"  - {n['relationship']}: {n['label']} ({n['type']})")
            return MCPToolResult("\n".join(lines))

        else:  # text
            parts = [
                f"# {node.label} ({node.entity_type})",
                f"{node.description[:300]}",
                "",
                "## Connections",
            ]
            for n in neighbors:
                parts.append(f"- [{n['relationship']}] → {n['label']} ({n['type']})")
            if props:
                parts.append("")
                parts.append("## Properties")
                for k, v in list(props.items())[:10]:
                    parts.append(f"- {k}: {v}")
            return MCPToolResult("\n".join(parts))

    async def _handle_reason(self, args: dict) -> MCPToolResult:
        """Run governed reasoning query."""
        self._ensure_graph()
        query = args.get("query", "")
        max_rounds = args.get("max_rounds", 3)

        if not query:
            return MCPToolResult("Query is required", is_error=True)

        result = await self._graph.areason(
            query, max_rounds=max_rounds, task_type="reason",
        )

        output = {
            "answer": result.answer,
            "confidence": result.confidence,
            "rounds": result.rounds_completed,
            "nodes_used": result.node_count,
            "cost_usd": round(result.cost_usd, 4),
            "active_nodes": result.active_nodes[:10],
        }
        return MCPToolResult(json.dumps(output, indent=2))

    async def _handle_inspect(self, args: dict) -> MCPToolResult:
        """Inspect graph structure."""
        self._ensure_graph()
        detail = args.get("detail", "summary")
        graph = self._graph

        if detail == "summary":
            # Count entity types
            type_counts: dict[str, int] = {}
            for n in graph.nodes.values():
                t = n.entity_type
                type_counts[t] = type_counts.get(t, 0) + 1

            output = {
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "entity_types": type_counts,
            }
            return MCPToolResult(json.dumps(output, indent=2))

        elif detail == "nodes":
            nodes = [
                {"id": n.id, "label": n.label, "type": n.entity_type}
                for n in list(graph.nodes.values())[:50]
            ]
            return MCPToolResult(json.dumps(nodes, indent=2))

        elif detail == "edges":
            edges = [
                {"source": e.source_id, "target": e.target_id,
                 "relationship": e.relationship, "weight": e.weight}
                for e in list(graph.edges.values())[:50]
            ]
            return MCPToolResult(json.dumps(edges, indent=2))

        elif detail == "types":
            types: dict[str, list[str]] = {}
            for n in graph.nodes.values():
                t = n.entity_type
                if t not in types:
                    types[t] = []
                if len(types[t]) < 5:
                    types[t].append(n.label)
            return MCPToolResult(json.dumps(types, indent=2))

        return MCPToolResult(f"Unknown detail level: {detail}", is_error=True)

    async def _handle_search(self, args: dict) -> MCPToolResult:
        """Semantic search over nodes."""
        self._ensure_graph()
        self._ensure_embedder()
        query = args.get("query", "")
        limit = min(args.get("limit", 5), self._config.max_search_results)

        if not query:
            return MCPToolResult("Query is required", is_error=True)

        # Embed query
        q_vec = self._embedder.embed(query)

        # Score all nodes
        scores: list[tuple[str, float]] = []
        for node in self._graph.nodes.values():
            text = f"{node.label} {node.entity_type} {node.description[:200]}"
            n_vec = self._embedder.embed(text)
            # Cosine similarity
            sim = float(q_vec @ n_vec / (max(1e-8, float(
                (q_vec @ q_vec) ** 0.5 * (n_vec @ n_vec) ** 0.5
            ))))
            scores.append((node.id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for nid, sim in scores[:limit]:
            node = self._graph.nodes[nid]
            results.append({
                "id": nid,
                "label": node.label,
                "type": node.entity_type,
                "relevance": round(sim, 3),
                "description": node.description[:150],
            })

        return MCPToolResult(json.dumps(results, indent=2))

    def _find_node(self, name: str) -> Any | None:
        """Find node by exact ID, label, or fuzzy match."""
        graph = self._graph

        # Exact ID match
        if name in graph.nodes:
            return graph.nodes[name]

        # Exact label match (case-insensitive)
        name_lower = name.lower()
        for node in graph.nodes.values():
            if node.label.lower() == name_lower:
                return node

        # Fuzzy match (substring)
        for node in graph.nodes.values():
            if name_lower in node.label.lower() or name_lower in node.id.lower():
                return node

        return None

    def _get_neighbors(self, node_id: str) -> list[dict]:
        """Get neighbor info for a node."""
        neighbors = []
        graph = self._graph

        for edge in graph.edges.values():
            if edge.source_id == node_id:
                other = graph.nodes.get(edge.target_id)
                if other:
                    neighbors.append({
                        "id": other.id,
                        "label": other.label,
                        "type": other.entity_type,
                        "relationship": edge.relationship,
                        "weight": edge.weight,
                    })
            elif edge.target_id == node_id:
                other = graph.nodes.get(edge.source_id)
                if other:
                    neighbors.append({
                        "id": other.id,
                        "label": other.label,
                        "type": other.entity_type,
                        "relationship": edge.relationship,
                        "weight": edge.weight,
                    })

        return neighbors
