"""Graqle MCP Development Server — governed development for Claude Code.

Production MCP server exposing 7 tools over JSON-RPC stdio transport.
Replaces flat-file CLAUDE.md reading with graph-powered context engineering.

FREE tier (3 tools):
    1. graq_context  — Smart context loading for session start
    2. graq_inspect   — Graph structure inspection
    3. graq_reason    — Graph-of-agents reasoning

PRO tier (4 tools, license-gated):
    4. graq_preflight — Governance check before code changes
    5. graq_lessons   — Query lessons relevant to current work
    6. graq_impact    — Trace downstream impacts of a change
    7. graq_learn     — Feed outcomes back for Bayesian graph learning

Usage:
    graq mcp serve                     # stdio transport (Claude Code)
    graq mcp serve --config my.yaml    # custom config

Claude Code .mcp.json:
    {
      "mcpServers": {
        "graq": {
          "command": "graq",
          "args": ["mcp", "serve"]
        }
      }
    }
"""

# ── graqle:intelligence ──
# module: graqle.plugins.mcp_dev_server
# risk: HIGH (impact radius: 5 modules)
# consumers: __init__, test_impact_filtering, test_lesson_hit_count, test_mcp_dev_server, test_mcp_dev_server_v015
# dependencies: __future__, json, logging, sys, asyncio +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import sys
import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.mcp")

try:
    from graqle.__version__ import __version__ as _version
except Exception:
    _version = "0.0.0"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_SENSITIVE_KEYS = frozenset({"api_key", "secret", "password", "token", "credential"})

_LESSON_ENTITY_TYPES = frozenset({
    "LESSON", "MISTAKE", "SAFETY", "ADR", "DECISION",
    "REQUIREMENT", "PROCEDURE", "DEFINITION",
})

_MAX_BFS_DEPTH = 3
_MAX_RESULTS = 50

# ---------------------------------------------------------------------------
# Tool Definitions (MCP protocol)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # ── FREE tier ──────────────────────────────────────────────────────────
    {
        "name": "graq_context",
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
                "caller": {
                    "type": "string",
                    "description": "Caller identifier for multi-agent tracking (e.g., 'agent-1', 'ci-pipeline')",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "graq_inspect",
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
        "name": "graq_reason",
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
                "caller": {
                    "type": "string",
                    "description": "Caller identifier for multi-agent tracking (e.g., 'agent-1', 'ci-pipeline')",
                },
            },
            "required": ["question"],
        },
    },
    # ── PRO tier ───────────────────────────────────────────────────────────
    {
        "name": "graq_preflight",
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
                "caller": {
                    "type": "string",
                    "description": "Caller identifier for multi-agent tracking (e.g., 'agent-1', 'ci-pipeline')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "graq_lessons",
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
        "name": "graq_impact",
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
        "name": "graq_learn",
        "description": (
            "Teach the knowledge graph. Three modes:\n"
            "1. 'outcome' (default) — Record a dev outcome, adjust edge weights\n"
            "2. 'entity' — Add a business entity (PRODUCT, CLIENT, TEAM, etc.)\n"
            "3. 'knowledge' — Teach domain knowledge (brand rules, copy, etc.)\n"
            "Call after completing a task, or to enrich the graph with business context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["outcome", "entity", "knowledge"],
                    "default": "outcome",
                    "description": "Learning mode: outcome (edge weight updates), entity (business nodes), knowledge (domain facts)",
                },
                "action": {
                    "type": "string",
                    "description": "[outcome mode] What was done",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "partial"],
                    "description": "[outcome mode] Task outcome",
                },
                "components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[outcome mode] Components involved",
                },
                "lesson": {
                    "type": "string",
                    "description": "[outcome mode] Optional new lesson learned",
                },
                "entity_id": {
                    "type": "string",
                    "description": "[entity mode] Unique entity ID (e.g. 'CrawlQ', 'Philips')",
                },
                "entity_type": {
                    "type": "string",
                    "description": "[entity mode] Type: PRODUCT, CLIENT, BUSINESS_OUTCOME, TEAM, SYNERGY, MARKET, COMPETITOR, METRIC",
                },
                "description": {
                    "type": "string",
                    "description": "[entity/knowledge mode] Description or fact text",
                },
                "connects_to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[entity mode] Node IDs to connect to",
                },
                "domain": {
                    "type": "string",
                    "description": "[knowledge mode] Domain: brand, copy, product, market, technical",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[knowledge mode] Tags for retrieval",
                },
            },
            "required": [],
        },
    },
    {
        "name": "graq_reload",
        "description": (
            "Force-reload the knowledge graph from disk. "
            "Use after external changes to graqle.json "
            "(e.g., after graq learn, graq scan, or manual edits)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "graq_audit",
        "description": (
            "Deep health audit of knowledge graph chunk coverage. "
            "Goes beyond validate (which checks descriptions) to audit "
            "the actual evidence chunks that reasoning agents depend on. "
            "Catches hollow KGs where nodes have descriptions but no chunks. "
            "Returns health status: CRITICAL, WARNING, MODERATE, or HEALTHY."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fix": {
                    "type": "boolean",
                    "default": False,
                    "description": "Auto-synthesize chunks for hollow nodes",
                },
                "verbose": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include per-node chunk details in output",
                },
            },
        },
    },
    {
        "name": "graq_gate",
        "description": (
            "Pre-compiled intelligence gate — instant context for any module (<100ms). "
            "Returns risk level, impact radius, consumers, dependencies, constraints, "
            "incidents, and public interfaces from .graqle/intelligence/. "
            "No scanning needed. Use before modifying any file to understand blast radius. "
            "Run 'graq compile' first to populate intelligence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "description": (
                        "Module name or file path to query. "
                        "Examples: 'graqle.core.graph', 'core/graph.py', 'graph'"
                    ),
                },
                "action": {
                    "type": "string",
                    "enum": ["context", "impact", "scorecard"],
                    "default": "context",
                    "description": (
                        "context: full module packet. "
                        "impact: what breaks if this module changes. "
                        "scorecard: overall project quality gate status."
                    ),
                },
            },
            "required": ["module"],
        },
    },
    {
        "name": "graq_drace",
        "description": (
            "DRACE governance scoring — query AI reasoning audit trails "
            "and development governance quality scores. "
            "DRACE = Dependency + Reasoning + Auditability + Constraint + Explainability. "
            "Each reasoning session is scored on 5 pillars (0.0-1.0). "
            "Use to inspect AI decision transparency and evidence quality."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["sessions", "trail", "score"],
                    "default": "sessions",
                    "description": (
                        "sessions: list recent audit sessions. "
                        "trail: get full audit trail for a session. "
                        "score: get DRACE score breakdown for a session."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (required for 'trail' and 'score' actions)",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Max sessions to return (for 'sessions' action)",
                },
            },
        },
    },
    {
        "name": "graq_runtime",
        "description": (
            "Query live runtime observability data from your cloud environment. "
            "Auto-detects AWS CloudWatch, Azure Monitor, GCP Cloud Logging, "
            "or local Docker/file logs. Returns classified runtime events "
            "(errors, timeouts, throttles) with severity levels and hit counts. "
            "Use this for debugging production issues — it bridges the gap "
            "between static code knowledge and live system behavior."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to investigate (e.g., 'errors in BAMR-API last 2 hours', "
                        "'Lambda timeouts', 'auth failures')"
                    ),
                },
                "source": {
                    "type": "string",
                    "enum": ["auto", "cloudwatch", "azure_monitor", "cloud_logging", "docker", "file"],
                    "default": "auto",
                    "description": "Log source (auto-detects if not specified)",
                },
                "service": {
                    "type": "string",
                    "description": "Filter to a specific service/Lambda/container name",
                },
                "hours": {
                    "type": "number",
                    "default": 6,
                    "description": "How far back to look (hours)",
                },
                "severity_filter": {
                    "type": "string",
                    "enum": ["all", "low", "medium", "high", "critical"],
                    "default": "high",
                    "description": "Minimum severity to return",
                },
                "ingest": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also ingest runtime events as RUNTIME_EVENT nodes into the KG",
                },
            },
        },
    },
    {
        "name": "graq_route",
        "description": (
            "Smart query router — classifies your question and recommends "
            "whether to use Graqle tools or external tools (CloudWatch, grep, git). "
            "Call this BEFORE investigating to get the most efficient tool strategy. "
            "Returns: category, recommended tools, confidence, and reasoning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or investigation topic to route",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "graq_lifecycle",
        "description": (
            "Session lifecycle hooks for development workflows. "
            "Call at key moments: session_start (load context), "
            "investigation_start (before debugging), fix_complete (after a fix). "
            "Returns relevant context, lessons, and graph status for each phase."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "enum": ["session_start", "investigation_start", "fix_complete"],
                    "description": "Lifecycle event type",
                },
                "context": {
                    "type": "string",
                    "description": "Description of what you're doing (task, bug description, fix summary)",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant files (optional)",
                },
            },
            "required": ["event"],
        },
    },
]

