"""graq grow — incrementally update the knowledge graph.

Called automatically by the git post-commit hook. Can also be run manually.
This is the core of GraQle's promise: the graph adapts and grows with
every commit. It does an incremental scan + ingest + merge.

The grow command:
  1. Re-scans changed files (git diff of last commit)
  2. Re-ingests markdown KG sources
  3. Merges into existing graqle.json
  4. Updates metrics
  5. Runs in <2 seconds for typical commits

Usage:
    graq grow             # Interactive output
    graq grow --quiet     # Silent (for git hooks)
    graq grow --full      # Full rescan (not just diff)
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.grow
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, logging, subprocess, time +5 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

console = Console()
logger = logging.getLogger("graqle.cli.grow")


def _get_changed_files() -> list[str]:
    """Get files changed in the last git commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        pass
    return []


def _incremental_scan(root: Path, changed_files: list[str]) -> tuple[list[dict], list[dict]]:
    """Scan only changed source files and return new nodes + edges."""
    import re

    from graqle.cli.commands.init import _should_skip

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    py_exts = {".py"}
    js_exts = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    source_exts = py_exts | js_exts

    for rel_path in changed_files:
        fpath = root / rel_path
        if not fpath.exists() or not fpath.is_file():
            continue

        # Bug 14 fix: skip build output, node_modules, etc.
        if _should_skip(Path(rel_path)):
            continue

        file_id = rel_path.replace("\\", "/")

        if fpath.suffix in source_exts:
            entity_type = "PythonModule" if fpath.suffix in py_exts else "JSModule"
            nodes.append({
                "id": file_id,
                "label": fpath.stem,
                "type": entity_type,
                "description": f"{entity_type}: {rel_path}",
            })
            node_ids.add(file_id)

            # Directory node
            parts = Path(rel_path).parts
            if len(parts) > 1:
                dir_id = "/".join(parts[:-1])
                if dir_id not in node_ids:
                    nodes.append({
                        "id": dir_id,
                        "label": parts[-2],
                        "type": "Directory",
                        "description": f"Directory: {dir_id}",
                    })
                    node_ids.add(dir_id)
                edges.append({
                    "source": dir_id,
                    "target": file_id,
                    "relationship": "CONTAINS",
                })

            # Parse imports + function definitions + calls (v0.12)
            try:
                content = fpath.read_text(errors="ignore")
                if fpath.suffix in py_exts:
                    # Imports
                    for match in re.finditer(
                        r"(?:from|import)\s+([\w.]+)", content
                    ):
                        module = match.group(1)
                        if "." in module:
                            target = module.replace(".", "/") + ".py"
                            edges.append({
                                "source": file_id,
                                "target": target,
                                "relationship": "IMPORTS",
                            })
                    # Function definitions → DEFINES edges
                    for match in re.finditer(
                        r"(?:def|class)\s+(\w+)", content
                    ):
                        func_name = match.group(1)
                        func_id = f"{file_id}::{func_name}"
                        if func_id not in node_ids:
                            nodes.append({
                                "id": func_id,
                                "label": func_name,
                                "type": "Function",
                                "description": f"Function/Class {func_name} in {rel_path}",
                            })
                            node_ids.add(func_id)
                        edges.append({
                            "source": file_id,
                            "target": func_id,
                            "relationship": "DEFINES",
                        })
                elif fpath.suffix in js_exts:
                    # Imports
                    for match in re.finditer(
                        r"""(?:import|require)\s*\(?\s*['"]([./][^'"]+)['"]\s*\)?""",
                        content,
                    ):
                        edges.append({
                            "source": file_id,
                            "target": match.group(1),
                            "relationship": "IMPORTS",
                        })
                    # Function/component definitions → DEFINES edges
                    for match in re.finditer(
                        r"(?:function|const|class)\s+(\w+)", content
                    ):
                        func_name = match.group(1)
                        func_id = f"{file_id}::{func_name}"
                        if func_id not in node_ids:
                            nodes.append({
                                "id": func_id,
                                "label": func_name,
                                "type": "Function",
                                "description": f"Function/Component {func_name} in {rel_path}",
                            })
                            node_ids.add(func_id)
                        edges.append({
                            "source": file_id,
                            "target": func_id,
                            "relationship": "DEFINES",
                        })
            except Exception:
                pass

    return nodes, edges


