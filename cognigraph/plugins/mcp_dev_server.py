"""CogniGraph MCP Development Server — governed development for Claude Code.

Production MCP server exposing 7 tools over JSON-RPC stdio transport.
Replaces flat-file CLAUDE.md reading with graph-powered context engineering.

FREE tier (3 tools):
    1. kogni_context  — Smart context loading for session start
    2. kogni_inspect   — Graph structure inspection
    3. kogni_reason    — Graph-of-agents reasoning

PRO tier (4 tools, license-gated):
    4. kogni_preflight — Governance check before code changes
    5. kogni_lessons   — Query lessons relevant to current work
    6. kogni_impact    — Trace downstream impacts of a change
    7. kogni_learn     — Feed outcomes back for Bayesian graph learning

Usage:
    kogni mcp serve                     # stdio transport (Claude Code)
    kogni mcp serve --config my.yaml    # custom config

Claude Code .mcp.json:
    {
      "mcpServers": {
        "kogni": {
          "command": "kogni",
          "args": ["mcp", "serve"]
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
import sys
import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("cognigraph.mcp")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRO_TOOLS = frozenset({
    "kogni_preflight",
    "kogni_lessons",
    "kogni_impact",
    "kogni_learn",
})

_PRO_FEATURE_MAP = {
    "kogni_preflight": "mcp_preflight",
    "kogni_lessons": "mcp_lessons",
    "kogni_impact": "mcp_impact",
    "kogni_learn": "mcp_learn",
}

_SENSITIVE_KEYS = frozenset({"api_key", "secret", "password", "token", "credential"})

_LESSON_ENTITY_TYPES = frozenset({"LESSON", "MISTAKE", "SAFETY", "ADR", "DECISION"})

_MAX_BFS_DEPTH = 3
_MAX_RESULTS = 50

# ---------------------------------------------------------------------------
# Tool Definitions (MCP protocol)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # ── FREE tier ──────────────────────────────────────────────────────────
    {
        "name": "kogni_context",
        "description": (
            "Get smart, focused context for your current task. "
            "Returns relevant knowledge graph nodes, active branch info, "
            "and applicable lessons in ~300-500 tokens. "
            "Use at session start instead of reading large files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What you're working on",
                },
                "level": {
                    "type": "string",
                    "enum": ["minimal", "standard", "deep"],
                    "default": "standard",
                    "description": (
                        "Context depth: minimal (~200 tokens), "
                        "standard (~400 tokens), deep (~800 tokens)"
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "kogni_inspect",
        "description": (
            "Inspect the project knowledge graph structure. "
            "Show nodes, edges, stats, or details for a specific node."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Specific node to inspect (optional)",
                },
                "stats": {
                    "type": "boolean",
                    "default": False,
                    "description": "Show full graph statistics",
                },
            },
        },
    },
    {
        "name": "kogni_reason",
        "description": (
            "Run graph-of-agents reasoning over the project knowledge graph. "
            "Each relevant node becomes an agent that reasons about your question, "
            "exchanges messages with neighbors, and collectively produces "
            "a synthesized answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Your question about the project",
                },
                "max_rounds": {
                    "type": "integer",
                    "default": 2,
                    "description": "Maximum message-passing rounds (1-5)",
                },
            },
            "required": ["question"],
        },
    },
    # ── PRO tier ───────────────────────────────────────────────────────────
    {
        "name": "kogni_preflight",
        "description": (
            "Run a governance preflight check before making code changes. "
            "Returns relevant lessons, past mistakes, applicable architectural "
            "decisions, and safety boundary warnings. "
            "Call this BEFORE modifying any file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "What you're about to do",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files being changed (optional)",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "kogni_lessons",
        "description": (
            "Find lessons and past mistakes relevant to a specific operation. "
            "Returns matching lessons with severity levels and hit counts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": (
                        "The operation (e.g., 'deployment', "
                        "'database migration', 'auth changes')"
                    ),
                },
                "severity_filter": {
                    "type": "string",
                    "enum": ["all", "critical", "high"],
                    "default": "high",
                    "description": "Minimum severity to return",
                },
            },
            "required": ["operation"],
        },
    },
    {
        "name": "kogni_impact",
        "description": (
            "Trace the downstream impact of a proposed change through "
            "the dependency graph. Shows which components are affected "
            "and their risk level."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "description": "Component being changed",
                },
                "change_type": {
                    "type": "string",
                    "enum": ["modify", "add", "remove", "deploy"],
                    "default": "modify",
                    "description": "Type of change being made",
                },
            },
            "required": ["component"],
        },
    },
    {
        "name": "kogni_learn",
        "description": (
            "Record a development outcome for graph learning. "
            "Strengthens edges between components that worked well together, "
            "weakens edges to components that caused issues. "
            "Call this after completing a task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "What was done",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "partial"],
                    "description": "Task outcome",
                },
                "components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Components involved",
                },
                "lesson": {
                    "type": "string",
                    "description": "Optional new lesson learned",
                },
            },
            "required": ["action", "outcome", "components"],
        },
    },
]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class KogniDevServer:
    """MCP server exposing 7 governed development tools over stdio.

    Implements the Model Context Protocol JSON-RPC transport.
    Graph is lazily loaded on first tool call.
    """

    def __init__(self, config_path: str = "cognigraph.yaml") -> None:
        self.config_path = config_path
        self._graph: Any = None  # CogniGraph, loaded lazily
        self._config: Any = None  # CogniGraphConfig
        self._graph_file: str | None = None  # path to the loaded graph JSON

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def _load_graph(self) -> Any | None:
        """Lazy-load the knowledge graph. Returns CogniGraph or None."""
        if self._graph is not None:
            return self._graph

        try:
            from cognigraph.config.settings import CogniGraphConfig
            from cognigraph.core.graph import CogniGraph

            cfg_path = Path(self.config_path)
            if cfg_path.exists():
                self._config = CogniGraphConfig.from_yaml(str(cfg_path))
            else:
                self._config = CogniGraphConfig.default()

            # Auto-discover graph file
            for candidate in [
                "cognigraph.json",
                "knowledge_graph.json",
                "graph.json",
            ]:
                p = Path(candidate)
                if p.exists():
                    self._graph = CogniGraph.from_json(str(p), config=self._config)
                    self._graph_file = str(p.resolve())
                    logger.info(
                        "Loaded graph: %d nodes, %d edges from %s",
                        len(self._graph.nodes),
                        len(self._graph.edges),
                        candidate,
                    )
                    return self._graph

            logger.warning("No graph file found in current directory")
            return None

        except Exception as exc:
            logger.error("Failed to load graph: %s", exc)
            return None

    def _require_graph(self) -> Any:
        """Load graph or raise with a helpful message."""
        graph = self._load_graph()
        if graph is None:
            raise RuntimeError(
                "No knowledge graph loaded. "
                "Place a cognigraph.json, knowledge_graph.json, or graph.json "
                "in the working directory, or run 'kogni scan --repo .' first."
            )
        return graph

    # ------------------------------------------------------------------
    # Node search helpers
    # ------------------------------------------------------------------

    def _find_node(self, name: str) -> Any | None:
        """Find node by exact ID, label, or fuzzy substring match."""
        graph = self._require_graph()
        if not name:
            return None

        # Exact ID
        if name in graph.nodes:
            return graph.nodes[name]

        # Case-insensitive label match
        name_lower = name.lower()
        for node in graph.nodes.values():
            if node.label.lower() == name_lower:
                return node

        # Substring match on id or label
        for node in graph.nodes.values():
            if name_lower in node.label.lower() or name_lower in node.id.lower():
                return node

        return None

    def _find_nodes_matching(self, text: str, *, limit: int = 20) -> list[Any]:
        """Find all nodes whose label/id/description fuzzy-match *text*."""
        graph = self._require_graph()
        text_lower = text.lower()
        tokens = text_lower.split()

        scored: list[tuple[float, Any]] = []
        for node in graph.nodes.values():
            haystack = f"{node.id} {node.label} {node.entity_type} {node.description[:200]}".lower()
            score = sum(1.0 for tok in tokens if tok in haystack)
            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in scored[:limit]]

    def _get_neighbor_summaries(self, node_id: str) -> list[dict[str, str]]:
        """Return compact neighbor info for a node."""
        graph = self._require_graph()
        neighbors: list[dict[str, str]] = []
        seen: set[str] = set()

        for edge in graph.edges.values():
            other_id: str | None = None
            if edge.source_id == node_id:
                other_id = edge.target_id
            elif edge.target_id == node_id:
                other_id = edge.source_id

            if other_id and other_id not in seen:
                seen.add(other_id)
                other = graph.nodes.get(other_id)
                if other:
                    neighbors.append({
                        "id": other.id,
                        "label": other.label,
                        "type": other.entity_type,
                        "relationship": edge.relationship,
                    })
        return neighbors

    def _redact(self, props: dict[str, Any]) -> dict[str, Any]:
        """Remove sensitive properties."""
        return {
            k: v for k, v in props.items()
            if k.lower() not in _SENSITIVE_KEYS and k != "chunks"
        }

    # ------------------------------------------------------------------
    # MCP protocol: tool listing
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions."""
        return TOOL_DEFINITIONS

    # ------------------------------------------------------------------
    # MCP protocol: tool dispatch
    # ------------------------------------------------------------------

    async def handle_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Route a tool call to the correct handler. Returns JSON string."""
        handlers: dict[str, Any] = {
            "kogni_context": self._handle_context,
            "kogni_inspect": self._handle_inspect,
            "kogni_reason": self._handle_reason,
            "kogni_preflight": self._handle_preflight,
            "kogni_lessons": self._handle_lessons,
            "kogni_impact": self._handle_impact,
            "kogni_learn": self._handle_learn,
        }

        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # PRO tier gate
        if name in _PRO_TOOLS:
            gate_msg = self._check_pro_license(name)
            if gate_msg is not None:
                return gate_msg

        try:
            return await handler(arguments)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)})

    def _check_pro_license(self, tool_name: str) -> str | None:
        """Return JSON error string if PRO license is missing, else None."""
        try:
            from cognigraph.licensing import has_feature

            feature = _PRO_FEATURE_MAP.get(tool_name, tool_name)
            if not has_feature(feature):
                return json.dumps({
                    "error": (
                        f"'{tool_name}' requires CogniGraph Pro. "
                        "Current tier: Free."
                    ),
                    "upgrade": "https://cognigraph.dev/pricing",
                    "tip": (
                        "Set COGNIGRAPH_LICENSE_KEY env var or place key "
                        "in ~/.cognigraph/license.key"
                    ),
                })
        except ImportError:
            # Licensing module not present — development mode, allow through
            pass
        return None

    # ==================================================================
    # Tool handlers
    # ==================================================================

    # ── 1. kogni_context (FREE) ───────────────────────────────────────

    async def _handle_context(self, args: dict[str, Any]) -> str:
        task = args.get("task", "")
        level = args.get("level", "standard")

        if not task:
            return json.dumps({"error": "Parameter 'task' is required."})

        graph = self._load_graph()

        parts: list[str] = []

        # ---- Active branch (from .gcc/registry.md) --------------------
        branch_info = self._read_active_branch()
        if branch_info:
            parts.append(f"## Active Branch\n{branch_info}")

        # ---- Relevant graph nodes -------------------------------------
        if graph is not None:
            matches = self._find_nodes_matching(task, limit=_context_limit(level))
            if matches:
                parts.append("## Relevant Nodes")
                for node in matches:
                    desc_limit = 80 if level == "minimal" else 200 if level == "standard" else 400
                    desc = node.description[:desc_limit]
                    line = f"- **{node.label}** ({node.entity_type}): {desc}"
                    parts.append(line)

                    if level == "deep":
                        neighbors = self._get_neighbor_summaries(node.id)
                        for nb in neighbors[:3]:
                            parts.append(
                                f"  - [{nb['relationship']}] {nb['label']} ({nb['type']})"
                            )

            # ---- Lessons / safety nodes -------------------------------
            lessons = self._find_lesson_nodes(task, severity_filter="critical")
            if lessons:
                parts.append("## Applicable Lessons")
                for lesson in lessons[:5]:
                    parts.append(f"- [{lesson['severity']}] {lesson['label']}: {lesson['description']}")
        else:
            parts.append(
                "_No knowledge graph loaded. "
                "Run `kogni scan --repo .` to build one._"
            )

        if not parts:
            parts.append(f"No specific context found for task: '{task}'")

        return json.dumps({
            "context": "\n\n".join(parts),
            "level": level,
            "nodes_matched": len(matches) if graph and matches else 0,
            "graph_loaded": graph is not None,
        })

    # ── 2. kogni_inspect (FREE) ───────────────────────────────────────

    async def _handle_inspect(self, args: dict[str, Any]) -> str:
        node_id = args.get("node_id")
        show_stats = args.get("stats", False)

        graph = self._require_graph()

        # Single node inspection
        if node_id:
            node = self._find_node(node_id)
            if node is None:
                return json.dumps({
                    "error": f"Node '{node_id}' not found.",
                    "hint": "Use kogni_inspect with stats=true to see available nodes.",
                })
            neighbors = self._get_neighbor_summaries(node.id)
            props = self._redact(node.properties)
            return json.dumps({
                "id": node.id,
                "label": node.label,
                "type": node.entity_type,
                "description": node.description[:500],
                "degree": node.degree,
                "properties": props,
                "neighbors": neighbors,
                "status": node.status.value if hasattr(node.status, "value") else str(node.status),
            })

        # Full graph stats
        if show_stats:
            stats = graph.stats
            type_counts: dict[str, int] = {}
            for n in graph.nodes.values():
                t = n.entity_type
                type_counts[t] = type_counts.get(t, 0) + 1

            return json.dumps({
                "total_nodes": stats.total_nodes,
                "total_edges": stats.total_edges,
                "avg_degree": round(stats.avg_degree, 2),
                "density": round(stats.density, 4),
                "connected_components": stats.connected_components,
                "hub_nodes": stats.hub_nodes[:10],
                "entity_types": type_counts,
                "graph_file": self._graph_file,
            })

        # Default: compact node listing
        nodes_list = []
        for nid, node in list(graph.nodes.items())[:_MAX_RESULTS]:
            nodes_list.append({
                "id": nid,
                "label": node.label,
                "type": node.entity_type,
                "degree": node.degree,
            })

        return json.dumps({
            "nodes": nodes_list,
            "total": len(graph.nodes),
            "shown": len(nodes_list),
        })

    # ── 3. kogni_reason (FREE) ────────────────────────────────────────

    async def _handle_reason(self, args: dict[str, Any]) -> str:
        question = args.get("question", "")
        max_rounds = min(max(args.get("max_rounds", 2), 1), 5)

        if not question:
            return json.dumps({"error": "Parameter 'question' is required."})

        graph = self._require_graph()

        # Try full areason if a backend is configured
        try:
            result = await graph.areason(question, max_rounds=max_rounds)
            return json.dumps({
                "answer": result.answer,
                "confidence": round(result.confidence, 3),
                "rounds": result.rounds_completed,
                "nodes_used": result.node_count,
                "active_nodes": result.active_nodes[:10],
                "cost_usd": round(result.cost_usd, 6),
                "latency_ms": round(result.latency_ms, 1),
            })
        except RuntimeError:
            # No backend configured — fall back to graph-traversal synthesis
            pass

        # Fallback: keyword-based graph traversal
        matches = self._find_nodes_matching(question, limit=8)
        if not matches:
            return json.dumps({
                "answer": "No relevant nodes found for this question.",
                "confidence": 0.0,
                "rounds": 0,
                "nodes_used": 0,
                "active_nodes": [],
                "mode": "fallback",
            })

        # Synthesize from node knowledge
        synthesis_parts: list[str] = []
        node_ids: list[str] = []
        for node in matches:
            desc = node.description[:300] if node.description else node.label
            synthesis_parts.append(
                f"[{node.label} ({node.entity_type})]: {desc}"
            )
            node_ids.append(node.id)

        answer = (
            f"Based on {len(matches)} relevant graph nodes:\n\n"
            + "\n\n".join(synthesis_parts)
        )

        return json.dumps({
            "answer": answer,
            "confidence": 0.5,
            "rounds": 0,
            "nodes_used": len(matches),
            "active_nodes": node_ids,
            "mode": "fallback_traversal",
            "hint": (
                "For full reasoning, configure a model backend "
                "(e.g., kogni reason --model qwen2.5:3b)."
            ),
        })

    # ── 4. kogni_preflight (PRO) ──────────────────────────────────────

    async def _handle_preflight(self, args: dict[str, Any]) -> str:
        action = args.get("action", "")
        files = args.get("files", [])

        if not action:
            return json.dumps({"error": "Parameter 'action' is required."})

        graph = self._load_graph()
        report: dict[str, Any] = {
            "action": action,
            "files": files,
            "warnings": [],
            "lessons": [],
            "safety_boundaries": [],
            "adrs": [],
            "risk_level": "low",
        }

        if graph is None:
            report["warnings"].append(
                "No knowledge graph loaded — preflight is limited to file-based checks."
            )
            return json.dumps(report)

        # Search for related lessons, mistakes, safety nodes
        search_text = action + " " + " ".join(files)
        lessons = self._find_lesson_nodes(search_text, severity_filter="all")

        for lesson in lessons:
            entry = {
                "label": lesson["label"],
                "severity": lesson["severity"],
                "description": lesson["description"],
                "type": lesson["entity_type"],
            }
            if lesson["entity_type"] in ("SAFETY", "SAFETY_BOUNDARY"):
                report["safety_boundaries"].append(entry)
            elif lesson["entity_type"] in ("ADR", "DECISION"):
                report["adrs"].append(entry)
            else:
                report["lessons"].append(entry)

        # Check if changed files match any known component nodes
        for fpath in files:
            fname = Path(fpath).name.lower()
            stem = Path(fpath).stem.lower()
            for node in graph.nodes.values():
                node_text = f"{node.id} {node.label}".lower()
                if stem in node_text or fname in node_text:
                    neighbors = self._get_neighbor_summaries(node.id)
                    if neighbors:
                        report["warnings"].append(
                            f"File '{fpath}' relates to node '{node.label}' "
                            f"which connects to {len(neighbors)} other components."
                        )

        # Compute risk level
        n_critical = sum(
            1 for l in report["lessons"]
            if l.get("severity") in ("CRITICAL", "critical")
        )
        n_safety = len(report["safety_boundaries"])
        if n_critical > 0 or n_safety > 0:
            report["risk_level"] = "high"
        elif len(report["lessons"]) > 2 or len(report["warnings"]) > 2:
            report["risk_level"] = "medium"

        return json.dumps(report)

    # ── 5. kogni_lessons (PRO) ────────────────────────────────────────

    async def _handle_lessons(self, args: dict[str, Any]) -> str:
        operation = args.get("operation", "")
        severity_filter = args.get("severity_filter", "high")

        if not operation:
            return json.dumps({"error": "Parameter 'operation' is required."})

        lessons = self._find_lesson_nodes(operation, severity_filter=severity_filter)

        return json.dumps({
            "operation": operation,
            "filter": severity_filter,
            "count": len(lessons),
            "lessons": lessons,
        })

    # ── 6. kogni_impact (PRO) ─────────────────────────────────────────

    async def _handle_impact(self, args: dict[str, Any]) -> str:
        component = args.get("component", "")
        change_type = args.get("change_type", "modify")

        if not component:
            return json.dumps({"error": "Parameter 'component' is required."})

        graph = self._require_graph()
        start_node = self._find_node(component)

        if start_node is None:
            # Try fuzzy match
            matches = self._find_nodes_matching(component, limit=3)
            if matches:
                return json.dumps({
                    "error": f"Component '{component}' not found exactly.",
                    "suggestions": [
                        {"id": m.id, "label": m.label, "type": m.entity_type}
                        for m in matches
                    ],
                })
            return json.dumps({"error": f"Component '{component}' not found in graph."})

        # BFS traversal for impact
        impact_tree = self._bfs_impact(
            start_node.id, change_type=change_type, max_depth=_MAX_BFS_DEPTH
        )

        # Risk summary
        risk_scores = {"remove": 3, "deploy": 2, "modify": 1, "add": 0.5}
        base_risk = risk_scores.get(change_type, 1)
        total_affected = len(impact_tree)
        overall_risk = "low"
        if total_affected > 5 or base_risk >= 3:
            overall_risk = "high"
        elif total_affected > 2 or base_risk >= 2:
            overall_risk = "medium"

        return json.dumps({
            "component": start_node.label,
            "change_type": change_type,
            "overall_risk": overall_risk,
            "affected_count": total_affected,
            "impact_tree": impact_tree,
        })

    def _bfs_impact(
        self,
        start_id: str,
        *,
        change_type: str = "modify",
        max_depth: int = _MAX_BFS_DEPTH,
    ) -> list[dict[str, Any]]:
        """BFS from start_id, returning downstream impact tree."""
        graph = self._require_graph()
        visited: set[str] = {start_id}
        queue: deque[tuple[str, int, str]] = deque()  # (node_id, depth, relationship)

        # Seed with direct neighbors
        for edge in graph.edges.values():
            if edge.source_id == start_id and edge.target_id not in visited:
                queue.append((edge.target_id, 1, edge.relationship))
            elif edge.target_id == start_id and edge.source_id not in visited:
                queue.append((edge.source_id, 1, edge.relationship))

        results: list[dict[str, Any]] = []

        while queue:
            nid, depth, rel = queue.popleft()
            if nid in visited or depth > max_depth:
                continue
            visited.add(nid)

            node = graph.nodes.get(nid)
            if node is None:
                continue

            # Risk assessment per node
            risk = "low"
            if change_type == "remove":
                risk = "high" if depth <= 1 else "medium"
            elif change_type == "deploy":
                risk = "medium" if depth <= 1 else "low"
            elif change_type == "modify":
                risk = "medium" if depth == 1 else "low"

            results.append({
                "id": nid,
                "label": node.label,
                "type": node.entity_type,
                "depth": depth,
                "relationship": rel,
                "risk": risk,
            })

            # Continue BFS
            if depth < max_depth:
                for edge in graph.edges.values():
                    next_id: str | None = None
                    if edge.source_id == nid and edge.target_id not in visited:
                        next_id = edge.target_id
                    elif edge.target_id == nid and edge.source_id not in visited:
                        next_id = edge.source_id
                    if next_id:
                        queue.append((next_id, depth + 1, edge.relationship))

        return results

    # ── 7. kogni_learn (PRO) ──────────────────────────────────────────

    async def _handle_learn(self, args: dict[str, Any]) -> str:
        action = args.get("action", "")
        outcome = args.get("outcome", "")
        components = args.get("components", [])
        lesson_text = args.get("lesson")

        if not action or not outcome or not components:
            return json.dumps({
                "error": "Parameters 'action', 'outcome', and 'components' are all required."
            })

        graph = self._load_graph()
        updates: list[dict[str, Any]] = []
        lesson_node_id: str | None = None

        if graph is not None:
            # Update edge weights between involved components
            weight_delta = {
                "success": 0.05,
                "failure": -0.1,
                "partial": -0.02,
            }.get(outcome, 0.0)

            component_ids: list[str] = []
            for comp in components:
                node = self._find_node(comp)
                if node:
                    component_ids.append(node.id)

            # Adjust edge weights between all pairs of involved nodes
            for i, nid_a in enumerate(component_ids):
                for nid_b in component_ids[i + 1:]:
                    edges = graph.get_edges_between(nid_a, nid_b)
                    for edge in edges:
                        old_weight = edge.weight
                        edge.weight = max(0.01, min(2.0, edge.weight + weight_delta))
                        updates.append({
                            "edge": edge.id,
                            "from": nid_a,
                            "to": nid_b,
                            "old_weight": round(old_weight, 4),
                            "new_weight": round(edge.weight, 4),
                            "delta": round(weight_delta, 4),
                        })

            # Add lesson node if provided
            if lesson_text:
                from cognigraph.core.node import CogniNode
                from cognigraph.core.edge import CogniEdge

                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                lesson_node_id = f"lesson_{ts}"
                severity = "HIGH" if outcome == "failure" else "MEDIUM"

                lesson_node = CogniNode(
                    id=lesson_node_id,
                    label=lesson_text[:80],
                    entity_type="LESSON",
                    description=lesson_text,
                    properties={
                        "severity": severity,
                        "outcome": outcome,
                        "action": action,
                        "hit_count": 0,
                        "created": ts,
                    },
                )
                graph.add_node(lesson_node)

                # Connect lesson to involved components
                for idx, nid in enumerate(component_ids):
                    edge = CogniEdge(
                        id=f"e_{lesson_node_id}_{nid}_{idx}",
                        source_id=lesson_node_id,
                        target_id=nid,
                        relationship="LEARNED_FROM",
                        weight=1.0,
                    )
                    graph.add_edge(edge)

            # Persist updated graph back to JSON
            self._save_graph(graph)

        return json.dumps({
            "recorded": True,
            "action": action,
            "outcome": outcome,
            "components": components,
            "edge_updates": updates,
            "lesson_node_id": lesson_node_id,
        })

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _find_lesson_nodes(
        self,
        text: str,
        *,
        severity_filter: str = "high",
    ) -> list[dict[str, Any]]:
        """Find LESSON / MISTAKE / SAFETY / ADR nodes matching text."""
        graph = self._load_graph()
        if graph is None:
            return []

        text_lower = text.lower()
        tokens = text_lower.split()

        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        filter_threshold = {
            "critical": 0,
            "high": 1,
            "all": 99,
        }.get(severity_filter, 1)

        results: list[dict[str, Any]] = []
        for node in graph.nodes.values():
            if node.entity_type.upper() not in _LESSON_ENTITY_TYPES:
                continue

            severity = node.properties.get("severity", "MEDIUM").upper()
            sev_rank = severity_order.get(severity, 2)
            if sev_rank > filter_threshold:
                continue

            haystack = f"{node.id} {node.label} {node.description[:300]}".lower()
            score = sum(1.0 for tok in tokens if tok in haystack)
            if score > 0 or severity_filter == "all":
                results.append({
                    "id": node.id,
                    "label": node.label,
                    "entity_type": node.entity_type,
                    "severity": severity,
                    "description": node.description[:200],
                    "hit_count": node.properties.get("hit_count", 0),
                    "score": score,
                })

        # Sort: highest severity first, then by relevance score
        results.sort(key=lambda x: (severity_order.get(x["severity"], 2), -x["score"]))
        return results[:_MAX_RESULTS]

    def _read_active_branch(self) -> str | None:
        """Read .gcc/registry.md to find the active branch, if present."""
        registry = Path(".gcc/registry.md")
        if not registry.exists():
            return None

        try:
            content = registry.read_text(encoding="utf-8")
            # Extract active branch from table rows
            lines = content.strip().split("\n")
            active_branches: list[str] = []
            for line in lines:
                lower = line.lower()
                if "working" in lower or "active" in lower:
                    active_branches.append(line.strip())
            if active_branches:
                return "\n".join(active_branches)
        except Exception:
            pass
        return None

    def _save_graph(self, graph: Any) -> None:
        """Persist graph back to its source JSON file."""
        if self._graph_file is None:
            return

        try:
            import networkx as nx

            G = graph.to_networkx()
            data = nx.node_link_data(G)
            Path(self._graph_file).write_text(
                json.dumps(data, indent=2, default=str)
            )
            logger.info("Graph saved to %s", self._graph_file)
        except Exception as exc:
            logger.error("Failed to save graph: %s", exc)

    # ==================================================================
    # MCP JSON-RPC stdio transport
    # ==================================================================

    async def _handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a single JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        # ---- MCP lifecycle methods ------------------------------------

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "kogni",
                        "version": "0.1.0",
                    },
                },
            }

        if method == "notifications/initialized":
            # Client confirms initialization — no response needed
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result_text = await self.handle_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                        "isError": True,
                    },
                }

        # Unrecognized method — return error only for requests with an id
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }
        return None

    async def run_stdio(self) -> None:
        """Run the MCP server over stdio (JSON-RPC, newline-delimited).

        Reads JSON-RPC requests from stdin (one per line),
        writes JSON-RPC responses to stdout (one per line).
        Diagnostic logging goes to stderr.
        """
        # Redirect logging to stderr so stdout stays clean for JSON-RPC
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger("cognigraph").addHandler(handler)

        logger.info("KogniDevServer starting on stdio transport")

        loop = asyncio.get_event_loop()

        # Set up async stdin reader
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        # Set up async stdout writer
        w_transport, w_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break  # EOF — client disconnected

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                request = json.loads(line_str)
                response = await self._handle_jsonrpc(request)

                if response is not None:
                    out = json.dumps(response) + "\n"
                    writer.write(out.encode("utf-8"))
                    await writer.drain()

            except json.JSONDecodeError as exc:
                error_resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                    "id": None,
                }
                writer.write((json.dumps(error_resp) + "\n").encode("utf-8"))
                await writer.drain()

            except Exception as exc:
                logger.exception("Unhandled error in stdio loop")
                error_resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": str(exc)},
                    "id": None,
                }
                try:
                    writer.write((json.dumps(error_resp) + "\n").encode("utf-8"))
                    await writer.drain()
                except Exception:
                    break  # stdout broken, exit

        logger.info("KogniDevServer shutting down")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_limit(level: str) -> int:
    """Number of nodes to include at each context level."""
    return {"minimal": 3, "standard": 6, "deep": 12}.get(level, 6)


# ---------------------------------------------------------------------------
# Entry point (for direct invocation)
# ---------------------------------------------------------------------------


def main(config_path: str = "cognigraph.yaml") -> None:
    """Start the MCP dev server on stdio."""
    server = KogniDevServer(config_path=config_path)
    asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
