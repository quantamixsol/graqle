"""kogni learn — Teach the knowledge graph new concepts.

Adds business-level nodes, relationships, and context that code scanning
can't discover. The graph becomes self-discovering and self-evolving:
users seed high-level concepts, CogniGraph finds connections autonomously.

Examples:
    kogni learn node "auth-service" --type SERVICE --desc "Handles JWT auth"
    kogni learn node "revenue-goal" --type BUSINESS_OUTCOME --desc "Hit $1M ARR by Q3"
    kogni learn edge "auth-service" "user-db" --relation DEPENDS_ON
    kogni learn file notes.md --auto-connect
    kogni learn discover --from "auth-service"
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

learn_app = typer.Typer(
    name="learn",
    help="Teach the knowledge graph new concepts, relationships, and business context.",
    no_args_is_help=True,
)

console = Console()


def _load_graph(graph_path: str = "cognigraph.json"):
    """Load graph from JSON file."""
    from cognigraph.core.graph import CogniGraph
    from cognigraph.config.settings import CogniGraphConfig

    config = CogniGraphConfig.default()
    config_file = Path("cognigraph.yaml")
    if config_file.exists():
        config = CogniGraphConfig.from_yaml(str(config_file))

    gpath = Path(graph_path)
    if not gpath.exists():
        console.print(f"[red]Graph file not found: {graph_path}[/red]")
        raise typer.Exit(1)

    return CogniGraph.from_json(str(gpath), config=config), str(gpath)


@learn_app.command("node")
def learn_node(
    node_id: str = typer.Argument(..., help="Unique node ID"),
    node_type: str = typer.Option("CONCEPT", "--type", "-t", help="Entity type (e.g. SERVICE, PRODUCT, BUSINESS_OUTCOME, CLIENT)"),
    description: str = typer.Option("", "--desc", "-d", help="Node description"),
    label: str = typer.Option(None, "--label", "-l", help="Display label (defaults to node_id)"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
    auto_connect: bool = typer.Option(True, "--auto-connect/--no-auto-connect", help="Auto-discover edges"),
) -> None:
    """Add a new node to the knowledge graph.

    Business-level nodes like PRODUCT, BUSINESS_OUTCOME, CLIENT, TEAM
    give CogniGraph cross-cutting reasoning that pure code scanning misses.
    """
    graph, gpath = _load_graph(graph_path)

    if node_id in graph.nodes:
        console.print(f"[yellow]Node '{node_id}' already exists — updating.[/yellow]")

    graph.add_node_simple(
        node_id,
        label=label or node_id,
        entity_type=node_type.upper(),
        description=description,
        properties={"source": "kogni_learn", "manual": True},
    )

    auto_edges = 0
    if auto_connect and hasattr(graph, "auto_connect"):
        auto_edges = graph.auto_connect([node_id])

    graph.to_json(gpath)

    console.print(f"[green]✓ Added node:[/green] {node_id} ({node_type})")
    if description:
        console.print(f"  Description: {description}")
    if auto_edges:
        console.print(f"  [cyan]Auto-connected {auto_edges} edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("edge")
def learn_edge(
    source: str = typer.Argument(..., help="Source node ID"),
    target: str = typer.Argument(..., help="Target node ID"),
    relation: str = typer.Option("RELATES_TO", "--relation", "-r", help="Edge relation type"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a relationship between two nodes."""
    graph, gpath = _load_graph(graph_path)

    for nid in [source, target]:
        if nid not in graph.nodes:
            console.print(f"[red]Node '{nid}' not found in graph[/red]")
            raise typer.Exit(1)

    graph.add_edge_simple(source, target, relation=relation.upper())
    graph.to_json(gpath)

    console.print(f"[green]✓ Added edge:[/green] {source} —[{relation}]→ {target}")


