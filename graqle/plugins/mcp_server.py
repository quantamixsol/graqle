"""GraQle MCP Server — governed context engineering for Claude Code.

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

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.plugins.mcp")


def _extract_json_from_llm(raw: str) -> str:
    """Extract JSON object from LLM output using brace counting (regex-safe).

    Replaces re.search(r"\\{.*\\}", raw, re.DOTALL) which raises on LLM output
    containing regex metacharacters (e.g. '[', '(', '*') inside string values.

    Also strips trailing commas before } or ] — a common LLM output artifact
    that breaks json.loads().
    """
    start = raw.find('{')
    if start == -1:
        raise ValueError(f"No JSON object in LLM response: {raw[:200]}")
    depth, end = 0, start
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    candidate = raw[start:end + 1]
    # Strip trailing commas before } or ] (common LLM output artifact)
    candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
    return candidate


def _compute_content_hash(predicted_subgraph: dict) -> str:
    """Compute a stable SHA-256 hash of a predicted subgraph.

    Hash is based on canonical content (labels + relationships),
    NOT on timestamps, UUIDs, or order-sensitive data.
    This makes deduplication deterministic across sessions.
    """
    canonical_parts = []

    # Anchor
    canonical_parts.append(predicted_subgraph.get("anchor_label", "").lower().strip())
    canonical_parts.append(predicted_subgraph.get("anchor_description", "").lower().strip())

    # Supporting nodes — sorted for order independence
    for sn in sorted(
        predicted_subgraph.get("supporting_nodes", []),
        key=lambda x: x.get("label", ""),
    ):
        canonical_parts.append(sn.get("label", "").lower().strip())

    # Causal edges — sorted for order independence
    for ce in sorted(
        predicted_subgraph.get("causal_edges", []),
        key=lambda x: f"{x.get('from_label', '')}-{x.get('to_label', '')}",
    ):
        canonical_parts.append(
            f"{ce.get('from_label', '').lower()}"
            f"-{ce.get('relationship', '').lower()}"
            f"-{ce.get('to_label', '').lower()}"
        )

    canonical = "|".join(canonical_parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    """GraQle MCP Server for Claude Code integration.

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
                    "Returns answer with confidence, governance score, and provenance.\n\n"
                    "Modes:\n"
                    "- standard (default): standard reasoning, byte-identical to prior behaviour\n"
                    "- predictive: runs the full PSE prediction pipeline (same as graq_predict)"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The reasoning query"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["standard", "predictive"],
                            "default": "standard",
                            "description": (
                                "'standard' is the default — identical to current behaviour. "
                                "'predictive' runs through the full PSE pipeline and returns "
                                "prediction fields including q_scores and prediction status."
                            )
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
            {
                "name": "graq_predict",
                "description": (
                    "Run governed reasoning over the knowledge graph and — if confidence "
                    "is sufficient — write the compound prediction as a new subgraph into "
                    "the graph permanently. Future similar queries activate the predicted "
                    "subgraph directly without re-reasoning. "
                    "Use for compound pattern detection, sub-threshold signal analysis, "
                    "and latent failure chain discovery.\n\n"
                    "Modes:\n"
                    "- compound (default): reason + optionally write to graph\n"
                    "- gate: read-only risk assessment — returns CLEAR/WARN/FLAG/INSUFFICIENT_GRAPH, never writes\n"
                    "- cascade_analysis: map failure cascade chain (root → tier-1 → tier-2 → terminal)\n"
                    "- discover: reason without write-back (alias for fold_back=False)"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The reasoning query"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["compound", "gate", "cascade_analysis", "discover"],
                            "default": "compound",
                            "description": (
                                "Operation mode. 'compound' reasons and optionally writes. "
                                "'gate' is read-only risk assessment (never writes). "
                                "'cascade_analysis' maps failure cascade chains. "
                                "'discover' reasons without write-back."
                            )
                        },
                        "max_rounds": {
                            "type": "integer",
                            "default": 3,
                            "description": "Maximum message-passing rounds (passed to graq_reason)"
                        },
                        "fold_back": {
                            "type": "boolean",
                            "default": True,
                            "description": "If false: reasons but does NOT write to graph (dry-run). Ignored in gate mode."
                        },
                        "confidence_threshold": {
                            "type": "number",
                            "default": 0.65,
                            "description": "Minimum answer_confidence to trigger write-back (0.0-1.0). Used in compound mode only."
                        },
                        "gate_threshold": {
                            "type": "number",
                            "default": 0.60,
                            "description": "Minimum answer_confidence to return WARN/FLAG in gate mode (0.0-1.0). Used in gate mode only."
                        },
                        "stg_class": {
                            "type": "string",
                            "enum": ["auto", "I", "II", "III", "IV"],
                            "default": "auto",
                            "description": (
                                "Prediction class. 'auto' escalates I→II→III until closure. "
                                "I=Completion, II=Extension, III=Composition, IV=Extrapolation. "
                                "Class IV requires allow_class_iv=True."
                            )
                        },
                        "allow_class_iv": {
                            "type": "boolean",
                            "default": False,
                            "description": "Explicit opt-in required for Class IV (Extrapolation) predictions. confidence_threshold must be >= 0.75."
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "default": 0.15,
                            "description": "Max cosine distance to existing nodes to detect duplicates"
                        },
                    },
                    "required": ["query"]
                }
            },
        ]

    def _ensure_graph(self) -> None:
        """Lazily load the knowledge graph."""
        if self._graph is not None:
            return

        from graqle.core.graph import Graqle

        self._graph = Graqle.from_json(self._config.graph_path, config="graqle.yaml")
        logger.info(f"Loaded graph: {len(self._graph.nodes)} nodes, {len(self._graph.edges)} edges")

    def _ensure_embedder(self) -> None:
        """Lazily load the embedding engine."""
        if self._embedder is not None:
            return
        from graqle.activation.embeddings import EmbeddingEngine
        self._embedder = EmbeddingEngine()

    def _get_active_embedding_model(self) -> str:
        """Return the name of the currently active embedding model.

        Used in graq_predict output so callers can detect if the model changed
        between calls — e.g. a mid-session model upgrade that would cause a
        dimension mismatch against the stored graph embeddings.
        """
        if self._embedder is None:
            return "unknown"
        return getattr(self._embedder, "model_name", "unknown")

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
            "graq_predict": self._handle_predict,
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
        """Run governed reasoning query.

        mode="standard" (default): byte-identical to prior behaviour.
        mode="predictive": delegates to _handle_predict — returns PSE fields.
        """
        self._ensure_graph()
        query = args.get("query", "")
        mode = args.get("mode", "standard")
        max_rounds = args.get("max_rounds", 3)

        if not query:
            return MCPToolResult("Query is required", is_error=True)

        if mode == "predictive":
            # Delegate to predict pipeline — passes through all predict args
            predict_args = {k: v for k, v in args.items() if k != "mode"}
            predict_args.setdefault("query", query)
            predict_args.setdefault("max_rounds", max_rounds)
            return await self._handle_predict(predict_args)

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

    # ------------------------------------------------------------------
    # graq_predict — Layer A: governed reasoning + fold-back write
    # ------------------------------------------------------------------

    async def _handle_predict(self, args: dict) -> MCPToolResult:
        """Run graq_reason then optionally write predicted subgraph to graph.

        Modes:
        - compound (default): reason + optional write-back
        - gate: read-only risk assessment, never writes
        - cascade_analysis: map failure cascade chain, optionally write
        - discover: reason without write-back (fold_back=False shorthand)
        """
        self._ensure_graph()
        self._ensure_embedder()

        query = args.get("query", "")
        mode = args.get("mode", "compound")
        max_rounds = args.get("max_rounds", 3)
        fold_back = args.get("fold_back", True)
        confidence_threshold = args.get("confidence_threshold", 0.65)
        gate_threshold = args.get("gate_threshold", 0.60)
        stg_class = args.get("stg_class", "auto")
        allow_class_iv = args.get("allow_class_iv", False)
        similarity_threshold = args.get("similarity_threshold", 0.15)

        if not query:
            return MCPToolResult("Query is required", is_error=True)

        # === stg_class guardrails ===
        if stg_class == "IV":
            if not allow_class_iv:
                return MCPToolResult(
                    "Class IV predictions require allow_class_iv=True (explicit opt-in).",
                    is_error=True,
                )
            if confidence_threshold < 0.75:
                return MCPToolResult(
                    "Class IV predictions require confidence_threshold >= 0.75.",
                    is_error=True,
                )

        # === Dispatch by mode ===
        if mode == "gate":
            return await self._handle_gate_mode(
                query=query,
                max_rounds=max_rounds,
                gate_threshold=gate_threshold,
            )

        if mode == "cascade_analysis":
            return await self._handle_cascade_mode(
                query=query,
                max_rounds=max_rounds,
                fold_back=fold_back,
                confidence_threshold=confidence_threshold,
                similarity_threshold=similarity_threshold,
            )

        if mode == "discover":
            fold_back = False  # discover is always dry-run

        # === STEP 1: Run graq_reason UNMODIFIED ===
        reason_result = await self._graph.areason(
            query, max_rounds=max_rounds, task_type="predict",
        )

        # === STEP 2: Compute answer_confidence from cross-node agreement ===
        # This is SEPARATE from reason_result.confidence (raw activation score).
        # answer_confidence measures answer quality, not activation relevance.
        answer_confidence = self._compute_answer_confidence(reason_result)

        # === STEP 3: Compute Q-scores (opaque quality dimensions) ===
        q_scores = self._compute_q_scores(reason_result, answer_confidence)

        # === STEP 4: Validate stg_class IV domain-intersection check ===
        if stg_class == "IV":
            domain_nodes = self._count_domain_intersection_nodes(reason_result)
            if domain_nodes < 50:
                output: dict[str, Any] = {
                    "answer": reason_result.answer,
                    "activation_confidence": reason_result.confidence,
                    "answer_confidence": answer_confidence,
                    "q_scores": q_scores,
                    "stg_class": stg_class,
                    "embedding_model": self._get_active_embedding_model(),
                    "rounds": reason_result.rounds_completed,
                    "nodes_used": reason_result.node_count,
                    "cost_usd": round(reason_result.cost_usd, 4),
                    "active_nodes": reason_result.active_nodes[:10],
                    "prediction": {
                        "status": "INSUFFICIENT_GRAPH",
                        "nodes_added": 0,
                        "edges_added": 0,
                        "anchor_node_id": None,
                        "content_hash": None,
                        "subgraph": None,
                    },
                }
                return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 5: Build base output (always returned, even if no write-back) ===
        output = {
            "answer": reason_result.answer,
            "activation_confidence": reason_result.confidence,   # raw, preserved unchanged
            "answer_confidence": answer_confidence,               # calibrated, gates fold-back
            "q_scores": q_scores,
            "stg_class": stg_class,
            "embedding_model": self._get_active_embedding_model(),  # FB-003: detect model changes
            "rounds": reason_result.rounds_completed,
            "nodes_used": reason_result.node_count,
            "cost_usd": round(reason_result.cost_usd, 4),
            "active_nodes": reason_result.active_nodes[:10],
            "prediction": {
                "status": "DRY_RUN",
                "nodes_added": 0,
                "edges_added": 0,
                "anchor_node_id": None,
                "content_hash": None,
                "subgraph": None,
            },
        }

        # === STEP 6: Confidence gate — uses answer_confidence, NOT activation_confidence ===
        if answer_confidence < confidence_threshold:
            output["prediction"]["status"] = "SKIPPED_LOW_CONFIDENCE"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 7: Dry-run gate — skip LLM generation if not writing back ===
        if not fold_back:
            output["prediction"]["status"] = "DRY_RUN"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 8: Generate predicted subgraph from reasoning output ===
        try:
            predicted_subgraph = await self._generate_predicted_subgraph(
                query=query,
                reason_result=reason_result,
            )
        except Exception as e:
            logger.warning(f"graq_predict: subgraph generation failed: {e}")
            output["prediction"]["status"] = "SKIPPED_GENERATION_ERROR"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 9: Content hash — deduplication ===
        content_hash = _compute_content_hash(predicted_subgraph)
        output["prediction"]["content_hash"] = content_hash

        if self._subgraph_is_duplicate(content_hash, predicted_subgraph, similarity_threshold):
            output["prediction"]["status"] = "SKIPPED_DUPLICATE"
            output["prediction"]["subgraph"] = predicted_subgraph
            return MCPToolResult(json.dumps(output, indent=2))

        output["prediction"]["subgraph"] = predicted_subgraph

        # === STEP 10: Write subgraph to graph (atomic) ===
        try:
            anchor_id, nodes_added, edges_added = self._write_subgraph(
                predicted_subgraph, content_hash
            )
            output["prediction"]["status"] = "WRITTEN"
            output["prediction"]["anchor_node_id"] = anchor_id
            output["prediction"]["nodes_added"] = nodes_added
            output["prediction"]["edges_added"] = edges_added
        except Exception as e:
            logger.error(f"graq_predict: write-back failed: {e}")
            output["prediction"]["status"] = "WRITE_FAILED"

        return MCPToolResult(json.dumps(output, indent=2))

    async def _handle_gate_mode(
        self,
        query: str,
        max_rounds: int,
        gate_threshold: float,
    ) -> MCPToolResult:
        """Gate mode: read-only risk assessment. Never writes to graph.

        Returns gate_status in {CLEAR, WARN, FLAG, INSUFFICIENT_GRAPH}
        and a list of risk_vectors (plain text descriptions).

        Gate status logic:
        - INSUFFICIENT_GRAPH: fewer than 10 nodes activated
        - CLEAR: answer_confidence below gate_threshold
        - WARN: answer_confidence >= gate_threshold, non-critical risk signals
        - FLAG: answer_confidence >= gate_threshold, critical risk signals
        """
        reason_result = await self._graph.areason(
            query, max_rounds=max_rounds, task_type="predict",
        )
        answer_confidence = self._compute_answer_confidence(reason_result)
        nodes_activated = len(reason_result.active_nodes)

        if nodes_activated < 10:
            gate_status = "INSUFFICIENT_GRAPH"
            risk_vectors: list[str] = []
        elif answer_confidence < gate_threshold:
            gate_status = "CLEAR"
            risk_vectors = []
        else:
            # Extract risk signals from answer text
            risk_vectors = self._extract_risk_vectors(reason_result.answer)
            critical_keywords = {
                "critical", "breaking", "remove", "delete", "drop", "fail",
                "security", "vulnerability", "breach", "corrupt", "data loss",
            }
            answer_lower = reason_result.answer.lower()
            has_critical = any(kw in answer_lower for kw in critical_keywords)
            gate_status = "FLAG" if has_critical else "WARN"

        output = {
            "gate_status": gate_status,
            "answer_confidence": answer_confidence,
            "nodes_activated": nodes_activated,
            "risk_vectors": risk_vectors,
            "answer": reason_result.answer,
            "rounds": reason_result.rounds_completed,
            "cost_usd": round(reason_result.cost_usd, 4),
            "mode": "gate",
        }
        return MCPToolResult(json.dumps(output, indent=2))

    async def _handle_cascade_mode(
        self,
        query: str,
        max_rounds: int,
        fold_back: bool,
        confidence_threshold: float,
        similarity_threshold: float,
    ) -> MCPToolResult:
        """Cascade analysis mode: map failure cascade chains.

        Maps: root cause → tier-1 impacts → tier-2 impacts → terminal effects.
        When fold_back=True and confidence is sufficient, writes the cascade
        graph to the KG using CASCADE_TRIGGER edge type.
        """
        reason_result = await self._graph.areason(
            query, max_rounds=max_rounds, task_type="predict",
        )
        answer_confidence = self._compute_answer_confidence(reason_result)
        q_scores = self._compute_q_scores(reason_result, answer_confidence)

        # Build cascade chain from reasoning output
        cascade_chain = self._extract_cascade_chain(reason_result.answer)
        tier_impacts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for item in cascade_chain:
            sev = item.get("severity", "LOW")
            if sev in tier_impacts:
                tier_impacts[sev] += 1

        output: dict[str, Any] = {
            "answer": reason_result.answer,
            "activation_confidence": reason_result.confidence,
            "answer_confidence": answer_confidence,
            "q_scores": q_scores,
            "mode": "cascade_analysis",
            "cascade_chain": cascade_chain,
            "tier_impacts": tier_impacts,
            "regulation_refs": self._extract_regulation_refs(reason_result.answer),
            "embedding_model": self._get_active_embedding_model(),
            "rounds": reason_result.rounds_completed,
            "nodes_used": reason_result.node_count,
            "cost_usd": round(reason_result.cost_usd, 4),
            "prediction": {
                "status": "DRY_RUN",
                "nodes_added": 0,
                "edges_added": 0,
                "anchor_node_id": None,
                "content_hash": None,
            },
        }

        if not fold_back or answer_confidence < confidence_threshold:
            if answer_confidence < confidence_threshold:
                output["prediction"]["status"] = "SKIPPED_LOW_CONFIDENCE"
            return MCPToolResult(json.dumps(output, indent=2))

        # Write cascade subgraph with CASCADE_TRIGGER edges
        try:
            cascade_subgraph = self._build_cascade_subgraph(query, cascade_chain, reason_result)
            content_hash = _compute_content_hash(cascade_subgraph)
            if not self._subgraph_is_duplicate(content_hash, cascade_subgraph, similarity_threshold):
                anchor_id, nodes_added, edges_added = self._write_subgraph(
                    cascade_subgraph, content_hash
                )
                output["prediction"]["status"] = "WRITTEN"
                output["prediction"]["anchor_node_id"] = anchor_id
                output["prediction"]["nodes_added"] = nodes_added
                output["prediction"]["edges_added"] = edges_added
                output["prediction"]["content_hash"] = content_hash
            else:
                output["prediction"]["status"] = "SKIPPED_DUPLICATE"
        except Exception as e:
            logger.error(f"graq_predict cascade: write-back failed: {e}")
            output["prediction"]["status"] = "WRITE_FAILED"

        return MCPToolResult(json.dumps(output, indent=2))

    def _compute_q_scores(self, reason_result: Any, answer_confidence: float) -> dict[str, float]:
        """Compute Q-function quality dimensions for a prediction.

        Returns three opaque scores in [0.0, 1.0]:
        - feasibility: structural admissibility of the prediction
        - novelty: distance from existing graph structure
        - goal_alignment: consistency with domain ontology

        These are independent quality dimensions. Callers can filter by
        dimension. Higher is better on all three. Scores are opaque —
        do not document or expose how they are computed internally.
        """
        # Feasibility: derived from activation breadth and answer confidence
        activation = getattr(reason_result, "confidence", 0.0)
        node_count = getattr(reason_result, "node_count", 0)
        feasibility = round(min(1.0, (answer_confidence * 0.6) + (min(node_count, 20) / 20 * 0.4)), 3)

        # Novelty: inverse of semantic overlap with activated nodes
        # (more active nodes from existing graph = lower novelty)
        novelty = round(max(0.0, 1.0 - (min(node_count, 50) / 50 * 0.5) - (activation * 0.2)), 3)

        # Goal alignment: blended from answer confidence and activation quality
        goal_alignment = round(min(1.0, answer_confidence * 0.7 + activation * 0.3), 3)

        return {
            "feasibility": feasibility,
            "novelty": novelty,
            "goal_alignment": goal_alignment,
        }

    def _count_domain_intersection_nodes(self, reason_result: Any) -> int:
        """Count nodes in the domain intersection for Class IV validation.

        Class IV requires >= 50 nodes in the domain intersection of the
        active subgraph. This checks the activated partition, not the
        full graph size.
        """
        active_nodes = getattr(reason_result, "active_nodes", [])
        # Count activated nodes that have meaningful entity types (not padding)
        domain_nodes = 0
        for nid in active_nodes:
            node = self._graph.nodes.get(nid)
            if node and node.entity_type not in ("Entity", "pse_predict"):
                domain_nodes += 1
        return domain_nodes

    def _extract_risk_vectors(self, answer: str) -> list[str]:
        """Extract risk signal sentences from a reasoning answer."""
        risk_keywords = {
            "risk", "fail", "break", "error", "crash", "timeout", "security",
            "vulnerability", "corrupt", "loss", "missing", "deprecated",
        }
        sentences = [s.strip() for s in answer.replace("\n", ". ").split(". ") if s.strip()]
        vectors = []
        for sentence in sentences:
            if any(kw in sentence.lower() for kw in risk_keywords):
                vectors.append(sentence[:200])
            if len(vectors) >= 5:
                break
        return vectors

    def _extract_cascade_chain(self, answer: str) -> list[dict]:
        """Extract a tiered cascade chain from a reasoning answer.

        Returns a list of cascade items with tier, label, impact, and severity.
        This is a heuristic extraction — the LLM answer is the source of truth.
        """
        lines = [l.strip() for l in answer.split("\n") if l.strip()]
        chain = []
        tier = 1
        severity_map = {"critical": "HIGH", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

        for line in lines[:20]:  # cap at 20 lines
            lower = line.lower()
            # Detect severity hint
            severity = "MEDIUM"
            for kw, sev in severity_map.items():
                if kw in lower:
                    severity = sev
                    break

            # Lines that look like cause/effect statements
            if any(marker in lower for marker in [
                "cause", "lead", "result", "trigger", "affect", "impact",
                "→", "->", "because", "therefore", "thus",
            ]):
                chain.append({
                    "tier": min(tier, 3),
                    "label": line[:120],
                    "impact": f"Downstream effect at tier {tier}",
                    "severity": severity,
                })
                tier += 1
                if tier > 3:
                    tier = 3

        return chain

    def _extract_regulation_refs(self, answer: str) -> list[str]:
        """Extract EU AI Act or other regulation references from answer."""
        import re
        refs = []
        # EU AI Act articles
        for m in re.finditer(r"(?:EU AI Act |Article |Art\. ?)\s*(\d+)", answer, re.IGNORECASE):
            refs.append(f"EU AI Act Article {m.group(1)}")
        # GDPR references
        for m in re.finditer(r"GDPR\s+(?:Article\s+)?(\d+)", answer, re.IGNORECASE):
            refs.append(f"GDPR Article {m.group(1)}")
        return list(dict.fromkeys(refs))[:10]  # deduplicate, cap at 10

    def _build_cascade_subgraph(
        self,
        query: str,
        cascade_chain: list[dict],
        reason_result: Any,
    ) -> dict:
        """Build a cascade subgraph dict suitable for _write_subgraph.

        Uses CASCADE_TRIGGER edge type for cascade relationships.
        """
        anchor_label = f"cascade: {query[:60]}"
        supporting = []
        edges = []

        prev_label = anchor_label
        for item in cascade_chain[:4]:  # max 4 tiers
            label = item.get("label", "")[:80]
            if not label:
                continue
            supporting.append({
                "label": label,
                "type": "pse_predict",
                "description": item.get("impact", ""),
                "relationship_to_anchor": "CASCADE_TRIGGER",
            })
            edges.append({
                "from_label": prev_label,
                "to_label": label,
                "relationship": "CASCADE_TRIGGER",
                "weight": 0.8 if item.get("severity") == "HIGH" else 0.6,
            })
            prev_label = label

        return {
            "anchor_label": anchor_label,
            "anchor_type": "pse_predict",
            "anchor_description": f"Failure cascade analysis for: {query[:100]}",
            "anchor_properties": {
                "source_query": query[:100],
                "derived_from": "graq_predict",
                "confidence": getattr(reason_result, "confidence", 0.0),
                "cascade_tiers": len(cascade_chain),
            },
            "supporting_nodes": supporting,
            "causal_edges": edges,
        }

    def _compute_answer_confidence(self, reason_result: Any) -> float:
        """Compute answer-quality confidence from cross-node agreement.

        Separate from ReasoningResult.confidence (raw activation-based score).
        Uses the message_trace already in the result — zero extra LLM calls.

        Measures cross-node message convergence and blends with activation
        confidence to produce an opaque score in [0.0, 1.0].
        """
        trace = getattr(reason_result, "message_trace", []) or []

        if not trace:
            # No trace — fall back to monotonic rescale of activation score
            raw = getattr(reason_result, "confidence", 0.0)
            return round(min(1.0, raw * 2.0 + 0.20), 3)

        # Extract final-round content per node (last message per source wins)
        final: dict[str, str] = {}
        for msg in trace:
            if isinstance(msg, dict):
                src = (msg.get("source_node_id") or
                       msg.get("sender") or
                       msg.get("source") or "")
                content = msg.get("content", "")
            else:
                # Message object
                src = (getattr(msg, "source_node_id", None) or
                       getattr(msg, "sender", None) or
                       getattr(msg, "source", None) or "")
                content = getattr(msg, "content", "")
            if src and content:
                final[src] = content  # last-write-wins = final round

        if len(final) < 2:
            raw = getattr(reason_result, "confidence", 0.0)
            return round(min(1.0, raw * 2.0 + 0.20), 3)

        # Pairwise Jaccard token overlap
        node_ids = list(final.keys())
        token_sets = {nid: set(final[nid].lower().split()) for nid in node_ids}

        pairs_total = 0
        pairs_agreed = 0
        AGREEMENT_THRESHOLD = float(os.environ.get("GRAQLE_AGREEMENT_THRESHOLD", "1.0"))

        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                a = token_sets[node_ids[i]]
                b = token_sets[node_ids[j]]
                union_size = len(a | b)
                if union_size == 0:
                    continue
                jaccard = len(a & b) / union_size
                pairs_total += 1
                if jaccard >= AGREEMENT_THRESHOLD:
                    pairs_agreed += 1

        if pairs_total == 0:
            raw = getattr(reason_result, "confidence", 0.0)
            return round(min(1.0, raw * 2.0 + 0.20), 3)

        agreement_ratio = pairs_agreed / pairs_total
        raw_activation = getattr(reason_result, "confidence", 0.0)

        blended = (0.70 * agreement_ratio) + (0.30 * min(1.0, raw_activation * 2.5))

        # Floor boosts for strong multi-node consensus
        n_nodes = len(final)
        if n_nodes >= 10 and agreement_ratio >= 0.5:
            blended = max(blended, 0.60)
        elif n_nodes >= 5 and agreement_ratio >= 0.4:
            blended = max(blended, 0.50)

        return round(min(1.0, blended), 3)

    def _get_entity_type_vocabulary(self) -> list[str]:
        """Return top entity types from the graph, sorted by frequency.

        Used to constrain predicted subgraph node types to the existing
        graph vocabulary — ensures predicted nodes are activation-visible.
        """
        type_counts: dict[str, int] = {}
        for node in self._graph.nodes.values():
            t = node.entity_type
            type_counts[t] = type_counts.get(t, 0) + 1
        # Top 10 by frequency; always include pse_predict as the fallback anchor type
        top_types = [t for t, _ in sorted(type_counts.items(), key=lambda x: -x[1])[:10]]
        if "pse_predict" not in top_types:
            top_types.append("pse_predict")
        return top_types

    async def _generate_predicted_subgraph(
        self,
        query: str,
        reason_result: Any,
    ) -> dict:
        """Generate a predicted subgraph from reasoning output.

        Makes ONE additional LLM call to structure the compound insight
        from graq_reason into a graph-native format: typed nodes + typed edges.

        Node types are constrained to the existing graph vocabulary so that
        predicted nodes are activation-visible to future PCST queries.

        Returns dict with 'nodes' and 'edges' lists.
        """
        # Collect context from activated nodes
        active_context_parts = []
        for nid in reason_result.active_nodes[:15]:
            node = self._graph.nodes.get(nid)
            if node:
                active_context_parts.append(
                    f"- {node.label} ({node.entity_type}): {node.description[:150]}"
                )
        active_context = "\n".join(active_context_parts)

        # Constrain types to the graph's vocabulary
        entity_types = self._get_entity_type_vocabulary()
        entity_type_list = ", ".join(entity_types)

        prediction_prompt = f"""You are a knowledge graph architect.

REASONING RESULT:
Query: {query}
Answer: {reason_result.answer}
Confidence: {reason_result.confidence:.0%}
Active nodes: {', '.join(reason_result.active_nodes[:10])}

ACTIVE NODE CONTEXT:
{active_context}

AVAILABLE ENTITY TYPES (use ONLY these — do not invent new types):
{entity_type_list}
Use "pse_predict" for compound-concept anchor nodes that don't fit any existing type.

TASK:
Extract the compound insight from the reasoning answer as a structured subgraph.
The subgraph must represent ONLY facts stated in the answer above — do not invent.

Output ONLY valid JSON in this exact format:
{{
  "anchor_label": "short compound concept name (3-6 words)",
  "anchor_type": "one of: {entity_type_list}",
  "anchor_description": "one sentence summary of the compound insight",
  "anchor_properties": {{
    "source_query": "{query[:100]}",
    "derived_from": "graq_predict",
    "confidence": {reason_result.confidence:.3f}
  }},
  "supporting_nodes": [
    {{
      "label": "node label",
      "type": "one of: {entity_type_list}",
      "description": "one sentence",
      "relationship_to_anchor": "CONTRIBUTES_TO | CAUSES | PREVENTS | MITIGATES"
    }}
  ],
  "causal_edges": [
    {{
      "from_label": "source node label",
      "to_label": "target node label",
      "relationship": "CAUSES | CONTRIBUTES_TO | MITIGATES | PREVENTS | REQUIRES",
      "weight": 0.8
    }}
  ]
}}

Rules:
- anchor_label: the new compound concept that did not exist before
- anchor_type: MUST be one of the AVAILABLE ENTITY TYPES listed above
- supporting_nodes: 1-4 nodes max (the causal chain, not every active node)
- supporting_nodes type: MUST be one of the AVAILABLE ENTITY TYPES listed above
- causal_edges: connect the chain (include anchor to each supporting node)
- weight: 0.5-1.0 based on confidence in the causal link
- NO invented facts — every claim must appear in the answer above"""

        # Fix FB-004: use task-based routing — node.backend is None after areason() deactivates nodes.
        # _get_backend_for_node() uses 3-tier routing (node-specific → default → auto-create).
        # It never returns None silently; raises RuntimeError on complete failure.
        if not reason_result.active_nodes:
            raise RuntimeError("graq_predict: no active nodes to derive backend from")
        backend = self._graph._get_backend_for_node(
            reason_result.active_nodes[0], task_type="predict"
        )

        raw = await backend.generate(prediction_prompt, max_tokens=1024, temperature=0.1)

        # Fix FB-005: use brace-counting extraction — re.search(r"\{.*\}") raises on LLM
        # output that contains regex metacharacters (e.g. '[', '(', '*' in string values).
        return json.loads(_extract_json_from_llm(raw))

    def _subgraph_is_duplicate(
        self,
        content_hash: str,
        predicted_subgraph: dict,
        similarity_threshold: float,
    ) -> bool:
        """Check if predicted subgraph already exists in the graph.

        Two-stage check:
        1. Exact hash match (O(n) scan of node properties)
        2. Semantic similarity of anchor label (embedding cosine distance)

        Returns True if duplicate detected (should skip write-back).
        """
        anchor_label = predicted_subgraph.get("anchor_label", "")

        # Stage 1: Exact hash match
        for node in self._graph.nodes.values():
            existing_hash = node.properties.get("pse_content_hash")
            if existing_hash == content_hash:
                logger.info(f"graq_predict: exact hash duplicate found: {node.id}")
                return True

        # Stage 2: Semantic similarity of anchor label
        if anchor_label and self._embedder is not None:
            try:
                anchor_vec = self._embedder.embed(anchor_label)
                for node in self._graph.nodes.values():
                    if node.properties.get("derived_from") != "graq_predict":
                        continue  # Only compare against previous predictions
                    node_vec = self._embedder.embed(node.label)
                    sim = float(
                        anchor_vec @ node_vec
                        / max(
                            1e-8,
                            float(
                                (anchor_vec @ anchor_vec) ** 0.5
                                * (node_vec @ node_vec) ** 0.5
                            ),
                        )
                    )
                    distance = 1.0 - sim
                    if distance < similarity_threshold:
                        logger.info(
                            f"graq_predict: semantic duplicate found: "
                            f"'{anchor_label}' ≈ '{node.label}' (distance={distance:.3f})"
                        )
                        return True
            except Exception as e:
                logger.warning(f"graq_predict: similarity check failed: {e}")

        return False

    def _write_subgraph(
        self,
        predicted_subgraph: dict,
        content_hash: str,
    ) -> tuple[str, int, int]:
        """Write predicted subgraph into the in-memory graph and persist to disk.

        Returns: (anchor_node_id, nodes_added, edges_added)

        Uses Graqle.to_json() for atomic persistence — same path used by
        all other write operations in the SDK.
        """
        from graqle.core.edge import CogniEdge
        from graqle.core.node import CogniNode

        # Safety guard: refuse to write to a graph with suspiciously few nodes
        # (prevents accidental writes from test mocks or unloaded graphs)
        if len(self._graph.nodes) < 10:
            raise RuntimeError(
                f"graq_predict: refusing write-back — graph has only "
                f"{len(self._graph.nodes)} nodes (expected a real loaded graph)"
            )

        anchor_label = predicted_subgraph.get("anchor_label", "pse-prediction")
        anchor_type = predicted_subgraph.get("anchor_type", "pse_predict")
        anchor_description = predicted_subgraph.get("anchor_description", "")

        # Validate anchor_type against graph vocabulary — reject unknown types
        allowed_types = self._get_entity_type_vocabulary()
        if anchor_type not in allowed_types:
            logger.warning(
                f"graq_predict: anchor_type '{anchor_type}' not in graph vocabulary "
                f"{allowed_types[:5]}... — defaulting to 'pse_predict'"
            )
            anchor_type = "pse_predict"
        anchor_properties = predicted_subgraph.get("anchor_properties", {})
        supporting_nodes = predicted_subgraph.get("supporting_nodes", [])
        causal_edges = predicted_subgraph.get("causal_edges", [])

        nodes_added = 0
        edges_added = 0

        # Build stable anchor ID from content hash (deterministic, not random)
        anchor_id = f"pse-pred-{content_hash[:12]}"

        # Safety: skip if anchor already exists (should have been caught by dedup)
        if anchor_id in self._graph.nodes:
            return anchor_id, 0, 0

        # --- Create anchor node ---
        anchor_props = {
            **anchor_properties,
            "pse_content_hash": content_hash,
            "derived_from": "graq_predict",
            "pse_version": "1.0",
        }

        anchor_node = CogniNode(
            id=anchor_id,
            label=anchor_label,
            entity_type=anchor_type,
            description=anchor_description,
            properties=anchor_props,
        )
        self._graph.nodes[anchor_id] = anchor_node
        nodes_added += 1

        # --- Create supporting nodes and register them ---
        label_to_id: dict[str, str] = {anchor_label: anchor_id}

        for sn in supporting_nodes:
            sn_label = sn.get("label", "")
            if not sn_label:
                continue

            # Reuse existing node with matching label rather than duplicating
            existing_id = None
            for nid, node in self._graph.nodes.items():
                if node.label.lower() == sn_label.lower():
                    existing_id = nid
                    break

            if existing_id:
                label_to_id[sn_label] = existing_id
            else:
                sn_id = f"pse-sup-{content_hash[:8]}-{uuid.uuid4().hex[:6]}"
                sn_node = CogniNode(
                    id=sn_id,
                    label=sn_label,
                    entity_type=sn.get("type", "KNOWLEDGE"),
                    description=sn.get("description", ""),
                    properties={
                        "derived_from": "graq_predict",
                        "pse_content_hash": content_hash,
                    },
                )
                self._graph.nodes[sn_id] = sn_node
                label_to_id[sn_label] = sn_id
                nodes_added += 1

        # --- Create causal edges ---
        for ce in causal_edges:
            from_label = ce.get("from_label", "")
            to_label = ce.get("to_label", "")
            relationship = ce.get("relationship", "CONTRIBUTES_TO")
            weight = float(ce.get("weight", 0.8))

            from_id = label_to_id.get(from_label)
            to_id = label_to_id.get(to_label)

            if not from_id or not to_id:
                continue  # Skip edges where nodes couldn't be resolved

            # Check if edge already exists (either direction)
            edge_exists = any(
                (e.source_id == from_id and e.target_id == to_id)
                or (e.source_id == to_id and e.target_id == from_id)
                for e in self._graph.edges.values()
            )
            if edge_exists:
                continue

            edge_id = f"pse-edge-{uuid.uuid4().hex[:12]}"
            new_edge = CogniEdge(
                id=edge_id,
                source_id=from_id,
                target_id=to_id,
                relationship=relationship,
                weight=weight,
                properties={"derived_from": "graq_predict"},
            )
            self._graph.edges[edge_id] = new_edge

            # Register edge IDs on the anchor node
            if from_id == anchor_id:
                self._graph.nodes[anchor_id].outgoing_edges.append(edge_id)
            if to_id == anchor_id:
                self._graph.nodes[anchor_id].incoming_edges.append(edge_id)

            edges_added += 1

        # --- Persist atomically using Graqle.to_json() ---
        graph_path = self._config.graph_path
        self._graph.to_json(graph_path)

        logger.info(
            f"graq_predict: wrote subgraph — anchor={anchor_id}, "
            f"{nodes_added} nodes, {edges_added} edges"
        )

        return anchor_id, nodes_added, edges_added
