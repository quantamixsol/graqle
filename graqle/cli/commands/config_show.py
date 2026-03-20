"""graq config — show resolved GraQle configuration.

Displays the fully resolved configuration including backend, model,
routing rules, graph connector, and embedding settings. Useful for
verifying what GraQle will actually use at runtime.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.config_show
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, os, pathlib, typer, rich, settings
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def config_command(
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show resolved GraQle configuration.

    Displays what backend, model, routing rules, and graph connector
    GraQle will use at runtime. Helps verify your setup before running queries.

    \b
    Examples:
        graq config
        graq config --json
        graq config --config custom.yaml
    """
    from graqle.config.settings import GraqleConfig

    config_path = Path(config)
    if config_path.exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()
        if not json_output:
            console.print(f"[yellow]No {config} found — showing defaults[/yellow]\n")

    if json_output:
        _output_json(cfg, config_path)
        return

    _output_rich(cfg, config_path)


def _resolve_env(value: str | None) -> tuple[str, bool]:
    """Resolve a value that may be an env var reference like ${VAR}."""
    if not value:
        return ("(not set)", False)
    if value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        resolved = os.environ.get(env_var)
        if resolved:
            masked = resolved[:4] + "..." + resolved[-4:] if len(resolved) > 8 else "***"
            return (f"${{{env_var}}} -> {masked}", True)
        return (f"${{{env_var}}} -> NOT SET", False)
    return (value, True)


def _output_json(cfg: "GraqleConfig", config_path: Path) -> None:
    """Output config as JSON for scripting/CI."""
    data = {
        "config_file": str(config_path) if config_path.exists() else None,
        "model": {
            "backend": cfg.model.backend,
            "model": cfg.model.model,
            "region": cfg.model.region,
            "host": cfg.model.host,
            "endpoint": cfg.model.endpoint,
            "api_key_set": bool(cfg.model.api_key and (
                not cfg.model.api_key.startswith("${")
                or os.environ.get(cfg.model.api_key[2:-1], "")
            )),
        },
        "graph": {
            "connector": cfg.graph.connector,
            "path": cfg.graph.path,
            "uri": cfg.graph.uri,
        },
        "routing": {
            "default_provider": cfg.routing.default_provider,
            "default_model": cfg.routing.default_model,
            "rules": [
                {"task": r.task, "provider": r.provider, "model": r.model}
                for r in cfg.routing.rules
            ],
        },
        "embeddings": {
            "backend": cfg.embeddings.backend,
            "model": cfg.embeddings.model,
            "dimension": cfg.embeddings.dimension,
        },
        "activation": {
            "strategy": cfg.activation.strategy,
            "max_nodes": cfg.activation.max_nodes,
        },
        "cost": {
            "budget_per_query": cfg.cost.budget_per_query,
            "prefer_local": cfg.cost.prefer_local,
            "fallback_to_api": cfg.cost.fallback_to_api,
        },
    }
    print(json.dumps(data, indent=2))


def _output_rich(cfg: "GraqleConfig", config_path: Path) -> None:
    """Output config as a Rich-formatted table."""
    from graqle.__version__ import __version__

    console.print(Panel.fit(
        f"[bold cyan]GraQle Config[/bold cyan] v{__version__}",
        border_style="cyan",
    ))

    # Model / Backend
    table = Table(title="Model & Backend", show_header=True, header_style="bold")
    table.add_column("Setting", min_width=20)
    table.add_column("Value")

    table.add_row("Backend", cfg.model.backend)
    table.add_row("Model", cfg.model.model)

    api_display, api_ok = _resolve_env(cfg.model.api_key)
    color = "green" if api_ok else "red"
    table.add_row("API Key", f"[{color}]{api_display}[/{color}]")

    if cfg.model.region:
        table.add_row("Region", cfg.model.region)
    if cfg.model.host:
        table.add_row("Host", cfg.model.host)
    if cfg.model.endpoint:
        table.add_row("Endpoint", cfg.model.endpoint)

    console.print(table)

    # Graph
    table2 = Table(title="Graph", show_header=True, header_style="bold")
    table2.add_column("Setting", min_width=20)
    table2.add_column("Value")
    table2.add_row("Connector", cfg.graph.connector)
    if cfg.graph.path:
        table2.add_row("Path", cfg.graph.path)
    if cfg.graph.uri:
        table2.add_row("URI", cfg.graph.uri)

    # Show graph file if it exists
    for candidate in ["graqle.json", "knowledge_graph.json", "graph.json"]:
        if Path(candidate).exists():
            size = Path(candidate).stat().st_size
            table2.add_row("Graph File", f"{candidate} ({size:,} bytes)")
            break

    console.print(table2)

    # Routing
    if cfg.routing.rules or cfg.routing.default_provider:
        table3 = Table(title="Task Routing", show_header=True, header_style="bold")
        table3.add_column("Task")
        table3.add_column("Provider")
        table3.add_column("Model")

        if cfg.routing.default_provider:
            table3.add_row(
                "[dim]default[/dim]",
                cfg.routing.default_provider,
                cfg.routing.default_model or "(backend default)",
            )
        for rule in cfg.routing.rules:
            table3.add_row(rule.task, rule.provider, rule.model or "(default)")

        console.print(table3)
    else:
        console.print("[dim]Routing: no task-specific rules (using single backend)[/dim]")

    # Embeddings
    table4 = Table(title="Embeddings & Activation", show_header=True, header_style="bold")
    table4.add_column("Setting", min_width=20)
    table4.add_column("Value")
    table4.add_row("Embedding Backend", cfg.embeddings.backend)
    table4.add_row("Embedding Model", cfg.embeddings.model)
    dim = cfg.embeddings.dimension if cfg.embeddings.dimension > 0 else "auto"
    table4.add_row("Dimension", str(dim))
    table4.add_row("Activation Strategy", cfg.activation.strategy)
    table4.add_row("Max Nodes", str(cfg.activation.max_nodes))
    console.print(table4)

    # Cost
    console.print(
        f"\n[dim]Cost: ${cfg.cost.budget_per_query:.2f}/query | "
        f"prefer_local={cfg.cost.prefer_local} | "
        f"fallback_to_api={cfg.cost.fallback_to_api}[/dim]"
    )