def _resolve_backend(backend: str, config: str) -> str:
    """Resolve the effective write backend.

    'auto' derives from graqle.yaml graph.connector (neo4j -> 'neo4j', else
    'local'). An explicit value is validated. Returns 'local' or 'neo4j'.
    """
    backend = (backend or "auto").lower()
    if backend in ("local", "neo4j"):
        return backend
    if backend != "auto":
        raise typer.BadParameter(
            f"--backend must be auto|local|neo4j, got {backend!r}"
        )
    # auto: read graph.connector from config (best-effort; default local)
    try:
        from graqle.config.settings import GraqleConfig
        cfg_path = Path(config)
        if cfg_path.exists():
            cfg = GraqleConfig.from_yaml(cfg_path)
            connector = getattr(getattr(cfg, "graph", None), "connector", None)
            if connector == "neo4j":
                return "neo4j"
    except Exception as exc:  # noqa: BLE001 — config read is best-effort
        logger.info("Backend auto-resolve fell back to local (%s)", exc)
    return "local"


def _embed_local(graph_path: Path, changed_node_ids: set[str], quiet: bool) -> None:
    """Incrementally embed changed nodes into .graqle/chunk_embeddings.npz.

    Loud-on-real-error, quiet-on-expected-degradation (v0.63.0 §3.3a). Never
    blocks the grow: embedding failure logs and returns.
    """
    try:
        from graqle.activation.chunk_scorer import ChunkScorer
        from graqle.core.graph import Graqle

        graph = Graqle.from_json(str(graph_path))
        scorer = ChunkScorer()
        stats = scorer.update_cache_incremental(graph, changed_node_ids)
        if not quiet:
            console.print(
                f"[dim]Embedded {stats['reembedded_nodes']} changed node(s): "
                f"+{stats['reembedded_chunks']} chunk(s), "
                f"+{stats['reembedded_descs']} desc(s)"
                f"{' (full rebuild)' if stats.get('rebuilt_full') else ''}[/dim]"
            )
    except Exception as exc:  # noqa: BLE001
        # Loud — the user must SEE embedding failed (anti-silent-fail guard).
        logger.warning(
            "Local embedding failed (%s: %s) — graph written but new nodes "
            "are not yet queryable by semantic search. Re-run with --embed "
            "once the cause is fixed.",
            type(exc).__name__, exc,
        )
        if not quiet:
            console.print(
                f"[yellow]Embedding skipped: {type(exc).__name__}: {exc}[/yellow]"
            )


def _write_neo4j(
    merged: dict[str, Any],
    new_node_ids: set[str],
    embed: bool,
    config: str,
    quiet: bool,
) -> None:
    """Write merged graph (and optionally embedded new chunks) to Neo4j.

    Graceful-but-loud: if Neo4j is unreachable the caller still writes
    graqle.json, so work is never lost. Connection-unavailable is logged
    INFO once (not WARNING-per-grow) to avoid CI noise (§3.3a).
    """
    try:
        from graqle.config.settings import GraqleConfig
        from graqle.connectors.neo4j import Neo4jConnector

        cfg_path = Path(config)
        cfg = GraqleConfig.from_yaml(cfg_path) if cfg_path.exists() else None
        graph_cfg = getattr(cfg, "graph", None) if cfg else None
        # Only pass keys that are actually set so Neo4jConnector's own
        # defaults (bolt://localhost:7687, user neo4j, db neo4j) apply when
        # config is silent. Passing None would clobber those defaults.
        conn_kwargs: dict[str, Any] = {}
        for cfg_key, arg_key in (
            ("uri", "uri"), ("username", "username"),
            ("password", "password"), ("database", "database"),
        ):
            val = getattr(graph_cfg, cfg_key, None)
            if val is not None:
                conn_kwargs[arg_key] = val
        connector = Neo4jConnector(**conn_kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Neo4j backend selected but connector unavailable (%s) — "
            "wrote graqle.json only; new nodes not in Neo4j until reachable.",
            exc,
        )
        return

    # Build nodes/edges dicts keyed by id from the merged graph.
    nodes = {n["id"]: n for n in merged.get("nodes", []) if "id" in n}
    edges = {
        e.get("id", f"{e['source']}->{e['target']}"): e
        for e in merged.get("links", merged.get("edges", []))
        if e.get("source") and e.get("target")
    }
    try:
        connector.save(nodes, edges)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Neo4j write unavailable (%s) — wrote graqle.json only.", exc
        )
        return

    if embed:
        try:
            embed_fn = _make_redacting_embed_fn()
            chunks_by_node = _chunks_for_nodes(nodes, new_node_ids)
            written = connector.save_chunks(chunks_by_node, embed_fn=embed_fn)
            if not quiet:
                console.print(f"[dim]Neo4j: +{written} embedded chunk(s)[/dim]")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Neo4j chunk embedding failed (%s: %s) — nodes/edges saved "
                "but new chunks not embedded in Neo4j.",
                type(exc).__name__, exc,
            )


