"""graq grow — incrementally update the knowledge graph.

Called automatically by the git post-commit hook. Can also be run manually.
This is the core of Graqle's promise: the graph adapts and grows with
every commit. It does an incremental scan + ingest + merge.

The grow command:
  1. Re-scans changed files (git diff of last commit)
  2. Re-ingests markdown KG sources
  3. Merges into existing graqle.json
  4. Updates metrics
  5. Runs in <2 seconds for typical commits

Usage:
    graq grow             # Interactive output
    graq grow --quiet     # Silent (for git hooks)
    graq grow --full      # Full rescan (not just diff)
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.grow
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, logging, subprocess, time +5 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

console = Console()
logger = logging.getLogger("graqle.cli.grow")


def _get_changed_files() -> list[str]:
    """Get files changed in the last git commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        pass
    return []


def _incremental_scan(root: Path, changed_files: list[str]) -> tuple[list[dict], list[dict]]:
    """Scan only changed source files and return new nodes + edges."""
    import re

    from graqle.cli.commands.init import _should_skip

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    py_exts = {".py"}
    js_exts = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    source_exts = py_exts | js_exts

    for rel_path in changed_files:
        fpath = root / rel_path
        if not fpath.exists() or not fpath.is_file():
            continue

        # Bug 14 fix: skip build output, node_modules, etc.
        if _should_skip(Path(rel_path)):
            continue

        file_id = rel_path.replace("\\", "/")

        if fpath.suffix in source_exts:
            entity_type = "PythonModule" if fpath.suffix in py_exts else "JSModule"
            nodes.append({
                "id": file_id,
                "label": fpath.stem,
                "type": entity_type,
                "description": f"{entity_type}: {rel_path}",
            })
            node_ids.add(file_id)

            # Directory node
            parts = Path(rel_path).parts
            if len(parts) > 1:
                dir_id = "/".join(parts[:-1])
                if dir_id not in node_ids:
                    nodes.append({
                        "id": dir_id,
                        "label": parts[-2],
                        "type": "Directory",
                        "description": f"Directory: {dir_id}",
                    })
                    node_ids.add(dir_id)
                edges.append({
                    "source": dir_id,
                    "target": file_id,
                    "relationship": "CONTAINS",
                })

            # Parse imports + function definitions + calls (v0.12)
            try:
                content = fpath.read_text(errors="ignore")
                if fpath.suffix in py_exts:
                    # Imports
                    for match in re.finditer(
                        r"(?:from|import)\s+([\w.]+)", content
                    ):
                        module = match.group(1)
                        if "." in module:
                            target = module.replace(".", "/") + ".py"
                            edges.append({
                                "source": file_id,
                                "target": target,
                                "relationship": "IMPORTS",
                            })
                    # Function definitions → DEFINES edges
                    for match in re.finditer(
                        r"(?:def|class)\s+(\w+)", content
                    ):
                        func_name = match.group(1)
                        func_id = f"{file_id}::{func_name}"
                        if func_id not in node_ids:
                            nodes.append({
                                "id": func_id,
                                "label": func_name,
                                "type": "Function",
                                "description": f"Function/Class {func_name} in {rel_path}",
                            })
                            node_ids.add(func_id)
                        edges.append({
                            "source": file_id,
                            "target": func_id,
                            "relationship": "DEFINES",
                        })
                elif fpath.suffix in js_exts:
                    # Imports
                    for match in re.finditer(
                        r"""(?:import|require)\s*\(?\s*['"]([./][^'"]+)['"]\s*\)?""",
                        content,
                    ):
                        edges.append({
                            "source": file_id,
                            "target": match.group(1),
                            "relationship": "IMPORTS",
                        })
                    # Function/component definitions → DEFINES edges
                    for match in re.finditer(
                        r"(?:function|const|class)\s+(\w+)", content
                    ):
                        func_name = match.group(1)
                        func_id = f"{file_id}::{func_name}"
                        if func_id not in node_ids:
                            nodes.append({
                                "id": func_id,
                                "label": func_name,
                                "type": "Function",
                                "description": f"Function/Component {func_name} in {rel_path}",
                            })
                            node_ids.add(func_id)
                        edges.append({
                            "source": file_id,
                            "target": func_id,
                            "relationship": "DEFINES",
                        })
            except Exception:
                pass

    return nodes, edges


