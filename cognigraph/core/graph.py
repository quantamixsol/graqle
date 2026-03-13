"""CogniGraph — the reasoning graph where every node is an agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import networkx as nx

from cognigraph.config.settings import CogniGraphConfig
from cognigraph.core.edge import CogniEdge
from cognigraph.core.message import Message
from cognigraph.core.node import CogniNode
from cognigraph.core.state import NodeState
from cognigraph.core.types import (
    GraphStats,
    ModelBackend,
    NodeConfig,
    NodeStatus,
    ReasoningResult,
)

logger = logging.getLogger("cognigraph")


class CogniGraph:
    """The reasoning graph — a knowledge graph where every node is an agent.

    CogniGraph is the primary entry point for the SDK. It wraps a
    knowledge graph (from NetworkX, Neo4j, or other sources) and
    provides reasoning capabilities through distributed model agents.
    """

    def __init__(
        self,
        nodes: dict[str, CogniNode] | None = None,
        edges: dict[str, CogniEdge] | None = None,
        config: CogniGraphConfig | None = None,
    ) -> None:
        self.nodes: dict[str, CogniNode] = nodes or {}
        self.edges: dict[str, CogniEdge] = edges or {}
        self.config = config or CogniGraphConfig.default()
        self._default_backend: ModelBackend | None = None
        self._node_backends: dict[str, ModelBackend] = {}
        self._orchestrator: Any = None  # set lazily
        self._activator: Any = None  # set lazily
        self._reformulator: Any = None  # set lazily (ADR-104)
        self._activation_memory: Any = None  # v0.12: cross-query learning
        self._neo4j_connector: Any = None  # set by from_neo4j / to_neo4j
        self._nx_graph: nx.Graph | None = None

        # Mandatory quality gate: enrich + enforce descriptions + auto-chunk
        if self.nodes:
            self._auto_enrich_descriptions()
            self._auto_load_chunks()
            self._enforce_no_empty_descriptions()

    # --- Construction ---

    @classmethod
    def from_networkx(
        cls,
        G: nx.Graph,
        config: CogniGraphConfig | None = None,
        node_label_key: str = "label",
        node_type_key: str = "type",
        node_desc_key: str = "description",
        edge_rel_key: str = "relationship",
    ) -> CogniGraph:
        """Create a CogniGraph from a NetworkX graph."""
        nodes: dict[str, CogniNode] = {}
        edges: dict[str, CogniEdge] = {}

        # Build nodes
        for node_id, data in G.nodes(data=True):
            nid = str(node_id)
            props = {k: v for k, v in data.items()
                     if k not in (node_label_key, node_type_key, node_desc_key)}
            nodes[nid] = CogniNode(
                id=nid,
                label=data.get(node_label_key, nid),
                entity_type=data.get(node_type_key, "Entity"),
                description=data.get(node_desc_key, ""),
                properties=props,
            )

        # Build edges
        for i, (src, tgt, data) in enumerate(G.edges(data=True)):
            src_id, tgt_id = str(src), str(tgt)
            edge_id = f"e_{src_id}_{tgt_id}_{i}"
            rel = data.get(edge_rel_key, "RELATED_TO")
            weight = data.get("weight", 1.0)
            props = {k: v for k, v in data.items()
                     if k not in (edge_rel_key, "weight")}
            edge = CogniEdge(
                id=edge_id,
                source_id=src_id,
                target_id=tgt_id,
                relationship=rel,
                weight=weight,
                properties=props,
            )
            edges[edge_id] = edge
            nodes[src_id].outgoing_edges.append(edge_id)
            nodes[tgt_id].incoming_edges.append(edge_id)

        graph = cls(nodes=nodes, edges=edges, config=config)
        graph._nx_graph = G
        return graph

    @classmethod
    def from_json(
        cls, path: str, config: CogniGraphConfig | str | None = None
    ) -> CogniGraph:
        """Create a CogniGraph from a JSON file.

        Parameters
        ----------
        path:
            Path to the JSON graph file.
        config:
            A ``CogniGraphConfig`` instance, a path to a YAML config file
            (string), or ``None`` for defaults.
        """
        import json
        from pathlib import Path as _Path

        # Bug 4 fix: handle string config path automatically
        if isinstance(config, str):
            config_path = _Path(config)
            if config_path.exists():
                config = CogniGraphConfig.from_yaml(config)
            else:
                logger.warning("Config file not found: %s — using defaults", config)
                config = None

        data = json.loads(_Path(path).read_text(encoding="utf-8"))
        # Bug 12 fix: pass edges= explicitly to suppress NetworkX FutureWarning
        G = nx.node_link_graph(data, edges="links")
        return cls.from_networkx(G, config=config)

    @classmethod
    def from_neo4j(
        cls,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
        config: CogniGraphConfig | None = None,
    ) -> CogniGraph:
        """Create a CogniGraph from a Neo4j database.

        Loads nodes and edges via Cypher, attaches chunks as node properties,
        and stores the connector for runtime Cypher vector search.
        """
        from cognigraph.connectors.neo4j import Neo4jConnector

        cfg = config or CogniGraphConfig.default()
        connector = Neo4jConnector(
            uri=uri,
            username=username,
            password=password,
            database=database,
            vector_index_name=cfg.graph.vector_index_name,
            embedding_dimension=cfg.graph.embedding_dimension,
        )

        # Load graph structure
        raw_nodes, raw_edges = connector.load()

        # Build CogniNodes
        nodes: dict[str, CogniNode] = {}
        for nid, data in raw_nodes.items():
            nodes[nid] = CogniNode(
                id=nid,
                label=data.get("label", nid),
                entity_type=data.get("type", "Entity"),
                description=data.get("description", ""),
                properties=data.get("properties", {}),
            )

        # Build CogniEdges
        edges: dict[str, CogniEdge] = {}
        for eid, data in raw_edges.items():
            src = str(data["source"])
            tgt = str(data["target"])
            if src not in nodes or tgt not in nodes:
                continue
            edge = CogniEdge(
                id=eid,
                source_id=src,
                target_id=tgt,
                relationship=data.get("relationship", "RELATED_TO"),
                weight=data.get("weight", 1.0),
                properties=data.get("properties", {}),
            )
            edges[eid] = edge
            nodes[src].outgoing_edges.append(eid)
            nodes[tgt].incoming_edges.append(eid)

        # Load chunks and attach to node properties
        try:
            chunks_by_node = connector.load_chunks()
            for nid, chunks in chunks_by_node.items():
                if nid in nodes:
                    nodes[nid].properties["chunks"] = chunks
        except Exception as exc:
            logger.warning("Failed to load chunks from Neo4j: %s", exc)

        graph = cls(nodes=nodes, edges=edges, config=cfg)
        graph._neo4j_connector = connector
        return graph

    def to_neo4j(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
        embed_fn: Any | None = None,
    ) -> None:
        """Export current graph to Neo4j. Creates schema, writes nodes + chunks.

        Args:
            embed_fn: Optional callable(text) -> list[float] for chunk embeddings.
                      If None, chunks are written without embeddings.
        """
        from cognigraph.connectors.neo4j import Neo4jConnector

        connector = Neo4jConnector(
            uri=uri,
            username=username,
            password=password,
            database=database,
            vector_index_name=self.config.graph.vector_index_name,
            embedding_dimension=self.config.graph.embedding_dimension,
        )

        # Create schema (constraints + vector index)
        connector.create_schema()

        # Prepare node data
        raw_nodes: dict[str, Any] = {}
        for nid, node in self.nodes.items():
            raw_nodes[nid] = {
                "label": node.label,
                "type": node.entity_type,
                "description": node.description,
                "properties": node.properties,
            }

        # Prepare edge data
        raw_edges: dict[str, Any] = {}
        for eid, edge in self.edges.items():
            raw_edges[eid] = {
                "source": edge.source_id,
                "target": edge.target_id,
                "relationship": edge.relationship,
                "weight": edge.weight,
            }

        # Write nodes and edges
        connector.save(raw_nodes, raw_edges)

        # Write chunks with optional embeddings
        chunks_by_node: dict[str, list[dict]] = {}
        for nid, node in self.nodes.items():
            chunks = node.properties.get("chunks", [])
            if chunks:
                chunks_by_node[nid] = chunks

        if chunks_by_node:
            connector.save_chunks(chunks_by_node, embed_fn=embed_fn)

        logger.info(
            "Exported to Neo4j: %d nodes, %d edges, %d nodes with chunks",
            len(raw_nodes), len(raw_edges), len(chunks_by_node),
        )

        # Store connector for runtime use
        self._neo4j_connector = connector

    # --- Public chunk management ---

    def rebuild_chunks(self, force: bool = False) -> int:
        """Rebuild chunks for all nodes from their source files.

        Use this after ``kogni init`` or when source files have changed.
        By default only fills in missing chunks; set *force=True* to
        re-read even nodes that already have chunks.

        Returns the number of nodes updated.
        """
        from pathlib import Path as _P

        updated = 0
        for node in self.nodes.values():
            if not force and node.properties.get("chunks"):
                continue

            file_path = (
                node.properties.get("file_path")
                or node.properties.get("source_file")
            )
            if not file_path:
                continue

            try:
                fp = _P(file_path)
                if not fp.exists() or not fp.is_file():
                    continue
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if not content.strip():
                    continue

                suffix = fp.suffix.lower()
                if suffix in (".py", ".js", ".ts", ".tsx", ".jsx"):
                    chunks = self._chunk_source_code(content, max_chunks=5)
                else:
                    chunks = [{"text": content[:4000], "type": suffix.lstrip(".") or "text"}]

                if chunks:
                    node.properties["chunks"] = chunks
                    updated += 1
            except Exception:
                continue

        logger.info("rebuild_chunks: updated %d nodes (force=%s)", updated, force)
        return updated

    # --- Node Enrichment & Validation ---

    def _enforce_no_empty_descriptions(self) -> None:
        """Enforce that no node has an empty description after enrichment.

        This is a mandatory quality gate. Nodes without descriptions produce
        agents that cannot reason, leading to low-confidence garbage answers.
        After auto-enrichment, any remaining empty nodes are a data quality
        issue that must be fixed by the KG builder.

        Raises:
            ValueError: If any nodes still have empty descriptions after
                auto-enrichment, listing the offending node IDs.
        """
        empty_nodes = [
            nid for nid, node in self.nodes.items()
            if not (node.description or "").strip()
        ]

        if empty_nodes:
            sample = empty_nodes[:10]
            remaining = len(empty_nodes) - len(sample)
            msg = (
                f"KG Quality Error: {len(empty_nodes)}/{len(self.nodes)} nodes have "
                f"empty descriptions. Agents cannot reason without descriptions.\n"
                f"Empty nodes: {sample}"
            )
            if remaining > 0:
                msg += f"\n... and {remaining} more"
            msg += (
                "\n\nFix: Add 'description' fields to your KG nodes. "
                "Example: {\"id\": \"svc::auth\", \"description\": \"Authentication "
                "service handling JWT tokens and session management\", ...}"
            )
            raise ValueError(msg)

    def _auto_enrich_descriptions(self) -> None:
        """Auto-generate descriptions for nodes that have empty descriptions.

        When a KG is loaded with nodes that have metadata/properties but no
        descriptions, the agents have nothing to reason from. This method
        synthesizes a description from all available node data so every agent
        has context.
        """
        enriched = 0
        empty_count = 0

        for nid, node in self.nodes.items():
            if node.description and node.description.strip():
                continue

            empty_count += 1
            parts = []

            # Start with type and label
            if node.entity_type and node.entity_type != "Entity":
                parts.append(f"[{node.entity_type}]")
            if node.label and node.label != nid:
                parts.append(node.label)

            # Add all properties as key-value context
            if node.properties:
                for key, val in node.properties.items():
                    if key in ("id", "label", "type", "description"):
                        continue
                    val_str = str(val)
                    if len(val_str) > 500:
                        val_str = val_str[:500] + "..."
                    if val_str:
                        parts.append(f"{key}: {val_str}")

            # Add edge context (what this node connects to)
            neighbors_out = []
            for eid in node.outgoing_edges:
                if eid in self.edges:
                    e = self.edges[eid]
                    target = self.nodes.get(e.target_id)
                    if target:
                        neighbors_out.append(
                            f"{e.relationship} -> {target.label or target.id}"
                        )
            neighbors_in = []
            for eid in node.incoming_edges:
                if eid in self.edges:
                    e = self.edges[eid]
                    source = self.nodes.get(e.source_id)
                    if source:
                        neighbors_in.append(
                            f"{source.label or source.id} -> {e.relationship}"
                        )

            if neighbors_out:
                parts.append(
                    "Connects to: " + "; ".join(neighbors_out[:5])
                )
            if neighbors_in:
                parts.append(
                    "Connected from: " + "; ".join(neighbors_in[:5])
                )

            if parts:
                node.description = ". ".join(parts)
                enriched += 1

        if empty_count > 0:
            pct = (empty_count / len(self.nodes)) * 100
            if pct > 50:
                logger.warning(
                    f"KG Quality Warning: {empty_count}/{len(self.nodes)} nodes "
                    f"({pct:.0f}%) had empty descriptions. Auto-enriched {enriched} "
                    f"from metadata/properties. For better reasoning quality, add "
                    f"rich descriptions to your nodes. See: "
                    f"https://cognigraph.dev/docs/kg-quality"
                )
            elif empty_count > 0:
                logger.info(
                    f"Auto-enriched {enriched}/{empty_count} nodes with "
                    f"empty descriptions from metadata."
                )

    def _auto_load_chunks(self) -> None:
        """Auto-load chunks from source files for nodes that have none.

        When a KG node has a ``source_file`` (or ``file_path``) property
        pointing to a readable file but carries no ``chunks``, this method
        reads the file and creates chunks so that reasoning agents have
        evidence to cite.  This is the critical bridge between hand-built
        KGs (which often omit chunks) and the evidence pipeline that
        agents depend on.
        """
        from pathlib import Path as _P

        loaded = 0
        for node in self.nodes.values():
            # Skip nodes that already have chunks
            if node.properties.get("chunks"):
                continue

            # Find a file reference
            file_path = (
                node.properties.get("file_path")
                or node.properties.get("source_file")
            )
            if not file_path:
                continue

            try:
                fp = _P(file_path)
                if not fp.exists() or not fp.is_file():
                    continue
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if not content.strip():
                    continue

                # For source code files, try semantic chunking
                suffix = fp.suffix.lower()
                if suffix in (".py", ".js", ".ts", ".tsx", ".jsx"):
                    chunks = self._chunk_source_code(content, max_chunks=5)
                else:
                    # For markdown, config, etc. — single chunk, capped at 4000 chars
                    chunks = [{"text": content[:4000], "type": suffix.lstrip(".") or "text"}]

                if chunks:
                    node.properties["chunks"] = chunks
                    loaded += 1
            except Exception:
                continue

        if loaded:
            logger.info(
                "Auto-loaded chunks for %d/%d nodes from source files.",
                loaded, len(self.nodes),
            )

    @staticmethod
    def _chunk_source_code(content: str, max_chunks: int = 5) -> list[dict[str, str]]:
        """Split source code into semantic chunks at function/class boundaries.

        Returns a list of ``{"text": ..., "type": ...}`` dicts, capped at
        *max_chunks* to stay within token budgets.
        """
        import re as _re

        chunks: list[dict[str, str]] = []
        # Split on top-level definitions
        pattern = _re.compile(
            r"^((?:async\s+)?(?:def|class|function|export\s+(?:default\s+)?(?:function|class))\s+\w+)",
            _re.MULTILINE,
        )
        parts = pattern.split(content)

        # parts[0] = module header, then alternating (match, body)
        if parts[0].strip():
            header = parts[0].strip()[:1500]
            chunks.append({"text": header, "type": "module_header"})

        i = 1
        while i < len(parts) - 1 and len(chunks) < max_chunks:
            sig = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            block = (sig + body).strip()[:1500]
            if block:
                btype = "class" if "class " in sig else "function"
                chunks.append({"text": block, "type": btype})
            i += 2

        # If no splits found, treat as single chunk
        if not chunks and content.strip():
            chunks.append({"text": content[:3000], "type": "source"})

        return chunks[:max_chunks]

    def validate(self) -> dict:
        """Validate knowledge graph quality for reasoning.

        Returns a dict with quality metrics and warnings. Call this before
        reasoning to ensure your KG will produce good results.

        Returns:
            dict with keys: total_nodes, nodes_with_descriptions,
            nodes_without_descriptions, avg_description_length,
            warnings, quality_score (0-100)
        """
        total = len(self.nodes)
        with_desc = 0
        desc_lengths = []
        no_desc_ids = []

        for nid, node in self.nodes.items():
            desc = (node.description or "").strip()
            if desc and len(desc) > 20:
                with_desc += 1
                desc_lengths.append(len(desc))
            else:
                no_desc_ids.append(nid)

        avg_len = sum(desc_lengths) / len(desc_lengths) if desc_lengths else 0
        pct_with = (with_desc / total * 100) if total > 0 else 0

        warnings = []
        if pct_with < 50:
            warnings.append(
                f"CRITICAL: Only {pct_with:.0f}% of nodes have descriptions. "
                f"Agents will produce low-quality reasoning. Add descriptions "
                f"to your nodes or use auto-enrichment."
            )
        elif pct_with < 80:
            warnings.append(
                f"WARNING: {100 - pct_with:.0f}% of nodes lack descriptions. "
                f"Consider enriching them for better results."
            )

        if avg_len < 50 and avg_len > 0:
            warnings.append(
                f"WARNING: Average description length is only {avg_len:.0f} chars. "
                f"Richer descriptions (100+ chars) produce better reasoning."
            )

        # Quality score: 0-100
        score = min(100, int(
            (pct_with * 0.6) +
            (min(avg_len, 200) / 200 * 40)
        ))

        result = {
            "total_nodes": total,
            "total_edges": len(self.edges),
            "nodes_with_descriptions": with_desc,
            "nodes_without_descriptions": len(no_desc_ids),
            "avg_description_length": round(avg_len, 1),
            "quality_score": score,
            "warnings": warnings,
        }

        if warnings:
            for w in warnings:
                logger.warning(w)
        else:
            logger.info(
                f"KG quality: {score}/100 — {with_desc}/{total} nodes with "
                f"descriptions (avg {avg_len:.0f} chars)"
            )

        return result

    # --- Model Assignment ---

    def set_default_backend(self, backend: ModelBackend) -> None:
        """Set the default model backend for all nodes."""
        self._default_backend = backend

    def configure_nodes(self, configs: dict[str, NodeConfig]) -> None:
        """Configure per-node model assignments.

        Supports glob patterns: "art_5_*" matches all nodes starting with "art_5_".
        Use "*" for the default fallback.
        """
        import fnmatch

        for pattern, node_config in configs.items():
            if pattern == "*":
                if node_config.backend:
                    self._default_backend = node_config.backend
                continue

            for node_id, node in self.nodes.items():
                if fnmatch.fnmatch(node_id, pattern):
                    if node_config.backend:
                        self._node_backends[node_id] = node_config.backend
                    if node_config.adapter_id:
                        node.adapter_id = node_config.adapter_id
                    if node_config.system_prompt:
                        node.system_prompt = node_config.system_prompt
                    if node_config.max_tokens != 512:
                        node.max_tokens = node_config.max_tokens
                    if node_config.temperature != 0.3:
                        node.temperature = node_config.temperature

    def _get_backend_for_node(self, node_id: str) -> ModelBackend:
        """Get the model backend for a specific node.

        Bug 5 fix: If no backend is set, auto-create one from config.
        """
        if node_id in self._node_backends:
            return self._node_backends[node_id]
        if self._default_backend is not None:
            return self._default_backend

        # Auto-create backend from config (Bug 5 fix)
        backend = self._auto_create_backend()
        if backend is not None:
            self._default_backend = backend
            return backend

        raise RuntimeError(
            f"No backend assigned for node '{node_id}'. "
            "Call set_default_backend() or configure_nodes() first."
        )

    def _auto_create_backend(self) -> ModelBackend | None:
        """Attempt to create a backend from self.config.model settings."""
        import os

        cfg = self.config
        backend_name = cfg.model.backend
        model_name = cfg.model.model
        api_key = cfg.model.api_key

        # Resolve env var references
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var)

        try:
            if backend_name == "anthropic":
                from cognigraph.backends.api import AnthropicBackend
                api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
                if api_key:
                    return AnthropicBackend(model=model_name, api_key=api_key)
            elif backend_name == "openai":
                from cognigraph.backends.api import OpenAIBackend
                api_key = api_key or os.environ.get("OPENAI_API_KEY")
                if api_key:
                    return OpenAIBackend(model=model_name, api_key=api_key)
            elif backend_name == "bedrock":
                from cognigraph.backends.api import BedrockBackend
                region = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
                return BedrockBackend(model=model_name, region=region)
            elif backend_name == "ollama":
                from cognigraph.backends.api import OllamaBackend
                return OllamaBackend(model=model_name)
        except (ImportError, Exception) as e:
            logger.debug("Auto-backend creation failed: %s", e)

        return None

    def assign_tiered_backends(
        self,
        hub_backend: ModelBackend,
        leaf_backend: ModelBackend,
        hub_threshold: int = 3,
    ) -> None:
        """Assign backends based on node connectivity (multi-tier model assignment).

        Hub nodes (degree > hub_threshold) get the stronger model.
        Leaf nodes get the faster model.
        """
        for node_id, node in self.nodes.items():
            if node.degree > hub_threshold:
                self._node_backends[node_id] = hub_backend
            else:
                self._node_backends[node_id] = leaf_backend
        # Set leaf as default fallback
        self._default_backend = leaf_backend

    # --- Reasoning ---

    def reason(
        self,
        query: str,
        *,
        max_rounds: int | None = None,
        strategy: str | None = None,
        node_ids: list[str] | None = None,
        context: Any = None,
    ) -> ReasoningResult:
        """Run synchronous reasoning query (convenience wrapper).

        Args:
            context: Optional ``ReformulationContext`` from an AI tool
                     (Claude Code, Cursor, Codex) for query enhancement.
        """
        return asyncio.run(
            self.areason(
                query,
                max_rounds=max_rounds,
                strategy=strategy,
                node_ids=node_ids,
                context=context,
            )
        )

    async def areason(
        self,
        query: str,
        *,
        max_rounds: int | None = None,
        strategy: str | None = None,
        node_ids: list[str] | None = None,
        context: Any = None,
    ) -> ReasoningResult:
        """Run async reasoning query — the core entry point.

        Args:
            context: Optional ``ReformulationContext`` from an AI tool
                     (Claude Code, Cursor, Codex) for query enhancement
                     before PCST activation (ADR-104).
        """
        from cognigraph.orchestration.orchestrator import Orchestrator

        max_rounds = max_rounds or self.config.orchestration.max_rounds
        strategy = strategy or self.config.activation.strategy

        # PERF: Adaptive scaling for large KGs (>5K nodes)
        # FEEDBACK: 93-95s per query on 13K graph. Target: <15s.
        # Scale down max_nodes and max_rounds based on graph size.
        graph_size = len(self)
        if graph_size > 5000 and max_rounds > 3:
            max_rounds = min(max_rounds, 3)
            logger.info(
                "Large graph (%d nodes): capping max_rounds to %d for performance",
                graph_size, max_rounds,
            )
        if graph_size > 10000 and max_rounds > 2:
            max_rounds = 2
            logger.info(
                "Very large graph (%d nodes): capping max_rounds to 2", graph_size
            )

        # Also cap max_nodes dynamically for the activator
        if graph_size > 5000 and self.config.activation.max_nodes > 25:
            self.config.activation.max_nodes = 25
            logger.info(
                "Large graph: capping activation max_nodes to 25"
            )

        # 0. Query reformulation (ADR-104)
        query = self._reformulate_query(query, context=context)

        # 1. Activate subgraph
        relevance_scores: dict[str, float] | None = None
        if node_ids is None:
            node_ids = self._activate_subgraph(query, strategy)
            # Capture relevance scores for confidence calibration (Bug 18)
            if self._activator is not None and hasattr(self._activator, "last_relevance"):
                relevance_scores = self._activator.last_relevance

        # 2. Assign backends to activated nodes
        for nid in node_ids:
            backend = self._get_backend_for_node(nid)
            self.nodes[nid].activate(backend)

        # 3. Run orchestrator (with MasterObserver if configured)
        if self._orchestrator is None:
            # Create SkillAdmin with hybrid scoring (Titan V2 preferred)
            skill_admin = None
            try:
                from cognigraph.ontology.skill_admin import SkillAdmin
                # SkillAdmin auto-initializes Titan V2 -> sentence-transformers -> regex
                skill_admin = SkillAdmin(use_titan=True)
            except Exception:
                try:
                    from cognigraph.ontology.skill_admin import SkillAdmin
                    skill_admin = SkillAdmin(use_titan=False)
                except Exception:
                    pass

            self._orchestrator = Orchestrator(
                config=self.config.orchestration,
                observer_config=self.config.observer,
                skill_admin=skill_admin,
            )

        result = await self._orchestrator.run(
            self, query, node_ids, max_rounds,
            relevance_scores=relevance_scores,
        )

        # 4. Deactivate nodes
        for nid in node_ids:
            self.nodes[nid].deactivate()

        # 5. Record metrics
        self._record_query_metrics(query, result, node_ids)

        # 6. Record activation memory (v0.12: cross-query learning)
        self._record_activation_memory(query, node_ids, result)

        return result

    async def areason_stream(
        self,
        query: str,
        *,
        max_rounds: int | None = None,
        strategy: str | None = None,
        node_ids: list[str] | None = None,
        context: Any = None,
    ) -> AsyncIterator:
        """Stream reasoning results as they become available.

        Usage:
            async for chunk in graph.areason_stream("query"):
                print(chunk.content)
        """
        from cognigraph.orchestration.streaming import StreamingOrchestrator

        max_rounds = max_rounds or self.config.orchestration.max_rounds
        strategy = strategy or self.config.activation.strategy

        # Query reformulation (ADR-104)
        query = self._reformulate_query(query, context=context)

        if node_ids is None:
            node_ids = self._activate_subgraph(query, strategy)

        for nid in node_ids:
            backend = self._get_backend_for_node(nid)
            self.nodes[nid].activate(backend)

        streamer = StreamingOrchestrator(self, max_rounds=max_rounds, strategy=strategy)
        async for chunk in streamer.stream(query, active_node_ids=node_ids):
            yield chunk

        for nid in node_ids:
            self.nodes[nid].deactivate()

    async def areason_batch(
        self,
        queries: list[str],
        *,
        max_rounds: int | None = None,
        strategy: str | None = None,
        max_concurrent: int = 5,
    ) -> list[ReasoningResult]:
        """Run multiple reasoning queries in parallel.

        Args:
            queries: List of queries to reason about
            max_concurrent: Max concurrent reasoning tasks

        Returns:
            List of ReasoningResult objects (one per query)
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded_reason(q: str) -> ReasoningResult:
            async with semaphore:
                return await self.areason(
                    q, max_rounds=max_rounds, strategy=strategy
                )

        tasks = [_bounded_reason(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[ReasoningResult] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Batch query failed: {r}")
                final.append(ReasoningResult(
                    answer=f"Error: {r}",
                    confidence=0.0,
                    rounds_completed=0,
                    node_count=0,
                    cost_usd=0.0,
                    latency_ms=0.0,
                ))
            else:
                final.append(r)
        return final

    def _record_query_metrics(
        self, query: str, result: ReasoningResult, node_ids: list[str]
    ) -> None:
        """Record query metrics for ROI tracking."""
        try:
            from cognigraph.metrics import get_metrics

            engine = get_metrics()

            # Start session if not active
            if not engine._session_active:
                engine.start_session()

            # Record the query — estimate result tokens from answer length
            result_tokens = len(result.answer) // 4  # ~4 chars per token
            engine.record_query(query, result_tokens)

            # Record node accesses
            for nid in node_ids:
                node = self.nodes.get(nid)
                label = node.label if node else nid
                tokens_returned = len(node.description) // 4 if node and node.description else 50
                engine.record_context_load(nid, tokens_returned)

            # Record graph stats
            from collections import Counter
            node_types = dict(Counter(n.entity_type for n in self.nodes.values()))
            edge_types = dict(Counter(e.relationship for e in self.edges.values()))
            engine.set_graph_stats(
                nodes=len(self.nodes),
                edges=len(self.edges),
                node_types=node_types,
                edge_types=edge_types,
            )

            # Record lessons applied (detect from answer content)
            import re
            lesson_refs = re.findall(r"LESSON[- ](\d+)", result.answer, re.IGNORECASE)
            for lesson_num in set(lesson_refs):
                engine.record_lesson_applied(
                    f"LESSON-{lesson_num}", query[:80]
                )

            # Record mistakes prevented (detect from answer content)
            mistake_refs = re.findall(r"MISTAKE[- ](\d+)", result.answer, re.IGNORECASE)
            for mistake_num in set(mistake_refs):
                engine.record_mistake_prevented(
                    f"MISTAKE-{mistake_num}", "detected-in-reasoning"
                )

            logger.debug(
                f"Metrics recorded: query tokens={result_tokens}, "
                f"nodes={len(node_ids)}, lessons={len(lesson_refs)}"
            )
        except Exception as e:
            logger.debug(f"Metrics recording skipped: {e}")

    def _record_activation_memory(
        self, query: str, node_ids: list[str], result: ReasoningResult,
    ) -> None:
        """Record activation patterns for cross-query learning (v0.12)."""
        try:
            from cognigraph.learning.activation_memory import ActivationMemory

            if self._activation_memory is None:
                self._activation_memory = ActivationMemory()
                self._activation_memory.load()

            self._activation_memory.record(query, node_ids, result)
        except Exception as e:
            logger.debug(f"Activation memory recording skipped: {e}")

    def _reformulate_query(self, query: str, *, context: Any = None) -> str:
        """Apply query reformulation if configured (ADR-104).

        Returns the reformulated query, or the original if reformulation
        is disabled, not applicable, or fails for any reason (fail-open).
        """
        try:
            cfg = self.config.reformulator
            if not cfg.enabled or cfg.mode == "off":
                return query

            if self._reformulator is None:
                from cognigraph.activation.reformulator import QueryReformulator

                # Resolve LLM backend for standalone mode
                llm_backend = None
                if cfg.llm_backend and cfg.llm_backend in self.config.models:
                    llm_backend = self._resolve_named_backend(cfg.llm_backend)
                elif cfg.mode == "llm" and self._default_backend is not None:
                    llm_backend = self._default_backend

                self._reformulator = QueryReformulator(
                    mode=cfg.mode,
                    backend=llm_backend,
                    enabled=cfg.enabled,
                    graph_summary=cfg.graph_summary,
                )

            result = self._reformulator.reformulate(query, context=context)
            if result.was_reformulated:
                logger.info(
                    "Query reformulated (%s, confidence=%.2f): %s",
                    result.context_source,
                    result.confidence,
                    result.reformulated_query[:100],
                )
            return result.reformulated_query
        except Exception as e:
            logger.debug("Query reformulation skipped: %s", e)
            return query

    def _resolve_named_backend(self, profile_name: str) -> Any:
        """Resolve a named model profile to a backend instance."""
        from cognigraph.config.settings import NamedModelConfig

        profile = self.config.models.get(profile_name)
        if profile is None:
            return None

        if profile.backend == "anthropic":
            from cognigraph.backends.api import AnthropicBackend
            return AnthropicBackend(model=profile.model, api_key=profile.api_key)
        elif profile.backend == "openai":
            from cognigraph.backends.api import OpenAIBackend
            return OpenAIBackend(model=profile.model, api_key=profile.api_key)
        elif profile.backend == "bedrock":
            from cognigraph.backends.api import BedrockBackend
            return BedrockBackend(model=profile.model)
        elif profile.backend == "ollama":
            from cognigraph.backends.api import OllamaBackend
            return OllamaBackend(model=profile.model)

        return None

    def _activate_subgraph(self, query: str, strategy: str) -> list[str]:
        """Select nodes to activate for a query.

        Strategy resolution order:
        1. "full" / "manual" / "top_k" — explicit strategies
        2. Direct file lookup — query mentions a known filename
        3. Neo4j CypherActivation — if connector available
        4. ChunkScorer (default) — chunk-level embedding search, no PCST
        5. PCST — legacy fallback (only if strategy="pcst" explicitly)
        """
        if strategy == "full":
            return list(self.nodes.keys())
        elif strategy == "manual":
            raise ValueError("Manual strategy requires explicit node_ids")
        elif strategy == "top_k":
            sorted_nodes = sorted(
                self.nodes.values(), key=lambda n: n.degree, reverse=True
            )
            k = min(self.config.activation.max_nodes, len(sorted_nodes))
            return [n.id for n in sorted_nodes[:k]]
        else:
            # Direct file lookup bypass (ADR-103 Layer 3)
            direct = self._direct_file_lookup(query)
            if direct:
                logger.info(
                    "Direct file lookup activated %d nodes (bypassing scoring)",
                    len(direct),
                )
                return direct

            # Neo4j CypherActivation (if connector available)
            if self._neo4j_connector is not None:
                try:
                    from cognigraph.activation.cypher_activation import CypherActivation
                    from cognigraph.activation.embeddings import EmbeddingEngine

                    if self._activator is None or not isinstance(self._activator, CypherActivation):
                        engine = EmbeddingEngine()
                        self._activator = CypherActivation(
                            connector=self._neo4j_connector,
                            embedding_engine=engine,
                            max_nodes=self.config.activation.max_nodes,
                        )
                    return self._activator.activate(self, query)
                except Exception as exc:
                    logger.warning("CypherActivation failed (%s), falling back", exc)

            # Legacy PCST — only if explicitly requested
            if strategy == "pcst":
                try:
                    from cognigraph.activation.pcst import PCSTActivation

                    if self._activator is None or not isinstance(
                        self._activator, PCSTActivation
                    ):
                        self._activator = PCSTActivation(
                            max_nodes=self.config.activation.max_nodes,
                            prize_scaling=self.config.activation.prize_scaling,
                            cost_scaling=self.config.activation.cost_scaling,
                        )
                    return self._activator.activate(self, query)
                except ImportError:
                    logger.warning("pcst_fast not installed, falling through to ChunkScorer")

            # ChunkScorer (new default) — chunk-level embedding search
            # v0.12: Adaptive node count — simple queries don't need max_nodes.
            from cognigraph.activation.chunk_scorer import ChunkScorer
            from cognigraph.activation.adaptive import QueryComplexityScorer

            configured_max = self.config.activation.max_nodes
            try:
                scorer = QueryComplexityScorer()
                profile = scorer.score(query)
                tier_map = {
                    "simple": max(4, configured_max // 4),
                    "moderate": max(8, configured_max // 2),
                    "complex": max(12, int(configured_max * 0.75)),
                    "expert": configured_max,
                }
                adaptive_max = tier_map.get(profile.tier, configured_max)
                logger.info(
                    "Adaptive ChunkScorer: tier=%s, max_nodes=%d (configured=%d), "
                    "composite=%.3f",
                    profile.tier, adaptive_max, configured_max,
                    profile.composite,
                )
            except Exception:
                adaptive_max = configured_max

            if self._activator is None or not isinstance(self._activator, ChunkScorer):
                self._activator = ChunkScorer(
                    max_nodes=adaptive_max,
                )
            else:
                self._activator.max_nodes = adaptive_max

            # v0.12.1: Pass activation memory boosts if available
            activation_boosts = None
            try:
                from cognigraph.learning.activation_memory import ActivationMemory
                if self._activation_memory is None:
                    self._activation_memory = ActivationMemory()
                    self._activation_memory.load()
                activation_boosts = self._activation_memory.get_boosts(query)
                if activation_boosts:
                    logger.info(
                        "ActivationMemory: %d node boosts for query",
                        len(activation_boosts),
                    )
            except Exception:
                pass

            return self._activator.activate(
                self, query, activation_boosts=activation_boosts
            )

    def _direct_file_lookup(self, query: str) -> list[str] | None:
        """Layer 3 (ADR-103): Directly activate nodes matching filenames in the query.

        If the query contains a recognisable filename (e.g., "auth.ts",
        "payment_service.py"), find the matching node(s) and return them
        plus their immediate neighbours.  This bypasses PCST entirely,
        guaranteeing the right file is always activated when explicitly named.

        Returns ``None`` if no filename match is found (→ fall through to PCST).

        Edge cases handled:
        - Multiple files mentioned → all are activated
        - File mentioned but not in graph → returns None (fall through to PCST)
        - Matched node has zero chunks → still activated (agent will use
          description; the user asked for it explicitly)
        - Very short filenames (<3 chars) → ignored to prevent false positives
        - Path fragments ("src/auth") → basename extracted ("auth")
        """
        import re as _re

        query_lower = query.lower()

        # Build a lookup: bare_name → node_id, full_label → node_id
        # Only for nodes whose label looks like a filename (contains '.')
        label_to_id: dict[str, str] = {}
        bare_to_id: dict[str, str] = {}

        for nid, node in self.nodes.items():
            label = (node.label or "").strip()
            if not label or len(label) < 3:
                continue

            label_lower = label.lower()
            # Normalize paths to basename
            if "/" in label_lower or "\\" in label_lower:
                label_lower = label_lower.replace("\\", "/").rsplit("/", 1)[-1]

            if "." in label_lower:
                # It looks like a filename
                label_to_id[label_lower] = nid
                bare = label_lower.rsplit(".", 1)[0]
                if len(bare) >= 3:
                    bare_to_id[bare] = nid

        if not label_to_id and not bare_to_id:
            return None

        matched_nodes: set[str] = set()

        # Check full filename matches (e.g., "auth.ts" in query)
        for fname, nid in label_to_id.items():
            if fname in query_lower:
                matched_nodes.add(nid)

        # Check bare name matches with word boundary (e.g., "auth" in query)
        for bare, nid in bare_to_id.items():
            if nid in matched_nodes:
                continue  # Already matched by full name
            if bare in query_lower:
                # Word boundary check to avoid substring false matches
                pattern = r"(?:^|[\s\-_/\\.,;:\"'()]){}(?:[\s\-_/\\.,;:\"'()]|$)".format(
                    _re.escape(bare)
                )
                if _re.search(pattern, query_lower):
                    matched_nodes.add(nid)

        if not matched_nodes:
            return None

        # Expand: add immediate neighbours of matched nodes
        max_nodes = getattr(self.config.activation, "max_nodes", 50)
        result: set[str] = set(matched_nodes)
        for nid in list(matched_nodes):
            for neighbor_id in self.get_neighbors(nid):
                result.add(neighbor_id)
                if len(result) >= max_nodes:
                    break
            if len(result) >= max_nodes:
                break

        return list(result)

    # --- Graph Operations ---

    def add_node(self, node: CogniNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: CogniEdge) -> None:
        """Add an edge to the graph."""
        self.edges[edge.id] = edge
        if edge.source_id in self.nodes:
            self.nodes[edge.source_id].outgoing_edges.append(edge.id)
        if edge.target_id in self.nodes:
            self.nodes[edge.target_id].incoming_edges.append(edge.id)

    def add_node_simple(
        self,
        node_id: str,
        *,
        label: str | None = None,
        entity_type: str = "CONCEPT",
        description: str = "",
        properties: dict | None = None,
    ) -> CogniNode:
        """Convenience: add a node from kwargs (used by kogni learn and /learn API)."""
        node = CogniNode(
            id=node_id,
            label=label or node_id,
            entity_type=entity_type,
            description=description,
            properties=properties or {},
        )
        self.add_node(node)
        return node

    def add_edge_simple(
        self,
        source_id: str,
        target_id: str,
        *,
        relation: str = "RELATES_TO",
    ) -> CogniEdge:
        """Convenience: add an edge from kwargs."""
        edge_id = f"{source_id}___{relation}___{target_id}"
        edge = CogniEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relation,
        )
        self.add_edge(edge)
        return edge

    def auto_connect(self, new_node_ids: list[str]) -> int:
        """Auto-discover edges between new nodes and existing nodes.

        Uses keyword overlap in descriptions to find connections.
        Returns number of edges added.
        """
        stopwords = {"the", "a", "an", "is", "in", "to", "of", "and", "for",
                      "it", "on", "with", "as", "at", "by", "this", "that"}
        edges_added = 0

        for new_id in new_node_ids:
            new_node = self.nodes.get(new_id)
            if not new_node or not new_node.description:
                continue

            new_words = set(new_node.description.lower().split()) - stopwords
            if len(new_words) < 2:
                continue

            for nid, node in self.nodes.items():
                if nid == new_id or not node.description:
                    continue
                # Skip if already connected
                existing = self.get_edges_between(new_id, nid)
                if existing:
                    continue

                node_words = set(node.description.lower().split()) - stopwords
                overlap = new_words & node_words
                if len(overlap) >= 3:
                    self.add_edge_simple(new_id, nid, relation="RELATED_TO")
                    edges_added += 1
                    if edges_added >= 20:  # Cap auto-connections
                        return edges_added

        return edges_added

    def to_json(self, path: str) -> None:
        """Save the graph to a JSON file (node_link_data format)."""
        import json as _json
        from pathlib import Path as _Path

        G = self.to_networkx()
        data = nx.node_link_data(G)
        _Path(path).write_text(
            _json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Saved graph to %s: %d nodes", path, len(self))

    def get_neighbors(self, node_id: str) -> list[str]:
        """Get IDs of all neighbor nodes."""
        node = self.nodes[node_id]
        neighbors = set()
        for eid in node.outgoing_edges:
            neighbors.add(self.edges[eid].target_id)
        for eid in node.incoming_edges:
            neighbors.add(self.edges[eid].source_id)
        return list(neighbors)

    def get_edges_between(self, source_id: str, target_id: str) -> list[CogniEdge]:
        """Get all edges between two nodes."""
        return [
            e for e in self.edges.values()
            if (e.source_id == source_id and e.target_id == target_id)
            or (e.source_id == target_id and e.target_id == source_id)
        ]

    def get_incoming_edges(self, node_id: str) -> list[CogniEdge]:
        """Get all incoming edges for a node."""
        return [self.edges[eid] for eid in self.nodes[node_id].incoming_edges]

    def get_outgoing_edges(self, node_id: str) -> list[CogniEdge]:
        """Get all outgoing edges for a node."""
        return [self.edges[eid] for eid in self.nodes[node_id].outgoing_edges]

    def to_networkx(self) -> nx.Graph:
        """Export to NetworkX graph — always builds fresh from current node state.

        This ensures runtime mutations (auto-chunk loading, description
        enrichment, property updates) are reflected in the exported graph.
        """
        G = nx.DiGraph()
        for nid, node in self.nodes.items():
            G.add_node(nid, label=node.label, type=node.entity_type,
                       description=node.description, **node.properties)
        for eid, edge in self.edges.items():
            G.add_edge(edge.source_id, edge.target_id,
                       relationship=edge.relationship, weight=edge.weight,
                       **edge.properties)
        return G

    # --- Inspection ---

    @property
    def stats(self) -> GraphStats:
        """Compute graph statistics."""
        G = self.to_networkx()
        degrees = [d for _, d in G.degree()]
        avg_deg = sum(degrees) / len(degrees) if degrees else 0.0

        # Find hub nodes (top 10% by degree)
        sorted_by_deg = sorted(
            self.nodes.values(), key=lambda n: n.degree, reverse=True
        )
        hub_count = max(1, len(sorted_by_deg) // 10)
        hubs = [n.id for n in sorted_by_deg[:hub_count]]

        return GraphStats(
            total_nodes=len(self.nodes),
            total_edges=len(self.edges),
            activated_nodes=sum(
                1 for n in self.nodes.values()
                if n.status != NodeStatus.IDLE
            ),
            avg_degree=avg_deg,
            density=nx.density(G) if len(G) > 1 else 0.0,
            connected_components=(
                nx.number_weakly_connected_components(G)
                if G.is_directed()
                else nx.number_connected_components(G)
            ),
            hub_nodes=hubs,
        )

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        domain = getattr(self.config, "domain", "unknown")
        return (
            f"CogniGraph(nodes={len(self.nodes)}, edges={len(self.edges)}, "
            f"config={domain})"
        )
