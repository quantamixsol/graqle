"""graq rebuild — Rebuild chunks and evidence for all KG nodes.

Ensures every node has fresh chunks from its source files so that
reasoning agents have evidence to cite. Run this after:
  - Installing/upgrading GraQle
  - Changing source files in your project
  - Loading a KG that was built without chunks (e.g., hand-built KGs)

Usage:
    graq rebuild                          # rebuild missing chunks only
    graq rebuild --force                  # re-read ALL source files
    graq rebuild --graph my.json          # specify a different graph
    graq rebuild --re-embed               # dry-run: show what re-embed would do (safe)
    graq rebuild --re-embed --force       # actually re-embed all nodes (writes to disk)
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.rebuild
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, logging, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("graqle.cli.rebuild")


def rebuild_command(
    graph_path: str = "graqle.json",
    config_path: str = "graqle.yaml",
    force: bool = False,
    re_embed: bool = False,
) -> int:
    """Rebuild chunks for all nodes in the KG.

    If re_embed=True without force=True, runs a safe dry-run that shows what
    would happen without writing anything to disk. Pass force=True to commit.

    Returns the number of nodes updated.
    """
    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    def _print(msg: str) -> None:
        if console:
            console.print(msg)
        else:
            print(msg)

    gp = Path(graph_path)
    if not gp.exists():
        _print(f"[red]Graph file not found: {graph_path}[/red]")
        _print("Run [cyan]graq init[/cyan] first to create a graph.")
        return 0

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

    # Load config
    cp = Path(config_path)
    config = GraqleConfig.from_yaml(str(cp)) if cp.exists() else GraqleConfig.default()

    # Load graph
    graph = Graqle.from_json(str(gp), config=config)

    _print(f"[bold cyan]Rebuilding chunks[/bold cyan] for {len(graph.nodes)} nodes...")
    if force:
        _print("[yellow]Force mode: re-reading ALL source files[/yellow]")

    t0 = time.monotonic()

    # Count nodes with chunks before
    before_count = sum(
        1 for n in graph.nodes.values()
        if n.properties.get("chunks")
    )

    # Rebuild
    updated = graph.rebuild_chunks(force=force)

    # Count after
    after_count = sum(
        1 for n in graph.nodes.values()
        if n.properties.get("chunks")
    )

    chunk_time = time.monotonic() - t0

    # Save back to JSON
    _save_graph(graph, str(gp))

    _print("\n[green]Done![/green]")
    _print(f"  Nodes with chunks: {before_count} -> {after_count}")
    _print(f"  Nodes updated: {updated}")
    _print(f"  Chunk rebuild time: {chunk_time:.1f}s")

    if after_count == 0:
        _print(
            "\n[yellow]Warning:[/yellow] No nodes have chunks. "
            "Make sure your nodes have 'source_file' or 'file_path' "
            "properties pointing to readable files."
        )

    # Rebuild embedding cache for fast query-time activation (v0.12.3)
    # Use config-driven embedding engine (BUG-2 fix: respects graqle.yaml embeddings section)
    t1 = time.monotonic()
    try:
        from graqle.activation.chunk_scorer import ChunkScorer
        from graqle.activation.embeddings import create_embedding_engine, get_engine_info

        engine = create_embedding_engine(config)
        engine_info = get_engine_info(engine)
        scorer = ChunkScorer(embedding_engine=engine)
        scorer.build_cache(graph)

        embed_time = time.monotonic() - t1
        cache_path = Path(".graqle/chunk_embeddings.npz")
        cache_size = cache_path.stat().st_size / 1024 if cache_path.exists() else 0

        _print(f"  [green]Embedding cache rebuilt[/green]")
        _print(f"  Embedding backend: [cyan]{engine_info['backend']}[/cyan]")
        _print(f"  Embedding model: [cyan]{engine_info['model']}[/cyan] ({engine_info['dimension']}-dim)")
        _print(f"  Embedding time: {embed_time:.1f}s")
        _print(f"  Cache size: {cache_size:.0f}KB")
    except Exception as exc:
        _print(f"  [dim]Embedding cache skipped: {exc}[/dim]")

    # --re-embed: re-compute all node embeddings with the active engine.
    # graq_predict flagged this as CRITICAL risk without proper guards (2026-03-25).
    # Safety protocol enforced here:
    #   1. Dry-run by default (re_embed=True, force=False) — shows impact, writes nothing
    #   2. Dimension pre-check before skip_validation is honored
    #   3. Snapshot (graqle.json.bak) written before any disk write
    #   4. Restore snapshot on any exception during re-embed
    if re_embed:
        _re_embed_nodes(graph, str(gp), config, force, _print)

    total_time = time.monotonic() - t0
    _print(f"\n  [bold]Total rebuild time: {total_time:.1f}s[/bold]")

    return updated


def _re_embed_nodes(graph: Graqle, graph_path: str, config, force: bool, _print) -> None:
    """Re-embed all nodes with the currently active embedding engine.

    Dry-run by default. Pass force=True to actually write to disk.
    Safety guards per graq_predict analysis (2026-03-25, 79% confidence):
    - Dimension pre-check before any write
    - Snapshot before write, restore on failure
    """
    import shutil

    try:
        from graqle.activation.embeddings import create_embedding_engine, get_engine_info
    except ImportError as exc:
        _print(f"[red]--re-embed requires embedding deps: {exc}[/red]")
        _print("Install with: pip install 'graqle[embeddings]'")
        return

    engine = create_embedding_engine(config)
    engine_info = get_engine_info(engine)
    active_model = engine_info.get("model", "unknown")
    active_dim = int(engine_info.get("dimension", 0))

    # Dimension pre-check: compare against _meta stored in graph
    # This check runs BEFORE skip_validation — graq_predict flagged that
    # skip_validation removes the only reconciliation point if this is skipped.
    import json as _json
    gp = Path(graph_path)
    with open(gp, encoding="utf-8") as _f:
        _raw = _json.load(_f)
    stored_meta = (_raw.get("graph") or {}).get("_meta", {})
    stored_dim = int(stored_meta.get("embedding_dim", 0))
    stored_model = stored_meta.get("embedding_model", "unknown")

    node_count = len(graph.nodes)

    _print(f"\n[bold cyan]--re-embed analysis[/bold cyan]")
    _print(f"  Nodes to re-embed: [cyan]{node_count}[/cyan]")
    _print(f"  Stored model:  [dim]{stored_model}[/dim] ({stored_dim}-dim)")
    _print(f"  Active model:  [cyan]{active_model}[/cyan] ({active_dim}-dim)")

    if stored_dim > 0 and active_dim > 0 and stored_dim != active_dim:
        _print(
            f"\n[yellow]Dimension change detected:[/yellow] "
            f"{stored_dim}-dim → {active_dim}-dim. "
            "All stored embeddings will be replaced."
        )
    elif stored_model != active_model and stored_model != "unknown":
        _print(
            f"\n[yellow]Model change detected:[/yellow] "
            f"{stored_model} → {active_model}."
        )

    if not force:
        _print(
            "\n[yellow]DRY RUN — nothing written.[/yellow] "
            "Pass [cyan]--force[/cyan] to actually re-embed and save."
        )
        return

    # Live run: snapshot first, restore on any failure
    backup_path = str(gp) + ".bak"
    _print(f"\n  Snapshotting graph → [dim]{backup_path}[/dim]")
    shutil.copy2(str(gp), backup_path)

    _print(f"  Re-embedding [cyan]{node_count}[/cyan] nodes with [cyan]{active_model}[/cyan]...")
    try:
        re_embedded = 0
        for node in graph.nodes.values():
            desc = node.description or node.label
            if not desc:
                continue
            embedding = engine.embed(desc)
            node.properties["_embedding_cache"] = embedding.tolist()
            re_embedded += 1

        # Save via to_json (writes _meta with new model/dim, uses _write_with_lock)
        graph.to_json(str(gp))

        _print(f"  [green]Re-embedded {re_embedded} nodes.[/green]")
        _print(f"  Snapshot retained at [dim]{backup_path}[/dim] — delete when satisfied.")
    except Exception as exc:
        _print(f"\n[red]Re-embed failed: {exc}[/red]")
        _print(f"[yellow]Restoring snapshot from {backup_path}...[/yellow]")
        shutil.copy2(backup_path, str(gp))
        _print("[green]Snapshot restored. Graph is unchanged.[/green]")
        raise


def _save_graph(graph: Graqle, path: str) -> None:
    """Save graph back to JSON, preserving node_link format (atomic write)."""
    import networkx as nx
    from graqle.core.graph import _write_with_lock

    G = graph.to_networkx()
    data = nx.node_link_data(G, edges="links")
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    _write_with_lock(path, content)
