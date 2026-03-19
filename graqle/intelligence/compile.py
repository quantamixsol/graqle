# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""graq compile — the Intelligence Compiler.

Orchestrates the full streaming intelligence pipeline:
1. Structural pass (instant project shape)
2. Import graph (dependency map)
3. Streaming deep scan (per-file validation + intelligence)
4. Emit to all outputs (JSON packets, inline headers, CLAUDE.md)

This is the core command that makes Graqle's Quality Gate operational.

See ADR-105 §Implementation Plan, Phase 1.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.compile
# risk: MEDIUM (impact radius: 3 modules)
# consumers: main, __init__, test_compile
# dependencies: __future__, logging, time, pathlib, typing +13 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from graqle.intelligence.claude_section import (
    detect_ai_tools,
    eject_section,
    generate_section,
    inject_section,
)
from graqle.intelligence.emitter import IntelligenceEmitter
from graqle.intelligence.invariants import detect_invariants
from graqle.intelligence.headers import eject_header, generate_header, inject_header
from graqle.intelligence.models import CuriosityInsight, InsightCategory, ModulePacket
from graqle.intelligence.pipeline import (
    import_graph_pass,
    resolve_pending_edges,
    stream_intelligence,
    structural_pass,
)
from graqle.intelligence.scorecard import RunningScorecard

logger = logging.getLogger("graqle.intelligence.compile")
console = Console()

# Insight category styling
_INSIGHT_STYLES = {
    InsightCategory.SUPERLATIVE: ("bold cyan", "★"),
    InsightCategory.WARNING: ("bold yellow", "⚠"),
    InsightCategory.SUGGESTION: ("blue", "💡"),
    InsightCategory.CONNECTION: ("magenta", "🔗"),
    InsightCategory.HISTORY: ("red", "📋"),
    InsightCategory.INVARIANT: ("bold red", "🔍"),
}


