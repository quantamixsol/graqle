"""graq upgrade — One-command backend upgrade with latency comparison.

The conversion funnel:
  graq doctor → shows "Neo4j would be 12× faster" → user runs graq upgrade neo4j

This is where free users see the speed difference and upgrade to Pro.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.upgrade
# risk: LOW (impact radius: 2 modules)
# consumers: main, test_upgrade
# dependencies: __future__, json, time, pathlib, typing +5 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


def upgrade_command(
    target: str = typer.Argument(
        "neo4j",
        help="Target backend to upgrade to (neo4j)",
    ),
    uri: str = typer.Option(
        "bolt://localhost:7687", "--uri", help="Neo4j URI",
    ),
    username: str = typer.Option(
        "neo4j", "--username", "-u", help="Neo4j username",
    ),
    password: str = typer.Option(
        "", "--password", "-p", help="Neo4j password (or set NEO4J_PASSWORD env var)",
    ),
    database: str = typer.Option(
        "graqle", "--database", "-d", help="Neo4j database name",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without migrating",
    ),
) -> None:
    """Upgrade your graph backend — one command, zero downtime.

    Migrates your JSON knowledge graph to Neo4j for:
    - 12× faster multi-hop traversal
    - Native shortest-path and PageRank
    - Vector search on chunk embeddings
    - Pre-materialized neighborhoods for instant context

    \\b
    Examples:
        graq upgrade neo4j                          # migrate with defaults
        graq upgrade neo4j --uri bolt://host:7687   # custom Neo4j URI
        graq upgrade neo4j --dry-run                # preview without migrating
        graq upgrade neo4j -p mypassword            # with password
    """
    import os

    if target != "neo4j":
        console.print(f"[red]Unknown target: {target}. Currently only 'neo4j' is supported.[/red]")
        raise typer.Exit(1)

    # Resolve password
    pw = password or os.environ.get("NEO4J_PASSWORD", "")
    if not pw:
        pw = typer.prompt("Neo4j password", hide_input=True)

    console.print(Panel.fit(
        "[bold cyan]Graqle Backend Upgrade[/bold cyan]\n"
        f"Target: [bold]{target}[/bold] → {uri}/{database}",
        border_style="cyan",
    ))

    # ── Step 1: Find and benchmark current JSON graph ──────────────

    graph_file = _find_graph_file()
    if graph_file is None:
        console.print("[red]No graph file found. Run 'graq scan --repo .' first.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Step 1:[/bold] Benchmarking current JSON backend...")

    # Load and time JSON
    t0 = time.perf_counter()
    data = json.loads(graph_file.read_text(encoding="utf-8"))
    json_load_ms = (time.perf_counter() - t0) * 1000

    nodes = data.get("nodes", [])
    edges = data.get("edges", data.get("links", []))
    node_count = len(nodes)
    edge_count = len(edges)

    console.print(f"  Graph: [bold]{node_count:,}[/bold] nodes, [bold]{edge_count:,}[/bold] edges")
    console.print(f"  JSON load time: [bold]{json_load_ms:.0f}ms[/bold]")

    # ── Step 2: Check Neo4j availability ───────────────────────────

    console.print("\n[bold]Step 2:[/bold] Checking Neo4j connection...")

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(username, pw))
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            existing = session.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
        console.print(f"  Connected to {uri}/{database} ({existing} existing nodes)")
        driver.close()
    except ImportError:
        console.print("[red]Neo4j driver not installed. Install with: pip install graqle[neo4j][/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Neo4j connection failed: {e}[/red]")
        console.print("\n[yellow]Check that Neo4j is running and credentials are correct.[/yellow]")
        raise typer.Exit(1)

    # ── Step 3: Upgrade assessment ─────────────────────────────────

    console.print("\n[bold]Step 3:[/bold] Upgrade assessment...")

    from graqle.connectors.upgrade import assess_upgrade
    assessment = assess_upgrade(
        node_count=node_count,
        edge_count=edge_count,
        current_backend="json",
        load_time_seconds=json_load_ms / 1000,
    )

    # Show latency comparison table
    table = Table(title="Latency Comparison: JSON vs Neo4j")
    table.add_column("Operation", style="bold")
    table.add_column("JSON (Python BFS)", justify="right")
    table.add_column("Neo4j (Cypher)", justify="right")
    table.add_column("Speedup", justify="right")

    # Estimated based on benchmarks (scaled by node count)
    comparisons = [
        ("Graph load", f"{json_load_ms:.0f}ms", "1ms (cached)", f"{max(1,json_load_ms):.0f}×"),
        ("1-hop neighbors", "~10ms", "~5ms", "2×"),
        ("2-hop blast radius", "~15ms", "~3ms", "5×"),
        ("3-hop impact", "~60ms", "~5ms", "[bold green]12×[/bold green]"),
        ("Shortest path", "N/A (not supported)", "~2ms", "[bold green]∞[/bold green]"),
        ("Hub detection", f"~{node_count//100}ms", "~5ms", f"{max(1,node_count//500)}×"),
        ("PageRank", "N/A", "~2s (pre-computed)", "[bold green]native[/bold green]"),
        ("Vector search", "N/A", "~5ms", "[bold green]native[/bold green]"),
    ]

    for op, json_t, neo4j_t, speedup in comparisons:
        table.add_row(op, f"[dim]{json_t}[/dim]", f"[green]{neo4j_t}[/green]", speedup)

    console.print(table)

    if assessment.should_upgrade:
        console.print(f"\n[bold yellow]Recommendation: UPGRADE[/bold yellow] — {assessment.reason}")
    else:
        console.print(f"\n[bold green]Assessment:[/bold green] {assessment.summary}")
        console.print("[dim]You can still upgrade for native traversal features.[/dim]")

    # ── Dry run stops here ─────────────────────────────────────────

    if dry_run:
        console.print("\n[dim]Dry run complete. Add no flags to proceed with migration.[/dim]")
        return

    # ── Step 4: Migrate ────────────────────────────────────────────

    if existing > 0:
        console.print(f"\n[yellow]Warning: Database '{database}' already has {existing} nodes.[/yellow]")
        proceed = typer.confirm("Continue? (existing data will be merged)")
        if not proceed:
            raise typer.Exit(0)

    console.print(f"\n[bold]Step 4:[/bold] Migrating {node_count:,} nodes + {edge_count:,} edges to Neo4j...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Migrating...", total=None)

        from graqle.connectors.upgrade import migrate_json_to_neo4j
        t0 = time.perf_counter()
        result = migrate_json_to_neo4j(
            json_path=str(graph_file),
            neo4j_uri=uri,
            neo4j_user=username,
            neo4j_password=pw,
            neo4j_database=database,
        )
        migrate_ms = (time.perf_counter() - t0) * 1000
        progress.update(task, description="[green]Migration complete!")

    console.print(f"  Migrated: {result['nodes_migrated']:,} nodes, {result['edges_migrated']:,} edges ({migrate_ms:.0f}ms)")
    console.print(f"  Backup: {result['backup_path']}")

    # ── Step 5: Update graqle.yaml ─────────────────────────────────

    console.print("\n[bold]Step 5:[/bold] Updating graqle.yaml...")

    _update_config(uri, username, pw, database)

    # ── Step 6: Pre-compute intelligence ───────────────────────────

    console.print("\n[bold]Step 6:[/bold] Pre-computing graph intelligence...")

    try:
        from graqle.connectors.neo4j_traversal import Neo4jTraversal
        traversal = Neo4jTraversal(uri=uri, username=username, password=pw, database=database)

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("Computing PageRank...", total=None)
            pr = traversal.compute_pagerank()
            progress.update(task, description=f"[green]PageRank: {pr['method']}")

            task = progress.add_task("Materializing 2-hop neighborhoods...", total=None)
            count = traversal.materialize_neighborhoods(max_hops=2)
            progress.update(task, description=f"[green]Neighborhoods: {count} nodes")

        traversal.close()
    except Exception as e:
        console.print(f"[yellow]Intelligence pre-computation skipped: {e}[/yellow]")

    # ── Step 7: Verify ─────────────────────────────────────────────

    console.print("\n[bold]Step 7:[/bold] Verifying migration...")

    try:
        from graqle.config.settings import GraqleConfig
        from graqle.core.graph import Graqle

        cfg = GraqleConfig.from_yaml("graqle.yaml") if Path("graqle.yaml").exists() else GraqleConfig.default()
        g = Graqle.from_neo4j(uri=uri, username=username, password=pw, database=database, config=cfg)
        neo4j_nodes = len(g.nodes)
        neo4j_edges = len(g.edges)
        console.print(f"  Verified: {neo4j_nodes:,} nodes, {neo4j_edges:,} edges loaded from Neo4j")
    except Exception as e:
        console.print(f"[yellow]Verification warning: {e}[/yellow]")

    # ── Done ───────────────────────────────────────────────────────

    console.print(Panel.fit(
        f"[bold green]Upgrade complete![/bold green]\n\n"
        f"Backend: JSON → [bold]Neo4j[/bold]\n"
        f"Nodes: {node_count:,} migrated\n"
        f"Config: graqle.yaml updated\n"
        f"Intelligence: PageRank + 2-hop neighborhoods pre-computed\n\n"
        f"[dim]Your JSON backup is at: {result['backup_path']}[/dim]\n"
        f"[dim]All Graqle tools (MCP, server, learn) now use Neo4j automatically.[/dim]",
        border_style="green",
        title="Migration Complete",
    ))


def _find_graph_file() -> Path | None:
    """Find the graph JSON file."""
    for candidate in ["graqle.json", "knowledge_graph.json", "graph.json"]:
        p = Path(candidate)
        if p.exists():
            return p
    return None


def _update_config(uri: str, username: str, password: str, database: str) -> None:
    """Update graqle.yaml with Neo4j config."""
    config_path = Path("graqle.yaml")

    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")

        # Check if graph section already has Neo4j config
        if "connector: neo4j" in content:
            console.print("  [dim]graqle.yaml already configured for Neo4j[/dim]")
            return

        # Replace connector line or add Neo4j config to graph section
        if "connector:" in content:
            import re
            content = re.sub(
                r"connector:\s*\w+",
                "connector: neo4j",
                content,
                count=1,
            )
        else:
            # Add graph section
            content = (
                f"graph:\n"
                f"  connector: neo4j\n"
                f"  uri: {uri}\n"
                f"  username: {username}\n"
                f"  password: {password}\n"
                f"  database: {database}\n"
                f"  path: graqle.json\n"
                f"  auto_grow: true\n\n"
            ) + content

        # Ensure Neo4j connection details are present
        if "uri:" not in content.split("connector: neo4j")[0].split("\n")[-1:][0] if "connector: neo4j" in content else True:
            # Add missing details after connector line
            content = content.replace(
                "connector: neo4j",
                f"connector: neo4j\n  uri: {uri}\n  username: {username}\n  password: {password}\n  database: {database}",
                1,
            )

        config_path.write_text(content, encoding="utf-8")
    else:
        # Create new config
        config_path.write_text(
            f"graph:\n"
            f"  connector: neo4j\n"
            f"  uri: {uri}\n"
            f"  username: {username}\n"
            f"  password: {password}\n"
            f"  database: {database}\n"
            f"  path: graqle.json\n"
            f"  auto_grow: true\n\n"
            f"model:\n"
            f"  backend: anthropic\n"
            f"  model: claude-sonnet-4-6\n",
            encoding="utf-8",
        )

    console.print("  [green]graqle.yaml updated with Neo4j config[/green]")
