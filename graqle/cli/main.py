"""Graqle CLI — graq command-line interface."""

from __future__ import annotations

import os
import sys

# Ensure Unicode output works on Windows cp1252 consoles (P0-2 fix).
# Rich renders Unicode arrows/symbols from graph data; without this,
# Windows terminals crash with UnicodeEncodeError on non-ASCII chars.
if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
    os.environ["PYTHONIOENCODING"] = "utf-8"

import typer
from rich.console import Console

from graqle.cli.commands.init import init_command
from graqle.cli.commands.ingest import ingest_command
from graqle.cli.commands.grow import grow_command
from graqle.cli.commands.metrics_cmd import metrics_command
from graqle.cli.commands.scan import scan_app
from graqle.cli.commands.doctor import doctor_command
from graqle.cli.commands.setup_guide import setup_guide_command
from graqle.cli.commands.register import register_command
from graqle.cli.commands.activate import activate_command
from graqle.cli.commands.billing import billing_command
from graqle.cli.commands.rebuild import rebuild_command
from graqle.cli.commands.learn import learn_app as learn_sub_app
from graqle.cli.commands.learned import learned_command
from graqle.cli.commands.link import link_app as link_sub_app
from graqle.cli.commands.selfupdate import selfupdate_command
from graqle.cli.commands.login import login_command, logout_command

def _version_callback(value: bool) -> None:
    if value:
        from graqle.__version__ import __version__
        print(f"graq {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="graq",
    help="Graqle — Graphs that think. Turn any KG into a reasoning network.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Graqle CLI — graphs that think."""


app.add_typer(scan_app, name="scan")
app.command(name="init")(init_command)
app.command(name="ingest")(ingest_command)
app.command(name="grow")(grow_command)
app.command(name="metrics")(metrics_command)
app.command(name="doctor")(doctor_command)
app.command(name="setup-guide")(setup_guide_command)
app.command(name="register")(register_command)
app.command(name="activate")(activate_command)
app.command(name="billing")(billing_command)
app.command(name="rebuild")(rebuild_command)
app.add_typer(learn_sub_app, name="learn")
app.command(name="learned")(learned_command)
app.add_typer(link_sub_app, name="link")
app.command(name="self-update")(selfupdate_command)
app.command(name="login")(login_command)
app.command(name="logout")(logout_command)
console = Console()

# ---------------------------------------------------------------------------
# MCP subcommand group: graq mcp serve
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
        "graqle.yaml", "--config", "-c", help="Config file path"
    ),
) -> None:
    """Start the Graqle MCP development server (stdio transport).

    Exposes 7 development intelligence tools over JSON-RPC stdio:
      graq_context, graq_inspect, graq_reason, graq_preflight,
      graq_lessons, graq_impact, graq_learn

    All tools are free for all users. Works with Claude Code, Cursor,
    VS Code, and Windsurf.

    Add to .mcp.json:
        { "mcpServers": { "graq": { "command": "graq", "args": ["mcp", "serve"] } } }
    """
    import asyncio
    from graqle.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer(config_path=config)
    asyncio.run(server.run_stdio())


