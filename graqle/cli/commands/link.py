"""graq link — Multi-project graph operations.

Merge multiple project KGs into a unified graph and create cross-project
edges. This enables Graqle reasoning across your entire ecosystem.

Examples:
    graq link merge project1/graqle.json project2/graqle.json -o merged.json
    graq link edge crawlq/tamr_sdk frictionmelt/retrieval --relation POWERS
    graq link stats merged.json
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from graqle.cli.console import ARROW, CHECK

link_app = typer.Typer(
    name="link",
    help="Multi-project graph operations — merge KGs and create cross-project edges.",
    no_args_is_help=True,
)

console = Console()


@link_app.command("merge")
def link_merge(
    graphs: list[str] = typer.Argument(..., help="Paths to graph JSON files to merge"),
    output: str = typer.Option("merged.json", "--output", "-o", help="Output merged graph path"),
    prefix_ids: bool = typer.Option(True, "--prefix/--no-prefix", help="Prefix node IDs with project name to avoid collisions"),
) -> None:
    """Merge multiple project KGs into a single unified graph.

    Each graph's nodes are optionally prefixed with the project directory
    name to prevent ID collisions (e.g. 'auth-lambda' → 'crawlq/auth-lambda').

    \b
    Examples:
        graq link merge project1/graqle.json project2/graqle.json
        graq link merge *.json --output unified.json --no-prefix
    """
    if len(graphs) < 2:
        console.print("[red]Need at least 2 graph files to merge.[/red]")
        raise typer.Exit(1)

    merged_nodes: list[dict] = []
    merged_links: list[dict] = []
    sources: list[dict] = []

    for gpath in graphs:
        p = Path(gpath)
        if not p.exists():
            console.print(f"[yellow]Skipping {gpath} — file not found[/yellow]")
            continue

        data = json.loads(p.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        links = data.get("links", data.get("edges", []))

        # Derive project prefix from parent dir or filename
        project_name = p.parent.name if p.parent.name != "." else p.stem
        if project_name in (".", ""):
            project_name = p.stem.replace("graqle", "default")

        node_id_map: dict[str, str] = {}

        for node in nodes:
            old_id = node.get("id", "")
            if prefix_ids and "/" not in old_id:
                new_id = f"{project_name}/{old_id}"
            else:
                new_id = old_id
            node_id_map[old_id] = new_id

            new_node = {**node, "id": new_id}
            # Tag with source project
            props = new_node.get("properties", {})
            if isinstance(props, dict):
                props["source_project"] = project_name
                new_node["properties"] = props
            merged_nodes.append(new_node)

        for link in links:
            src = link.get("source", "")
            tgt = link.get("target", "")
            new_link = {
                **link,
                "source": node_id_map.get(src, src),
                "target": node_id_map.get(tgt, tgt),
            }
            merged_links.append(new_link)

        sources.append({
            "project": project_name,
            "file": str(p),
            "nodes": len(nodes),
            "links": len(links),
        })

    # Deduplicate nodes by ID (last wins)
    seen_ids: dict[str, int] = {}
    deduped_nodes: list[dict] = []
    for node in merged_nodes:
        nid = node.get("id", "")
        if nid in seen_ids:
            deduped_nodes[seen_ids[nid]] = node
        else:
            seen_ids[nid] = len(deduped_nodes)
            deduped_nodes.append(node)

    merged_data = {
        "directed": True,
        "multigraph": False,
        "graph": {"merged_from": [s["project"] for s in sources]},
        "nodes": deduped_nodes,
        "links": merged_links,
    }

    Path(output).write_text(
        json.dumps(merged_data, indent=2, default=str), encoding="utf-8"
    )

    console.print(f"\n[bold green]{CHECK} Merged {len(sources)} projects[/bold green]")
    table = Table(title="Merge Summary")
    table.add_column("Project", style="cyan")
    table.add_column("Nodes", justify="right")
    table.add_column("Links", justify="right")
    for s in sources:
        table.add_row(s["project"], str(s["nodes"]), str(s["links"]))
    table.add_row("[bold]Total[/bold]", f"[bold]{len(deduped_nodes)}[/bold]", f"[bold]{len(merged_links)}[/bold]")
    console.print(table)
    console.print(f"  Output: [bold]{output}[/bold]")


@link_app.command("edge")
def link_edge(
    source: str = typer.Argument(..., help="Source node ID (can use project/node format)"),
    target: str = typer.Argument(..., help="Target node ID (can use project/node format)"),
    relation: str = typer.Option("POWERS", "--relation", "-r", help="Edge relation type"),
    weight: float = typer.Option(1.0, "--weight", "-w", help="Edge weight"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a cross-project edge between two nodes.

    Use project/node notation for clarity.

    \b
    Examples:
        graq link edge crawlq/tamr_sdk frictionmelt/retrieval --relation POWERS
        graq link edge graqle/reasoning tracegov/compliance --relation ENABLES
    """
    from graqle.core.graph import Graqle
    from graqle.config.settings import GraqleConfig

    p = Path(graph_path)
    if not p.exists():
        console.print(f"[red]Graph not found: {graph_path}[/red]")
        raise typer.Exit(1)

    config = GraqleConfig.default()
    config_file = Path("graqle.yaml")
    if config_file.exists():
        config = GraqleConfig.from_yaml(str(config_file))

    graph = Graqle.from_json(str(p), config=config)

    # Fuzzy-find source and target
    def _find(name: str) -> str | None:
        if name in graph.nodes:
            return name
        name_lower = name.lower()
        for nid in graph.nodes:
            if name_lower in nid.lower():
                return nid
        return None

    src_id = _find(source)
    tgt_id = _find(target)

    if not src_id:
        console.print(f"[red]Source node '{source}' not found in graph[/red]")
        raise typer.Exit(1)
    if not tgt_id:
        console.print(f"[red]Target node '{target}' not found in graph[/red]")
        raise typer.Exit(1)

    graph.add_edge_simple(src_id, tgt_id, relation=relation.upper(), weight=weight)
    graph.to_json(str(p))

    console.print(f"[green]{CHECK} Cross-project edge:[/green] {src_id} --[{relation}]{ARROW} {tgt_id}")
    console.print(f"  Weight: {weight}")


