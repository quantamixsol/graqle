"""graq rebuild — Rebuild chunks and evidence for all KG nodes.

Ensures every node has fresh chunks from its source files so that
reasoning agents have evidence to cite. Run this after:
  - Installing/upgrading Graqle
  - Changing source files in your project
  - Loading a KG that was built without chunks (e.g., hand-built KGs)

Usage:
    graq rebuild                     # rebuild missing chunks only
    graq rebuild --force             # re-read ALL source files
    graq rebuild --graph my.json     # specify a different graph
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
) -> int:
    """Rebuild chunks for all nodes in the KG.

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

    total_time = time.monotonic() - t0
    _print(f"\n  [bold]Total rebuild time: {total_time:.1f}s[/bold]")

    return updated


def _save_graph(graph: Graqle, path: str) -> None:
    """Save graph back to JSON, preserving node_link format."""
    import networkx as nx

    G = graph.to_networkx()
    data = nx.node_link_data(G, edges="links")

    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