@app.command()
def run(
    query: str = typer.Argument(..., help="The reasoning query"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    max_rounds: int = typer.Option(5, "--max-rounds", "-r", help="Max message-passing rounds"),
    strategy: str = typer.Option(None, "--strategy", "-s", help="Activation strategy (default: from config, usually 'chunk')"),
    protocol: str = typer.Option(
        "consensus", "--protocol", "-p",
        help="Reasoning protocol: consensus (default) or debate",
    ),
    explain: bool = typer.Option(
        False, "--explain", "-e", help="Output full explanation trace with provenance",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run a reasoning query on the Graqle.

    \b
    Protocols:
        consensus — standard message-passing with convergence (default)
        debate    -- adversarial debate: opening -> challenge -> rebuttal -> synthesis

    \b
    Examples:
        graq run "what calls the auth service?"
        graq run "CORS issue?" --protocol debate --explain
    """
    import asyncio
    import logging

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle
    from pathlib import Path

    # Load config
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()
        if verbose:
            console.print("[yellow]No config file found, using defaults[/yellow]")

    # Use config strategy if not overridden by CLI flag
    strategy = strategy or cfg.activation.strategy

    console.print(f"[bold cyan]Graqle[/bold cyan] -- Graphs that think")
    console.print(f"Query: [green]{query}[/green]")
    console.print(f"Strategy: {strategy} | Protocol: {protocol} | Max rounds: {max_rounds}")

    # Try to load graph from config
    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph source configured. Use 'graq init' to set up.[/yellow]")
        return

    # Create real backend from config (Anthropic, Bedrock, OpenAI, Ollama)
    backend = _create_backend_from_config(cfg, verbose=verbose)
    graph.set_default_backend(backend)

    # Run reasoning with selected protocol
    result = asyncio.run(
        graph.areason(query, max_rounds=max_rounds, strategy=strategy)
    )

    # If debate protocol, run debate on active nodes
    if protocol == "debate" and result.active_nodes:
        console.print(f"\n[bold yellow]Debate Protocol[/bold yellow] — {len(result.active_nodes)} nodes")
        try:
            from graqle.orchestration.debate import DebateProtocol
            debate = DebateProtocol(challenge_rounds=1, parallel=True)
            debate_messages = asyncio.run(
                debate.run(graph, query, result.active_nodes)
            )
            total_exchanges = sum(len(msgs) for msgs in debate_messages.values())
            console.print(f"  Debate: {total_exchanges} exchanges across {len(debate_messages)} nodes")
        except Exception as e:
            console.print(f"  [yellow]Debate skipped: {e}[/yellow]")

    # Display results
    console.print(f"\n[bold green]Answer:[/bold green]")
    console.print(result.answer)
    console.print(f"\n[dim]Confidence: {result.confidence:.0%} | "
                  f"Rounds: {result.rounds_completed} | "
                  f"Nodes: {result.node_count} | "
                  f"Cost: ${result.cost_usd:.4f} | "
                  f"Latency: {result.latency_ms:.0f}ms[/dim]")

    # Track usage + check milestones (non-blocking)
    try:
        from graqle.leads.collector import (
            check_milestone,
            get_milestone_nudge,
            get_registration_nudge,
            track_usage,
        )
        track_usage("reason_query")
        milestone = check_milestone()
        if milestone:
            console.print(f"\n{get_milestone_nudge(milestone)}")
        else:
            nudge = get_registration_nudge()
            if nudge:
                console.print(f"\n{nudge}")
    except Exception:
        pass  # Never fail on telemetry

    # Explanation trace
    if explain:
        console.print(f"\n[bold]Explanation Trace[/bold]")
        try:
            from graqle.orchestration.explanation import ExplanationTrace
            trace = ExplanationTrace(query=query)
            # Build trace from message trace in result
            if result.message_trace:
                for i, msg_dict in enumerate(result.message_trace):
                    round_num = msg_dict.get("round", i)
                    node_id = msg_dict.get("source_node_id", f"node-{i}")
                    content = msg_dict.get("content", "")
                    confidence = msg_dict.get("confidence", 0.5)
                    from graqle.orchestration.explanation import NodeClaim
                    trace.claims.append(NodeClaim(
                        node_id=node_id,
                        round_num=round_num,
                        content=content[:300],
                        confidence=confidence,
                        reasoning_type=msg_dict.get("reasoning_type", "INITIAL"),
                    ))
                trace.final_answer = result.answer
            console.print(trace.to_summary())
        except Exception as e:
            console.print(f"  [yellow]Trace error: {e}[/yellow]")


@app.command()
def context(
    service: str = typer.Argument(..., help="Service/entity to get context for"),
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, yaml"),
) -> None:
    """Get structured context for a service (Claude Code integration).

    Returns focused, 500-token context instead of loading 20-60K tokens
    of raw files. Designed to be called from CLAUDE.md rules.
    """
    from graqle.config.settings import GraqleConfig
    from pathlib import Path

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)

    if graph is None:
        # Fallback: generate context from service name
        console.print(f"# Context for: {service}")
        console.print(f"No graph loaded. Run 'graq scan --repo .' first.")
        return

    # Find the service node
    node = graph.nodes.get(service)
    if node is None:
        # Substring match
        matches = [
            nid for nid in graph.nodes
            if service.lower() in nid.lower()
        ]
        if matches:
            node = graph.nodes[matches[0]]
        else:
            # Fuzzy match using difflib
            import difflib
            close = difflib.get_close_matches(
                service.lower(),
                [nid.lower() for nid in graph.nodes],
                n=3,
                cutoff=0.4,
            )
            if close:
                # Map lowered IDs back to original IDs
                lower_to_orig = {nid.lower(): nid for nid in graph.nodes}
                suggestions = [lower_to_orig[c] for c in close]
                console.print(f"Service '{service}' not found in graph.")
                console.print(f"Did you mean: {', '.join(suggestions)}")
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
            context_parts.append(f"  -> {rel} -> {n.label}: {n.description[:100]}")

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
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    stats: bool = typer.Option(False, "--stats", help="Show graph statistics"),
) -> None:
    """Inspect the Graqle — show nodes, edges, stats."""
    from graqle.config.settings import GraqleConfig
    from pathlib import Path

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph loaded.[/yellow]")
        return

    if stats:
        s = graph.stats
        console.print(f"[bold]Graqle Stats[/bold]")
        console.print(f"  Nodes: {s.total_nodes}")
        console.print(f"  Edges: {s.total_edges}")
        console.print(f"  Avg degree: {s.avg_degree:.1f}")
        console.print(f"  Density: {s.density:.3f}")
        console.print(f"  Components: {s.connected_components}")
        console.print(f"  Hub nodes: {', '.join(s.hub_nodes)}")
    else:
        console.print(f"[bold]Graqle[/bold]: {graph}")
        for nid, node in list(graph.nodes.items())[:20]:
            console.print(f"  [{node.entity_type}] {nid}: {node.label} (degree={node.degree})")
        if len(graph.nodes) > 20:
            console.print(f"  ... and {len(graph.nodes) - 20} more nodes")


@app.command()
def serve(
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of workers"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on changes"),
) -> None:
    """Start the Graqle API server."""
    missing = []
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        missing.append("uvicorn")
    try:
        import fastapi  # noqa: F401
    except ImportError:
        missing.append("fastapi")
    if missing:
        console.print(
            f"[red]Missing server dependencies: {', '.join(missing)}[/red]\n"
            "\n"
            "  Install with:\n"
            "    [cyan]pip install 'graqle\\[server]'[/cyan]\n"
            "\n"
            "  This installs: uvicorn, fastapi, httptools, uvloop (unix)\n"
        )
        raise typer.Exit(1)

    console.print(f"[bold cyan]Graqle Server[/bold cyan] starting on {host}:{port}")
    uvicorn.run(
        "graqle.server.app:create_app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        factory=True,
    )


@app.command()
def studio(
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8888, "--port", "-p", help="Bind port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
) -> None:
    """Launch Graqle Studio — local visual dashboard.

    \b
    Opens an interactive dashboard at http://127.0.0.1:8888/studio/ with:
      - Graph explorer (D3 force-directed visualization)
      - Live reasoning view (SSE streaming)
      - Metrics dashboard (tokens, cost, ROI)
      - Settings & Neo4j status

    \b
    Examples:
        graq studio
        graq studio --port 9000
        graq studio --no-browser
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Server dependencies not installed.[/red]\n"
            "\n"
            "  Install with:\n"
            "    [cyan]pip install 'graqle\\[studio]'[/cyan]\n"
            "\n"
            "  This installs: uvicorn, fastapi, jinja2\n"
        )
        raise typer.Exit(1)

    from pathlib import Path
    from graqle.config.settings import GraqleConfig

    # Load config
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    # Load graph
    graph = _load_graph(cfg)

    # Load metrics engine if available
    metrics = None
    try:
        from graqle.metrics.engine import MetricsEngine
        metrics = MetricsEngine()
    except Exception:
        pass

    console.print(f"[bold cyan]Graqle Studio[/bold cyan] — Graphs that think")
    if graph:
        console.print(f"  Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    else:
        console.print("  [yellow]No graph loaded — dashboard will show empty state[/yellow]")

    # Build FastAPI app with studio mounted
    from fastapi import FastAPI
    from graqle.studio.app import mount_studio

    app_instance = FastAPI(title="Graqle Studio", version="0.11.0")

    state = {
        "graph": graph,
        "config": cfg,
        "metrics": metrics,
    }
    mount_studio(app_instance, state)

    url = f"http://{host}:{port}/studio/"
    console.print(f"  URL: [bold]{url}[/bold]")

    # Auto-open browser
    if not no_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app_instance, host=host, port=port, log_level="info")


@app.command()
def bench(
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    queries: int = typer.Option(5, "--queries", "-n", help="Number of test queries"),
    max_rounds: int = typer.Option(3, "--max-rounds", "-r", help="Max rounds per query"),
) -> None:
    """Run a performance benchmark on sample queries."""
    import asyncio
    import time

    from graqle.config.settings import GraqleConfig
    from pathlib import Path

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[yellow]No graph loaded. Run 'graq scan --repo .' first.[/yellow]")
        return

    backend = _create_backend_from_config(cfg)

    # Fail fast: verify backend can actually respond before running N queries
    if hasattr(backend, "is_fallback") and backend.is_fallback:
        console.print(f"[red]Backend unavailable: {getattr(backend, 'fallback_reason', 'unknown')}[/red]")
        console.print("[yellow]Fix the backend configuration before running benchmarks.[/yellow]")
        raise typer.Exit(1)

    graph.set_default_backend(backend)

    # Quick smoke test — one query to catch errors early
    try:
        smoke = asyncio.run(graph.areason("smoke test", max_rounds=1))
    except Exception as e:
        console.print(f"[red]Backend error: {e}[/red]")
        console.print("[yellow]Fix the backend before running benchmarks. Run 'graq doctor' for help.[/yellow]")
        raise typer.Exit(1)

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
def validate(
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    graph_path: str = typer.Option(None, "--graph", "-g", help="Path to JSON graph file"),
    fix: bool = typer.Option(False, "--fix", help="Auto-enrich empty descriptions from metadata"),
) -> None:
    """Validate knowledge graph quality for reasoning.

    Checks that nodes have descriptions so agents can reason effectively.
    Use --fix to auto-enrich empty nodes from their metadata/properties.

    \b
    Examples:
        graq validate
        graq validate --graph my_kg.json --fix
    """
    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle
    from pathlib import Path

    if graph_path and Path(graph_path).exists():
        graph = Graqle.from_json(graph_path)
    else:
        if Path(config).exists():
            cfg = GraqleConfig.from_yaml(config)
        else:
            cfg = GraqleConfig.default()
        graph = _load_graph(cfg)

    if graph is None:
        console.print("[red]No graph found. Provide --graph or set up graqle.yaml[/red]")
        raise typer.Exit(1)

    report = graph.validate()

    # Display report
    score = report["quality_score"]
    color = "green" if score >= 70 else "yellow" if score >= 40 else "red"
    console.print(f"\n[bold]KG Quality Report[/bold]")
    console.print(f"  Nodes: {report['total_nodes']} | Edges: {report['total_edges']}")
    console.print(f"  With descriptions: {report['nodes_with_descriptions']}")
    console.print(f"  Without descriptions: {report['nodes_without_descriptions']}")
    console.print(f"  Avg description length: {report['avg_description_length']} chars")
    console.print(f"  Quality score: [{color}]{score}/100[/{color}]")

    if report["warnings"]:
        console.print(f"\n[yellow]Warnings:[/yellow]")
        for w in report["warnings"]:
            console.print(f"  ! {w}")

    if fix and report["nodes_without_descriptions"] > 0:
        console.print(f"\n[cyan]Auto-enrichment already applied during load.[/cyan]")
        console.print(f"To improve quality further, add rich descriptions to your KG nodes.")

    if score >= 70:
        console.print(f"\n[green]KG is ready for reasoning.[/green]")
    elif score >= 40:
        console.print(f"\n[yellow]KG quality is moderate. Consider enriching node descriptions.[/yellow]")
    else:
        console.print(f"\n[red]KG quality is low. Agents will produce poor reasoning.[/red]")
        console.print(f"[red]Add descriptions to your nodes before running queries.[/red]")


@app.command()
def version() -> None:
    """Show Graqle version."""
    from graqle.__version__ import __version__
    console.print(f"Graqle v{__version__}")


# ---------------------------------------------------------------------------
# Ontology subcommand group: graq ontology generate / detect
# ---------------------------------------------------------------------------

ontology_app = typer.Typer(
    name="ontology",
    help="Ontology tools — detect domain, generate schema, validate graph.",
    no_args_is_help=True,
)
app.add_typer(ontology_app, name="ontology")


@ontology_app.command("detect")
def ontology_detect(
    path: str = typer.Argument(".", help="Project root to analyze"),
) -> None:
    """Detect the domain of a codebase and show domain profile."""
    from pathlib import Path
    from graqle.ontology.domain_detector import detect_domain

    root = Path(path).resolve()
    profile = detect_domain(root)

    console.print(f"[bold cyan]Domain Profile[/bold cyan]")
    console.print(f"  Primary: [bold]{profile.primary_domain}[/bold] ({profile.confidence:.0%})")
    console.print(f"  Secondary: {', '.join(profile.secondary_domains[:5])}")
    console.print(f"  Language: {profile.language} | Frameworks: {', '.join(profile.frameworks[:5])}")
    console.print(f"  Frontend: {'yes' if profile.has_frontend else 'no'} | "
                  f"Backend: {'yes' if profile.has_backend else 'no'} | "
                  f"ML: {'yes' if profile.has_ml else 'no'} | "
                  f"CI/CD: {'yes' if profile.has_ci_cd else 'no'}")
    console.print(f"  Docker: {'yes' if profile.has_docker else 'no'} | "
                  f"K8s: {'yes' if profile.has_kubernetes else 'no'} | "
                  f"Serverless: {'yes' if profile.has_serverless else 'no'} | "
                  f"Tests: {'yes' if profile.has_tests else 'no'}")


@ontology_app.command("generate")
def ontology_generate(
    path: str = typer.Argument(".", help="Project root to analyze"),
    api_key: str = typer.Option(
        None, "--api-key", help="API key for LLM ontology generation",
    ),
    model: str = typer.Option(
        "claude-sonnet-4-6", "--model", "-m",
        help="Model for ontology generation (best LLM recommended)",
    ),
    output: str = typer.Option(
        None, "--output", "-o", help="Save ontology to JSON file",
    ),
) -> None:
    """Generate a domain-specific ontology using LLM analysis.

    Detects the project domain and uses Claude Sonnet (or specified model)
    to generate comprehensive node types and edge types.

    \b
    Examples:
        graq ontology generate
        graq ontology generate --api-key sk-... --output ontology.json
    """
    import json as json_lib
    import os
    from pathlib import Path
    from graqle.ontology.domain_detector import auto_ontology, detect_domain
    from graqle.ontology.schema import get_all_node_types, get_all_edge_types

    root = Path(path).resolve()
    ont_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    console.print(f"[bold cyan]Generating Domain Ontology[/bold cyan]")

    node_shapes, edge_shapes = auto_ontology(root, api_key=ont_key, register=True)

    console.print(f"  Generated [green]{len(node_shapes)}[/green] node types, "
                  f"[green]{len(edge_shapes)}[/green] edge types")
    console.print(f"  Total registered: {len(get_all_node_types())} node types, "
                  f"{len(get_all_edge_types())} edge types")

    if output:
        out_data = {
            "node_types": [
                {"type": s.node_type, "description": s.description,
                 "properties": [p.name for p in s.properties]}
                for s in node_shapes
            ],
            "edge_types": [
                {"type": s.edge_type, "description": s.description,
                 "sources": s.valid_source_types, "targets": s.valid_target_types}
                for s in edge_shapes
            ],
        }
        Path(output).write_text(
            json_lib.dumps(out_data, indent=2), encoding="utf-8",
        )
        console.print(f"  Saved to [bold]{output}[/bold]")


@ontology_app.command("from-text")
def ontology_from_text(
    file: str = typer.Argument(..., help="Text/regulation file to generate ontology from"),
    domain: str = typer.Option("auto", "--domain", "-d", help="Domain name"),
    output: str = typer.Option(None, "--output", "-o", help="Save to JSON"),
) -> None:
    """Generate OWL + SHACL ontology from a regulatory/governance text file.

    Uses Innovation #8 (OntologyGenerator) — reads a document once with a
    high-end LLM and generates structured semantic constraints.

    \b
    Example:
        graq ontology from-text regulations/eu_ai_act.txt --domain eu_ai_act
    """
    import asyncio
    import json as json_lib
    import os
    from pathlib import Path

    file_path = Path(file)
    if not file_path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    text = file_path.read_text(encoding="utf-8", errors="ignore")
    domain_name = domain if domain != "auto" else file_path.stem

    console.print(f"[bold cyan]OntologyGenerator[/bold cyan] — Innovation #8")
    console.print(f"  Document: {file_path.name} ({len(text):,} chars)")
    console.print(f"  Domain: {domain_name}")

    # Try to use Anthropic backend
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY required for ontology generation[/red]")
        raise typer.Exit(1)

    try:
        from graqle.backends.anthropic_backend import AnthropicBackend
        backend = AnthropicBackend(model="claude-sonnet-4-6", api_key=api_key)
    except ImportError:
        # Fallback to mock for structure demo
        from graqle.backends.mock import MockBackend
        backend = MockBackend()

    from graqle.ontology.ontology_generator import OntologyGenerator
    generator = OntologyGenerator(backend=backend)

    console.print("  Generating... (one-time LLM call)")
    owl, constraints = asyncio.run(
        generator.generate_from_text(text, domain_name)
    )

    console.print(f"  [green]Generated: {len(owl)} types, {len(constraints)} constraints[/green]")
    console.print(f"  Cost: ${generator.generation_cost:.4f}")

    if output:
        out_data = {
            "owl_hierarchy": owl,
            "semantic_constraints": OntologyGenerator.constraints_to_dict(constraints),
        }
        Path(output).write_text(
            json_lib.dumps(out_data, indent=2), encoding="utf-8",
        )
        console.print(f"  Saved to [bold]{output}[/bold]")
    else:
        for etype, parent in list(owl.items())[:10]:
            console.print(f"    {etype} -> {parent}")
        if len(owl) > 10:
            console.print(f"    ... and {len(owl) - 10} more")


@app.command()
def reason(
    query: str = typer.Argument(..., help="The reasoning query"),
    graph_path: str = typer.Option(None, "--graph", "-g", help="Path to JSON graph file"),
    model: str = typer.Option("qwen2.5:3b", "--model", "-m", help="Ollama model name"),
    host: str = typer.Option("http://localhost:11434", "--host", help="Ollama host"),
    max_rounds: int = typer.Option(3, "--max-rounds", "-r", help="Max message-passing rounds"),
    strategy: str = typer.Option(None, "--strategy", "-s", help="Activation strategy (default: from config, usually 'chunk')"),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text, json"),
) -> None:
    """Run reasoning with real Ollama GPU backend."""
    import asyncio

    from graqle.backends.api import OllamaBackend
    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle
    from pathlib import Path

    # Load graph
    if graph_path and Path(graph_path).exists():
        graph = Graqle.from_json(graph_path)
    else:
        graph = _load_graph(GraqleConfig.default())
        if graph is None:
            console.print("[red]No graph found. Provide --graph path/to/graph.json[/red]")
            raise typer.Exit(1)

    # Use config strategy if not overridden by CLI flag
    strategy = strategy or "chunk"

    # Set backend
    backend = OllamaBackend(model=model, host=host)
    graph.set_default_backend(backend)

    console.print(f"[bold cyan]Graqle[/bold cyan] reasoning with {model}")
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
    """Load graph from config or auto-discover. Returns Graqle or None."""
    from graqle.core.graph import Graqle
    from pathlib import Path

    # 1. Neo4j backend — primary production path
    if cfg.graph.connector == "neo4j":
        return Graqle.from_neo4j(
            uri=cfg.graph.uri or "bolt://localhost:7687",
            username=cfg.graph.username or "neo4j",
            password=cfg.graph.password or "",
            database=cfg.graph.database or "neo4j",
            config=cfg,
        )

    # 2. JSON/NetworkX fallback — local development / quick testing
    if cfg.graph.connector == "networkx":
        json_path = Path("graqle.json")
        if json_path.exists():
            return Graqle.from_json(str(json_path), config=cfg)

    # 3. Auto-discover: look for any .json graph file
    for candidate in ["graqle.json", "knowledge_graph.json", "graph.json"]:
        if Path(candidate).exists():
            return Graqle.from_json(candidate, config=cfg)

    return None


def _create_backend_from_config(cfg, verbose: bool = False):
    """Create a real model backend from graqle.yaml config.

    Tries to instantiate the configured backend (Anthropic, OpenAI, Bedrock,
    Ollama). Falls back to MockBackend with LOUD warning if all real backends fail.
    """
    import os
    from graqle.backends.mock import MockBackend

    backend_name = cfg.model.backend
    model_name = cfg.model.model
    api_key = cfg.model.api_key

    # Resolve env var references like ${ANTHROPIC_API_KEY}
    if api_key and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        api_key = os.environ.get(env_var)

    def _mock_fallback(reason: str) -> MockBackend:
        console.print(f"[bold yellow]WARNING: {reason}[/bold yellow]")
        console.print("[yellow]  Falling back to mock backend — results will NOT be real LLM reasoning.[/yellow]")
        console.print("[yellow]  Run 'graq doctor' to diagnose and fix.[/yellow]")
        return MockBackend(is_fallback=True, fallback_reason=reason)

    try:
        if backend_name == "anthropic":
            from graqle.backends.api import AnthropicBackend
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return _mock_fallback("ANTHROPIC_API_KEY not set")
            backend = AnthropicBackend(model=model_name, api_key=api_key)
            if verbose:
                console.print(f"[green]Backend: Anthropic ({model_name})[/green]")
            return backend

        elif backend_name == "openai":
            from graqle.backends.api import OpenAIBackend
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return _mock_fallback("OPENAI_API_KEY not set")
            backend = OpenAIBackend(model=model_name, api_key=api_key)
            if verbose:
                console.print(f"[green]Backend: OpenAI ({model_name})[/green]")
            return backend

        elif backend_name == "bedrock":
            from graqle.backends.api import BedrockBackend
            region = getattr(cfg.model, "region", None) or os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
            backend = BedrockBackend(model=model_name, region=region)
            if verbose:
                console.print(f"[green]Backend: Bedrock ({model_name} in {region})[/green]")
            return backend

        elif backend_name == "ollama":
            from graqle.backends.api import OllamaBackend
            host = getattr(cfg.model, "host", None) or "http://localhost:11434"
            backend = OllamaBackend(model=model_name, host=host)
            if verbose:
                console.print(f"[green]Backend: Ollama ({model_name})[/green]")
            return backend

        elif backend_name == "local":
            return _mock_fallback("Local backend not yet supported in CLI")

        else:
            return _mock_fallback(f"Unknown backend '{backend_name}'")

    except ImportError as e:
        return _mock_fallback(f"Missing package: {e}. Install with: pip install graqle[api]")
    except Exception as e:
        return _mock_fallback(f"Backend init failed: {e}")


if __name__ == "__main__":
    app()