def _chunks_for_nodes(
    nodes: dict[str, Any], new_node_ids: set[str]
) -> dict[str, list[dict]]:
    """Build {node_id: [chunk-dicts]} for the new nodes, for save_chunks().

    Falls back to a single description-chunk when a node has no explicit
    chunks (mirrors build_cache's desc-only path).
    """
    out: dict[str, list[dict]] = {}
    for nid in new_node_ids:
        node = nodes.get(nid)
        if node is None:
            continue
        props = node.get("properties", {}) if isinstance(node, dict) else {}
        chunks = props.get("chunks") or []
        if chunks:
            out[nid] = [c for c in chunks if isinstance(c, (dict, str))]
        else:
            desc = node.get("description", "") if isinstance(node, dict) else ""
            if desc:
                out[nid] = [{"text": desc, "type": "description"}]
    return out


def _make_redacting_embed_fn():
    """Return embed_fn(text) -> list[float] with R-SEC-1 redaction applied.

    Wraps EmbeddingEngine.embed and routes text through the same G4 gate
    used by ChunkScorer so SECRET+ content never reaches the embedding API.
    """
    from graqle.activation.chunk_scorer import ChunkScorer
    from graqle.activation.embeddings import EmbeddingEngine

    engine = EmbeddingEngine()

    def embed_fn(text: str) -> list:
        redacted = ChunkScorer._redact_texts_for_embedding([text])[0]
        vec = engine.embed(redacted)
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    return embed_fn