# Backward-compat: register kogni_* aliases so old .mcp.json configs still work.
# Each kogni_* tool mirrors the corresponding graq_* tool exactly.
_KOGNI_ALIASES: list[dict[str, Any]] = []
for _tool in TOOL_DEFINITIONS:
    if _tool["name"].startswith("graq_") and _tool["name"] not in ("graq_reload", "graq_audit"):
        _alias = dict(_tool)
        _alias["name"] = _tool["name"].replace("graq_", "kogni_", 1)
        _KOGNI_ALIASES.append(_alias)
TOOL_DEFINITIONS.extend(_KOGNI_ALIASES)
del _KOGNI_ALIASES


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


_WRITE_TOOLS = frozenset({"graq_learn", "graq_reload", "kogni_learn"})


class KogniDevServer:
    """MCP server exposing 7 governed development tools over stdio.

    Implements the Model Context Protocol JSON-RPC transport.
    Graph is lazily loaded on first tool call.

    Parameters
    ----------
    config_path:
        Path to graqle.yaml configuration file.
    read_only:
        If ``True``, mutation tools (graq_learn, graq_reload) are blocked.
        Only read-only tools are exposed: graq_context, graq_inspect,
        graq_reason, graq_preflight, graq_lessons, graq_impact.
    """

    def __init__(self, config_path: str = "graqle.yaml", read_only: bool = False) -> None:
        self.config_path = config_path
        self.read_only = read_only
        self._graph: Any = None  # Graqle, loaded lazily
        self._config: Any = None  # GraqleConfig
        self._graph_file: str | None = None  # path to the loaded graph JSON
        self._graph_mtime: float = 0.0
        self._gov: Any = None  # GovernanceMiddleware, loaded lazily
        self._neo4j_traversal: Any = None  # Neo4jTraversal, set when Neo4j active

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def _load_graph(self) -> Any | None:
        """Lazy-load the knowledge graph. Reloads automatically if file changed on disk."""
        # Hot-reload: check if graph file changed since last load
        if self._graph is not None and self._graph_file is not None:
            try:
                current_mtime = Path(self._graph_file).stat().st_mtime
                if current_mtime > self._graph_mtime:
                    logger.info("Graph file changed on disk — reloading")
                    self._graph = None  # Force reload
            except OSError:
                pass  # File gone — use cached graph

        if self._graph is not None:
            return self._graph

        try:
            from graqle.config.settings import GraqleConfig
            from graqle.core.graph import Graqle

            cfg_path = Path(self.config_path)
            if cfg_path.exists():
                self._config = GraqleConfig.from_yaml(str(cfg_path))
            else:
                self._config = GraqleConfig.default()

            # Try Neo4j if configured
            connector = getattr(getattr(self._config, "graph", None), "connector", "networkx")
            if connector == "neo4j":
                try:
                    graph_cfg = self._config.graph
                    self._graph = Graqle.from_neo4j(
                        uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
                        username=getattr(graph_cfg, "username", None) or "neo4j",
                        password=getattr(graph_cfg, "password", None) or "",
                        database=getattr(graph_cfg, "database", None) or "neo4j",
                        config=self._config,
                    )
                    self._graph_file = f"neo4j://{getattr(graph_cfg, 'uri', 'localhost')}"
                    self._graph_mtime = 9999999999.0  # No file-based hot-reload for Neo4j
                    self._assign_backend(self._graph, self._config)
                    # Initialize Neo4j-native traversal engine for fast queries
                    try:
                        from graqle.connectors.neo4j_traversal import Neo4jTraversal
                        self._neo4j_traversal = Neo4jTraversal(
                            uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
                            username=getattr(graph_cfg, "username", None) or "neo4j",
                            password=getattr(graph_cfg, "password", None) or "",
                            database=getattr(graph_cfg, "database", None) or "neo4j",
                        )
                        logger.info("Neo4j traversal engine initialized (Cypher-native)")
                    except Exception as te:
                        logger.warning("Neo4j traversal engine not available: %s", te)
                    logger.info(
                        "Loaded graph from Neo4j: %d nodes, %d edges",
                        len(self._graph.nodes),
                        len(self._graph.edges),
                    )
                    return self._graph
                except Exception as neo4j_exc:
                    logger.warning("Neo4j load failed (%s), falling back to JSON", neo4j_exc)

            # Auto-discover graph file (JSON/NetworkX fallback)
            for candidate in [
                "graqle.json",
                "knowledge_graph.json",
                "graph.json",
            ]:
                p = Path(candidate)
                if p.exists():
                    self._graph = Graqle.from_json(str(p), config=self._config)
                    self._graph_file = str(p.resolve())
                    self._graph_mtime = p.stat().st_mtime
                    # Assign real backend from config
                    self._assign_backend(self._graph, self._config)
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

    @staticmethod
    def _assign_backend(graph: Any, cfg: Any) -> None:
        """Create and assign a real model backend from config to the graph.

        Tries configured backend (Anthropic, OpenAI, Bedrock, Ollama).
        Falls back to mock only if real backend can't be created.
        """
        import os

        backend_name = cfg.model.backend
        model_name = cfg.model.model
        api_key = cfg.model.api_key

        # Resolve env var references like ${ANTHROPIC_API_KEY}
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var)

        try:
            if backend_name == "anthropic":
                from graqle.backends.api import AnthropicBackend
                if not api_key:
                    api_key = os.environ.get("ANTHROPIC_API_KEY")
                if api_key:
                    graph.set_default_backend(AnthropicBackend(model=model_name, api_key=api_key))
                    logger.info("Backend: Anthropic (%s)", model_name)
                    return

            elif backend_name == "openai":
                from graqle.backends.api import OpenAIBackend
                if not api_key:
                    api_key = os.environ.get("OPENAI_API_KEY")
                if api_key:
                    graph.set_default_backend(OpenAIBackend(model=model_name, api_key=api_key))
                    logger.info("Backend: OpenAI (%s)", model_name)
                    return

            elif backend_name == "bedrock":
                from graqle.backends.api import BedrockBackend
                region = getattr(cfg.model, "region", None) or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
                graph.set_default_backend(BedrockBackend(model=model_name, region=region))
                logger.info("Backend: Bedrock (%s in %s)", model_name, region)
                return

            elif backend_name == "ollama":
                from graqle.backends.api import OllamaBackend
                host = getattr(cfg.model, "host", None) or "http://localhost:11434"
                graph.set_default_backend(OllamaBackend(model=model_name, host=host))
                logger.info("Backend: Ollama (%s)", model_name)
                return

        except Exception as exc:
            logger.warning("Failed to create %s backend: %s", backend_name, exc)

        # No real backend available — LOUD warning
        logger.warning(
            "NO LLM BACKEND CONFIGURED — reasoning will use graph traversal only. "
            "Run 'graq doctor' to diagnose. "
            "Quick fix: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    def _require_graph(self) -> Any:
        """Load graph or raise with a helpful message."""
        graph = self._load_graph()
        if graph is None:
            raise RuntimeError(
                "No knowledge graph loaded. "
                "Place a graqle.json, knowledge_graph.json, or graph.json "
                "in the working directory, or run 'graq scan --repo .' first."
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
        """Return compact neighbor info for a node.

        Uses Neo4j-native Cypher query when available (~2ms).
        Falls back to Python edge iteration (~10ms).
        """
        # Fast path: Neo4j-native neighbor query
        if getattr(self, "_neo4j_traversal", None) is not None:
            try:
                ctx = self._neo4j_traversal.node_context(node_id, max_neighbors=30)
                if ctx.get("found"):
                    return ctx.get("neighbors", [])
            except Exception:
                pass  # Fall through to Python path

        # Fallback: Python iteration
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
        """Return MCP tool definitions.

        In read-only mode, mutation tools (graq_learn, graq_reload) are excluded.
        """
        if self.read_only:
            return [t for t in TOOL_DEFINITIONS if t["name"] not in _WRITE_TOOLS]
        return TOOL_DEFINITIONS

    # ------------------------------------------------------------------
    # MCP protocol: tool dispatch
    # ------------------------------------------------------------------

    async def handle_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Route a tool call to the correct handler. Returns JSON string."""
        # Block write tools in read-only mode
        if self.read_only and name in _WRITE_TOOLS:
            return json.dumps({
                "error": f"Tool '{name}' is blocked in read-only mode. "
                "The MCP server was started with --read-only.",
            })

        handlers: dict[str, Any] = {
            "graq_context": self._handle_context,
            "graq_inspect": self._handle_inspect,
            "graq_reason": self._handle_reason,
            "graq_preflight": self._handle_preflight,
            "graq_lessons": self._handle_lessons,
            "graq_impact": self._handle_impact,
            "graq_learn": self._handle_learn,
            "graq_reload": self._handle_reload,
            "graq_audit": self._handle_audit,
            "graq_runtime": self._handle_runtime,
            "graq_route": self._handle_route,
            "graq_lifecycle": self._handle_lifecycle,
            "graq_gate": self._handle_gate,
            "graq_drace": self._handle_drace,
            # Backward-compat aliases (kogni_* → graq_*)
            "kogni_context": self._handle_context,
            "kogni_inspect": self._handle_inspect,
            "kogni_reason": self._handle_reason,
            "kogni_preflight": self._handle_preflight,
            "kogni_lessons": self._handle_lessons,
            "kogni_impact": self._handle_impact,
            "kogni_learn": self._handle_learn,
            "kogni_runtime": self._handle_runtime,
            "kogni_route": self._handle_route,
            "kogni_lifecycle": self._handle_lifecycle,
            "kogni_gate": self._handle_gate,
            "kogni_drace": self._handle_drace,
        }

        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Track caller in metrics if provided
        caller = arguments.get("caller", "")
        if caller:
            try:
                from graqle.metrics.engine import MetricsEngine
                metrics = MetricsEngine()
                metrics.record_query(f"mcp:{name}", 0, caller=caller)
            except Exception:
                pass  # Never fail on metrics tracking

        try:
            return await handler(arguments)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)})


    # ==================================================================
    # Tool handlers
    # ==================================================================

    # ── 1. graq_context (FREE) ───────────────────────────────────────

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
                "Run `graq scan --repo .` to build one._"
            )

        if not parts:
            parts.append(f"No specific context found for task: '{task}'")

        return json.dumps({
            "context": "\n\n".join(parts),
            "level": level,
            "nodes_matched": len(matches) if graph and matches else 0,
            "graph_loaded": graph is not None,
        })

    # ── 2. graq_inspect (FREE) ───────────────────────────────────────

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
                    "hint": "Use graq_inspect with stats=true to see available nodes.",
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

    # ── 3. graq_reason (FREE) ────────────────────────────────────────

    async def _handle_reason(self, args: dict[str, Any]) -> str:
        import time as _time

        question = args.get("question", "")
        max_rounds = min(max(args.get("max_rounds", 2), 1), 5)

        if not question:
            return json.dumps({"error": "Parameter 'question' is required."})

        t0 = _time.monotonic()
        graph = self._require_graph()

        # Detect backend status BEFORE attempting reasoning
        backend_status = self._check_backend_status(graph)

        # Try full areason if a backend is configured
        try:
            result = await graph.areason(
                question, max_rounds=max_rounds, task_type="reason",
            )
            result_dict = {
                "answer": result.answer,
                "confidence": round(result.confidence, 3),
                "rounds": result.rounds_completed,
                "nodes_used": result.node_count,
                "active_nodes": result.active_nodes[:10],
                "cost_usd": round(result.cost_usd, 6),
                "latency_ms": round(result.latency_ms, 1),
                "mode": result.reasoning_mode,
                "backend_status": result.backend_status,
                "backend_error": result.backend_error,
            }
            duration_ms = (_time.monotonic() - t0) * 1000

            # Governance audit
            gov = self._get_governance()
            if gov is not None:
                try:
                    session = gov.get_or_start_session(f"reason:{question[:50]}")
                    gov.log_tool_call(
                        session, "graq_reason", args, result_dict,
                        duration_ms=duration_ms,
                        nodes_consulted=result.node_count,
                    )
                except Exception as exc:
                    logger.debug("Governance logging failed: %s", exc)

            return json.dumps(result_dict)
        except RuntimeError as exc:
            # Backend failed — DO NOT silently fall back.
            # Surface the error clearly AND provide fallback results.
            backend_status["status"] = "unavailable"
            backend_status["error"] = str(exc)[:200]
        except Exception as exc:
            backend_status["status"] = "error"
            backend_status["error"] = str(exc)[:200]

        # Fallback: keyword-based graph traversal (clearly labeled)
        matches = self._find_nodes_matching(question, limit=8)
        if not matches:
            return json.dumps({
                "answer": "No relevant nodes found for this question.",
                "confidence": 0.0,
                "rounds": 0,
                "nodes_used": 0,
                "active_nodes": [],
                "mode": "fallback_traversal",
                "backend_status": backend_status["status"],
                "backend_error": backend_status.get("error", ""),
                "hint": (
                    "LLM reasoning is unavailable. Results are keyword-match only. "
                    "Fix: check credentials and run 'graq doctor'. "
                    f"Backend: {backend_status.get('backend', 'unknown')}"
                ),
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
            "backend_status": backend_status["status"],
            "backend_error": backend_status.get("error", ""),
            "hint": (
                "WARNING: LLM reasoning is unavailable — this is keyword-match only, "
                "NOT multi-hop graph reasoning. Results may be inaccurate. "
                "Fix: run 'graq doctor' to diagnose backend issues."
            ),
        })

    # ── 4. graq_preflight (PRO) ──────────────────────────────────────

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

    # ── 5. graq_lessons (PRO) ────────────────────────────────────────

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

    # ── 6. graq_impact (PRO) ─────────────────────────────────────────

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

    # Structural edges that should NOT propagate impact (they connect siblings
    # via parent directories, producing "everything in components/" results).
    _STRUCTURAL_EDGES: set[str] = {"CONTAINS", "DEFINES"}

    def _bfs_impact(
        self,
        start_id: str,
        *,
        change_type: str = "modify",
        max_depth: int = _MAX_BFS_DEPTH,
    ) -> list[dict[str, Any]]:
        """BFS from start_id, following only dependency edges (not structural).

        Uses Neo4j-native Cypher traversal when available (~5ms).
        Falls back to Python BFS over in-memory graph (~60ms).
        """
        # Fast path: Neo4j-native traversal
        if getattr(self, "_neo4j_traversal", None) is not None:
            try:
                return self._neo4j_traversal.impact_bfs(
                    start_id,
                    max_depth=max_depth,
                    change_type=change_type,
                    limit=_MAX_RESULTS,
                )
            except Exception as exc:
                logger.warning("Neo4j traversal failed (%s), falling back to Python BFS", exc)

        # Fallback: Python BFS over in-memory graph
        graph = self._require_graph()
        visited: set[str] = {start_id}
        queue: deque[tuple[str, int, str]] = deque()  # (node_id, depth, relationship)

        # Seed: who *depends on* start_id?  Follow reverse IMPORTS/CALLS, and
        # forward edges from start_id that are dependency-typed.
        for edge in graph.edges.values():
            rel = getattr(edge, "relationship", "")
            if rel in self._STRUCTURAL_EDGES:
                continue
            if edge.source_id == start_id and edge.target_id not in visited:
                queue.append((edge.target_id, 1, rel))
            elif edge.target_id == start_id and edge.source_id not in visited:
                queue.append((edge.source_id, 1, rel))

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

            # Continue BFS — only follow dependency edges
            if depth < max_depth:
                for edge in graph.edges.values():
                    edge_rel = getattr(edge, "relationship", "")
                    if edge_rel in self._STRUCTURAL_EDGES:
                        continue
                    next_id: str | None = None
                    if edge.source_id == nid and edge.target_id not in visited:
                        next_id = edge.target_id
                    elif edge.target_id == nid and edge.source_id not in visited:
                        next_id = edge.source_id
                    if next_id:
                        queue.append((next_id, depth + 1, edge_rel))

        return results

    # ── 7. graq_learn (PRO) ──────────────────────────────────────────

    async def _handle_learn(self, args: dict[str, Any]) -> str:
        mode = args.get("mode", "outcome")

        if mode == "entity":
            return await self._handle_learn_entity(args)
        elif mode == "knowledge":
            return await self._handle_learn_knowledge(args)
        else:
            return await self._handle_learn_outcome(args)

    async def _handle_learn_outcome(self, args: dict[str, Any]) -> str:
        """Original learn mode: record dev outcomes, adjust edge weights."""
        action = args.get("action", "")
        outcome = args.get("outcome", "")
        components = args.get("components", [])
        lesson_text = args.get("lesson")

        if not action or not outcome or not components:
            return json.dumps({
                "error": "Outcome mode requires 'action', 'outcome', and 'components'."
            })

        graph = self._load_graph()
        updates: list[dict[str, Any]] = []
        lesson_node_id: str | None = None

        if graph is not None:
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

            if lesson_text:
                from graqle.core.node import CogniNode
                from graqle.core.edge import CogniEdge

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

                for idx, nid in enumerate(component_ids):
                    edge = CogniEdge(
                        id=f"e_{lesson_node_id}_{nid}_{idx}",
                        source_id=lesson_node_id,
                        target_id=nid,
                        relationship="LEARNED_FROM",
                        weight=1.0,
                    )
                    graph.add_edge(edge)

            self._save_graph(graph)

        return json.dumps({
            "recorded": True,
            "mode": "outcome",
            "action": action,
            "outcome": outcome,
            "components": components,
            "edge_updates": updates,
            "lesson_node_id": lesson_node_id,
        })

    async def _handle_learn_entity(self, args: dict[str, Any]) -> str:
        """Entity mode: add business-level nodes (PRODUCT, CLIENT, etc.)."""
        entity_id = args.get("entity_id", "")
        entity_type = args.get("entity_type", "PRODUCT")
        description = args.get("description", "")
        connects_to = args.get("connects_to", [])

        if not entity_id:
            return json.dumps({
                "error": "Entity mode requires 'entity_id'."
            })

        graph = self._load_graph()
        if graph is None:
            return json.dumps({"error": "No graph loaded."})

        graph.add_node_simple(
            entity_id,
            label=entity_id.replace("_", " ").title(),
            entity_type=entity_type.upper(),
            description=description,
            properties={
                "source": "graq_learn_entity",
                "manual": True,
                "business_entity": True,
            },
        )

        edges_added: list[str] = []
        for target in connects_to:
            node = self._find_node(target)
            if node:
                graph.add_edge_simple(entity_id, node.id, relation="RELATES_TO")
                edges_added.append(node.id)

        auto_edges = 0
        if hasattr(graph, "auto_connect"):
            auto_edges = graph.auto_connect([entity_id])

        self._save_graph(graph)

        return json.dumps({
            "recorded": True,
            "mode": "entity",
            "entity_id": entity_id,
            "entity_type": entity_type.upper(),
            "description": description[:100],
            "connected_to": edges_added,
            "auto_edges": auto_edges,
            "total_nodes": len(graph.nodes),
        })

    async def _handle_learn_knowledge(self, args: dict[str, Any]) -> str:
        """Knowledge mode: teach domain facts that can't be extracted from code."""
        description = args.get("description", "")
        domain = args.get("domain", "general")
        tags = args.get("tags", [])

        if not description:
            return json.dumps({
                "error": "Knowledge mode requires 'description' (the fact to teach)."
            })

        graph = self._load_graph()
        if graph is None:
            return json.dumps({"error": "No graph loaded."})

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        node_id = f"knowledge_{domain}_{ts}"

        graph.add_node_simple(
            node_id,
            label=description[:80],
            entity_type="KNOWLEDGE",
            description=description,
            properties={
                "source": "graq_learn_knowledge",
                "domain": domain,
                "tags": tags,
                "created": ts,
                "manual": True,
            },
        )

        auto_edges = 0
        if hasattr(graph, "auto_connect"):
            auto_edges = graph.auto_connect([node_id])

        self._save_graph(graph)

        return json.dumps({
            "recorded": True,
            "mode": "knowledge",
            "node_id": node_id,
            "domain": domain,
            "description": description[:100],
            "tags": tags,
            "auto_edges": auto_edges,
            "total_nodes": len(graph.nodes),
        })

    async def _handle_reload(self, args: dict[str, Any]) -> str:
        """Force-reload the knowledge graph from disk."""
        old_count = len(self._graph.nodes) if self._graph else 0
        self._graph = None  # Force reload
        self._graph_mtime = 0.0
        graph = self._load_graph()
        new_count = len(graph.nodes) if graph else 0
        return json.dumps({
            "status": "reloaded",
            "previous_nodes": old_count,
            "current_nodes": new_count,
            "graph_file": self._graph_file,
        })

    # ── 9. graq_audit ─────────────────────────────────────────────

    async def _handle_audit(self, args: dict[str, Any]) -> str:
        """Deep chunk health audit of the knowledge graph."""
        graph = self._load_graph()
        if graph is None:
            return json.dumps({"error": "No graph loaded."})

        fix = args.get("fix", False)
        verbose = args.get("verbose", False)

        # Reuse the audit logic from the CLI command
        from graqle.cli.commands.audit import _run_audit

        report = _run_audit(graph)

        # Apply fix if requested
        if fix and report["nodes_without_chunks"]:
            before = report["nodes_with_chunks"]
            graph.rebuild_chunks(force=False)
            report = _run_audit(graph)
            report["fix_applied"] = True
            report["nodes_gained_chunks"] = report["nodes_with_chunks"] - before

            # Persist if graph file is known
            if self._graph_file:
                try:
                    graph.to_json(self._graph_file)
                    report["saved_to"] = self._graph_file
                except Exception as exc:
                    report["save_error"] = str(exc)

        # Trim hollow_nodes detail unless verbose
        if not verbose and report.get("hollow_nodes"):
            report["hollow_nodes_sample"] = report["hollow_nodes"][:5]
            report["hollow_nodes_total"] = len(report["hollow_nodes"])
            del report["hollow_nodes"]

        return json.dumps(report, indent=2)

    # ── 10. graq_runtime ────────────────────────────────────────────

    async def _handle_runtime(self, args: dict[str, Any]) -> str:
        """Query live runtime observability data."""
        query = args.get("query", "")
        source = args.get("source", "auto")
        service = args.get("service")
        hours = min(max(args.get("hours", 6), 0.1), 168)  # 1 week max
        severity_filter = args.get("severity_filter", "high")
        ingest = args.get("ingest", False)

        try:
            from graqle.runtime.detector import detect_environment
            from graqle.runtime.fetcher import create_fetcher
            from graqle.runtime.kg_builder import RuntimeKGBuilder

            # Detect environment
            env = detect_environment()

            # Resolve source
            provider = source if source != "auto" else env.provider

            # Get runtime config from graqle.yaml if available
            log_groups: list[str] = []
            log_paths: list[str] = []
            if self._config and hasattr(self._config, "runtime"):
                rt_cfg = self._config.runtime
                for src in rt_cfg.sources:
                    if src.log_group:
                        log_groups.append(src.log_group)
                    if src.log_path:
                        log_paths.append(src.log_path)

            # Infer service from query if not provided
            if not service and query:
                # Simple extraction: look for capitalized words or quoted strings
                import re
                quoted = re.findall(r'"([^"]+)"', query)
                if quoted:
                    service = quoted[0]

            # Create fetcher and fetch
            fetcher = create_fetcher(
                provider,
                region=env.region,
                log_groups=log_groups or None,
                log_paths=log_paths or None,
            )

            # Health check first
            health = fetcher.health_check()
            if health.get("status") == "error":
                return json.dumps({
                    "error": f"Runtime source unavailable: {health.get('error', 'unknown')}",
                    "provider": provider,
                    "environment": {
                        "detected": env.provider,
                        "confidence": env.confidence,
                        "region": env.region,
                    },
                    "hint": health.get("hint", "Check credentials and provider configuration."),
                })

            result = await fetcher.fetch(
                hours=hours,
                service=service,
                severity_filter=severity_filter,
                max_events=100,
            )

            # Build summary
            summary = RuntimeKGBuilder.summary(result)

            # Optionally ingest into KG
            ingest_result = None
            if ingest and result.events:
                graph_path = self._graph_file or "graqle.json"
                builder = RuntimeKGBuilder(graph_path=graph_path)
                ingest_result = builder.ingest_into_graph(result)
                # Force graph reload to pick up new nodes
                self._graph = None
                self._graph_mtime = 0.0

            response: dict[str, Any] = {
                "environment": {
                    "detected": env.provider,
                    "confidence": env.confidence,
                    "region": env.region,
                    "log_sources": env.log_sources,
                },
                "summary": summary,
                "events": [
                    {
                        "id": e.id,
                        "category": e.category,
                        "severity": e.severity,
                        "service": e.service_name,
                        "hits": e.hit_count,
                        "message": e.message[:300],
                        "timestamp": e.timestamp,
                    }
                    for e in result.events[:20]  # Return top 20 in response
                ],
                "fetch_duration_ms": round(result.fetch_duration_ms, 1),
            }

            if ingest_result:
                response["ingest"] = ingest_result
            if result.errors:
                response["errors"] = result.errors

            return json.dumps(response)

        except ImportError as exc:
            return json.dumps({
                "error": f"Runtime module dependency missing: {exc}",
                "hint": "pip install boto3 (for AWS) or azure-monitor-query (for Azure) or google-cloud-logging (for GCP)",
            })
        except Exception as exc:
            return json.dumps({"error": f"Runtime fetch failed: {exc}"})

    # ── 11. graq_route ──────────────────────────────────────────────

    async def _handle_route(self, args: dict[str, Any]) -> str:
        """Smart query router — recommend Graqle vs external tools."""
        question = args.get("question", "")

        if not question:
            return json.dumps({"error": "Parameter 'question' is required."})

        from graqle.runtime.router import route_question

        # Check if runtime data is available
        has_runtime = True  # graq_runtime is now built-in

        recommendation = route_question(question, has_runtime=has_runtime)

        return json.dumps(recommendation.to_dict())

    # ── 12. graq_lifecycle ────────────────────────────────────────────

    async def _handle_lifecycle(self, args: dict[str, Any]) -> str:
        """Session lifecycle hooks — context at key dev moments."""
        event = args.get("event", "")
        context_text = args.get("context", "")
        files = args.get("files", [])

        if not event:
            return json.dumps({"error": "Parameter 'event' is required."})

        graph = self._load_graph()
        response: dict[str, Any] = {
            "event": event,
            "graph_loaded": graph is not None,
        }

        if event == "session_start":
            # Return graph stats + backend status + recent lessons
            if graph is not None:
                stats = graph.stats
                response["graph"] = {
                    "nodes": stats.total_nodes,
                    "edges": stats.total_edges,
                    "components": stats.connected_components,
                    "hub_nodes": stats.hub_nodes[:5],
                }
            backend_status = self._check_backend_status(graph)
            response["backend"] = backend_status
            # Active branch info
            branch_info = self._read_active_branch()
            if branch_info:
                response["active_branch"] = branch_info
            # Recent lessons
            if graph is not None and context_text:
                lessons = self._find_lesson_nodes(context_text, severity_filter="high")
                if lessons:
                    response["relevant_lessons"] = lessons[:5]

        elif event == "investigation_start":
            # Return context nodes + lessons + route recommendation for the bug
            if context_text:
                if graph is not None:
                    matches = self._find_nodes_matching(context_text, limit=10)
                    if matches:
                        response["relevant_nodes"] = [
                            {"id": m.id, "label": m.label, "type": m.entity_type}
                            for m in matches
                        ]
                    lessons = self._find_lesson_nodes(context_text, severity_filter="all")
                    if lessons:
                        response["past_lessons"] = lessons[:5]
                # Route recommendation
                try:
                    from graqle.runtime.router import route_question
                    rec = route_question(context_text, has_runtime=True)
                    response["recommended_approach"] = rec.to_dict()
                except Exception:
                    pass

        elif event == "fix_complete":
            # Return impact analysis for changed files + preflight warnings
            if graph is not None and files:
                warnings: list[str] = []
                for fpath in files:
                    fname = Path(fpath).stem.lower()
                    for node in graph.nodes.values():
                        node_text = f"{node.id} {node.label}".lower()
                        if fname in node_text:
                            neighbors = self._get_neighbor_summaries(node.id)
                            if neighbors:
                                warnings.append(
                                    f"Changed '{fpath}' relates to '{node.label}' "
                                    f"({len(neighbors)} connections)"
                                )
                            break
                if warnings:
                    response["impact_warnings"] = warnings
            if context_text:
                response["suggestion"] = (
                    "Consider running graq_learn to record this fix outcome "
                    "so the graph remembers the pattern."
                )
        else:
            return json.dumps({"error": f"Unknown event type: {event}. Use: session_start, investigation_start, fix_complete"})

        return json.dumps(response)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _check_backend_status(self, graph: Any) -> dict[str, Any]:
        """Check the status of the configured LLM backend.

        Returns a dict with 'status' ('ok', 'unavailable', 'not_configured')
        and diagnostic info.
        """
        status: dict[str, Any] = {"status": "unknown", "backend": "unknown"}

        if graph is None:
            status["status"] = "no_graph"
            return status

        # Check if graph has a real backend assigned
        backend = getattr(graph, "_default_backend", None)
        if backend is None:
            status["status"] = "not_configured"
            status["hint"] = "No LLM backend configured. Run 'graq doctor'."
            return status

        backend_name = getattr(backend, "name", str(type(backend).__name__))
        status["backend"] = backend_name

        # Detect mock/fallback backends
        if "mock" in backend_name.lower() or getattr(backend, "is_fallback", False):
            status["status"] = "unavailable"
            reason = getattr(backend, "fallback_reason", "Backend fell back to mock")
            status["error"] = reason
            status["hint"] = "LLM backend is not connected. Run 'graq doctor' to diagnose."
            return status

        status["status"] = "ok"
        return status

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
        matched = results[:_MAX_RESULTS]

        # Increment hit_count on each matched lesson node (BUG-7 fix)
        if matched and graph is not None:
            for result in matched:
                node = graph.nodes.get(result["id"])
                if node is not None:
                    current = node.properties.get("hit_count", 0)
                    node.properties["hit_count"] = current + 1
                    result["hit_count"] = current + 1
            self._save_graph(graph)

        return matched

    def _get_governance(self) -> Any:
        """Lazy-load governance middleware."""
        if self._gov is None:
            try:
                from graqle.intelligence.governance.middleware import GovernanceMiddleware
                self._gov = GovernanceMiddleware(Path("."))
            except Exception as exc:
                logger.debug("Governance middleware unavailable: %s", exc)
        return self._gov

    async def _handle_gate(self, args: dict[str, Any]) -> str:
        """Pre-compiled intelligence gate — instant module context (<100ms).

        Delegates to graqle.intelligence.gate.IntelligenceGate for clean separation.
        Automatically logged to governance audit trail.
        """
        import time as _time

        from graqle.intelligence.gate import IntelligenceGate

        t0 = _time.monotonic()
        gate = IntelligenceGate(Path("."))
        module_query = args.get("module", "")
        action = args.get("action", "context")

        if action == "scorecard":
            result = gate.get_scorecard()
        elif not module_query:
            result = {"error": "Parameter 'module' is required."}
        elif action == "impact":
            result = gate.get_impact(module_query)
        else:
            result = gate.get_context(module_query)

        duration_ms = (_time.monotonic() - t0) * 1000

        # Governance audit: log this tool call
        gov = self._get_governance()
        if gov is not None:
            try:
                session = gov.get_or_start_session(f"gate:{module_query or 'scorecard'}")
                gov.log_tool_call(session, "graq_gate", args, result, duration_ms=duration_ms)
            except Exception as exc:
                logger.debug("Governance logging failed: %s", exc)

        return json.dumps(result)

    async def _handle_drace(self, args: dict[str, Any]) -> str:
        """DRACE governance scoring — query audit trail and session scores.

        Actions:
        - "score": Get DRACE score for a session
        - "sessions": List recent audit sessions
        - "trail": Get full audit trail for a session
        """
        gov = self._get_governance()
        if gov is None:
            return json.dumps({"error": "Governance middleware not available."})

        action = args.get("action", "sessions")
        session_id = args.get("session_id", "")

        if action == "sessions":
            from graqle.intelligence.governance.audit import AuditTrail
            trail = AuditTrail(Path("."))
            sessions = trail.list_sessions(limit=args.get("limit", 10))
            return json.dumps({"sessions": sessions, "count": len(sessions)})

        if action == "trail" and session_id:
            from graqle.intelligence.governance.audit import AuditTrail
            trail = AuditTrail(Path("."))
            session = trail.load_session(session_id)
            if session is None:
                return json.dumps({"error": f"Session '{session_id}' not found."})
            return json.dumps(session.model_dump(), default=str)

        if action == "score" and session_id:
            from graqle.intelligence.governance.audit import AuditTrail
            trail = AuditTrail(Path("."))
            session = trail.load_session(session_id)
            if session is None:
                return json.dumps({"error": f"Session '{session_id}' not found."})
            entries_data = [e.model_dump() for e in session.entries]
            score = gov._scorer.score_session(entries_data)
            score.session_id = session_id
            return json.dumps(score.to_dict())

        return json.dumps({"error": f"Unknown action: {action}. Use: sessions, trail, score."})

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
                json.dumps(data, indent=2, default=str), encoding="utf-8"
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
                        "name": "graq",
                        "version": _version,
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

        Uses a thread-based approach for stdin reads to avoid
        ``loop.connect_read_pipe`` / ``connect_write_pipe`` which crash on
        Windows ProactorEventLoop (OSError: [WinError 6] The handle is
        invalid).  Works on Windows, Linux, and macOS.
        """
        # Redirect logging to stderr so stdout stays clean for JSON-RPC
        # Bug 16 fix: only add handler if none exists yet (prevents duplicate logs)
        cg_logger = logging.getLogger("graqle")
        if not cg_logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
            cg_logger.addHandler(handler)

        logger.info("KogniDevServer starting on stdio transport (v%s)", _version)

        # Version mismatch detection: warn if a previous MCP was running a different version
        try:
            version_file = Path(".graqle/mcp.version")
            if version_file.exists():
                last_version = version_file.read_text(encoding="utf-8").strip()
                if last_version and last_version != _version:
                    logger.warning(
                        "VERSION MISMATCH: Previous MCP server was v%s, "
                        "now starting v%s. If you just upgraded, this is expected. "
                        "If not, run 'graq self-update' to align versions.",
                        last_version,
                        _version,
                    )
        except Exception:
            pass  # Non-critical

        loop = asyncio.get_event_loop()

        # -- Cross-platform stdin reading via a background thread ----------
        # ``sys.stdin.buffer.readline()`` is blocking, so we run it in the
        # default ThreadPoolExecutor and await the future.

        import functools

        def _blocking_readline() -> bytes:
            """Read one line from stdin (blocking).  Returns b'' on EOF."""
            try:
                return sys.stdin.buffer.readline()
            except (OSError, ValueError):
                # stdin closed or invalid
                return b""

        def _write_stdout(data: bytes) -> None:
            """Write *data* to stdout and flush (blocking-safe)."""
            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except (OSError, ValueError):
                pass  # stdout closed

        while True:
            try:
                line = await loop.run_in_executor(None, _blocking_readline)
                if not line:
                    break  # EOF — client disconnected

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                request = json.loads(line_str)
                response = await self._handle_jsonrpc(request)

                if response is not None:
                    out = (json.dumps(response) + "\n").encode("utf-8")
                    await loop.run_in_executor(
                        None, functools.partial(_write_stdout, out)
                    )

            except json.JSONDecodeError as exc:
                error_resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                    "id": None,
                }
                out = (json.dumps(error_resp) + "\n").encode("utf-8")
                await loop.run_in_executor(
                    None, functools.partial(_write_stdout, out)
                )

            except Exception as exc:
                logger.exception("Unhandled error in stdio loop")
                error_resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": str(exc)},
                    "id": None,
                }
                try:
                    out = (json.dumps(error_resp) + "\n").encode("utf-8")
                    await loop.run_in_executor(
                        None, functools.partial(_write_stdout, out)
                    )
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


def main(config_path: str = "graqle.yaml") -> None:
    """Start the MCP dev server on stdio."""
    server = KogniDevServer(config_path=config_path)
    asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
