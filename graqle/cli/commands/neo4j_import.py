"""Neo4j import command — transfer graqle.json KG to Neo4j.

Reads the local graqle.json knowledge graph and batch-writes all nodes
and edges to Neo4j using the existing Neo4jConnector.create_schema() /
save() / health_check() API.  Handles the 64 K-node / 108 K-edge scale
of the production Graqle KG.

Usage:
    graq neo4j-import                         # uses env vars + graqle.json
    graq neo4j-import --dry-run               # stats only, no write
    graq neo4j-import --batch-size 200        # smaller batches
    graq neo4j-import --skip-schema           # skip IF schema already exists
    graq neo4j-import --kg-file /path/to.json # explicit KG file

Environment variables (all optional, shown with defaults):
    NEO4J_URI       bolt://localhost:7687
    NEO4J_USERNAME  neo4j
    NEO4J_PASSWORD  (empty — set this before running)
    NEO4J_DATABASE  neo4j
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.neo4j_import
# risk: LOW
# dependencies: json, os, pathlib, typing, typer, rich, graqle.connectors.neo4j
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_connector():
    """Build Neo4jConnector from env vars. Raises ImportError if driver missing."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    from graqle.connectors.neo4j import Neo4jConnector  # lazy — requires graqle[neo4j]

    return Neo4jConnector(
        uri=uri,
        username=username,
        password=password,
        database=database,
    )