@link_app.command("stats")
def link_stats(
    graph_path: str = typer.Argument("graqle.json", help="Path to merged graph file"),
) -> None:
    """Show multi-project statistics for a merged graph.

    Displays per-project node counts, cross-project edges, and
    overall graph health.
    """
    p = Path(graph_path)
    if not p.exists():
        console.print(f"[red]Graph not found: {graph_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))

    # Count per-project nodes
    project_counts: dict[str, int] = {}
    for node in nodes:
        nid = node.get("id", "")
        if "/" in nid:
            project = nid.split("/")[0]
        else:
            props = node.get("properties", {})
            project = props.get("source_project", "unknown") if isinstance(props, dict) else "unknown"
        project_counts[project] = project_counts.get(project, 0) + 1

    # Count cross-project edges
    cross_edges = 0
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        src_proj = src.split("/")[0] if "/" in src else "default"
        tgt_proj = tgt.split("/")[0] if "/" in tgt else "default"
        if src_proj != tgt_proj:
            cross_edges += 1

    console.print(f"\n[bold]Multi-Project Graph Stats[/bold]")
    console.print(f"  File: {graph_path} ({p.stat().st_size / 1024 / 1024:.1f} MB)")
    console.print(f"  Total nodes: {len(nodes)}")
    console.print(f"  Total edges: {len(links)}")
    console.print(f"  Cross-project edges: {cross_edges}")

    if project_counts:
        table = Table(title="Per-Project Breakdown")
        table.add_column("Project", style="cyan")
        table.add_column("Nodes", justify="right")
        table.add_column("Share", justify="right")
        for proj, count in sorted(project_counts.items(), key=lambda x: -x[1]):
            pct = count / len(nodes) * 100 if nodes else 0
            table.add_row(proj, str(count), f"{pct:.1f}%")
        console.print(table)
