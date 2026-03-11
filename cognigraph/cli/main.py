"""CogniGraph CLI — kogni command-line interface."""

from __future__ import annotations

import typer
from rich.console import Console

from cognigraph.cli.commands.init import init_command
from cognigraph.cli.commands.scan import scan_app

app = typer.Typer(
    name="kogni",
    help="CogniGraph — Graphs that think. Turn any KG into a reasoning network.",
    no_args_is_help=True,
)
app.add_typer(scan_app, name="scan")
app.command(name="init")(init_command)
console = Console()

# ---------------------------------------------------------------------------
# MCP subcommand group: kogni mcp serve
# ---------------------------------------------------------------------------

mcp_app = typer.Typer(
    name="mcp",
    help="MCP (Model Context Protocol) server for Claude Code integration.",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    config: str = typer.Option(
        "cognigraph.yaml", "--config", "-c", help="Config file path"
    ),
) -> None:
    """Start the CogniGraph MCP development server (stdio transport for Claude Code).

    Exposes 7 governed development tools over JSON-RPC stdio:
      FREE:  kogni_context, kogni_inspect, kogni_reason
      PRO:   kogni_preflight, kogni_lessons, kogni_impact, kogni_learn

    Add to .mcp.json:
        { "mcpServers": { "kogni": { "command": "kogni", "args": ["mcp", "serve"] } } }
    """
    import asyncio
    from cognigraph.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer(config_path=config)
    asyncio.run(server.run_stdio())