def _load_kg(kg_file: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load graqle.json; returns (nodes_dict, edges_dict).

    Raises typer.Exit(1) with a user-friendly message on any parse error.
    """
    console.print(f"[dim]Loading KG from {kg_file} …[/dim]")
    try:
        with kg_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        console.print(f"[red]✗ graqle.json is not valid JSON: {exc}[/red]")
        console.print(f"  File: {kg_file}")
        raise typer.Exit(1)
    except OSError as exc:
        console.print(f"[red]✗ Cannot read KG file: {exc}[/red]")
        raise typer.Exit(1)

    # graqle.json top-level keys: "nodes" (dict[id→data]) and "edges" (dict[id→data])
    nodes: dict[str, Any] = data.get("nodes", {})
    edges: dict[str, Any] = data.get("edges", {})

    if not nodes:
        console.print("[yellow]⚠ No nodes found in KG file — nothing to import.[/yellow]")

    return nodes, edges


def _batch_save_nodes(connector, nodes: dict[str, Any], batch_size: int) -> int:
    """Write nodes in batches; returns count written. Raises on connector error."""
    items = list(nodes.items())
    total = len(items)
    written = 0
    failed_batches: list[str] = []

    with Progress(
        TextColumn("[bold green]Nodes"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("writing", total=total)
        for i in range(0, total, batch_size):
            chunk_items = items[i : i + batch_size]
            chunk_nodes = {nid: ndata for nid, ndata in chunk_items}
            try:
                connector.save(chunk_nodes, {})
                written += len(chunk_items)
            except Exception as exc:
                batch_label = f"batch {i // batch_size + 1} (nodes {i}–{i + len(chunk_items) - 1})"
                failed_batches.append(f"{batch_label}: {exc}")
                console.print(f"[yellow]  ⚠ {batch_label} failed — skipping[/yellow]")
            progress.update(task, advance=len(chunk_items))

    if failed_batches:
        console.print(f"[yellow]⚠ {len(failed_batches)} node batch(es) failed:[/yellow]")
        for msg in failed_batches:
            console.print(f"  • {msg}")

    return written


def _batch_save_edges(connector, edges: dict[str, Any], batch_size: int) -> int:
    """Write edges in batches; returns count written. Reports failures per-batch."""
    items = list(edges.items())
    total = len(items)
    written = 0
    failed_batches: list[str] = []

    with Progress(
        TextColumn("[bold cyan]Edges"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("writing", total=total)
        for i in range(0, total, batch_size):
            chunk_items = items[i : i + batch_size]
            chunk_edges = {eid: edata for eid, edata in chunk_items}
            try:
                connector.save({}, chunk_edges)
                written += len(chunk_items)
            except Exception as exc:
                batch_label = f"batch {i // batch_size + 1} (edges {i}–{i + len(chunk_items) - 1})"
                failed_batches.append(f"{batch_label}: {exc}")
                console.print(f"[yellow]  ⚠ {batch_label} failed — skipping[/yellow]")
            progress.update(task, advance=len(chunk_items))

    if failed_batches:
        console.print(f"[yellow]⚠ {len(failed_batches)} edge batch(es) failed:[/yellow]")
        for msg in failed_batches:
            console.print(f"  • {msg}")

    return written


def _validate(connector, expected_nodes: int, expected_edges: int) -> bool:
    """Query Neo4j counts and print validation table. Returns True if node count matches."""
    health = connector.health_check()
    actual_nodes = health.get("node_count")
    vi_state = health.get("vector_index_state", "?")

    t = Table(title="Neo4j Validation")
    t.add_column("Entity", style="cyan")
    t.add_column("Expected", style="yellow")
    t.add_column("Actual", style="magenta")
    t.add_column("Status", style="bold")

    node_ok = isinstance(actual_nodes, int) and actual_nodes == expected_nodes
    t.add_row(
        "Nodes",
        f"{expected_nodes:,}",
        f"{actual_nodes:,}" if isinstance(actual_nodes, int) else str(actual_nodes),
        "[green]✓[/green]" if node_ok else "[red]✗[/red]",
    )
    t.add_row(
        "Edges (written)",
        f"{expected_edges:,}",
        "(see edge count above)",
        "[dim]~[/dim]",
    )
    t.add_row(
        "Vector index",
        "ONLINE",
        vi_state,
        "[green]✓[/green]" if vi_state == "ONLINE" else "[yellow]?[/yellow]",
    )
    console.print(t)

    if not node_ok:
        console.print(
            "[yellow]⚠ Node count mismatch — possible causes: MERGE deduplication "
            "on re-import, or some batches failed.[/yellow]"
        )
    return node_ok


# ── CLI command ───────────────────────────────────────────────────────────────

def neo4j_import_cmd(
    kg_file: Path = typer.Option(
        Path("graqle.json"),
        "--kg-file",
        "-f",
        help="Path to graqle.json knowledge graph",
    ),
    batch_size: int = typer.Option(
        500,
        "--batch-size",
        "-b",
        min=1,
        max=5000,
        help="Nodes/edges per Neo4j UNWIND batch (1–5000)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print stats and exit without writing to Neo4j",
    ),
    skip_schema: bool = typer.Option(
        False,
        "--skip-schema",
        help="Skip create_schema() — use if constraints/index already exist",
    ),
) -> None:
    """Transfer the local graqle.json knowledge graph to Neo4j.

    Reads NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE
    from the environment (shown with defaults in --help).

    Steps:
      1. Load graqle.json
      2. create_schema()  — idempotent: uniqueness constraints + vector index
      3. Batch-write nodes (UNWIND MERGE, --batch-size at a time)
      4. Batch-write edges
      5. Validate via health_check()
    """
    kg_path = kg_file if isinstance(kg_file, Path) else Path(kg_file)
    if not kg_path.exists():
        console.print(f"[red]✗ KG file not found: {kg_path}[/red]")
        console.print("  Run 'graq scan repo .' first, or pass --kg-file <path>.")
        raise typer.Exit(1)

    nodes, edges = _load_kg(kg_path)

    # ── Stats table ──────────────────────────────────────────────────────────
    t = Table(title="GraQle KG → Neo4j Transfer Plan")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="magenta")
    t.add_row("KG file", str(kg_path.resolve()))
    t.add_row("Nodes", f"{len(nodes):,}")
    t.add_row("Edges", f"{len(edges):,}")
    t.add_row("Batch size", f"{batch_size:,}")
    t.add_row("Node batches", f"{max(1, (len(nodes) + batch_size - 1) // batch_size):,}")
    t.add_row("Edge batches", f"{max(1, (len(edges) + batch_size - 1) // batch_size):,}")
    t.add_row("NEO4J_URI", os.environ.get("NEO4J_URI", "bolt://localhost:7687 (default)"))
    t.add_row("NEO4J_DATABASE", os.environ.get("NEO4J_DATABASE", "neo4j (default)"))
    t.add_row("NEO4J_PASSWORD set?", "yes" if os.environ.get("NEO4J_PASSWORD") else "[yellow]no — using empty string[/yellow]")
    console.print(t)

    if dry_run:
        console.print("[yellow]--dry-run: no data written.[/yellow]")
        raise typer.Exit(0)

    # ── Connect ──────────────────────────────────────────────────────────────
    console.print("[dim]Connecting to Neo4j …[/dim]")
    try:
        connector = _get_connector()
    except ImportError:
        console.print("[red]✗ neo4j driver not installed.[/red]")
        console.print("  Run: pip install graqle[neo4j]")
        raise typer.Exit(1)

    if not connector.validate():
        console.print("[red]✗ Neo4j connection failed.[/red]")
        console.print("  Check NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD and that Neo4j is running.")
        raise typer.Exit(1)

    console.print("[green]✓ Connected to Neo4j.[/green]")

    try:
        # ── Schema ───────────────────────────────────────────────────────────
        if not skip_schema:
            console.print("[dim]Creating schema (constraints + vector index) …[/dim]")
            try:
                connector.create_schema()
                console.print("[green]✓ Schema ready.[/green]")
            except Exception as exc:
                console.print(f"[yellow]⚠ Schema creation warning: {exc}[/yellow]")
                console.print("  Continuing — constraints may already exist.")

        # ── Nodes ─────────────────────────────────────────────────────────
        console.print(f"\n[bold]Writing {len(nodes):,} nodes …[/bold]")
        written_nodes = _batch_save_nodes(connector, nodes, batch_size)
        console.print(f"[green]✓ {written_nodes:,} / {len(nodes):,} nodes written.[/green]")

        # ── Edges ─────────────────────────────────────────────────────────
        console.print(f"\n[bold]Writing {len(edges):,} edges …[/bold]")
        written_edges = _batch_save_edges(connector, edges, batch_size)
        console.print(f"[green]✓ {written_edges:,} / {len(edges):,} edges written.[/green]")

        # ── Validate ──────────────────────────────────────────────────────
        console.print("\n[dim]Validating …[/dim]")
        ok = _validate(connector, len(nodes), len(edges))

        if ok:
            console.print("\n[bold green]✓ Transfer complete.[/bold green]")
            console.print(
                "\n[dim]Next: update graqle.yaml → graph.connector: neo4j "
                "then run 'graq doctor' to verify.[/dim]"
            )
        else:
            console.print(
                "\n[yellow]⚠ Transfer finished with warnings — review output above.[/yellow]"
            )
            raise typer.Exit(2)

    finally:
        if "connector" in dir():
            try:
                connector.close()
            except Exception:
                pass