def grow_command(
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress output (for git hooks)"
    ),
    full: bool = typer.Option(
        False, "--full", "-f", help="Full rescan instead of incremental"
    ),
    config: str = typer.Option(
        "graqle.yaml", "--config", "-c", help="Config file path"
    ),
    embed: bool = typer.Option(
        True, "--embed/--no-embed",
        help="Embed new chunks so they're queryable by reasoning (default: on). "
             "Incremental — only changed nodes are re-embedded.",
    ),
    backend: str = typer.Option(
        "auto", "--backend",
        help="Where to write the graph: auto (from graqle.yaml graph.connector) "
             "| local (graqle.json) | neo4j",
    ),
) -> None:
    """Incrementally update the knowledge graph.

    Called automatically by the git post-commit hook. Scans changed files,
    re-ingests markdown KG sources, merges into graqle.json, embeds the new
    chunks, and writes to the configured backend (local JSON or Neo4j).

    \b
    Auto (git hook):
        graq grow --quiet

    \b
    Manual full rescan:
        graq grow --full

    \b
    Skip embedding (legacy v0.62.x behaviour):
        graq grow --no-embed

    \b
    Force a specific backend:
        graq grow --backend neo4j
    """
    root = Path(".").resolve()
    start = time.perf_counter()

    graph_path = root / "graqle.json"
    if not graph_path.exists():
        if not quiet:
            console.print("[yellow]No graqle.json found. Run 'graq init' first.[/yellow]")
        return

    # Load existing graph
    try:
        existing = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        if not quiet:
            console.print("[red]Failed to read graqle.json[/red]")
        return

    new_nodes: list[dict[str, Any]] = []
    new_links: list[dict[str, Any]] = []

    # ── Code scan (incremental or full) ──────────────────────────
    if full:
        # Full rescan
        try:
            from graqle.cli.commands.init import scan_repository
            graph_data = scan_repository(root)
            new_nodes.extend(graph_data.get("nodes", []))
            new_links.extend(graph_data.get("links", []))
        except Exception as e:
            if not quiet:
                console.print(f"[yellow]Full scan failed: {e}[/yellow]")
    else:
        # Incremental: only changed files
        changed = _get_changed_files()
        if changed:
            inc_nodes, inc_edges = _incremental_scan(root, changed)
            new_nodes.extend(inc_nodes)
            new_links.extend(inc_edges)

    # ── Knowledge ingestion ──────────────────────────────────────
    try:
        from graqle.cli.commands.ingest import (
            _discover_sources_auto,
            _discover_sources_from_config,
        )
        from graqle.ontology.markdown_parser import parse_and_infer

        config_path_obj = Path(config)
        kg_sources = _discover_sources_from_config(config_path_obj)
        if not kg_sources:
            kg_sources = _discover_sources_auto(root)

        if kg_sources:
            entities, edges_list = parse_and_infer(kg_sources)
            for e in entities:
                new_nodes.append(e.to_node_dict())
            for edge in edges_list:
                new_links.append({
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "relationship": edge.relationship,
                    "confidence": edge.confidence,
                    "source_file": edge.source_file,
                })
    except Exception:
        pass  # Ingestion is best-effort

    # ── Merge ────────────────────────────────────────────────────
    if not new_nodes and not new_links:
        if not quiet:
            console.print("[dim]No changes detected — graph unchanged.[/dim]")
        return

    from graqle.cli.commands.ingest import _merge_graphs
    merged = _merge_graphs(existing, new_nodes, new_links)
    stats = merged.pop("_merge_stats", {})

    # Write (atomic: temp file + rename to prevent data loss on MemoryError).
    # The graqle.json serialization is byte-for-byte unchanged from v0.62.x
    # (EG_15 guard) — embedding + Neo4j writes are sidecar/separate-store only.
    from graqle.core.graph import _write_with_lock
    content = json.dumps(merged, indent=2, default=str, ensure_ascii=False)
    _write_with_lock(str(graph_path), content)

    # v0.63.0: embed new chunks + write configured backend so new code is
    # actually queryable by reasoning (the end-to-end auto-grow fix).
    new_node_ids = {n["id"] for n in new_nodes if isinstance(n, dict) and "id" in n}
    resolved_backend = _resolve_backend(backend, config)
    if resolved_backend == "neo4j":
        _write_neo4j(merged, new_node_ids, embed=embed, config=config, quiet=quiet)
    if embed and new_node_ids:
        _embed_local(graph_path, new_node_ids, quiet=quiet)

    elapsed = time.perf_counter() - start

    # ── Update metrics ───────────────────────────────────────────
    try:
        from graqle.metrics.engine import MetricsEngine
        metrics = MetricsEngine(root / ".graqle")
        metrics.load()
        type_counts = Counter(n.get("type", "") for n in merged.get("nodes", []))
        metrics.graph_stats_current = {
            "nodes": len(merged.get("nodes", [])),
            "edges": len(merged.get("links", [])),
            "node_types": dict(type_counts.most_common()),
        }
        metrics.save()
    except Exception:
        pass

    if not quiet:
        added = stats.get("nodes_added", 0)
        updated = stats.get("nodes_updated", 0)
        edges_added = stats.get("edges_added", 0)
        total = len(merged.get("nodes", []))
        console.print(
            f"[green]Graph updated[/green] in {elapsed:.1f}s: "
            f"+{added} nodes, ~{updated} updated, +{edges_added} edges "
            f"({total} total)"
        )

    # Auto cloud sync (if authenticated — silent skip otherwise)
    try:
        from graqle.cli.commands.cloud import auto_cloud_sync
        auto_cloud_sync(root, quiet=quiet, graph_json=merged)
    except Exception:
        pass  # Cloud sync is non-blocking