@app.command()
def run(
    query: str = typer.Argument(..., help="The reasoning query"),
    config: str = typer.Option("cognigraph.yaml", "--config", "-c", help="Config file path"),
    max_rounds: int = typer.Option(5, "--max-rounds", "-r", help="Max message-passing rounds"),
    strategy: str = typer.Option("pcst", "--strategy", "-s", help="Activation strategy"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run a reasoning query on the CogniGraph."""
    import asyncio
    import logging

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    from cognigraph.config.settings import CogniGraphConfig
    from cognigraph.core.graph import CogniGraph
    from cognigraph.backends.mock import MockBackend
    from pathlib import Path

    # Load config
    if Path(config).exists():
        cfg = CogniGraphConfig.from_yaml(config)
    else:
        cfg = CogniGraphConfig.default()
        if verbose:
            console.print("[yellow]No config file found, using defaults[/yellow]")

    # For now, create a mock demonstration
    # In production, this would load from connector
    console.print(f"[bold cyan]CogniGraph[/bold cyan] — Graphs that think")
    console.print(f"Query: [green]{query}[/green]")
    console.print(f"Strategy: {strategy} | Max rounds: {max_rounds}")

    # Try to load graph from config
    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph source configured. Use 'kogni init' to set up.[/yellow]")
        return

    # Set mock backend if no real backend configured
    backend = MockBackend()
    graph.set_default_backend(backend)

    # Run reasoning
    result = asyncio.run(
        graph.areason(query, max_rounds=max_rounds, strategy=strategy)
    )

    # Display results
    console.print(f"\n[bold green]Answer:[/bold green]")
    console.print(result.answer)
    console.print(f"\n[dim]Confidence: {result.confidence:.0%} | "
                  f"Rounds: {result.rounds_completed} | "
                  f"Nodes: {result.node_count} | "
                  f"Cost: ${result.cost_usd:.4f} | "
                  f"Latency: {result.latency_ms:.0f}ms[/dim]")


@app.command()
def context(
    service: str = typer.Argument(..., help="Service/entity to get context for"),
    config: str = typer.Option("cognigraph.yaml", "--config", "-c"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, yaml"),
) -> None:
    """Get structured context for a service (Claude Code integration).

    Returns focused, 500-token context instead of loading 20-60K tokens
    of raw files. Designed to be called from CLAUDE.md rules.
    """
    from cognigraph.config.settings import CogniGraphConfig
    from pathlib import Path

    if Path(config).exists():
        cfg = CogniGraphConfig.from_yaml(config)
    else:
        cfg = CogniGraphConfig.default()

    graph = _load_graph(cfg)

    if graph is None:
        # Fallback: generate context from service name
        console.print(f"# Context for: {service}")
        console.print(f"No graph loaded. Run 'kogni scan --repo .' first.")
        return

    # Find the service node
    node = graph.nodes.get(service)
    if node is None:
        # Fuzzy match
        matches = [
            nid for nid in graph.nodes
            if service.lower() in nid.lower()
        ]
        if matches:
            node = graph.nodes[matches[0]]
        else:
            console.print(f"Service '{service}' not found in graph.")
            return

    # Build context output
    neighbors = graph.get_neighbors(node.id)
    context_parts = [
        f"# {node.label} ({node.entity_type})",
        f"Description: {node.description}",
    ]

    if node.properties:
        context_parts.append("Properties:")
        for k, v in node.properties.items():
            context_parts.append(f"  {k}: {v}")

    if neighbors:
        context_parts.append(f"Connected to: {', '.join(neighbors)}")
        for nid in neighbors[:5]:
            n = graph.nodes[nid]
            edges = graph.get_edges_between(node.id, nid)
            rel = edges[0].relationship if edges else "RELATED_TO"
            context_parts.append(f"  → {rel} → {n.label}: {n.description[:100]}")

    output = "\n".join(context_parts)

    if format == "json":
        import json
        console.print(json.dumps({
            "service": node.id,
            "label": node.label,
            "type": node.entity_type,
            "description": node.description,
            "neighbors": neighbors,
        }, indent=2))
    else:
        console.print(output)


@app.command()
def inspect(
    config: str = typer.Option("cognigraph.yaml", "--config", "-c"),
    stats: bool = typer.Option(False, "--stats", help="Show graph statistics"),
) -> None:
    """Inspect the CogniGraph — show nodes, edges, stats."""
    from cognigraph.config.settings import CogniGraphConfig
    from pathlib import Path

    if Path(config).exists():
        cfg = CogniGraphConfig.from_yaml(config)
    else:
        cfg = CogniGraphConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph loaded.[/yellow]")
        return

    if stats:
        s = graph.stats
        console.print(f"[bold]CogniGraph Stats[/bold]")
        console.print(f"  Nodes: {s.total_nodes}")
        console.print(f"  Edges: {s.total_edges}")
        console.print(f"  Avg degree: {s.avg_degree:.1f}")
        console.print(f"  Density: {s.density:.3f}")
        console.print(f"  Components: {s.connected_components}")
        console.print(f"  Hub nodes: {', '.join(s.hub_nodes)}")
    else:
        console.print(f"[bold]CogniGraph[/bold]: {graph}")
        for nid, node in list(graph.nodes.items())[:20]:
            console.print(f"  [{node.entity_type}] {nid}: {node.label} (degree={node.degree})")
        if len(graph.nodes) > 20:
            console.print(f"  ... and {len(graph.nodes) - 20} more nodes")


@app.command()
def serve(
    config: str = typer.Option("cognigraph.yaml", "--config", "-c"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of workers"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on changes"),
) -> None:
    """Start the CogniGraph API server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Install with: pip install cognigraph[server][/red]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]CogniGraph Server[/bold cyan] starting on {host}:{port}")
    uvicorn.run(
        "cognigraph.server.app:create_app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        factory=True,
    )


@app.command()
def bench(
    config: str = typer.Option("cognigraph.yaml", "--config", "-c"),
    queries: int = typer.Option(5, "--queries", "-n", help="Number of test queries"),
    max_rounds: int = typer.Option(3, "--max-rounds", "-r", help="Max rounds per query"),
) -> None:
    """Run a performance benchmark on sample queries."""
    import asyncio
    import time

    from cognigraph.config.settings import CogniGraphConfig
    from cognigraph.backends.mock import MockBackend
    from pathlib import Path

    if Path(config).exists():
        cfg = CogniGraphConfig.from_yaml(config)
    else:
        cfg = CogniGraphConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph loaded. Run 'kogni scan --repo .' first.[/yellow]")
        return

    graph.set_default_backend(MockBackend())

    test_queries = [
        f"Test query {i}: analyze the relationships in this graph"
        for i in range(queries)
    ]

    console.print(f"[cyan]Benchmarking {queries} queries, {max_rounds} max rounds...[/cyan]")

    start = time.perf_counter()
    results = asyncio.run(
        graph.areason_batch(test_queries, max_rounds=max_rounds)
    )
    elapsed = time.perf_counter() - start

    # Report
    avg_conf = sum(r.confidence for r in results) / len(results)
    avg_rounds = sum(r.rounds_completed for r in results) / len(results)
    total_cost = sum(r.cost_usd for r in results)

    console.print(f"\n[bold green]Benchmark Results[/bold green]")
    console.print(f"  Queries: {queries}")
    console.print(f"  Total time: {elapsed:.2f}s")
    console.print(f"  Avg per query: {elapsed / queries * 1000:.0f}ms")
    console.print(f"  Avg confidence: {avg_conf:.0%}")
    console.print(f"  Avg rounds: {avg_rounds:.1f}")
    console.print(f"  Total cost: ${total_cost:.4f}")
    console.print(f"  Nodes in graph: {len(graph)}")


@app.command()
def version() -> None:
    """Show CogniGraph version."""
    from cognigraph.__version__ import __version__
    console.print(f"CogniGraph v{__version__}")


@app.command()
def reason(
    query: str = typer.Argument(..., help="The reasoning query"),
    graph_path: str = typer.Option(None, "--graph", "-g", help="Path to JSON graph file"),
    model: str = typer.Option("qwen2.5:3b", "--model", "-m", help="Ollama model name"),
    host: str = typer.Option("http://localhost:11434", "--host", help="Ollama host"),
    max_rounds: int = typer.Option(3, "--max-rounds", "-r", help="Max message-passing rounds"),
    strategy: str = typer.Option("pcst", "--strategy", "-s", help="Activation strategy"),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text, json"),
) -> None:
    """Run reasoning with real Ollama GPU backend."""
    import asyncio

    from cognigraph.backends.api import OllamaBackend
    from cognigraph.config.settings import CogniGraphConfig
    from cognigraph.core.graph import CogniGraph
    from pathlib import Path

    # Load graph
    if graph_path and Path(graph_path).exists():
        graph = CogniGraph.from_json(graph_path)
    else:
        graph = _load_graph(CogniGraphConfig.default())
        if graph is None:
            console.print("[red]No graph found. Provide --graph path/to/graph.json[/red]")
            raise typer.Exit(1)

    # Set backend
    backend = OllamaBackend(model=model, host=host)
    graph.set_default_backend(backend)

    console.print(f"[bold cyan]CogniGraph[/bold cyan] reasoning with {model}")
    console.print(f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    console.print(f"Query: [green]{query}[/green]")

    result = asyncio.run(
        graph.areason(query, max_rounds=max_rounds, strategy=strategy)
    )

    if output_format == "json":
        import json
        console.print(json.dumps({
            "answer": result.answer,
            "confidence": result.confidence,
            "rounds": result.rounds_completed,
            "nodes": result.node_count,
            "cost_usd": result.cost_usd,
            "latency_ms": result.latency_ms,
            "active_nodes": result.active_nodes,
        }, indent=2))
    else:
        console.print(f"\n[bold green]Answer:[/bold green] {result.answer}")
        console.print(f"[dim]Confidence: {result.confidence:.0%} | Rounds: {result.rounds_completed} | "
                      f"Nodes: {result.node_count} | Cost: ${result.cost_usd:.4f} | "
                      f"Latency: {result.latency_ms:.0f}ms[/dim]")


def _load_graph(cfg):
    """Load graph from config or auto-discover. Returns CogniGraph or None."""
    from cognigraph.core.graph import CogniGraph
    from pathlib import Path

    # 1. Check for cognigraph.json in current directory
    if cfg.graph.connector == "networkx":
        json_path = Path("cognigraph.json")
        if json_path.exists():
            return CogniGraph.from_json(str(json_path), config=cfg)

    # 2. Auto-discover: look for any .json graph file
    for candidate in ["cognigraph.json", "knowledge_graph.json", "graph.json"]:
        if Path(candidate).exists():
            return CogniGraph.from_json(candidate, config=cfg)

    if cfg.graph.connector == "neo4j":
        return None
    return None


# ---------------------------------------------------------------------------
# MCP subcommand
# ---------------------------------------------------------------------------

mcp_app = typer.Typer(help="CogniGraph MCP server for Claude Code integration.")


@mcp_app.command("serve")
def mcp_serve(
    config: str = typer.Option("cognigraph.yaml", "--config", "-c", help="Config file path"),
) -> None:
    """Start the CogniGraph MCP server (stdio transport for Claude Code).

    This server exposes governed development tools via the Model Context Protocol.
    It is designed to be launched automatically by Claude Code via .mcp.json.
    """
    import asyncio

    from cognigraph.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer(config_path=config)
    asyncio.run(server.run_stdio())


app.add_typer(mcp_app, name="mcp")


if __name__ == "__main__":
    app()
