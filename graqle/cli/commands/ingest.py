"""graq ingest — extract knowledge from markdown KG files into a structured graph.

Parses markdown knowledge graph files (.gcc/departments/, .gcc/project-kg.md,
tasks/lessons-distilled.md, etc.), extracts entities and edges using a formal
ontology with SHACL-like validation, and produces a networkx-compatible JSON
graph file.

This is the core ingestion pipeline for Graqle:
  1. Discover source files (from graqle.yaml departments list, or .gcc/ scan)
  2. Parse each file with the context-aware markdown parser
  3. Deduplicate entities by ID
  4. Infer edges between entities from cross-references
  5. Merge with existing graqle.json (if --merge)
  6. Run SHACL validation
  7. Write output

Usage:
    graq ingest                          # Auto-discover sources, write graqle.json
    graq ingest --sources ".gcc/**/*.md" # Custom glob pattern
    graq ingest --no-validate            # Skip SHACL validation
    graq ingest --no-merge               # Replace instead of merge
    graq ingest --output graph.json      # Custom output path
    graq ingest --verbose                # Detailed extraction log
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
logger = logging.getLogger("graqle.cli.ingest")


# ---------------------------------------------------------------------------
# Source file discovery
# ---------------------------------------------------------------------------

def _discover_sources_from_config(config_path: Path) -> list[Path]:
    """Read graqle.yaml and extract department file paths."""
    sources: list[Path] = []
    if not config_path.exists():
        return sources

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return sources

    # Check for departments list in config
    departments = cfg.get("departments", [])
    if isinstance(departments, list):
        root = config_path.parent
        for dept in departments:
            if isinstance(dept, str):
                path = root / dept
                if path.exists():
                    sources.append(path)
            elif isinstance(dept, dict):
                file_path = dept.get("file", dept.get("path", ""))
                if file_path:
                    path = root / file_path
                    if path.exists():
                        sources.append(path)

    return sources


def _discover_sources_auto(root: Path) -> list[Path]:
    """Auto-discover markdown KG files in standard locations."""
    sources: list[Path] = []
    candidates: list[Path] = []

    # .gcc/departments/*.md
    dept_dir = root / ".gcc" / "departments"
    if dept_dir.is_dir():
        candidates.extend(sorted(dept_dir.glob("*-kg.md")))
        candidates.extend(sorted(dept_dir.glob("*_kg.md")))

    # .gcc/project-kg.md
    project_kg = root / ".gcc" / "project-kg.md"
    if project_kg.exists():
        candidates.append(project_kg)

    # tasks/lessons-distilled.md
    lessons = root / "tasks" / "lessons-distilled.md"
    if lessons.exists():
        candidates.append(lessons)

    # Fallback: any .md in .gcc/
    if not candidates:
        gcc_dir = root / ".gcc"
        if gcc_dir.is_dir():
            for md in sorted(gcc_dir.glob("*.md")):
                if md.name not in ("main.md", "registry.md"):
                    candidates.append(md)

    # Deduplicate
    seen: set[Path] = set()
    for c in candidates:
        resolved = c.resolve()
        if resolved not in seen:
            seen.add(resolved)
            sources.append(c)

    return sources


def _resolve_glob_sources(pattern: str, root: Path) -> list[Path]:
    """Resolve a glob pattern to a list of files."""
    sources: list[Path] = []
    for p in sorted(root.glob(pattern)):
        if p.is_file() and p.suffix.lower() == ".md":
            sources.append(p)
    return sources


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def _merge_graphs(existing: dict[str, Any], new_nodes: list[dict[str, Any]],
                  new_links: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge new nodes/links into an existing graph, updating existing nodes."""
    # Build index of existing nodes
    existing_nodes: dict[str, dict[str, Any]] = {}
    for node in existing.get("nodes", []):
        existing_nodes[node["id"]] = node

    # Build index of existing edges
    existing_edges: set[tuple[str, str, str]] = set()
    for link in existing.get("links", []):
        key = (link.get("source", ""), link.get("target", ""),
               link.get("relationship", ""))
        existing_edges.add(key)

    # Stats
    added = 0
    updated = 0
    edges_added = 0

    # Merge nodes
    for node in new_nodes:
        nid = node["id"]
        if nid in existing_nodes:
            # Update existing node (merge metadata)
            existing_nodes[nid].update(node)
            updated += 1
        else:
            existing_nodes[nid] = node
            added += 1

    # Merge edges
    merged_links = list(existing.get("links", []))
    for link in new_links:
        key = (link.get("source", ""), link.get("target", ""),
               link.get("relationship", ""))
        if key not in existing_edges:
            existing_edges.add(key)
            merged_links.append(link)
            edges_added += 1

    return {
        "directed": True,
        "multigraph": False,
        "graph": existing.get("graph", {}),
        "nodes": list(existing_nodes.values()),
        "links": merged_links,
        "_merge_stats": {
            "nodes_added": added,
            "nodes_updated": updated,
            "edges_added": edges_added,
        },
    }


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

