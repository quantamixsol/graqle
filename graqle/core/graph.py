"""GraQle — the reasoning graph where every node is an agent."""

# ── graqle:intelligence ──
# module: graqle.core.graph
# risk: CRITICAL (impact radius: 26 modules)
# consumers: sdk_self_audit, governance_example, __init__, benchmark_runner, run_multigov_v2 +21 more
# dependencies: __future__, asyncio, logging, typing, networkx +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import copy
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any, Callable

import networkx as nx

from graqle.config.settings import GraqleConfig
from graqle.core.edge import CogniEdge
from graqle.core.node import CogniNode
from graqle.core.types import (
    GraphStats,
    ModelBackend,
    NodeConfig,
    NodeStatus,
    ReasoningResult,
)

logger = logging.getLogger("graqle")


# OT-060: Process-scoped Neo4j escape hatch via NEO4J_DISABLED env var.
# Purpose: let hosts with tight handshake deadlines (VS Code MCP server,
# CI jobs, Lambda) tell graQle to skip bolt:// dials entirely for this
# process. Neo4j remains a first-class power-user storage + reasoning
# backend — this is a per-process override, not a feature removal.
_neo4j_disabled_warned: bool = False


def _neo4j_disabled() -> bool:
    """Return True iff the NEO4J_DISABLED env var is set to a truthy value.

    Truthy values: "1", "true", "yes", "on" (case-insensitive, whitespace-trimmed).
    All other values (unset, empty, "0", "false", "no", "off", etc.) return False.

    Evaluated on every call — not cached — so tests can monkeypatch the env
    var between assertions and the SDK honors runtime env changes.
    """
    import os
    return os.environ.get("NEO4J_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _emit_neo4j_disabled_warning() -> None:
    """Log a single WARNING per process when the NEO4J_DISABLED gate fires.

    Best-effort single-emission semantics using a module-level bool. In CPython
    the GIL makes the check-and-set atomic enough for a logging purpose; we
    accept the theoretical possibility of a duplicate warning under extreme
    concurrent first-fire conditions.
    """
    global _neo4j_disabled_warned
    if not _neo4j_disabled_warned:
        logger.warning(
            "Neo4j backend disabled for this process via NEO4J_DISABLED=true. "
            "Graph loaded from JSON fallback. This is a process-scoped override; "
            "Neo4j remains fully supported. See `graq upgrade neo4j`."
        )
        _neo4j_disabled_warned = True


def _acquire_lock(lock_path: str):
    """Acquire a cross-platform file lock. Returns the lock file descriptor.

    The caller MUST call ``_release_lock(fd, lock_path)`` when done.
    This enables atomic read-modify-write operations on graph files.
    """
    import sys as _sys
    import time as _time

    if _sys.platform == "win32":
        import msvcrt
        fd = open(lock_path, "w")
        try:
            for attempt in range(10):
                try:
                    msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
                    return fd
                except OSError:
                    if attempt == 9:
                        raise
                    _time.sleep(0.1)
        except BaseException:
            fd.close()
            raise
        return fd  # unreachable but satisfies type checkers
    else:
        import fcntl
        fd = open(lock_path, "w")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        return fd


def _release_lock(fd, lock_path: str) -> None:
    """Release a file lock acquired by ``_acquire_lock``."""
    import sys as _sys

    if fd is None:
        return
    try:
        if _sys.platform == "win32":
            import msvcrt
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        fd.close()
        try:
            import os
            os.unlink(lock_path)
        except OSError:
            pass


def _validate_graph_data(data: dict, existing_path: str | None = None) -> None:
    """Validate graph data before saving. Raises ValueError on corruption.

    Checks:
    1. ``directed`` and ``multigraph`` are booleans (not MagicMock strings)
    2. ``nodes`` is a non-empty list
    3. If existing graph exists, refuse to save if node count drops >50%
       (prevents accidental data wipe)
    """
    if not isinstance(data.get("directed"), bool):
        raise ValueError(
            f"Graph validation failed: 'directed' is {type(data.get('directed')).__name__}, expected bool. "
            "This may indicate test mock contamination."
        )
    if not isinstance(data.get("multigraph"), bool):
        raise ValueError(
            f"Graph validation failed: 'multigraph' is {type(data.get('multigraph')).__name__}, expected bool."
        )

    nodes_key = "nodes" if "nodes" in data else None
    if nodes_key is None or not isinstance(data[nodes_key], list):
        raise ValueError("Graph validation failed: 'nodes' must be a list.")

    new_count = len(data[nodes_key])

    # Check for catastrophic node loss
    if existing_path:
        import json as _json
        from pathlib import Path as _P
        existing = _P(existing_path)
        if existing.exists():
            try:
                old_data = _json.loads(existing.read_text(encoding="utf-8"))
                old_count = len(old_data.get("nodes", []))
                if old_count > 0 and new_count == 0:
                    raise ValueError(
                        f"Graph validation failed: saving 0 nodes would wipe {old_count} existing nodes. "
                        "Use force=True to override."
                    )
                if old_count > 10 and new_count < old_count * 0.5:
                    raise ValueError(
                        f"Graph validation failed: node count dropping from {old_count} to {new_count} "
                        f"({100*new_count/old_count:.0f}%). This may indicate data corruption. "
                        "Use force=True to override."
                    )
            except (_json.JSONDecodeError, KeyError):
                pass  # Existing file is already corrupt, allow overwrite


def _write_with_lock(file_path: str, content: str) -> None:
    """Write content to a file with cross-platform file locking and atomic rename.

    Uses ``msvcrt.locking`` on Windows and ``fcntl.flock`` on Unix to
    prevent concurrent write corruption when multiple agents or processes
    access the same graph file.

    Writes to a temporary file first, then renames to the target path.
    This prevents data loss if serialization or disk write fails mid-way
    (e.g. MemoryError, disk full). The original file is only replaced
    after the new content is fully written and flushed.
    """
    import os
    import tempfile

    lock_path = file_path + ".lock"
    fd = None
    tmp_path = None
    try:
        fd = _acquire_lock(lock_path)
        # Write to temp file in same directory (ensures same filesystem for rename)
        dir_path = os.path.dirname(file_path) or "."
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dir_path,
            suffix=".tmp", delete=False,
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        # Atomic rename (POSIX) / near-atomic (Windows)
        os.replace(tmp_path, file_path)
        tmp_path = None  # Rename succeeded, don't clean up
    finally:
        # Clean up temp file if rename didn't happen
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        _release_lock(fd, lock_path)


def _read_modify_write(file_path: str, modify_fn) -> None:
    """Atomically read a JSON file, modify it, and write it back under lock.

    This prevents the read-modify-write race condition (DF-006) where
    concurrent processes read the same state and overwrite each other.

    Parameters
    ----------
    file_path:
        Path to the JSON file.
    modify_fn:
        Callable that receives the parsed JSON data dict, modifies it
        in-place (or returns a new dict), and returns the modified data.
    """
    import json as _json

    lock_path = file_path + ".lock"
    fd = None
    try:
        fd = _acquire_lock(lock_path)

        # Read current state under lock
        try:
            with open(file_path, encoding="utf-8") as f:
                data = _json.load(f)
        except (FileNotFoundError, _json.JSONDecodeError):
            data = {"directed": True, "multigraph": False, "graph": {},
                    "nodes": [], "links": []}

        # Modify
        result = modify_fn(data)
        if result is not None:
            data = result

        # Validate before writing (pass existing_path for loss protection)
        _validate_graph_data(data, existing_path=file_path)

        # Write back under same lock
        content = _json.dumps(data, indent=2, default=str)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    finally:
        _release_lock(fd, lock_path)


class Graqle:
    """The reasoning graph — a knowledge graph where every node is an agent.

    GraQle is the primary entry point for the SDK. It wraps a
    knowledge graph (from NetworkX, Neo4j, or other sources) and
    provides reasoning capabilities through distributed model agents.
    """

    def __init__(
        self,
        nodes: dict[str, CogniNode] | None = None,
        edges: dict[str, CogniEdge] | None = None,
        config: GraqleConfig | None = None,
    ) -> None:
        self.nodes: dict[str, CogniNode] = nodes or {}
        self.edges: dict[str, CogniEdge] = edges or {}
        self.config = config or GraqleConfig.default()
        self._default_backend: ModelBackend | None = None
        self._node_backends: dict[str, ModelBackend] = {}
        self._orchestrator: Any = None  # set lazily
        self._activator: Any = None  # set lazily
        self._reformulator: Any = None  # set lazily (ADR-104)
        self._task_router: Any = None  # set lazily (v0.22: task-based routing)
        self._activation_memory: Any = None  # v0.12: cross-query learning
        self._neo4j_connector: Any = None  # set by from_neo4j / to_neo4j
        self._nx_graph: nx.Graph | None = None

        # Mandatory quality gate: enrich + enforce descriptions + auto-chunk
        if self.nodes:
            self._auto_enrich_descriptions()
            self._auto_load_chunks()
            self._enforce_no_empty_descriptions()

    # ------------------------------------------------------------------
    # ADR-128: Atomic batch reclassification (copy-on-write)
    # ------------------------------------------------------------------

    def reclassify_batch(
        self,
        reclassify_fn: Callable[[dict], None],
        *,
        validate: bool = True,
        max_node_loss_pct: float = 0.5,
    ) -> dict:
        """Atomic copy-on-write batch reclassification of all graph nodes.

        Prevents split-brain state: the live ``/reason`` endpoint never sees
        a partially reclassified graph.  All mutations happen on a deep-copied
        shadow; only on full success is the real graph updated in a single
        GIL-protected pass.

        The ``reclassify_fn`` receives a plain dict with keys ``entity_type``,
        ``label``, ``name``, and ``properties`` extracted from each
        :class:`CogniNode`. It may mutate the dict in-place. On success,
        changes are written back to the original CogniNode attributes.

        Args:
            reclassify_fn: Mutating callable applied to each node-data dict.
            validate: When True, check for dangling edges and node-count
                collapse before committing.
            max_node_loss_pct: Minimum fraction of original node count that
                must survive in the shadow copy (0.0-1.0).

        Returns:
            Stats dict: ``{"reclassified": N, "skipped": N, "failed": 0, "by_type": {...}}``

        Raises:
            RuntimeError: If any per-node reclassification raises, or if
                validation detects dangling edges / excessive node loss.
        """
        original_count = len(self.nodes)

        # Step 1 — extract node data into shadow dicts (deep-copied)
        shadow_nodes: dict[str, dict] = {}
        for nid, node in self.nodes.items():
            shadow_nodes[nid] = copy.deepcopy({
                "entity_type": node.entity_type,
                "label": node.label,
                "name": getattr(node, "label", nid),
                "properties": dict(node.properties) if node.properties else {},
            })

        # Step 2 — apply reclassify_fn per node, collect failures
        failures: list[tuple[str, Exception]] = []
        reclassified = 0
        skipped = 0
        by_type: dict[str, int] = defaultdict(int)

        for nid, node_data in shadow_nodes.items():
            old_type = node_data.get("entity_type")
            try:
                reclassify_fn(node_data)
            except Exception as exc:  # noqa: BLE001
                failures.append((nid, exc))
                continue

            new_type = node_data.get("entity_type")
            if new_type != old_type:
                reclassified += 1
                by_type[new_type] += 1
            else:
                skipped += 1

        # Step 3 — abort on ANY failure; original graph untouched
        if failures:
            raise RuntimeError(
                f"reclassify_batch aborted: {len(failures)} node(s) failed. "
                f"Original graph unchanged. First: {failures[0][0]}: {failures[0][1]}"
            )

        # Step 4 — optional validation
        if validate:
            shadow_ids = set(shadow_nodes.keys())
            # Dangling-edge check
            for eid, edge in self.edges.items():
                if edge.source_id not in shadow_ids or edge.target_id not in shadow_ids:
                    raise RuntimeError(
                        f"Dangling edge detected: ({edge.source_id} -> {edge.target_id}). "
                        "Aborting."
                    )
            # Node-count collapse check
            if original_count > 0 and len(shadow_ids) < original_count * max_node_loss_pct:
                raise RuntimeError(
                    f"Node count collapse: {len(shadow_ids)}/{original_count} "
                    f"below {max_node_loss_pct:.0%} threshold. Aborting."
                )

        # Step 5 — atomic swap: write shadow data back to CogniNodes
        for nid, node_data in shadow_nodes.items():
            node = self.nodes[nid]
            node.entity_type = node_data["entity_type"]
            # Merge any new properties added by reclassification
            for key in ("domain", "reclassification_confidence",
                        "reclassification_source", "reclassification_from"):
                if key in node_data:
                    node.properties[key] = node_data[key]

        # Step 6 — invalidate caches
        self._activator = None
        self._nx_graph = None

        # Step 7 — return stats
        return {
            "reclassified": reclassified,
            "skipped": skipped,
            "failed": 0,
            "by_type": dict(by_type),
        }

    # --- Construction ---

    @classmethod
    def from_networkx(
        cls,
        G: nx.Graph,
        config: GraqleConfig | None = None,
        node_label_key: str = "label",
        node_type_key: str = "type",
        node_desc_key: str = "description",
        edge_rel_key: str = "relationship",
    ) -> Graqle:
        """Create a GraQle from a NetworkX graph."""
        nodes: dict[str, CogniNode] = {}
        edges: dict[str, CogniEdge] = {}

        # Build nodes
        for node_id, data in G.nodes(data=True):
            nid = str(node_id)
            props = {k: v for k, v in data.items()
                     if k not in (node_label_key, node_type_key, node_desc_key)}
            # Accept both "type" and "entity_type" keys (scanner writes entity_type)
            etype = data.get(node_type_key) or data.get("entity_type", "Entity")
            # Remove entity_type from props if it leaked in
            props.pop("entity_type", None)
            # Flatten nested "properties" or "metadata" dict
            # (NetworkX preserves it as a node attr; hand-built KGs may use
            # "metadata" instead of "properties" — normalize both)
            for _alias in ("properties", "metadata"):
                if _alias in props and isinstance(props[_alias], dict):
                    nested = props.pop(_alias)
                    nested.update(props)  # existing props override nested
                    props = nested
                    break
            nodes[nid] = CogniNode(
                id=nid,
                label=data.get(node_label_key, nid),
                entity_type=etype,
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
        cls, path: str, config: GraqleConfig | str | None = None,
        skip_validation: bool = False,
    ) -> Graqle:
        """Create a GraQle from a JSON file.

        Parameters
        ----------
        path:
            Path to the JSON graph file.
        config:
            A ``GraqleConfig`` instance, a path to a YAML config file
            (string), or ``None`` for defaults.
        skip_validation:
            If True, bypass the embedding-dimension mismatch check (P2).
            Use ONLY from ``graq rebuild --re-embed`` after verifying the
            dimension difference intentionally — e.g. embedding model upgrade.
            Default False: all normal callers retain the safety check.
        """
        import json
        from pathlib import Path as _Path

        # Bug 4 fix: handle string config path automatically
        if isinstance(config, str):
            config_path = _Path(config)
            if config_path.exists():
                config = GraqleConfig.from_yaml(config)
            else:
                logger.warning("Config file not found: %s — using defaults", config)
                config = None

        data = json.loads(_Path(path).read_text(encoding="utf-8"))
        # Normalize: accept both "edges" and "links" keys (scanner writes "edges",
        # older NetworkX defaults to "links").  Always pass edges= explicitly.
        if "edges" in data and "links" not in data:
            data["links"] = data.pop("edges")

        # P2: validate embedding provenance if stored (graphs built with v0.34.0+)
        # skip_validation=True bypasses this check — ONLY for graq rebuild --re-embed.
        _graph_val = data.get("graph")
        _meta = (_graph_val if isinstance(_graph_val, dict) else {}).get("_meta")
        if _meta and not skip_validation:
            _stored_model = _meta.get("embedding_model", "unknown")
            _stored_dim = _meta.get("embedding_dim", 0)
            if _stored_dim > 0:
                try:
                    from graqle.activation.embeddings import create_embedding_engine
                    from graqle.core.exceptions import EmbeddingDimensionMismatchError
                    _cfg = config if isinstance(config, object) else None
                    _engine = create_embedding_engine(_cfg)
                    _active_model = getattr(_engine, "model_name", "unknown")
                    _active_dim = (
                        getattr(_engine, "_dim", None)
                        or getattr(_engine, "_dimension", None)
                        or (getattr(getattr(_cfg, "embeddings", None), "dimension", 0) or 384)
                    )
                    if int(_active_dim) != int(_stored_dim):
                        raise EmbeddingDimensionMismatchError(
                            stored_model=_stored_model,
                            stored_dim=_stored_dim,
                            active_model=_active_model,
                            active_dim=int(_active_dim),
                        )
                except (ImportError, AttributeError):
                    pass  # Cannot validate — proceed without check

        G = nx.node_link_graph(data, edges="links")
        return cls.from_networkx(G, config=config)

    @classmethod
    def from_neo4j(
        cls,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
        config: GraqleConfig | None = None,
    ) -> Graqle:
        """Create a GraQle from a Neo4j database.

        Loads nodes and edges via Cypher, attaches chunks as node properties,
        and stores the connector for runtime Cypher vector search.
        """
        # OT-060: Process-scoped escape hatch. When NEO4J_DISABLED=true,
        # raise before importing Neo4jConnector or dialing bolt://.
        # Zero dials, zero retries. Callers already wrap this in try/except
        # and fall back to JSON, so the existing graceful-degradation
        # contract is preserved.
        if _neo4j_disabled():
            _emit_neo4j_disabled_warning()
            raise RuntimeError(
                "Neo4j backend is disabled for this process (NEO4J_DISABLED=true). "
                "Your graph is still available via the local graqle.json file. "
                "To re-enable Neo4j, unset NEO4J_DISABLED in your environment. "
                "Neo4j remains fully supported for users who want a local graph DB — "
                "see `graq upgrade neo4j`."
            )

        from graqle.connectors.neo4j import Neo4jConnector

        cfg = config or GraqleConfig.default()
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
        # OT-060: Process-scoped escape hatch. When NEO4J_DISABLED=true,
        # raise before importing Neo4jConnector or dialing bolt://.
        # Use Graqle.to_json() to export locally instead.
        if _neo4j_disabled():
            _emit_neo4j_disabled_warning()
            raise RuntimeError(
                "Neo4j backend is disabled for this process (NEO4J_DISABLED=true). "
                "Your graph is still available via the local graqle.json file. "
                "To re-enable Neo4j, unset NEO4J_DISABLED in your environment. "
                "Use Graqle.to_json() to export locally, or see `graq upgrade neo4j` "
                "to set up a local Neo4j instance."
            )

        from graqle.connectors.neo4j import Neo4jConnector

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

        Use this after ``graq init`` or when source files have changed.
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
                    chunks = self._chunk_source_code(content)
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

            # Start with a human-readable type sentence
            etype = node.entity_type if node.entity_type and node.entity_type != "Entity" else ""
            label = node.label if node.label and node.label != nid else ""
            if etype and label:
                parts.append(f"{label} is a {etype.lower()}")
            elif etype:
                parts.append(f"[{etype}] {nid}")
            elif label:
                parts.append(label)

            # Add contextual source file info
            source_file = (node.properties or {}).get("source_file", "")
            if source_file:
                parts.append(f"defined in {source_file}")

            # Add high-value properties with human-readable formatting
            # Prioritise: purpose, context, risk, status, consumers, dependencies
            priority_keys = [
                "purpose", "context", "status", "risk", "risk_level",
                "severity", "full_text", "root_cause", "fix",
            ]
            if node.properties:
                # Priority keys first
                for key in priority_keys:
                    val = node.properties.get(key)
                    if val:
                        val_str = str(val)
                        if len(val_str) > 300:
                            val_str = val_str[:300] + "..."
                        parts.append(f"{key}: {val_str}")

                # Then remaining properties (skip duplicates, internal, and sensitive keys)
                # ADR-151 G3: prevent sensitive properties from entering descriptions
                from graqle.core.redaction import DEFAULT_SENSITIVE_KEYS
                skip_keys = {"id", "label", "type", "description", "source_file",
                             "source_line", "confidence", "source",
                             } | set(priority_keys) | DEFAULT_SENSITIVE_KEYS
                for key, val in node.properties.items():
                    if key in skip_keys:
                        continue
                    val_str = str(val)
                    if len(val_str) > 300:
                        val_str = val_str[:300] + "..."
                    if val_str and val_str not in ("None", "0", ""):
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
                    f"https://graqle.com/docs/kg-quality"
                )
            elif empty_count > 0:
                logger.info(
                    f"Auto-enriched {enriched}/{empty_count} nodes with "
                    f"empty descriptions from metadata."
                )

    def _auto_load_chunks(self) -> None:
        """Auto-load chunks for nodes that have none.

        Three-tier chunk resolution:
        T1. Node already has ``chunks`` in properties → skip.
        T2. Node has ``source_file`` / ``file_path`` → read file, chunk it.
        T3. Node has only a description (hand-built KG) → synthesize a
            single chunk from description + metadata so the agent has
            *some* evidence to cite during reasoning.

        T3 is the critical safety net for hand-built / curated KGs where
        nodes represent concepts, decisions, or entities rather than code
        files.  Without T3, these nodes pass validation but produce hollow
        reasoning because agents have no evidence chunks.
        """
        from pathlib import Path as _P

        file_loaded = 0
        desc_loaded = 0
        for node in self.nodes.values():
            # T1: Skip nodes that already have chunks (non-empty list),
            # OR nodes that explicitly set chunks=[] (opt-out from T3 synthesis)
            if "chunks" in node.properties:
                continue

            # T2: Try to load from a referenced file
            file_path = (
                node.properties.get("file_path")
                or node.properties.get("source_file")
            )
            if file_path:
                try:
                    fp = _P(file_path)
                    if fp.exists() and fp.is_file():
                        content = fp.read_text(encoding="utf-8", errors="ignore")
                        if content.strip():
                            suffix = fp.suffix.lower()
                            if suffix in (".py", ".js", ".ts", ".tsx", ".jsx"):
                                chunks = self._chunk_source_code(content)
                            else:
                                chunks = [{"text": content[:4000], "type": suffix.lstrip(".") or "text"}]
                            if chunks:
                                node.properties["chunks"] = chunks
                                file_loaded += 1
                                continue
                except Exception:
                    pass

            # T3: Synthesize chunk from description + metadata for hand-built nodes
            desc = (node.description or "").strip()
            if desc and len(desc) > 30:
                # Build a richer chunk by combining description with key properties
                parts = [desc]
                # Include select metadata fields that add context
                # ADR-151 G2: skip sensitive property keys in chunk synthesis
                from graqle.core.redaction import DEFAULT_SENSITIVE_KEYS
                skip_keys = {"chunks", "chunk_count", "file_path", "source_file"
                             } | DEFAULT_SENSITIVE_KEYS
                for k, v in node.properties.items():
                    if k in skip_keys:
                        continue
                    if isinstance(v, (str, int, float, bool)):
                        parts.append(f"{k}: {v}")
                    elif isinstance(v, list) and len(v) <= 10:
                        parts.append(f"{k}: {', '.join(str(x) for x in v)}")
                chunk_text = "\n".join(parts)
                node.properties["chunks"] = [
                    {"text": chunk_text, "type": "synthesized"}
                ]
                desc_loaded += 1

        if file_loaded or desc_loaded:
            logger.info(
                "Auto-loaded chunks: %d from files, %d from descriptions "
                "(%d/%d nodes now have chunks).",
                file_loaded, desc_loaded,
                sum(1 for n in self.nodes.values()
                    if n.properties.get("chunks")),
                len(self.nodes),
            )

    @staticmethod
    def _chunk_source_code(content: str, max_chunks: int = 15) -> list[dict[str, str]]:
        """Split source code into semantic chunks at function/class boundaries.

        Returns a list of ``{"text": ..., "type": ...}`` dicts, capped at
        *max_chunks* to stay within token budgets.  Raised from 5 to 15
        (OT-018) so files up to ~600 lines are fully indexed.
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

        # Chunk coverage check
        nodes_with_chunks = 0
        total_chunks = 0
        no_chunk_ids = []
        for nid, node in self.nodes.items():
            chunks = node.properties.get("chunks", [])
            if chunks:
                nodes_with_chunks += 1
                total_chunks += len(chunks)
            else:
                no_chunk_ids.append(nid)

        chunk_pct = (nodes_with_chunks / total * 100) if total > 0 else 0
        if chunk_pct == 0:
            warnings.append(
                "CRITICAL: No nodes have chunks. Reasoning agents will have "
                "descriptions only — no evidence to cite. Add chunks via "
                "'properties.chunks' or use 'graph.rebuild_chunks()'."
            )
        elif chunk_pct < 50:
            warnings.append(
                f"WARNING: Only {chunk_pct:.0f}% of nodes have chunks. "
                f"Agents without chunks produce lower-quality reasoning. "
                f"Nodes missing chunks: {no_chunk_ids[:10]}"
            )

        # Quality score: 0-100 (description 40% + chunks 40% + avg_len 20%)
        score = min(100, int(
            (pct_with * 0.4) +
            (chunk_pct * 0.4) +
            (min(avg_len, 200) / 200 * 20)
        ))

        result = {
            "total_nodes": total,
            "total_edges": len(self.edges),
            "nodes_with_descriptions": with_desc,
            "nodes_without_descriptions": len(no_desc_ids),
            "avg_description_length": round(avg_len, 1),
            "nodes_with_chunks": nodes_with_chunks,
            "nodes_without_chunks": len(no_chunk_ids),
            "total_chunks": total_chunks,
            "quality_score": score,
            "warnings": warnings,
        }

        if warnings:
            for w in warnings:
                logger.warning(w)
        else:
            logger.info(
                f"KG quality: {score}/100 — {with_desc}/{total} nodes with "
                f"descriptions (avg {avg_len:.0f} chars), "
                f"{nodes_with_chunks}/{total} nodes with chunks "
                f"({total_chunks} total)"
            )

        return result

    # ------------------------------------------------------------------
    # S6: ReasoningCoordinator integration helpers
    # ------------------------------------------------------------------

    async def _areason_coordinated(
        self,
        query: str,
        *,
        max_rounds: int,
        strategy: str,
        node_ids: list[str],
        context: Any,
        task_type: str | None,
    ) -> ReasoningResult:
        """Run reasoning via ReasoningCoordinator (S6 multi-agent coordination).

        Lazy-imports coordinator components to avoid circular imports.
        S7 will populate agent_roster from graph nodes; for now it is an
        empty placeholder so the coordinator skeleton can be exercised.
        """
        from graqle.reasoning.coordinator import (
            CoordinatorConfig as _CoordConfig,
            ReasoningCoordinator,
        )

        cfg = self.config.coordinator
        coord_config = _CoordConfig(
            COORDINATOR_DECOMPOSITION_PROMPT=cfg.decomposition_prompt or "Decompose the query.",
            COORDINATOR_SYNTHESIS_PROMPT=cfg.synthesis_prompt or "Synthesize the results.",
            max_specialists=cfg.max_specialists,
            specialist_timeout_seconds=cfg.specialist_timeout_seconds,
        )

        llm_backend = self._get_backend_for_node(
            node_ids[0] if node_ids else next(iter(self.nodes), ""),
            task_type=task_type,
        )

        # S7: Populate agent roster from activated graph nodes
        from graqle.core.agent_adapter import CogniNodeAgent

        agent_roster: list[Any] = []
        for nid in node_ids:
            node = self.nodes.get(nid)
            if node is not None:
                nid_backend = self._get_backend_for_node(nid, task_type=task_type)
                if nid_backend is not None:
                    agent_roster.append(CogniNodeAgent(node=node, backend=nid_backend))

        async with ReasoningCoordinator(
            llm_backend=llm_backend,
            agent_roster=agent_roster,
            config=coord_config,
        ) as coordinator:
            decomposition = await coordinator.decompose(query)
            results = await coordinator.dispatch(decomposition)
            synthesis = await coordinator.synthesize(results)

        # S7: Governance gate on coordinator synthesis output
        # TS-BLOCK is unconditional — never overridable (CC7.4)
        synthesis_text = getattr(synthesis, "merged_answer", "")
        governance_cfg = getattr(self.config, "governance", None)
        if governance_cfg is not None:
            try:
                from graqle.core.governance import GovernanceMiddleware
                gw = GovernanceMiddleware(governance_cfg)
                gate_result = gw.check(
                    content=synthesis_text,
                    action="reason",
                    risk_level="LOW",
                )
                if gate_result.blocked:
                    logger.warning("Coordinator synthesis blocked by governance: %s", gate_result.reason)
                    raise RuntimeError(f"Governance blocked coordinator output: {gate_result.reason}")
            except ImportError:
                pass  # governance module not available

        return self._synthesis_to_reasoning_result(synthesis, query, node_ids)

    def _synthesis_to_reasoning_result(
        self,
        synthesis: Any,
        query: str,
        node_ids: list[str],
    ) -> ReasoningResult:
        """Map SynthesisResult to ReasoningResult.

        Uses getattr with defaults for forward compatibility.
        """
        return ReasoningResult(
            query=query,
            answer=getattr(synthesis, "merged_answer", ""),
            confidence=0.0,
            rounds_completed=1,
            active_nodes=list(node_ids),
            message_trace=[],
            cost_usd=0.0,
            latency_ms=0.0,
            reasoning_mode="coordinator",
            metadata={"coordinator": True, "clearance": str(getattr(synthesis, "clearance", ""))},
        )

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

    def _get_task_router(self) -> Any:
        """Lazily create and return the task router from config."""
        if self._task_router is None:
            from graqle.routing import TaskRouter
            routing_cfg = self.config.routing
            config_dict: dict[str, Any] = {}
            if routing_cfg.default_provider:
                config_dict["default_provider"] = routing_cfg.default_provider
            if routing_cfg.default_model:
                config_dict["default_model"] = routing_cfg.default_model
            if routing_cfg.rules:
                config_dict["rules"] = [
                    {"task": r.task, "provider": r.provider,
                     "model": r.model, "reason": r.reason,
                     "region": getattr(r, "region", None),
                     "profile": getattr(r, "profile", None)}
                    for r in routing_cfg.rules
                ]
            self._task_router = TaskRouter.from_config(config_dict or None)
        return self._task_router

    def _get_backend_for_node(
        self, node_id: str, *, task_type: str | None = None,
    ) -> ModelBackend:
        """Get the model backend for a specific node.

        Bug 5 fix: If no backend is set, auto-create one from config.
        v0.22: If task_type is provided, check task-based routing first.
        """
        # v0.22: Task-based routing takes precedence over node-level assignment
        if task_type:
            router = self._get_task_router()
            routed = router.get_backend_for_task(task_type)
            if routed is not None:
                return routed

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
                from graqle.backends.api import AnthropicBackend
                api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
                if api_key:
                    return AnthropicBackend(model=model_name, api_key=api_key)
            elif backend_name == "openai":
                from graqle.backends.api import OpenAIBackend
                api_key = api_key or os.environ.get("OPENAI_API_KEY")
                if api_key:
                    return OpenAIBackend(model=model_name, api_key=api_key)
            elif backend_name == "bedrock":
                from graqle.backends.api import BedrockBackend
                region = getattr(cfg.model, "region", None) or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "eu-central-1"
                return BedrockBackend(model=model_name, region=region)
            elif backend_name == "ollama":
                from graqle.backends.api import OllamaBackend
                return OllamaBackend(model=model_name)
            elif backend_name == "gemini":
                from graqle.backends.gemini import GeminiBackend
                return GeminiBackend(model=model_name, api_key=api_key)
            else:
                # Check provider presets (groq, deepseek, together, etc.)
                from graqle.backends.providers import PROVIDER_PRESETS
                if backend_name in PROVIDER_PRESETS:
                    from graqle.backends.providers import create_provider_backend
                    return create_provider_backend(
                        backend_name, model=model_name, api_key=api_key
                    )
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
        task_type: str | None = None,
    ) -> ReasoningResult:
        """Run synchronous reasoning query (convenience wrapper).

        Args:
            context: Optional ``ReformulationContext`` from an AI tool
                     (Claude Code, Cursor, Codex) for query enhancement.
            task_type: Optional task type for routing (e.g. "reason", "context").
        """
        return asyncio.run(
            self.areason(
                query,
                max_rounds=max_rounds,
                strategy=strategy,
                node_ids=node_ids,
                context=context,
                task_type=task_type,
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
        task_type: str | None = None,
    ) -> ReasoningResult:
        """Run async reasoning query — the core entry point.

        Args:
            context: Optional ``ReformulationContext`` from an AI tool
                     (Claude Code, Cursor, Codex) for query enhancement
                     before PCST activation (ADR-104).
            task_type: Optional task type for task-based model routing (v0.22).
        """
        from graqle.orchestration.orchestrator import Orchestrator

        max_rounds = max_rounds or self.config.orchestration.max_rounds
        strategy = strategy or self.config.activation.strategy

        # PERF: Adaptive scaling for large KGs
        # Scale max_rounds for performance, but DON'T starve max_nodes —
        # multi-repo graphs need MORE nodes, not fewer, because cross-cutting
        # concerns span 40-60+ nodes across projects.
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

        # Detect multi-project graph and scale max_nodes UP, not down
        is_multi_project = any(
            "/" in nid for nid in list(self.nodes.keys())[:100]
        )
        configured_max = self.config.activation.max_nodes
        if is_multi_project and configured_max < 50:
            # Multi-repo graphs need more nodes for cross-cutting queries
            self.config.activation.max_nodes = max(configured_max, 50)
            logger.info(
                "Multi-project graph: raised activation max_nodes to %d",
                self.config.activation.max_nodes,
            )
        elif graph_size > 10000 and configured_max > 50:
            # Only cap for very large single-repo graphs
            self.config.activation.max_nodes = 50
            logger.info(
                "Large single-repo graph: capping activation max_nodes to 50"
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

        # Filter stale node IDs from embedding cache (Bug: dangling cache refs)
        node_ids = [nid for nid in node_ids if nid in self.nodes]

        # 1.5 ADR-151 SECURITY GATE (G1): Redact via node snapshots.
        # B1 fix: fail-CLOSED — security gate MUST load or operation blocks.
        # B2 fix: deep-copy nodes — never mutate originals across await.
        # Snapshots replace originals in self.nodes during reasoning,
        # then originals are restored. No mutation of original node objects.
        _original_nodes: dict[str, Any] = {}  # nid -> original node reference
        llm_redaction_cfg = getattr(self.config, "llm_redaction", None)
        if llm_redaction_cfg is None or llm_redaction_cfg.enabled:
            from graqle.security.content_gate import ContentSecurityGate

            _gate = ContentSecurityGate()

            for nid in node_ids:
                node = self.nodes[nid]
                _original_nodes[nid] = node  # save reference to original

                # B4 fix: full deepcopy isolates ALL mutable attributes
                # (properties, tags, metadata, embeddings, relations)
                snapshot = copy.deepcopy(node)

                # Redact snapshot via unified gate
                chunks_text = []
                for c in snapshot.properties.get("chunks", []):
                    if isinstance(c, dict):
                        chunks_text.append(c.get("text", ""))
                    elif isinstance(c, str):
                        chunks_text.append(c)

                safe_props, safe_desc, _ = _gate.prepare_node_for_llm(
                    snapshot.properties, snapshot.description or "", chunks_text,
                )
                snapshot.properties = safe_props
                snapshot.description = safe_desc

                # Swap: put snapshot in graph for orchestrator to use
                self.nodes[nid] = snapshot

        # 2. Assign backends to activated nodes
        for nid in node_ids:
            backend = self._get_backend_for_node(nid, task_type=task_type)
            self.nodes[nid].activate(backend)

        # S6: Coordinator feature-flag branch
        if self.config.coordinator.enabled:
            try:
                coord_result = await self._areason_coordinated(
                    query,
                    max_rounds=max_rounds,
                    strategy=strategy,
                    node_ids=node_ids,
                    context=context,
                    task_type=task_type,
                )
            except Exception as _coord_exc:  # noqa: BLE001
                # M2: Structured fallback logging for diagnostics
                import hashlib as _hl
                _qhash = _hl.md5(query.encode()).hexdigest()[:8]
                logger.warning(
                    "Coordinator path failed, falling back to orchestrator. "
                    "error=%s query_hash=%s node_count=%d coordinator_enabled=%s "
                    "max_specialists=%s timeout=%s",
                    _coord_exc,
                    _qhash,
                    len(node_ids) if node_ids else 0,
                    getattr(self.config.coordinator, "enabled", "?"),
                    getattr(self.config.coordinator, "max_specialists", "?"),
                    getattr(self.config.coordinator, "specialist_timeout_seconds", "?"),
                )
                coord_result = None

            if coord_result is not None:
                # Deactivate nodes, restore originals, record metrics, return early
                for nid in node_ids:
                    self.nodes[nid].deactivate()
                for nid, orig in _original_nodes.items():
                    self.nodes[nid] = orig
                coord_result.metadata["coordinator_path"] = True
                return coord_result

        # 3. Run orchestrator (with MasterObserver if configured)
        if self._orchestrator is None:
            # Create unified SkillPipeline (type-first, semantic fallback)
            skill_pipeline = None
            try:
                from graqle.ontology.domain_registry import DomainRegistry
                from graqle.ontology.domains import collect_all_skills, register_all_domains
                from graqle.ontology.skill_pipeline import SkillPipeline

                # Build registry with all available domains
                registry = DomainRegistry()
                skill_config = self.config.skills
                domain_filter = skill_config.domains or None
                register_all_domains(registry, only=domain_filter)

                # Create pipeline with config
                skill_pipeline = SkillPipeline(
                    mode=skill_config.mode,
                    max_per_node=skill_config.max_per_node,
                    use_titan=skill_config.use_titan,
                    registry=registry,
                )
                # Register all domain skills into the pipeline
                skill_pipeline.register_domain_skills(collect_all_skills(only=domain_filter))
            except Exception:
                # Fallback: try legacy SkillAdmin if pipeline fails
                try:
                    from graqle.ontology.skill_admin import SkillAdmin
                    skill_pipeline = SkillAdmin(use_titan=True)
                except Exception:
                    pass

            self._orchestrator = Orchestrator(
                config=self.config.orchestration,
                observer_config=self.config.observer,
                skill_admin=skill_pipeline,
            )

        result = await self._orchestrator.run(
            self, query, node_ids, max_rounds,
            relevance_scores=relevance_scores,
        )

        # 4. Deactivate nodes and restore originals (B2: snapshots discarded)
        for nid in node_ids:
            if nid in self.nodes:
                self.nodes[nid].deactivate()
        for nid, original in _original_nodes.items():
            self.nodes[nid] = original  # restore original, discard snapshot

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
        from graqle.orchestration.streaming import StreamingOrchestrator

        max_rounds = max_rounds or self.config.orchestration.max_rounds
        strategy = strategy or self.config.activation.strategy

        # Query reformulation (ADR-104)
        query = self._reformulate_query(query, context=context)

        if node_ids is None:
            node_ids = self._activate_subgraph(query, strategy)

        # Filter stale node IDs from embedding cache (Bug: dangling cache refs)
        node_ids = [nid for nid in node_ids if nid in self.nodes]

        # ADR-151 SECURITY GATE (G1): Redact before streaming (B1+B2 fix)
        _original_nodes_stream: dict[str, Any] = {}
        llm_redaction_cfg = getattr(self.config, "llm_redaction", None)
        if llm_redaction_cfg is None or llm_redaction_cfg.enabled:
            from graqle.security.content_gate import ContentSecurityGate

            _gate = ContentSecurityGate()

            for nid in node_ids:
                node = self.nodes[nid]
                _original_nodes_stream[nid] = node

                # B4 fix: full deepcopy isolates ALL mutable attributes
                snapshot = copy.deepcopy(node)

                chunks_text = []
                for c in snapshot.properties.get("chunks", []):
                    if isinstance(c, dict):
                        chunks_text.append(c.get("text", ""))
                    elif isinstance(c, str):
                        chunks_text.append(c)

                safe_props, safe_desc, _ = _gate.prepare_node_for_llm(
                    snapshot.properties, snapshot.description or "", chunks_text,
                )
                snapshot.properties = safe_props
                snapshot.description = safe_desc
                self.nodes[nid] = snapshot

        for nid in node_ids:
            backend = self._get_backend_for_node(nid)
            self.nodes[nid].activate(backend)

        streamer = StreamingOrchestrator(self, max_rounds=max_rounds, strategy=strategy)
        async for chunk in streamer.stream(query, active_node_ids=node_ids):
            yield chunk

        for nid in node_ids:
            self.nodes[nid].deactivate()

        # ADR-151 G1: Restore original nodes after streaming (B2)
        for nid, original in _original_nodes_stream.items():
            self.nodes[nid] = original

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
            from graqle.metrics import get_metrics

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
            logger.warning("Metrics recording failed: %s", e)

    def _record_activation_memory(
        self, query: str, node_ids: list[str], result: ReasoningResult,
    ) -> None:
        """Record activation patterns for cross-query learning (v0.12)."""
        try:
            from graqle.learning.activation_memory import ActivationMemory

            if self._activation_memory is None:
                self._activation_memory = ActivationMemory()
                self._activation_memory.load()

            self._activation_memory.record(query, node_ids, result)
        except Exception as e:
            logger.warning("Activation memory recording failed: %s", e)

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
                from graqle.activation.reformulator import QueryReformulator

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

        profile = self.config.models.get(profile_name)
        if profile is None:
            return None

        if profile.backend == "anthropic":
            from graqle.backends.api import AnthropicBackend
            return AnthropicBackend(model=profile.model, api_key=profile.api_key)
        elif profile.backend == "openai":
            from graqle.backends.api import OpenAIBackend
            return OpenAIBackend(model=profile.model, api_key=profile.api_key)
        elif profile.backend == "bedrock":
            from graqle.backends.api import BedrockBackend
            return BedrockBackend(model=profile.model)
        elif profile.backend == "ollama":
            from graqle.backends.api import OllamaBackend
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
                    from graqle.activation.cypher_activation import CypherActivation
                    from graqle.activation.embeddings import EmbeddingEngine

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
                    from graqle.activation.pcst import PCSTActivation

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
            from graqle.activation.adaptive import QueryComplexityScorer
            from graqle.activation.chunk_scorer import ChunkScorer

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
                # Use config-driven embedding engine factory (BUG-5 fix)
                # Routes to TitanV2Engine / EmbeddingEngine / SimpleEmbeddingEngine
                # based on graqle.yaml embeddings config
                _emb_engine = None
                try:
                    from graqle.activation.embeddings import create_embedding_engine
                    _emb_engine = create_embedding_engine(self.config)
                except Exception:
                    pass
                # Pass domain registry for skill-aware activation boost
                _domain_reg = None
                if self.config and self.config.activation.skill_aware:
                    try:
                        from graqle.ontology.domain_registry import DomainRegistry
                        from graqle.ontology.domains import register_all_domains
                        _domain_reg = DomainRegistry()
                        register_all_domains(_domain_reg)
                    except Exception:
                        _domain_reg = None
                self._activator = ChunkScorer(
                    embedding_engine=_emb_engine,
                    max_nodes=adaptive_max,
                    domain_registry=_domain_reg,
                )
            else:
                self._activator.max_nodes = adaptive_max

            # v0.12.1: Pass activation memory boosts if available
            activation_boosts = None
            try:
                from graqle.learning.activation_memory import ActivationMemory
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
                pattern = rf"(?:^|[\s\-_/\\.,;:\"'()]){_re.escape(bare)}(?:[\s\-_/\\.,;:\"'()]|$)"
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
        """Convenience: add a node from kwargs (used by graq learn and /learn API)."""
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

        Delegates to semantic_auto_connect() which uses a 3-tier fallback:
        Bedrock Titan V2 -> sentence-transformers -> keyword overlap.
        Returns number of edges added.
        """
        return self.semantic_auto_connect(new_node_ids)

    def semantic_auto_connect(
        self,
        new_node_ids: list[str],
        *,
        threshold: float = 0.7,
        max_edges: int = 20,
        method: str = "auto",
    ) -> int:
        """Semantic auto-connect using embedding similarity.

        Uses a 3-tier fallback chain for computing similarity:
        1. Bedrock Titan V2 embeddings (production, 1024-dim)
        2. sentence-transformers (local, 384-dim)
        3. keyword overlap (zero-dependency fallback)

        Args:
            new_node_ids: IDs of newly added nodes to connect.
            threshold: Cosine similarity threshold for creating edges (0.0-1.0).
            max_edges: Maximum number of auto-edges to create.
            method: "auto" (fallback chain), "bedrock", "transformers", or "keyword".

        Returns:
            Number of edges added.
        """
        import numpy as np

        engine = self._get_embedding_engine(method)

        # Collect candidate nodes with descriptions
        candidate_ids = [
            nid for nid in self.nodes
            if nid not in new_node_ids and self.nodes[nid].description
        ]
        new_ids_with_desc = [
            nid for nid in new_node_ids
            if nid in self.nodes and self.nodes[nid].description
        ]

        if not new_ids_with_desc or not candidate_ids:
            return 0

        # If using keyword fallback, delegate to legacy method
        if engine is None:
            return self._keyword_auto_connect(new_node_ids, max_edges=max_edges)

        # Compute embeddings for candidates (use cached when available)
        candidate_embeddings = self._get_or_compute_embeddings(
            candidate_ids, engine
        )
        new_embeddings = self._get_or_compute_embeddings(
            new_ids_with_desc, engine
        )

        # P4: dimension guard — catch mixed-dim graphs that predate v0.34.0 _meta
        all_embeddings = [e for e in candidate_embeddings + new_embeddings if e is not None]
        if all_embeddings:
            dims = {e.shape[0] for e in all_embeddings}
            if len(dims) > 1:
                from graqle.core.exceptions import EmbeddingDimensionMismatchError
                raise EmbeddingDimensionMismatchError(
                    stored_model="unknown", stored_dim=min(dims),
                    active_model=getattr(engine, "model_name", "unknown"),
                    active_dim=max(dims),
                )

        edges_added = 0
        for i, new_id in enumerate(new_ids_with_desc):
            new_emb = new_embeddings[i]
            if new_emb is None:
                continue

            # Score all candidates
            scored: list[tuple[str, float]] = []
            for j, cand_id in enumerate(candidate_ids):
                cand_emb = candidate_embeddings[j]
                if cand_emb is None:
                    continue
                # Skip if already connected
                if self.get_edges_between(new_id, cand_id):
                    continue
                sim = float(np.dot(new_emb, cand_emb) / (
                    np.linalg.norm(new_emb) * np.linalg.norm(cand_emb) + 1e-9
                ))
                if sim >= threshold:
                    scored.append((cand_id, sim))

            # Sort by similarity descending, connect top matches
            scored.sort(key=lambda x: x[1], reverse=True)
            for cand_id, sim in scored:
                if edges_added >= max_edges:
                    return edges_added
                self.add_edge_simple(new_id, cand_id, relation="SEMANTICALLY_RELATED")
                # Store similarity score on the edge
                edge_id = f"{new_id}___SEMANTICALLY_RELATED___{cand_id}"
                if edge_id in self.edges:
                    self.edges[edge_id].properties["similarity"] = round(sim, 4)
                edges_added += 1

        return edges_added

    def _get_embedding_engine(self, method: str = "auto"):
        """Get the best available embedding engine using fallback chain.

        Returns an engine with .embed(text) -> np.ndarray, or None for keyword fallback.
        """
        if method == "keyword":
            return None

        # Tier 1: Bedrock Titan V2
        if method in ("auto", "bedrock"):
            try:
                from graqle.activation.embeddings import TitanV2Engine
                engine = TitanV2Engine()
                # Test connectivity with a small embed
                engine.embed("test")
                logger.info("Semantic auto-connect: using Bedrock Titan V2")
                return engine
            except Exception as e:
                if method == "bedrock":
                    logger.error("Bedrock Titan V2 requested but unavailable: %s", e)
                    return None
                logger.debug("Bedrock Titan V2 unavailable: %s", e)

        # Tier 2: sentence-transformers
        if method in ("auto", "transformers"):
            try:
                from graqle.activation.embeddings import EmbeddingEngine
                engine = EmbeddingEngine()
                engine._load()
                if not engine._use_simple:
                    logger.info("Semantic auto-connect: using sentence-transformers")
                    return engine
                if method == "transformers":
                    logger.error("sentence-transformers requested but not installed")
                    return None
            except Exception as e:
                logger.debug("sentence-transformers unavailable: %s", e)

        # Tier 3: keyword fallback (return None signals keyword mode)
        logger.info("Semantic auto-connect: falling back to keyword overlap")
        return None

    def _get_or_compute_embeddings(
        self,
        node_ids: list[str],
        engine,
    ) -> list:
        """Get cached embeddings or compute new ones.

        Stores embeddings in node.properties['_embedding_cache'] to avoid
        recomputation across calls.
        """
        import hashlib

        import numpy as np

        results = []
        for nid in node_ids:
            node = self.nodes[nid]
            desc = node.description or ""
            if not desc:
                results.append(None)
                continue

            # P0: include model name in cache key so changing models invalidates stale vectors
            _engine_model = getattr(engine, "model_name", "unknown")
            content_hash = f"{_engine_model}:{hashlib.md5(desc.encode()).hexdigest()}"
            cached = node.properties.get("_embedding_cache")

            if cached and isinstance(cached, dict) and cached.get("hash") == content_hash:
                emb = np.array(cached["vector"], dtype=np.float32)
                results.append(emb)
            else:
                try:
                    emb = engine.embed(desc)
                    # Cache on the node (excluded from JSON serialization via _ prefix)
                    node.properties["_embedding_cache"] = {
                        "hash": content_hash,
                        "vector": emb.tolist(),
                    }
                    results.append(emb)
                except Exception as e:
                    logger.warning("Embedding failed for node %s: %s", nid, e)
                    results.append(None)

        return results

    def _keyword_auto_connect(
        self, new_node_ids: list[str], *, max_edges: int = 20
    ) -> int:
        """Legacy keyword-overlap auto-connect (fallback when no embeddings available)."""
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
                existing = self.get_edges_between(new_id, nid)
                if existing:
                    continue

                node_words = set(node.description.lower().split()) - stopwords
                overlap = new_words & node_words
                if len(overlap) >= 3:
                    self.add_edge_simple(new_id, nid, relation="RELATED_TO")
                    edges_added += 1
                    if edges_added >= max_edges:
                        return edges_added

        return edges_added

    def to_json(self, path: str) -> None:
        """Save the graph to a JSON file (node_link_data format).

        Uses file-level locking to prevent concurrent write corruption
        when multiple agents access the same graph file. Cross-platform:
        uses ``msvcrt`` on Windows and ``fcntl`` on Unix.

        Validates graph data before writing to prevent corruption (DF-005).
        """
        import json as _json
        from pathlib import Path as _Path

        G = self.to_networkx()

        # P1: write embedding provenance into graph metadata so from_json can validate
        try:
            from graqle.activation.embeddings import create_embedding_engine
            _emb_engine = create_embedding_engine(self.config)
            _model = getattr(_emb_engine, "model_name", "unknown")
            _dim_attr = getattr(_emb_engine, "_dim", None) or getattr(_emb_engine, "_dimension", None)
            if _dim_attr is None:
                # EmbeddingEngine: actual dim from config or default 384
                _cfg_dim = getattr(getattr(self.config, "embeddings", None), "dimension", 0)
                _dim_attr = _cfg_dim if _cfg_dim and _cfg_dim > 0 else 384
            G.graph["_meta"] = {
                "embedding_model": _model,
                "embedding_dim": int(_dim_attr),
                "graqle_version": getattr(__import__("graqle"), "__version__", "unknown"),
            }
        except Exception:
            pass  # Never block a save due to metadata failure

        data = nx.node_link_data(G, edges="links")

        # Validate before saving (DF-005: prevent MagicMock/corruption writes)
        _validate_graph_data(data, existing_path=path)

        content = _json.dumps(data, indent=2, default=str)

        file_path = _Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with file locking for multi-agent safety
        _write_with_lock(str(file_path), content)
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
            # Filter out keys already passed as named args to avoid
            # "got multiple values for keyword argument" when properties
            # contain 'relationship' or 'weight' (e.g. loaded from Neo4j).
            props = {k: v for k, v in edge.properties.items()
                     if k not in ("relationship", "weight")}
            G.add_edge(edge.source_id, edge.target_id,
                       relationship=edge.relationship, weight=edge.weight,
                       **props)
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

    def project_context(self) -> dict:
        """Return a snapshot of the active project identity and graph stats.

        Used by the server health endpoint and MCP initialize response to surface
        which project/graph is currently loaded.
        """
        from pathlib import Path

        cfg = self.config
        graph_path_raw = getattr(getattr(cfg, "graph", None), "path", None)
        graph_path: str | None = None
        project_name: str = getattr(cfg, "project_name", "") or ""
        source_mode: str = getattr(cfg, "source_mode", "auto") or "auto"

        if graph_path_raw:
            abs_path = Path(graph_path_raw).resolve()
            graph_path = str(abs_path)
            if not project_name:
                project_name = abs_path.parent.name or abs_path.stem
        elif not project_name:
            project_name = Path.cwd().name

        return {
            "project_name": project_name,
            "source_mode": source_mode,
            "graph_path": graph_path,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    def __repr__(self) -> str:
        domain = getattr(self.config, "domain", "unknown")
        return (
            f"Graqle(nodes={len(self.nodes)}, edges={len(self.edges)}, "
            f"config={domain})"
        )
