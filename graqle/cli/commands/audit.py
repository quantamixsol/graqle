"""graq audit — Deep health audit for knowledge graph chunk coverage.

Checks every node for proper chunk content, identifies hollow nodes
(description-only, no evidence), and reports chunk type distribution.
Optionally fixes issues with --fix.

This command was created after discovering that hand-built KGs can pass
validate() at 88% quality while having ZERO chunks, producing hollow
reasoning where agents have no evidence to cite.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.audit
# risk: LOW (impact radius: 4 modules)
# consumers: main, middleware, __init__, test_audit
# dependencies: __future__, pathlib, typing, typer, console
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from graqle.cli.console import create_console

console = create_console()


def audit_command(
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    graph_path: str = typer.Option(
        None, "--graph", "-g", help="Path to JSON graph file"
    ),
    fix: bool = typer.Option(
        False, "--fix", help="Auto-synthesize chunks for hollow nodes"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-node chunk details"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON (for CI/MCP integration)"
    ),
) -> None:
    """Deep health audit of knowledge graph chunk coverage.

    Goes beyond validate (which checks descriptions) to audit the actual
    evidence chunks that reasoning agents depend on. Catches hollow KGs
    where nodes have descriptions but no chunks.

    \b
    Examples:
        graq audit
        graq audit --graph cognigraph.json --verbose
        graq audit --fix            # auto-synthesize missing chunks
        graq audit --json           # machine-readable output
    """
    import json as _json

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

    # Load graph
    if graph_path and Path(graph_path).exists():
        graph = Graqle.from_json(graph_path)
    else:
        if Path(config).exists():
            cfg = GraqleConfig.from_yaml(config)
        else:
            cfg = GraqleConfig.default()
        graph = _load_graph_for_audit(cfg)

    if graph is None:
        console.print("[red]No graph found. Provide --graph or set up graqle.yaml[/red]")
        raise typer.Exit(1)

    # Run the audit
    report = _run_audit(graph)

    if json_output:
        print(_json.dumps(report, indent=2))
        return

    # Display rich output
    _display_report(report, verbose=verbose)

    # Fix if requested
    if fix and report["nodes_without_chunks"]:
        before = report["nodes_with_chunks"]
        rebuilt = graph.rebuild_chunks(force=False)
        after_report = _run_audit(graph)
        after = after_report["nodes_with_chunks"]
        console.print(
            f"\n[cyan]Auto-fix: {after - before} nodes gained chunks "
            f"({after}/{report['total_nodes']} now covered)[/cyan]"
        )

        # Save if changes were made
        if after > before and graph_path:
            graph.to_json(graph_path)
            console.print(f"[green]Saved to {graph_path}[/green]")

    # Exit code
    if report["health"] == "CRITICAL":
        raise typer.Exit(2)
    elif report["health"] == "WARNING":
        raise typer.Exit(1)


def _run_audit(graph: Any) -> dict[str, Any]:
    """Run a comprehensive chunk audit on a loaded Graqle graph."""
    total = len(graph.nodes)
    nodes_with_chunks = 0
    nodes_without_chunks = 0
    total_chunks = 0
    hollow_nodes: list[dict] = []
    chunk_type_counts: dict[str, int] = {}
    node_type_coverage: dict[str, dict] = {}

    for nid, node in graph.nodes.items():
        chunks = node.properties.get("chunks", [])
        etype = node.entity_type

        # Track per-entity-type coverage
        if etype not in node_type_coverage:
            node_type_coverage[etype] = {"total": 0, "with_chunks": 0, "total_chunks": 0}
        node_type_coverage[etype]["total"] += 1

        if chunks:
            nodes_with_chunks += 1
            total_chunks += len(chunks)
            node_type_coverage[etype]["with_chunks"] += 1
            node_type_coverage[etype]["total_chunks"] += len(chunks)

            # Count chunk types
            for chunk in chunks:
                ctype = chunk.get("type", "unknown") if isinstance(chunk, dict) else "raw"
                chunk_type_counts[ctype] = chunk_type_counts.get(ctype, 0) + 1
        else:
            nodes_without_chunks += 1
            has_desc = bool((node.description or "").strip())
            hollow_nodes.append({
                "id": nid,
                "type": etype,
                "has_description": has_desc,
                "has_file_path": bool(node.properties.get("file_path") or node.properties.get("source_file")),
                "description_length": len((node.description or "").strip()),
            })

    chunk_pct = (nodes_with_chunks / total * 100) if total > 0 else 0
    avg_chunks = (total_chunks / nodes_with_chunks) if nodes_with_chunks > 0 else 0

    # Determine health level
    if chunk_pct == 0:
        health = "CRITICAL"
    elif chunk_pct < 50:
        health = "WARNING"
    elif chunk_pct < 80:
        health = "MODERATE"
    else:
        health = "HEALTHY"

    # Identify fixable nodes (have description or file_path)
    fixable = sum(1 for h in hollow_nodes if h["has_description"] or h["has_file_path"])

    return {
        "total_nodes": total,
        "total_edges": len(graph.edges),
        "nodes_with_chunks": nodes_with_chunks,
        "nodes_without_chunks": nodes_without_chunks,
        "total_chunks": total_chunks,
        "chunk_coverage_pct": round(chunk_pct, 1),
        "avg_chunks_per_node": round(avg_chunks, 1),
        "chunk_types": chunk_type_counts,
        "node_type_coverage": node_type_coverage,
        "hollow_nodes": hollow_nodes,
        "fixable_nodes": fixable,
        "health": health,
    }


def _display_report(report: dict, verbose: bool = False) -> None:
    """Display audit report with Rich formatting."""
    health = report["health"]
    health_colors = {
        "CRITICAL": "red",
        "WARNING": "yellow",
        "MODERATE": "cyan",
        "HEALTHY": "green",
    }
    color = health_colors.get(health, "white")

    console.print("\n[bold]Chunk Health Audit[/bold]")
    console.print(f"  Nodes: {report['total_nodes']} | Edges: {report['total_edges']}")
    console.print(
        f"  Chunk coverage: [{color}]{report['chunk_coverage_pct']}%[/{color}] "
        f"({report['nodes_with_chunks']}/{report['total_nodes']} nodes)"
    )
    console.print(f"  Total chunks: {report['total_chunks']}")
    console.print(f"  Avg chunks/node: {report['avg_chunks_per_node']}")
    console.print(f"  Health: [{color}]{health}[/{color}]")

    # Chunk type distribution
    if report["chunk_types"]:
        console.print("\n[bold]Chunk Types:[/bold]")
        for ctype, count in sorted(report["chunk_types"].items(), key=lambda x: -x[1]):
            console.print(f"    {ctype}: {count}")

    # Per-entity-type coverage
    console.print("\n[bold]Coverage by Node Type:[/bold]")
    for etype, stats in sorted(report["node_type_coverage"].items()):
        pct = (stats["with_chunks"] / stats["total"] * 100) if stats["total"] > 0 else 0
        ecolor = "green" if pct >= 80 else "yellow" if pct >= 50 else "red"
        console.print(
            f"    {etype:20s} [{ecolor}]{stats['with_chunks']}/{stats['total']}[/{ecolor}] "
            f"({stats['total_chunks']} chunks)"
        )

    # Hollow nodes
    if report["hollow_nodes"]:
        console.print(
            f"\n[yellow]Hollow Nodes ({report['nodes_without_chunks']} total, "
            f"{report['fixable_nodes']} fixable with --fix):[/yellow]"
        )
        if verbose:
            for h in report["hollow_nodes"]:
                fix_hint = "file" if h["has_file_path"] else ("desc" if h["has_description"] else "manual")
                console.print(
                    f"    {h['id']:40s} [{h['type']:15s}] "
                    f"desc={h['description_length']:3d}ch  fix={fix_hint}"
                )
        else:
            console.print("    Use --verbose to see all hollow nodes")

    # Actionable advice
    if health == "CRITICAL":
        console.print(
            "\n[red bold]CRITICAL: No nodes have chunks. Reasoning will be hollow.[/red bold]"
        )
        console.print(
            "[red]Run 'graq audit --fix' to auto-synthesize from descriptions,[/red]"
        )
        console.print(
            "[red]or add chunks manually to your graqle.json nodes.[/red]"
        )
    elif health == "WARNING":
        console.print(
            "\n[yellow]WARNING: <50% chunk coverage. Run 'graq audit --fix' to improve.[/yellow]"
        )
    elif health == "HEALTHY":
        console.print("\n[green]KG is healthy for reasoning.[/green]")


def _load_graph_for_audit(cfg: Any) -> Any:
    """Load graph from config, same logic as validate command."""
    from graqle.core.graph import Graqle

    if cfg.graph.connector == "neo4j":
        return Graqle.from_neo4j(
            uri=cfg.graph.uri or "bolt://localhost:7687",
            username=cfg.graph.username or "neo4j",
            password=cfg.graph.password or "",
            database=cfg.graph.database or "neo4j",
            config=cfg,
        )

    if cfg.graph.connector == "networkx":
        p = Path("graqle.json")
        if p.exists():
            return Graqle.from_json(str(p), config=cfg)

    for candidate in ["graqle.json", "knowledge_graph.json", "graph.json", "cognigraph.json"]:
        if Path(candidate).exists():
            return Graqle.from_json(candidate, config=cfg)

    return None