def ingest_command(
    sources: str = typer.Option(
        "",
        "--sources", "-s",
        help="Glob pattern or comma-separated file paths to ingest. "
             "Default: auto-discover from graqle.yaml and .gcc/",
    ),
    output: str = typer.Option(
        "graqle.json",
        "--output", "-o",
        help="Output JSON file path",
    ),
    merge: bool = typer.Option(
        True,
        "--merge/--no-merge",
        help="Merge with existing graqle.json (default: merge)",
    ),
    validate: bool = typer.Option(
        True,
        "--validate/--no-validate",
        help="Run SHACL validation after ingestion (default: validate)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed extraction log",
    ),
    config: str = typer.Option(
        "graqle.yaml",
        "--config", "-c",
        help="Config file path",
    ),
) -> None:
    """Ingest markdown KG files into a structured Graqle knowledge graph.

    Parses markdown knowledge graph files, extracts entities and edges
    using a formal ontology with SHACL-like validation, and produces
    a networkx-compatible JSON graph.

    \b
    Auto-discover (default):
        graq ingest

    \b
    Custom sources:
        graq ingest --sources ".gcc/**/*.md"
        graq ingest --sources ".gcc/project-kg.md,tasks/lessons-distilled.md"

    \b
    Replace mode:
        graq ingest --no-merge
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    root = Path(".").resolve()
    config_path = Path(config)

    console.print(Panel(
        "[bold cyan]Graqle Knowledge Ingestion[/bold cyan]\n"
        "[dim]Extracting structured knowledge from markdown KG files[/dim]",
        border_style="cyan",
    ))

    # ── Step 1: Discover source files ─────────────────────────────────
    source_files: list[Path] = []

    if sources:
        # User-provided sources
        if "," in sources:
            for s in sources.split(","):
                p = Path(s.strip())
                if p.exists():
                    source_files.append(p)
                else:
                    console.print(f"  [yellow]Warning:[/yellow] File not found: {s.strip()}")
        elif "*" in sources:
            source_files = _resolve_glob_sources(sources, root)
        else:
            p = Path(sources)
            if p.exists():
                source_files.append(p)
            else:
                console.print(f"  [yellow]Warning:[/yellow] File not found: {sources}")
    else:
        # Auto-discover
        source_files = _discover_sources_from_config(config_path)
        if not source_files:
            source_files = _discover_sources_auto(root)

    if not source_files:
        console.print("[red]No source files found.[/red] Use --sources or set up .gcc/ directory.")
        raise typer.Exit(1)

    console.print(f"\n[bold]Step 1/4:[/bold] Discovered {len(source_files)} source file(s)")
    for sf in source_files:
        rel = sf.relative_to(root) if sf.is_relative_to(root) else sf
        console.print(f"  [dim]{rel}[/dim]")

    # ── Step 2: Parse files ───────────────────────────────────────────
    console.print(f"\n[bold]Step 2/4:[/bold] Parsing markdown files...")

    from graqle.ontology.markdown_parser import parse_and_infer, ExtractedEntity, ExtractedEdge

    start_time = time.perf_counter()
    entities, edges = parse_and_infer(source_files, verbose=verbose)
    parse_time = time.perf_counter() - start_time

    console.print(f"  Extracted [cyan]{len(entities)}[/cyan] entities, "
                  f"[cyan]{len(edges)}[/cyan] edges "
                  f"in {parse_time:.2f}s")

    if verbose:
        _print_entity_summary(entities)

    # ── Step 3: Build graph ───────────────────────────────────────────
    console.print(f"\n[bold]Step 3/4:[/bold] Building graph...")

    new_nodes = [e.to_node_dict() for e in entities]
    new_links = [
        {
            "source": edge.source_id,
            "target": edge.target_id,
            "relationship": edge.relationship,
            "confidence": edge.confidence,
            "source_file": edge.source_file,
        }
        for edge in edges
    ]

    out_path = Path(output)

    if merge and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            graph_data = _merge_graphs(existing, new_nodes, new_links)
            stats = graph_data.pop("_merge_stats", {})
            console.print(f"  Merged with existing graph: "
                          f"[green]+{stats.get('nodes_added', 0)}[/green] nodes added, "
                          f"[yellow]{stats.get('nodes_updated', 0)}[/yellow] updated, "
                          f"[green]+{stats.get('edges_added', 0)}[/green] edges added")
        except (json.JSONDecodeError, KeyError) as e:
            console.print(f"  [yellow]Warning:[/yellow] Could not parse existing {output}: {e}")
            console.print(f"  Creating new graph instead.")
            graph_data = _build_new_graph(new_nodes, new_links)
    else:
        graph_data = _build_new_graph(new_nodes, new_links)
        console.print(f"  Created new graph: "
                      f"[cyan]{len(graph_data['nodes'])}[/cyan] nodes, "
                      f"[cyan]{len(graph_data['links'])}[/cyan] edges")

    # ── Step 4: Validate ──────────────────────────────────────────────
    if validate:
        console.print(f"\n[bold]Step 4/4:[/bold] Running SHACL validation...")

        from graqle.ontology.schema import validate_graph

        report = validate_graph(graph_data)
        console.print(f"  {report.summary().replace(chr(10), ', ')}")

        if report.error_count > 0:
            console.print(f"  [red]{report.error_count} errors found[/red]")
            if verbose:
                for v in report.violations:
                    if v.severity == "ERROR":
                        console.print(f"    [red]ERROR[/red] {v.node_id}: {v.message}")
        elif report.warning_count > 0:
            console.print(f"  [yellow]{report.warning_count} warnings[/yellow] (non-blocking)")
            if verbose:
                for v in report.violations[:20]:
                    if v.severity == "WARNING":
                        console.print(f"    [yellow]WARN[/yellow] {v.node_id}: {v.message}")
        else:
            console.print(f"  [green]All nodes and edges valid[/green]")
    else:
        console.print(f"\n[bold]Step 4/4:[/bold] [dim]Validation skipped (--no-validate)[/dim]")

    # ── Write output ──────────────────────────────────────────────────
    out_path.write_text(
        json.dumps(graph_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )

    total_nodes = len(graph_data.get("nodes", []))
    total_edges = len(graph_data.get("links", []))

    console.print()
    console.print(Panel(
        f"[bold green]Ingestion complete[/bold green]\n\n"
        f"  Nodes: [cyan]{total_nodes}[/cyan]\n"
        f"  Edges: [cyan]{total_edges}[/cyan]\n"
        f"  Output: [dim]{out_path.resolve()}[/dim]\n\n"
        f"Next: [bold]graq context <service>[/bold] or [bold]graq inspect --stats[/bold]",
        border_style="green",
        title="Done",
    ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_new_graph(nodes: list[dict[str, Any]],
                     links: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a fresh networkx node_link_data graph."""
    return {
        "directed": True,
        "multigraph": False,
        "graph": {"source": "graq ingest"},
        "nodes": nodes,
        "links": links,
    }


def _print_entity_summary(entities: list[Any]) -> None:
    """Print a summary table of extracted entities by type."""
    from collections import Counter
    type_counts: Counter[str] = Counter()
    for e in entities:
        type_counts[e.node_type] += 1

    table = Table(title="Extracted Entity Types", show_header=True, header_style="bold cyan")
    table.add_column("Type", style="bold")
    table.add_column("Count", justify="right")

    for node_type, count in type_counts.most_common():
        table.add_row(node_type, str(count))

    table.add_row("[bold]Total[/bold]", f"[bold]{len(entities)}[/bold]")
    console.print(table)
