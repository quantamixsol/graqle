"""graq verify — Pre-commit Quality Gate verification.

Checks staged/changed files against compiled intelligence:
1. Impact analysis: what modules are affected by the change?
2. Constraint check: does the change violate any constraints?
3. Risk assessment: what's the blast radius?
4. Recommendation: safe to commit or needs review?

This is Layer C (Enforcement) of the Quality Gate.
The architecture cures itself — using GraQle makes the codebase easier
for GraQle (and any AI tool) to reason about.

See §Layer C: Enforcement.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.verify
# risk: MEDIUM (impact radius: 2 modules)
# consumers: main, test_verify
# dependencies: __future__, json, logging, subprocess, pathlib +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from graqle.intelligence.gate import IntelligenceGate

logger = logging.getLogger("graqle.intelligence.verify")
console = Console()


def _check_staleness_and_recompile(root: Path) -> bool:
    """Check if graqle.json is newer than compiled intelligence.

    If stale, triggers incremental recompile and records the event.
    Returns True if recompile happened.
    """
    import time

    graph_file = None
    for candidate in ["graqle.json", "knowledge_graph.json", "graph.json"]:
        p = root / candidate
        if p.exists():
            graph_file = p
            break

    if graph_file is None:
        return False

    intel_index = root / ".graqle" / "intelligence" / "module_index.json"
    if not intel_index.exists():
        return False

    # Compare modification times
    graph_mtime = graph_file.stat().st_mtime
    intel_mtime = intel_index.stat().st_mtime

    if graph_mtime <= intel_mtime:
        return False  # Intelligence is up-to-date

    console.print(
        "\n[yellow]Stale intelligence detected[/yellow] — "
        "graph was updated since last compile. Auto-recompiling..."
    )

    try:
        t0 = time.perf_counter()
        from graqle.intelligence.compile import compile_intelligence
        result = compile_intelligence(root, inject=True, verbose=False)
        duration = time.perf_counter() - t0

        modules_updated = result.get("total_modules", 0)
        console.print(
            f"[green]Auto-recompiled[/green]: {modules_updated} modules in {duration:.1f}s"
        )

        # Record the recompile event
        try:
            from graqle.intelligence.learning_tracker import LearningTracker
            tracker = LearningTracker(root)
            tracker.record_recompile(
                trigger="staleness_auto",
                modules_updated=modules_updated,
                duration_seconds=duration,
            )
        except Exception:
            pass  # Tracker is best-effort

        return True
    except Exception as exc:
        console.print(f"[yellow]Auto-recompile failed: {exc}[/yellow]")
        return False


def verify_changes(
    root: Path,
    files: list[str] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Verify staged/changed files against compiled intelligence.

    Returns a verdict dict with impact analysis and recommendations.
    """
    gate = IntelligenceGate(root)

    if not gate.is_compiled:
        console.print("[yellow]No compiled intelligence found. Run 'graq compile' first.[/yellow]")
        return {"verdict": "SKIP", "reason": "no intelligence compiled"}

    # Check staleness and auto-recompile if needed (Option B)
    _check_staleness_and_recompile(root)

    # Get changed files
    changed_files = files or _get_changed_files(root)
    if not changed_files:
        console.print("[green]No changes to verify.[/green]")
        return {"verdict": "PASS", "reason": "no changes"}

    console.print(f"\n🔍 [bold]GraQle Quality Gate[/bold] — verifying {len(changed_files)} changed file(s)...\n")

    # Analyze each changed file
    affected_modules: list[dict[str, Any]] = []
    total_consumers = 0
    max_risk = "LOW"
    violated_constraints: list[dict[str, str]] = []
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    for fpath in changed_files:
        # Get module context
        context = gate.get_context(fpath)
        if "error" in context:
            continue

        module_name = context.get("module", fpath)
        risk_level = context.get("risk_level", "LOW")
        consumers = context.get("consumers", [])
        constraints = context.get("constraints", [])
        incidents = context.get("incidents", [])

        # Track impact
        affected_modules.append({
            "module": module_name,
            "file": fpath,
            "risk_level": risk_level,
            "consumer_count": len(consumers),
            "consumers": [c.get("module", c) if isinstance(c, dict) else c for c in consumers[:5]],
            "constraints": constraints,
            "incidents": incidents,
        })

        total_consumers += len(consumers)
        if risk_order.get(risk_level, 0) > risk_order.get(max_risk, 0):
            max_risk = risk_level

        # Check constraints
        for constraint in constraints:
            violated_constraints.append({
                "module": module_name,
                "constraint": constraint,
            })

    # Determine verdict
    if max_risk == "CRITICAL" and strict:
        verdict = "BLOCK"
        reason = f"CRITICAL risk module modified ({total_consumers} downstream consumers)"
    elif violated_constraints and strict:
        verdict = "BLOCK"
        reason = f"{len(violated_constraints)} constraint(s) require review"
    elif max_risk in ("HIGH", "CRITICAL"):
        verdict = "WARN"
        reason = f"{max_risk} risk — {total_consumers} downstream consumers affected"
    else:
        verdict = "PASS"
        reason = f"Changes affect {len(affected_modules)} module(s), risk level: {max_risk}"

    # Print report
    _print_verify_report(affected_modules, violated_constraints, verdict, reason)

    return {
        "verdict": verdict,
        "reason": reason,
        "changed_files": changed_files,
        "affected_modules": len(affected_modules),
        "total_consumers": total_consumers,
        "max_risk": max_risk,
        "constraints": violated_constraints,
        "modules": affected_modules,
    }


