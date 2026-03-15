"""graq learned — List all KNOWLEDGE and manually-added LESSON nodes.

Shows what the graph has been taught via `graq learn knowledge` and
`graq learn entity/node` (manual nodes).

Examples:
    graq learned
    graq learned --domain brand
    graq learned --domain technical
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.learned
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, pathlib, typer, console, table
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def learned_command(
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    domain: str = typer.Option(None, "--domain", "-d", help="Filter by domain (e.g. brand, copy, product, market, technical)"),
) -> None:
    """List all KNOWLEDGE and manually-added LESSON nodes in the graph.

    Shows what the graph has been taught — useful for auditing learned
    facts, reviewing domain knowledge, and checking hit counts.
    """
    from graqle.core.graph import Graqle
    from graqle.config.settings import GraqleConfig

    config = GraqleConfig.default()
    config_file = Path("graqle.yaml")
    if config_file.exists():
        config = GraqleConfig.from_yaml(str(config_file))

    gpath = Path(graph_path)
    if not gpath.exists():
        console.print(f"[red]Graph file not found: {graph_path}[/red]")
        raise typer.Exit(1)

    graph = Graqle.from_json(str(gpath), config=config)

    # Collect KNOWLEDGE and LESSON nodes (also manually-added nodes)
    learned_nodes = []
    for nid, node in graph.nodes.items():
        etype = node.entity_type.upper() if node.entity_type else ""
        is_knowledge = etype == "KNOWLEDGE"
        is_lesson = etype == "LESSON"
        is_manual = node.properties.get("manual", False) if node.properties else False

        if not (is_knowledge or is_lesson or is_manual):
            continue

        node_domain = (node.properties or {}).get("domain", "")
        if domain and node_domain != domain:
            continue

        hit_count = (node.properties or {}).get("hit_count", 0)
        created = (node.properties or {}).get("created", "")
        desc = (node.description or "")[:80]

        learned_nodes.append({
            "id": nid,
            "type": etype,
            "domain": node_domain,
            "description": desc,
            "created": created,
            "hit_count": hit_count,
        })

    if not learned_nodes:
        if domain:
            console.print(f"[yellow]No learned nodes found for domain '{domain}'.[/yellow]")
        else:
            console.print("[yellow]No learned nodes found. Teach the graph with 'graq learn knowledge'.[/yellow]")
        return

    # Sort: KNOWLEDGE first, then LESSON, then manual; within each group by created desc
    type_order = {"KNOWLEDGE": 0, "LESSON": 1}
    learned_nodes.sort(key=lambda n: (type_order.get(n["type"], 2), n["created"]), reverse=True)

    table = Table(title=f"Learned Nodes ({len(learned_nodes)})")
    table.add_column("ID", style="cyan", max_width=40)
    table.add_column("Type", style="yellow")
    table.add_column("Domain", style="magenta")
    table.add_column("Description", max_width=50)
    table.add_column("Created", style="dim")
    table.add_column("Hits", style="green", justify="right")

    for n in learned_nodes:
        table.add_row(
            n["id"],
            n["type"],
            n["domain"],
            n["description"],
            n["created"],
            str(n["hit_count"]),
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(learned_nodes)} learned nodes in graph[/dim]")
