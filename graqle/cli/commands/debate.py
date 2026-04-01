"""graq debate — Multi-backend debate CLI command (R15, ADR-139).

Usage:
    graq debate "your query" --panelists p1 p2 p3
    graq debate "your query" --ab  # side-by-side with standard reasoning
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from graqle.config.settings import DebateConfig, GraqleConfig, NamedModelConfig
from graqle.core.types import DebateCostBudget
from graqle.intelligence.governance.debate_cost_gate import DebateCostGate
from graqle.orchestration.backend_pool import BackendPool
from graqle.orchestration.debate import DebateOrchestrator

console = Console()
debate_app = typer.Typer(name="debate", help="Multi-backend debate reasoning")


def _create_named_backend(name: str, model_cfg: NamedModelConfig):
    """Create a backend from a named model config."""
    from graqle.cli.main import _create_backend_from_config

    cfg = GraqleConfig(
        model={
            "backend": model_cfg.backend,
            "model": model_cfg.model,
            "api_key": model_cfg.api_key,
        }
    )
    return _create_backend_from_config(cfg, verbose=False)


@debate_app.callback(invoke_without_command=True)
def debate(
    query: str = typer.Argument(..., help="The reasoning query"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    ab: bool = typer.Option(False, "--ab", help="A/B comparison: debate vs standard reasoning"),
    max_rounds: int = typer.Option(0, "--max-rounds", "-r", help="Max debate rounds (0 = use config)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run a multi-backend debate query.

    Requires debate.mode != 'off' and debate.panelists configured in graqle.yaml.

    A/B mode (--ab) runs the same query through both standard reasoning
    and multi-backend debate, displaying results side-by-side.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Load config
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        console.print("[red]Config file not found. Run 'graq init' first.[/red]")
        raise typer.Exit(1)

    # Check debate is configured
    if cfg.debate.mode == "off" and not ab:
        console.print("[red]debate.mode is 'off' in config. Set to 'debate' or 'ensemble'.[/red]")
        raise typer.Exit(1)

    if not cfg.debate.panelists:
        console.print("[red]No debate.panelists configured in graqle.yaml.[/red]")
        raise typer.Exit(1)

    # Build panelist backends
    panelists = []
    for name in cfg.debate.panelists:
        if name not in cfg.models:
            console.print(f"[red]Panelist '{name}' not in models config.[/red]")
            raise typer.Exit(1)
        backend = _create_named_backend(name, cfg.models[name])
        panelists.append((name, backend))

    console.print("[bold]GraQle Debate[/bold] — Graphs that debate, verify, and prove.")
    console.print(f"Query: [green]{query}[/green]")
    console.print(f"Panelists: {', '.join(cfg.debate.panelists)}")

    rounds = max_rounds if max_rounds > 0 else cfg.debate.max_rounds

    # Run debate
    pool = BackendPool(panelists)
    budget = DebateCostBudget(
        initial_budget=cfg.debate.cost_ceiling_usd,
        decay_factor=cfg.debate.decay_factor,
    )
    cost_gate = DebateCostGate(budget)
    debate_config = DebateConfig(
        mode=cfg.debate.mode,
        panelists=cfg.debate.panelists,
        max_rounds=rounds,
        convergence_threshold=cfg.debate.convergence_threshold,
        cost_ceiling_usd=cfg.debate.cost_ceiling_usd,
        require_citation=cfg.debate.require_citation,
    )
    orchestrator = DebateOrchestrator(debate_config, pool, cost_gate)

    trace = asyncio.run(orchestrator.run(query))

    # Display debate results
    console.print(f"\n[bold green]Synthesis:[/bold green]")
    console.print(trace.synthesis or "[dim]No synthesis produced[/dim]")
    console.print(
        f"\n[dim]Confidence: {trace.final_confidence:.0%} | "
        f"Rounds: {trace.rounds_completed} | "
        f"Consensus: {'Yes' if trace.consensus_reached else 'No'} | "
        f"Cost: ${trace.total_cost_usd:.4f} | "
        f"Latency: {trace.total_latency_ms:.0f}ms | "
        f"Turns: {len(trace.turns)}[/dim]"
    )

    # A/B comparison
    if ab:
        console.print("\n[bold yellow]── A/B Comparison ──[/bold yellow]")
        from graqle.cli.main import _create_backend_from_config, _load_graph

        graph = _load_graph(cfg)
        if graph is None:
            console.print("[yellow]No graph for standard reasoning comparison.[/yellow]")
            return

        backend = _create_backend_from_config(cfg, verbose=verbose)
        graph.set_default_backend(backend)
        t0 = time.perf_counter()
        standard_result = asyncio.run(graph.areason(query))
        standard_ms = (time.perf_counter() - t0) * 1000.0

        # Side-by-side table
        table = Table(title="A/B Comparison")
        table.add_column("Metric", style="bold")
        table.add_column("Standard", style="cyan")
        table.add_column("Debate", style="green")

        table.add_row("Confidence", f"{standard_result.confidence:.0%}", f"{trace.final_confidence:.0%}")
        table.add_row("Cost", f"${standard_result.cost_usd:.4f}", f"${trace.total_cost_usd:.4f}")
        table.add_row("Latency", f"{standard_ms:.0f}ms", f"{trace.total_latency_ms:.0f}ms")
        table.add_row("Rounds", str(standard_result.rounds_completed), str(trace.rounds_completed))
        table.add_row("Nodes/Turns", str(standard_result.node_count), str(len(trace.turns)))
        table.add_row("Consensus", "N/A", "Yes" if trace.consensus_reached else "No")

        console.print(table)

        console.print("\n[bold cyan]Standard Answer:[/bold cyan]")
        console.print(standard_result.answer[:500])
        console.print("\n[bold green]Debate Synthesis:[/bold green]")
        console.print((trace.synthesis or "")[:500])