def _get_changed_files(root: Path) -> list[str]:
    """Get list of changed files (staged + unstaged) via git."""
    try:
        # Staged files
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=root, timeout=10,
        )
        staged = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Unstaged modified files
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=root, timeout=10,
        )
        unstaged = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Combine and deduplicate
        all_files = list(set(staged + unstaged))
        # Filter to code files only
        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx"}
        return [f for f in all_files if f and Path(f).suffix.lower() in code_exts]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _print_verify_report(
    modules: list[dict[str, Any]],
    constraints: list[dict[str, str]],
    verdict: str,
    reason: str,
) -> None:
    """Print the verification report."""
    if not modules:
        return

    # Impact table
    table = Table(title="Change Impact Analysis")
    table.add_column("Module", style="bold")
    table.add_column("Risk", justify="center")
    table.add_column("Consumers", justify="right")
    table.add_column("Constraints", justify="right")

    for mod in modules:
        risk_style = {
            "CRITICAL": "bold red",
            "HIGH": "bold yellow",
            "MEDIUM": "cyan",
            "LOW": "green",
        }.get(mod["risk_level"], "white")

        short_name = mod["module"].rsplit(".", 1)[-1]
        table.add_row(
            short_name,
            f"[{risk_style}]{mod['risk_level']}[/{risk_style}]",
            str(mod["consumer_count"]),
            str(len(mod["constraints"])),
        )

    console.print(table)

    # Show constraint warnings
    if constraints:
        console.print("\n⚠️  [bold yellow]Active Constraints:[/bold yellow]")
        for c in constraints:
            short_mod = c["module"].rsplit(".", 1)[-1]
            console.print(f"  • [bold]{short_mod}[/bold]: {c['constraint']}")

    # Show top consumers for high-impact modules
    high_impact = [m for m in modules if m["consumer_count"] >= 3]
    if high_impact:
        console.print("\n🔗 [bold]High-Impact Modules:[/bold]")
        for mod in high_impact:
            short_name = mod["module"].rsplit(".", 1)[-1]
            consumer_names = ", ".join(c.rsplit(".", 1)[-1] for c in mod["consumers"])
            console.print(f"  {short_name} → {consumer_names}")
            if mod.get("incidents"):
                console.print(f"    [red]⚠ Incident history: {mod['incidents'][0][:60]}[/red]")

    # Verdict
    verdict_style = {
        "PASS": "bold green",
        "WARN": "bold yellow",
        "BLOCK": "bold red",
        "SKIP": "dim",
    }.get(verdict, "white")

    console.print(f"\n[{verdict_style}]Verdict: {verdict}[/{verdict_style}] — {reason}\n")


# ─── CLI Command ──────────────────────────────────────────────────────

verify_command = typer.Typer(
    name="verify",
    help="Verify changes against compiled intelligence — the Quality Gate check.",
    no_args_is_help=False,
    invoke_without_command=True,
)


@verify_command.callback(invoke_without_command=True)
def verify_main(
    path: str = typer.Argument(".", help="Project root directory"),
    strict: bool = typer.Option(False, "--strict", help="Block on HIGH/CRITICAL risk changes"),
    files: list[str] = typer.Option(None, "--file", "-f", help="Specific files to verify"),
) -> None:
    """Verify staged changes against compiled intelligence.

    Checks impact, constraints, and risk level before commit.
    Run 'graq compile' first to populate intelligence.

    \\b
    Examples:
        graq verify                        # verify all staged changes
        graq verify --strict               # block on high-risk changes
        graq verify -f graqle/core/graph.py  # verify specific file
    """
    root = Path(path).resolve()
    result = verify_changes(root, files=files, strict=strict)

    if result["verdict"] == "BLOCK":
        raise typer.Exit(1)
