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
from pathlib import Path
from typing import Optional

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

    from graqle.core.graph import Graqle
    from graqle.config.settings import GraqleConfig

    # Load config
    cp = Path(config_path)
    config = GraqleConfig.from_yaml(str(cp)) if cp.exists() else GraqleConfig.default()

    # Load graph
    graph = Graqle.from_json(str(gp), config=config)

    _print(f"[bold cyan]Rebuilding chunks[/bold cyan] for {len(graph.nodes)} nodes...")
    if force:
        _print("[yellow]Force mode: re-reading ALL source files[/yellow]")

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

    # Save back to JSON
    _save_graph(graph, str(gp))

    _print(f"\n[green]Done![/green]")
    _print(f"  Nodes with chunks: {before_count} -> {after_count}")
    _print(f"  Nodes updated: {updated}")

    if after_count == 0:
        _print(
            "\n[yellow]Warning:[/yellow] No nodes have chunks. "
            "Make sure your nodes have 'source_file' or 'file_path' "
            "properties pointing to readable files."
        )


    # Rebuild embedding cache for fast query-time activation (v0.12.3)
    try:
        from graqle.activation.chunk_scorer import ChunkScorer
        scorer = ChunkScorer()
        scorer.build_cache(graph)
        _print(f"  [green]Embedding cache rebuilt[/green]")
    except Exception as exc:
        _print(f"  [dim]Embedding cache skipped: {exc}[/dim]")

    return updated


def _save_graph(graph: "Graqle", path: str) -> None:
    """Save graph back to JSON, preserving node_link format."""
    import networkx as nx

    G = graph.to_networkx()
    data = nx.node_link_data(G, edges="links")

    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