def grow_command(
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress output (for git hooks)"
    ),
    full: bool = typer.Option(
        False, "--full", "-f", help="Full rescan instead of incremental"
    ),
    config: str = typer.Option(
        "graqle.yaml", "--config", "-c", help="Config file path"
    ),
) -> None:
    """Incrementally update the knowledge graph.

    Called automatically by the git post-commit hook. Scans changed files,
    re-ingests markdown KG sources, and merges into graqle.json.

    \b
    Auto (git hook):
        graq grow --quiet

    \b
    Manual full rescan:
        graq grow --full
    """
    root = Path(".").resolve()
    start = time.perf_counter()

    graph_path = root / "graqle.json"
    if not graph_path.exists():
        if not quiet:
            console.print("[yellow]No graqle.json found. Run 'graq init' first.[/yellow]")
        return

    # Load existing graph
    try:
        existing = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        if not quiet:
            console.print("[red]Failed to read graqle.json[/red]")
        return

    new_nodes: list[dict[str, Any]] = []
    new_links: list[dict[str, Any]] = []

    # ── Code scan (incremental or full) ──────────────────────────
    if full:
        # Full rescan
        try:
            from graqle.cli.commands.init import scan_repository
            graph_data = scan_repository(root)
            new_nodes.extend(graph_data.get("nodes", []))
            new_links.extend(graph_data.get("links", []))
        except Exception as e:
            if not quiet:
                console.print(f"[yellow]Full scan failed: {e}[/yellow]")
    else:
        # Incremental: only changed files
        changed = _get_changed_files()
        if changed:
            inc_nodes, inc_edges = _incremental_scan(root, changed)
            new_nodes.extend(inc_nodes)
            new_links.extend(inc_edges)

    # ── Knowledge ingestion ──────────────────────────────────────
    try:
        from graqle.cli.commands.ingest import (
            _discover_sources_auto,
            _discover_sources_from_config,
        )
        from graqle.ontology.markdown_parser import parse_and_infer

        config_path_obj = Path(config)
        kg_sources = _discover_sources_from_config(config_path_obj)
        if not kg_sources:
            kg_sources = _discover_sources_auto(root)

        if kg_sources:
            entities, edges_list = parse_and_infer(kg_sources)
            for e in entities:
                new_nodes.append(e.to_node_dict())
            for edge in edges_list:
                new_links.append({
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "relationship": edge.relationship,
                    "confidence": edge.confidence,
                    "source_file": edge.source_file,
                })
    except Exception:
        pass  # Ingestion is best-effort

    # ── Merge ────────────────────────────────────────────────────
    if not new_nodes and not new_links:
        if not quiet:
            console.print("[dim]No changes detected — graph unchanged.[/dim]")
        return

    from graqle.cli.commands.ingest import _merge_graphs
    merged = _merge_graphs(existing, new_nodes, new_links)
    stats = merged.pop("_merge_stats", {})

    # Write
    graph_path.write_text(
        json.dumps(merged, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )

    elapsed = time.perf_counter() - start

    # ── Update metrics ───────────────────────────────────────────
    try:
        from graqle.metrics.engine import MetricsEngine
        metrics = MetricsEngine(root / ".graqle")
        metrics.load()
        type_counts = Counter(n.get("type", "") for n in merged.get("nodes", []))
        metrics.graph_stats_current = {
            "nodes": len(merged.get("nodes", [])),
            "edges": len(merged.get("links", [])),
            "node_types": dict(type_counts.most_common()),
        }
        metrics.save()
    except Exception:
        pass

    if not quiet:
        added = stats.get("nodes_added", 0)
        updated = stats.get("nodes_updated", 0)
        edges_added = stats.get("edges_added", 0)
        total = len(merged.get("nodes", []))
        console.print(
            f"[green]Graph updated[/green] in {elapsed:.1f}s: "
            f"+{added} nodes, ~{updated} updated, +{edges_added} edges "
            f"({total} total)"
        )
