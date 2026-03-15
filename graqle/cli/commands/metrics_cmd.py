"""graq metrics — show Graqle usage metrics and ROI.

Displays cumulative usage statistics, token savings, safety check
effectiveness, and optionally generates a markdown dashboard or
prints a JSON dump.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.metrics_cmd
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, pathlib, typer, console +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json as json_lib
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from graqle.metrics.engine import MetricsEngine

console = Console()


def metrics_command(
    report: bool = typer.Option(
        False, "--report", "-r", help="Show ROI report"
    ),
    dashboard: bool = typer.Option(
        False, "--dashboard", "-d", help="Generate markdown dashboard"
    ),
    reset: bool = typer.Option(
        False, "--reset", help="Reset all metrics"
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output as JSON"
    ),
) -> None:
    """Show Graqle usage metrics and ROI."""
    metrics_dir = Path.cwd() / ".graqle"
    engine = MetricsEngine(metrics_dir=metrics_dir)

    # ---- Reset -------------------------------------------------------
    if reset:
        engine.reset()
        console.print("[bold yellow]All metrics have been reset.[/bold yellow]")
        return

    # ---- JSON output -------------------------------------------------
    if json_output:
        console.print(json_lib.dumps(engine.get_summary(), indent=2))
        return

    # ---- ROI report --------------------------------------------------
    if report:
        console.print(engine.get_roi_report())
        return

    # ---- Markdown dashboard ------------------------------------------
    if dashboard:
        from graqle.metrics.dashboard import generate_dashboard

        out_path = metrics_dir / "dashboard.md"
        generate_dashboard(engine, output=out_path)
        console.print(
            f"[bold green]Dashboard written to[/bold green] {out_path}"
        )
        return

    # ---- Default: rich summary table ---------------------------------
    summary = engine.get_summary()

    # Header panel
    console.print(
        Panel(
            f"[bold cyan]Graqle Metrics[/bold cyan]\n"
            f"Tracking since {summary['init_timestamp'][:10]}",
            border_style="cyan",
        )
    )

    # Main stats table
    stats_table = Table(
        title="Cumulative Statistics",
        show_header=True,
        header_style="bold magenta",
    )
    stats_table.add_column("Metric", style="dim", min_width=26)
    stats_table.add_column("Value", justify="right")

    stats_table.add_row("Context loads", f"{summary['context_loads']:,}")
    stats_table.add_row("Reasoning queries", f"{summary['queries']:,}")
    stats_table.add_row("Tokens saved", f"{summary['tokens_saved']:,}")
    stats_table.add_row("Mistakes prevented", f"{summary['mistakes_prevented']:,}")
    stats_table.add_row("Lessons applied", f"{summary['lessons_applied']:,}")
    stats_table.add_row("Safety checks", f"{summary['safety_checks']:,}")
    stats_table.add_row("Violations blocked", f"{summary['safety_blocks']:,}")
    stats_table.add_row("Sessions completed", f"{summary['sessions_count']:,}")
    stats_table.add_row(
        "Unique nodes accessed", f"{summary['unique_nodes_accessed']:,}"
    )

    console.print(stats_table)

    # Token efficiency
    context_loads = summary["context_loads"]
    tokens_saved = summary["tokens_saved"]
    if context_loads > 0:
        avg_saved = tokens_saved // context_loads
        avg_returned = 25_000 - avg_saved
        reduction = round(25_000 / max(avg_returned, 1), 1)
        cost_saved = (tokens_saved / 1000) * 0.015

        eff_table = Table(
            title="Token Efficiency",
            show_header=True,
            header_style="bold green",
        )
        eff_table.add_column("Metric", style="dim", min_width=30)
        eff_table.add_column("Value", justify="right")

        eff_table.add_row("Avg tokens without Graqle", "25,000")
        eff_table.add_row("Avg tokens with Graqle", f"{avg_returned:,}")
        eff_table.add_row("Reduction factor", f"{reduction}x")
        eff_table.add_row(
            "Estimated cost savings", f"${cost_saved:,.2f}"
        )

        console.print(eff_table)

    # Graph stats
    gs = summary.get("graph_stats_current") or summary.get("graph_stats")
    if gs:
        gs_table = Table(
            title="Graph Statistics",
            show_header=True,
            header_style="bold blue",
        )
        gs_table.add_column("Metric", style="dim", min_width=20)
        gs_table.add_column("Value", justify="right")
        gs_table.add_row("Nodes", f"{gs.get('nodes', 0):,}")
        gs_table.add_row("Edges", f"{gs.get('edges', 0):,}")

        node_types: dict[str, int] = gs.get("node_types", {})
        if node_types:
            gs_table.add_row(
                "Node types",
                ", ".join(f"{t}({c})" for t, c in sorted(node_types.items())),
            )
        edge_types: dict[str, int] = gs.get("edge_types", {})
        if edge_types:
            gs_table.add_row(
                "Edge types",
                ", ".join(f"{t}({c})" for t, c in sorted(edge_types.items())),
            )
        console.print(gs_table)

    # Top nodes
    node_access = engine.node_access
    if node_access:
        top_table = Table(
            title="Top Accessed Nodes",
            show_header=True,
            header_style="bold yellow",
        )
        top_table.add_column("Node", style="dim")
        top_table.add_column("Accesses", justify="right")
        top_table.add_column("Last Accessed")

        ranked = sorted(
            node_access.items(), key=lambda kv: kv[1]["count"], reverse=True
        )[:10]
        for node_id, info in ranked:
            top_table.add_row(
                node_id,
                f"{info['count']:,}",
                info.get("last_accessed", "—")[:10],
            )
        console.print(top_table)

    # Safety
    safety_checks = summary["safety_checks"]
    safety_blocks = summary["safety_blocks"]
    if safety_checks > 0:
        block_rate = safety_blocks / safety_checks * 100
        console.print(
            Panel(
                f"Safety checks: [bold]{safety_checks:,}[/bold]  |  "
                f"Blocked: [bold red]{safety_blocks:,}[/bold red]  |  "
                f"Block rate: [bold]{block_rate:.1f}%[/bold]",
                title="Safety Boundary Effectiveness",
                border_style="red",
            )
        )

    # Recent sessions
    sessions = engine.sessions
    if sessions:
        sess_table = Table(
            title=f"Recent Sessions (last {min(len(sessions), 5)})",
            show_header=True,
            header_style="bold",
        )
        sess_table.add_column("#", justify="right", style="dim")
        sess_table.add_column("Date")
        sess_table.add_column("Queries", justify="right")
        sess_table.add_column("Tokens Saved", justify="right")
        sess_table.add_column("Lessons", justify="right")
        sess_table.add_column("Mistakes Prevented", justify="right")

        for idx, sess in enumerate(
            sessions[-5:], start=max(len(sessions) - 4, 1)
        ):
            sess_table.add_row(
                str(idx),
                sess.get("date", "—")[:10],
                f"{sess.get('queries', 0):,}",
                f"{sess.get('tokens_saved', 0):,}",
                f"{sess.get('lessons_applied', 0):,}",
                f"{sess.get('mistakes_prevented', 0):,}",
            )
        console.print(sess_table)

    # Hint
    console.print(
        "\n[dim]Use --report for ROI report, --dashboard for markdown, "
        "--json for raw data.[/dim]"
    )