def compile_intelligence(
    root: Path,
    inject: bool = True,
    eject: bool = False,
    no_dashboard: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run the full intelligence compilation pipeline.

    Returns a summary dict with results.
    """
    total_start = time.perf_counter()

    if eject:
        return _run_eject(root)

    # ─── Phase 1: Structural Pass (<3s) ──────────────────────────
    phase1_start = time.perf_counter()
    console.print("\n⚡ [bold]Graqle Quality Gate[/bold] — compiling intelligence...\n")

    shape = structural_pass(root)
    phase1_time = time.perf_counter() - phase1_start

    # Print project shape
    lang_parts = []
    if shape.has_python:
        py_count = shape.extension_counts.get(".py", 0)
        lang_parts.append(f"{py_count} Python")
    if shape.has_typescript or shape.has_javascript:
        js_count = shape.extension_counts.get(".js", 0) + shape.extension_counts.get(".jsx", 0)
        ts_count = shape.extension_counts.get(".ts", 0) + shape.extension_counts.get(".tsx", 0)
        if ts_count:
            lang_parts.append(f"{ts_count} TypeScript")
        if js_count:
            lang_parts.append(f"{js_count} JavaScript")

    config_count = len(shape.config_files)
    test_count = len(shape.test_files)

    console.print(f"  Project: [bold]{root.name}[/bold]")
    console.print(f"  Files: {', '.join(lang_parts)}, {config_count} configs")
    if shape.framework_hints:
        console.print(f"  Detected: {', '.join(shape.framework_hints)}")
    if shape.ai_tools:
        console.print(f"  AI tools: {', '.join(shape.ai_tools)}")
    if test_count:
        console.print(f"  Tests: {test_count} test files")
    console.print(f"  [dim]({phase1_time:.1f}s)[/dim]\n")

    # ─── Phase 2: Import Graph (<10s) ────────────────────────────
    phase2_start = time.perf_counter()
    console.print("🔍 Building dependency graph...")

    ig = import_graph_pass(shape.code_files, root)
    phase2_time = time.perf_counter() - phase2_start

    # Show top importees
    if ig.import_counts:
        top_imports = sorted(ig.import_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        for fpath, count in top_imports:
            short = fpath.rsplit("/", 1)[-1] if "/" in fpath else fpath
            level = "CRITICAL" if count >= 10 else "HIGH" if count >= 5 else "MEDIUM"
            style = "bold red" if level == "CRITICAL" else "bold yellow" if level == "HIGH" else "cyan"
            console.print(f"  [{style}]{short}[/{style}] — imported by {count} modules ({level})")

    console.print(f"  [dim]({phase2_time:.1f}s)[/dim]\n")

    # ─── Phase 3: Streaming Deep Scan ────────────────────────────
    console.print("🧠 Deep scan (validated per file)...")

    from graqle.intelligence.models import FileIntelligenceUnit

    scorecard = RunningScorecard()
    all_packets: list[ModulePacket] = []
    all_units: list[FileIntelligenceUnit] = []
    files_injected = 0
    total_insights = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=len(shape.code_files))

        for unit, insights in stream_intelligence(root, shape, ig):
            all_units.append(unit)
            all_packets.append(unit.module_packet)

            # Ingest into scorecard
            scorecard.ingest(unit)

            # Show insights
            for insight in insights:
                total_insights += 1
                style, icon = _INSIGHT_STYLES.get(insight.category, ("white", "•"))
                short_mod = insight.module.rsplit(".", 1)[-1]
                progress.console.print(
                    f"  {icon} [bold]{short_mod}[/bold] — [{style}]{insight.message}[/{style}]"
                )

            # Update progress
            status = "✓" if unit.is_healthy else "⚠"
            short_name = Path(unit.file_path).name
            progress.update(task, advance=1, description=f"{status} {short_name}")

    phase3_time = time.perf_counter() - phase2_start - phase2_time

    # ─── Phase 3b: Edge Resolution (second pass) ─────────────────
    resolved, still_pending = resolve_pending_edges(all_units)
    if resolved > 0:
        console.print(f"\n🔗 Edge resolution: {resolved} cross-module edges resolved")
    if still_pending > 0:
        console.print(f"  [dim]{still_pending} external edges unresolved (expected)[/dim]")

    # Recalculate scorecard coverage after resolution
    scorecard.recalculate_edge_coverage(all_units)

    # ─── Phase 3c: Invariant Detection ─────────────────────────────
    invariant_insights = detect_invariants(all_units)
    if invariant_insights:
        console.print(f"\n🔍 Invariant detector: {len(invariant_insights)} violations found")
        for inv in invariant_insights:
            style, icon = _INSIGHT_STYLES.get(inv.category, ("white", "•"))
            short_mod = inv.module.rsplit(".", 1)[-1]
            console.print(f"  {icon} [bold]{short_mod}[/bold] — [{style}]{inv.message}[/{style}]")
        total_insights += len(invariant_insights)
        # Attach invariant insights to the relevant units
        _attach_invariant_insights(all_units, invariant_insights)

    # ─── Phase 4: Emit Index + CLAUDE.md Section ─────────────────
    emitter = IntelligenceEmitter(root)
    for unit in all_units:
        emitter.emit_unit(unit)
    emitter.emit_index(scorecard)

    # Inject inline headers (after resolution for accurate data)
    if inject:
        for unit in all_units:
            fpath = root / unit.file_path
            ext = fpath.suffix.lower()
            header = generate_header(unit.module_packet, ext)
            if header and inject_header(fpath, header):
                files_injected += 1

    # CLAUDE.md / .cursorrules section
    ai_tools = detect_ai_tools(root)
    section = generate_section(all_packets, scorecard)
    ai_files_injected = 0
    for tool_name, tool_path in ai_tools.items():
        if inject_section(tool_path, section):
            ai_files_injected += 1
            console.print(f"\n📝 Intelligence section injected into [bold]{tool_path.name}[/bold]")

    # If no AI tool file found, create a minimal CLAUDE.md
    if not ai_tools and inject:
        claude_path = root / "CLAUDE.md"
        if not claude_path.exists():
            claude_path.write_text(
                f"# {root.name}\n\n{section}\n",
                encoding="utf-8",
            )
            console.print("\n📝 Created [bold]CLAUDE.md[/bold] with intelligence section")
            ai_files_injected += 1

    total_time = time.perf_counter() - total_start

    # ─── Final Report ────────────────────────────────────────────
    cov = scorecard.coverage
    _print_final_report(
        scorecard, all_packets, total_time,
        files_injected, ai_files_injected, total_insights,
    )

    return {
        "total_modules": len(all_packets),
        "total_nodes": scorecard.total_nodes,
        "total_edges": scorecard.total_edges,
        "chunk_coverage": cov.chunk_coverage,
        "description_coverage": cov.description_coverage,
        "edge_integrity": cov.edge_integrity,
        "health": cov.health,
        "auto_repairs": scorecard.auto_repairs,
        "files_injected": files_injected,
        "ai_files_injected": ai_files_injected,
        "insights": total_insights,
        "duration_seconds": round(total_time, 1),
    }


def _attach_invariant_insights(
    all_units: list[FileIntelligenceUnit],
    insights: list[CuriosityInsight],
) -> None:
    """Attach invariant insights to the unit whose module matches."""
    module_to_unit: dict[str, FileIntelligenceUnit] = {
        u.module_packet.module: u for u in all_units
    }
    for insight in insights:
        unit = module_to_unit.get(insight.module)
        if unit:
            unit.insights.append(insight)
        elif all_units:
            # Fallback: attach to first unit so it's not lost
            all_units[0].insights.append(insight)


def _run_eject(root: Path) -> dict[str, Any]:
    """Remove all intelligence injections."""
    console.print("\n🧹 Ejecting intelligence from source files...")

    ejected_headers = 0
    ejected_sections = 0

    # Eject inline headers
    for fpath in root.rglob("*.py"):
        if eject_header(fpath):
            ejected_headers += 1
    for ext in ("*.js", "*.ts", "*.jsx", "*.tsx"):
        for fpath in root.rglob(ext):
            if eject_header(fpath):
                ejected_headers += 1

    # Eject CLAUDE.md / .cursorrules sections
    ai_tools = detect_ai_tools(root)
    for tool_name, tool_path in ai_tools.items():
        if eject_section(tool_path):
            ejected_sections += 1

    console.print(f"  Ejected {ejected_headers} inline headers")
    console.print(f"  Ejected {ejected_sections} AI tool sections")
    console.print("  [green]✓ Clean[/green]\n")

    return {"ejected_headers": ejected_headers, "ejected_sections": ejected_sections}


def _print_final_report(
    scorecard: RunningScorecard,
    packets: list[ModulePacket],
    total_time: float,
    files_injected: int,
    ai_files_injected: int,
    total_insights: int,
) -> None:
    """Print the final compilation report."""
    cov = scorecard.coverage

    # Coverage scorecard
    health_style = {
        "HEALTHY": "bold green",
        "WARNING": "bold yellow",
        "CRITICAL": "bold red",
    }.get(cov.health, "white")

    table = Table(title="Quality Gate Scorecard", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Status", justify="center")

    def _status(pct: float, good: float = 95, warn: float = 80) -> str:
        if pct >= good:
            return "[green]✓[/green]"
        if pct >= warn:
            return "[yellow]⚠[/yellow]"
        return "[red]✗[/red]"

    table.add_row("Chunk coverage", f"{cov.chunk_coverage}%", _status(cov.chunk_coverage))
    table.add_row("Description coverage", f"{cov.description_coverage}%", _status(cov.description_coverage))
    table.add_row("Edge integrity", f"{cov.edge_integrity}%", _status(cov.edge_integrity, 99, 95))
    table.add_row("Auto-repairs", str(scorecard.auto_repairs), "[dim]—[/dim]")
    table.add_row("Degraded nodes", str(scorecard.degraded_nodes), "[green]✓[/green]" if scorecard.degraded_nodes == 0 else "[red]✗[/red]")
    table.add_row("", "", "")
    table.add_row("Health", cov.health, f"[{health_style}]{cov.health}[/{health_style}]")

    console.print()
    console.print(table)

    # Summary
    console.print(f"\n📦 [bold]{len(packets)} modules[/bold] compiled to .graqle/intelligence/")
    if files_injected:
        console.print(f"📝 [bold]{files_injected} files[/bold] received inline intelligence headers")
    if ai_files_injected:
        console.print(f"🤖 [bold]{ai_files_injected} AI tool config(s)[/bold] updated")
    if total_insights:
        console.print(f"💡 [bold]{total_insights} insights[/bold] discovered")
    console.print(f"⏱  Completed in [bold]{total_time:.1f}s[/bold]")
    console.print()


# ─── CLI Command ─────────────────────────────────────────────────────

compile_command = typer.Typer(
    name="compile",
    help="Compile intelligence from your codebase — the Quality Gate.",
    no_args_is_help=False,
    invoke_without_command=True,
)


@compile_command.callback(invoke_without_command=True)
def compile_main(
    path: str = typer.Argument(".", help="Project root directory"),
    inject: bool = typer.Option(True, "--inject/--no-inject", help="Inject inline intelligence headers"),
    eject: bool = typer.Option(False, "--eject", help="Remove all intelligence injections"),
    hooks: bool = typer.Option(False, "--hooks", help="Install pre-commit Quality Gate hook"),
    unhook: bool = typer.Option(False, "--unhook", help="Remove pre-commit Quality Gate hook"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Compile intelligence from your codebase.

    Scans all source files, validates per-file with 6 quality gates,
    and emits intelligence to .graqle/intelligence/, inline headers,
    and CLAUDE.md/AI tool config files.

    \b
    Examples:
        graq compile              # compile current directory
        graq compile ./my-project # compile specific directory
        graq compile --no-inject  # skip inline header injection
        graq compile --eject      # remove all injected intelligence
        graq compile --hooks      # install pre-commit hook
        graq compile --unhook     # remove pre-commit hook
    """
    from graqle.intelligence.hooks import install_hook, uninstall_hook

    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error: {path} is not a directory[/red]")
        raise typer.Exit(1)

    # Hook management (standalone operations)
    if unhook:
        if uninstall_hook(root):
            console.print("[green]✓ Pre-commit hook removed.[/green]")
        else:
            console.print("[dim]No Graqle hook found.[/dim]")
        raise typer.Exit(0)

    result = compile_intelligence(root, inject=inject, eject=eject, verbose=verbose)

    # Install hooks after successful compile
    if hooks:
        if install_hook(root):
            console.print("🔒 [bold]Pre-commit Quality Gate hook installed.[/bold]")
            console.print("   Every commit will be verified against compiled intelligence.")
        else:
            console.print("[dim]Hook already installed or no .git directory.[/dim]")

    # Exit code based on health
    if result.get("health") == "CRITICAL":
        raise typer.Exit(2)
    elif result.get("health") == "WARNING":
        raise typer.Exit(1)