@learn_app.command("file")
def learn_file(
    file_path: str = typer.Argument(..., help="Path to a markdown/text file with knowledge"),
    node_type: str = typer.Option("DOCUMENT", "--type", "-t", help="Entity type for file node"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
    auto_connect: bool = typer.Option(True, "--auto-connect/--no-auto-connect", help="Auto-discover edges"),
) -> None:
    """Learn from a file — extract concepts and add to graph.

    Reads markdown, text, or JSON files and creates nodes from their content.
    """
    fpath = Path(file_path)
    if not fpath.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    graph, gpath = _load_graph(graph_path)
    content = fpath.read_text(encoding="utf-8", errors="ignore")

    # Add the file as a node
    node_id = fpath.stem.replace(" ", "_").lower()
    graph.add_node_simple(
        node_id,
        label=fpath.name,
        entity_type=node_type.upper(),
        description=content[:500],  # First 500 chars as description
        properties={
            "source": "kogni_learn",
            "file_path": str(fpath),
            "content_length": len(content),
        },
    )

    auto_edges = 0
    if auto_connect and hasattr(graph, "auto_connect"):
        auto_edges = graph.auto_connect([node_id])

    graph.to_json(gpath)

    console.print(f"[green]✓ Learned from file:[/green] {fpath.name}")
    console.print(f"  Node: {node_id} ({node_type})")
    if auto_edges:
        console.print(f"  [cyan]Auto-connected {auto_edges} edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("entity")
def learn_entity(
    entity_id: str = typer.Argument(..., help="Unique entity ID (e.g. 'CrawlQ', 'Philips')"),
    entity_type: str = typer.Option("PRODUCT", "--type", "-t", help="Entity type: PRODUCT, CLIENT, BUSINESS_OUTCOME, TEAM, SYNERGY, MARKET"),
    description: str = typer.Option("", "--desc", "-d", help="Business description"),
    connects: str = typer.Option(None, "--connects", help="Comma-separated node IDs to connect to"),
    relation: str = typer.Option("RELATES_TO", "--relation", "-r", help="Edge relation for --connects"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a business-level entity to the knowledge graph.

    Code scanning discovers modules and files. This command adds the
    business context that code scanning can't: products, clients,
    outcomes, teams, synergies, and market segments.

    \b
    Examples:
        kogni learn entity "CrawlQ" --type PRODUCT --desc "Content ERP for enterprise"
        kogni learn entity "Philips" --type CLIENT --desc "75% content time reduction"
        kogni learn entity "content_compliance" --type SYNERGY --connects "CrawlQ,TracGov"
    """
    graph, gpath = _load_graph(graph_path)

    # Business types get special properties
    business_types = {"PRODUCT", "CLIENT", "BUSINESS_OUTCOME", "TEAM", "SYNERGY", "MARKET", "COMPETITOR", "METRIC"}
    etype = entity_type.upper()
    if etype not in business_types:
        console.print(f"[yellow]Note: '{etype}' is not a standard business type. Standard types: {', '.join(sorted(business_types))}[/yellow]")

    if entity_id in graph.nodes:
        console.print(f"[yellow]Entity '{entity_id}' already exists — updating.[/yellow]")

    graph.add_node_simple(
        entity_id,
        label=entity_id.replace("_", " ").title(),
        entity_type=etype,
        description=description,
        properties={
            "source": "kogni_learn_entity",
            "manual": True,
            "business_entity": True,
        },
    )

    edges_added = 0
    if connects:
        targets = [t.strip() for t in connects.split(",") if t.strip()]
        for target in targets:
            if target not in graph.nodes:
                # Fuzzy match
                matches = [nid for nid in graph.nodes if target.lower() in nid.lower()]
                if matches:
                    target = matches[0]
                    console.print(f"  [dim]Fuzzy matched → {target}[/dim]")
                else:
                    console.print(f"  [yellow]Skipping '{target}' — not found in graph[/yellow]")
                    continue
            graph.add_edge_simple(entity_id, target, relation=relation.upper())
            edges_added += 1

    auto_edges = 0
    if hasattr(graph, "auto_connect"):
        auto_edges = graph.auto_connect([entity_id])

    graph.to_json(gpath)

    console.print(f"[green]✓ Business entity added:[/green] {entity_id} ({etype})")
    if description:
        console.print(f"  Description: {description}")
    if edges_added:
        console.print(f"  [cyan]Connected to {edges_added} nodes via {relation}[/cyan]")
    if auto_edges:
        console.print(f"  [cyan]Auto-discovered {auto_edges} additional edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("knowledge")
def learn_knowledge(
    fact: str = typer.Argument(..., help="The knowledge to teach (e.g. 'Target audience is C-suite')"),
    domain: str = typer.Option("general", "--domain", "-d", help="Knowledge domain: brand, copy, product, market, technical"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags for retrieval"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Teach domain knowledge that can't be extracted from code.

    Unlike 'kogni learn node' which adds generic nodes, this creates
    KNOWLEDGE nodes with domain tagging for smarter retrieval during
    reasoning and preflight checks.

    \b
    Examples:
        kogni learn knowledge "Target audience is C-suite in regulated industries" --domain brand
        kogni learn knowledge "TAMR+ means intelligent document retrieval" --domain copy
        kogni learn knowledge "Free tier: 500 nodes, 3 queries/month" --domain product
    """
    from datetime import datetime, timezone

    graph, gpath = _load_graph(graph_path)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    node_id = f"knowledge_{domain}_{ts}"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    graph.add_node_simple(
        node_id,
        label=fact[:80],
        entity_type="KNOWLEDGE",
        description=fact,
        properties={
            "source": "kogni_learn_knowledge",
            "domain": domain,
            "tags": tag_list,
            "created": ts,
            "manual": True,
        },
    )

    # Auto-connect to existing nodes that share keywords
    auto_edges = 0
    if hasattr(graph, "auto_connect"):
        auto_edges = graph.auto_connect([node_id])

    graph.to_json(gpath)

    console.print(f"[green]✓ Knowledge taught:[/green] {fact[:60]}...")
    console.print(f"  Domain: {domain} | Node: {node_id}")
    if tag_list:
        console.print(f"  Tags: {', '.join(tag_list)}")
    if auto_edges:
        console.print(f"  [cyan]Auto-connected {auto_edges} edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("discover")
def learn_discover(
    from_node: str = typer.Option(None, "--from", "-f", help="Start discovery from this node"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
    depth: int = typer.Option(2, "--depth", help="Discovery depth (hops)"),
) -> None:
    """Auto-discover new connections and concepts in the graph.

    This is the self-evolving feature: CogniGraph analyzes existing nodes
    and suggests new nodes/edges that users haven't thought of.
    """
    graph, gpath = _load_graph(graph_path)

    # Find nodes with few connections (potential discovery targets)
    isolated = []
    for nid, node in graph.nodes.items():
        if node.degree <= 1:
            isolated.append((nid, node.entity_type, node.label))

    if from_node:
        if from_node not in graph.nodes:
            console.print(f"[red]Node '{from_node}' not found[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]Discovery from: {from_node}[/bold]")
        neighbors = graph.get_neighbors(from_node)
        console.print(f"  Current connections: {len(neighbors)}")

        # Suggest connections based on shared types
        node = graph.nodes[from_node]
        suggestions = []
        for nid, n in graph.nodes.items():
            if nid == from_node or nid in neighbors:
                continue
            # Same type = potential peer
            if n.entity_type == node.entity_type:
                suggestions.append((nid, "SAME_TYPE", n.label))
            # Description keyword overlap
            if node.description and n.description:
                node_words = set(node.description.lower().split())
                n_words = set(n.description.lower().split())
                overlap = node_words & n_words - {"the", "a", "an", "is", "in", "to", "of", "and", "for"}
                if len(overlap) >= 3:
                    suggestions.append((nid, "KEYWORD_OVERLAP", f"{len(overlap)} shared terms"))

        if suggestions[:10]:
            table = Table(title="Suggested Connections")
            table.add_column("Node ID", style="cyan")
            table.add_column("Reason", style="yellow")
            table.add_column("Detail")
            for nid, reason, detail in suggestions[:10]:
                table.add_row(nid, reason, detail)
            console.print(table)
        else:
            console.print("  [dim]No new connections suggested[/dim]")

    if isolated:
        console.print(f"\n[bold yellow]⚠ {len(isolated)} isolated nodes (≤1 connection):[/bold yellow]")
        for nid, ntype, label in isolated[:15]:
            console.print(f"  • {nid} ({ntype})")
        if len(isolated) > 15:
            console.print(f"  ... and {len(isolated) - 15} more")

    console.print(f"\n[dim]Graph: {len(graph)} nodes, use 'kogni learn edge' to add connections[/dim]")


@learn_app.command("batch")
def learn_batch(
    file_path: str = typer.Argument(..., help="JSON file with nodes and edges to add"),
    graph_path: str = typer.Option("cognigraph.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Batch learn from a JSON file.

    File format:
    {
        "nodes": [{"id": "...", "type": "...", "label": "...", "description": "..."}],
        "edges": [{"source": "...", "target": "...", "relation": "..."}]
    }
    """
    fpath = Path(file_path)
    if not fpath.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(fpath.read_text())
    graph, gpath = _load_graph(graph_path)

    nodes_added = 0
    for node_data in data.get("nodes", []):
        nid = node_data.get("id")
        if not nid:
            continue
        graph.add_node_simple(
            nid,
            label=node_data.get("label", nid),
            entity_type=node_data.get("type", "CONCEPT").upper(),
            description=node_data.get("description", ""),
            properties=node_data.get("properties", {}),
        )
        nodes_added += 1

    edges_added = 0
    for edge_data in data.get("edges", []):
        src = edge_data.get("source")
        tgt = edge_data.get("target")
        if src and tgt and src in graph.nodes and tgt in graph.nodes:
            graph.add_edge_simple(src, tgt, relation=edge_data.get("relation", "RELATES_TO").upper())
            edges_added += 1

    graph.to_json(gpath)

    console.print(f"[green]✓ Batch learned:[/green] {nodes_added} nodes, {edges_added} edges")
    console.print(f"  Graph: {len(graph)} nodes total")
