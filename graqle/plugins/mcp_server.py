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
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.plugins.mcp")


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
            {
                "name": "graq_predict",
                "description": (
                    "Run governed reasoning over the knowledge graph and — if confidence "
                    "is sufficient — write the compound prediction as a new subgraph into "
                    "the graph permanently. Future similar queries activate the predicted "
                    "subgraph directly without re-reasoning. "
                    "Use for compound pattern detection, sub-threshold signal analysis, "
                    "and latent failure chain discovery."
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
                            "description": "Maximum message-passing rounds (passed to graq_reason)"
                        },
                        "fold_back": {
                            "type": "boolean",
                            "default": True,
                            "description": "If false: reasons but does NOT write to graph (dry-run)"
                        },
                        "confidence_threshold": {
                            "type": "number",
                            "default": 0.45,
                            "description": "Minimum answer_confidence to trigger write-back (0.0-1.0). Uses cross-node agreement score, not raw activation confidence."
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

    # ------------------------------------------------------------------
    # graq_predict — Layer A: governed reasoning + fold-back write
    # ------------------------------------------------------------------

    async def _handle_predict(self, args: dict) -> MCPToolResult:
        """Run graq_reason then optionally write predicted subgraph to graph."""
        self._ensure_graph()
        self._ensure_embedder()

        query = args.get("query", "")
        max_rounds = args.get("max_rounds", 3)
        fold_back = args.get("fold_back", True)
        confidence_threshold = args.get("confidence_threshold", 0.45)
        similarity_threshold = args.get("similarity_threshold", 0.15)

        if not query:
            return MCPToolResult("Query is required", is_error=True)

        # === STEP 1: Run graq_reason UNMODIFIED ===
        reason_result = await self._graph.areason(
            query, max_rounds=max_rounds, task_type="predict",
        )

        # === STEP 2: Compute answer_confidence from cross-node agreement ===
        # This is SEPARATE from reason_result.confidence (raw activation score).
        # answer_confidence measures answer quality, not activation relevance.
        answer_confidence = self._compute_answer_confidence(reason_result)

        # === STEP 3: Build base output (always returned, even if no write-back) ===
        output: dict[str, Any] = {
            "answer": reason_result.answer,
            "activation_confidence": reason_result.confidence,   # raw, preserved unchanged
            "answer_confidence": answer_confidence,               # calibrated, gates fold-back
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

        # === STEP 4: Confidence gate — uses answer_confidence, NOT activation_confidence ===
        if answer_confidence < confidence_threshold:
            output["prediction"]["status"] = "SKIPPED_LOW_CONFIDENCE"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 5: Dry-run gate — skip LLM generation if not writing back ===
        if not fold_back:
            output["prediction"]["status"] = "DRY_RUN"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 6: Generate predicted subgraph from reasoning output ===
        try:
            predicted_subgraph = await self._generate_predicted_subgraph(
                query=query,
                reason_result=reason_result,
            )
        except Exception as e:
            logger.warning(f"graq_predict: subgraph generation failed: {e}")
            output["prediction"]["status"] = "SKIPPED_GENERATION_ERROR"
            return MCPToolResult(json.dumps(output, indent=2))

        # === STEP 7: Content hash — deduplication ===
        content_hash = _compute_content_hash(predicted_subgraph)
        output["prediction"]["content_hash"] = content_hash

        if self._subgraph_is_duplicate(content_hash, predicted_subgraph, similarity_threshold):
            output["prediction"]["status"] = "SKIPPED_DUPLICATE"
            output["prediction"]["subgraph"] = predicted_subgraph
            return MCPToolResult(json.dumps(output, indent=2))

        output["prediction"]["subgraph"] = predicted_subgraph

        # === STEP 8: Write subgraph to graph (atomic) ===
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

    def _compute_answer_confidence(self, reason_result: Any) -> float:
        """Compute answer-quality confidence from cross-node agreement.

        Separate from ReasoningResult.confidence (raw activation-based score).
        Uses the message_trace already in the result — zero extra LLM calls.

        Agreement = fraction of node-pairs whose final-round messages share
        >= 12% Jaccard token overlap (soft agreement threshold).
        High-quality answer = many nodes converged on similar content.

        Blends cross-node agreement with activation confidence.
        Returns float in [0.0, 1.0].
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
        AGREEMENT_THRESHOLD = 0.15  # 15% token overlap = rough agreement (raised from 0.12 in v0.35.0 — 0.12 over-counted boilerplate text as agreement)

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

        # Use the first available backend from activated nodes
        backend = None
        for nid in reason_result.active_nodes:
            node = self._graph.nodes.get(nid)
            if node and node.backend:
                backend = node.backend
                break

        if backend is None:
            raise RuntimeError("No backend available for subgraph generation")

        raw = await backend.generate(prediction_prompt, max_tokens=1024, temperature=0.1)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in prediction response: {raw[:200]}")

        return json.loads(json_match.group())

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
