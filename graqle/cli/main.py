"""Graqle CLI — graq command-line interface."""

# ── graqle:intelligence ──
# module: graqle.cli.main
# risk: MEDIUM (impact radius: 2 modules)
# consumers: test_learned, test_version
# dependencies: __future__, console, os, sys, typer +22 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import sys

import typer

from graqle.cli.commands.activate import activate_command
from graqle.cli.commands.audit import audit_command
from graqle.cli.commands.billing import billing_command
from graqle.cli.commands.doctor import doctor_command
from graqle.cli.commands.grow import grow_command
from graqle.cli.commands.ingest import ingest_command
from graqle.cli.commands.init import init_command
from graqle.cli.commands.learn import learn_app as learn_sub_app
from graqle.cli.commands.learned import learned_command
from graqle.cli.commands.link import link_app as link_sub_app
from graqle.cli.commands.login import login_command, logout_command
from graqle.cli.commands.metrics_cmd import metrics_command
from graqle.cli.commands.rebuild import rebuild_command
from graqle.cli.commands.register import register_command
from graqle.cli.commands.scan import scan_app
from graqle.cli.commands.scorch import scorch_app
from graqle.cli.commands.cloud import cloud_app
from graqle.cli.commands.migrate import migrate_command
from graqle.cli.commands.selfupdate import selfupdate_command
from graqle.cli.commands.setup_guide import setup_guide_command
from graqle.cli.commands.sync import sync_app as sync_sub_app
from graqle.cli.commands.team import team_app as team_sub_app
from graqle.cli.commands.upgrade import upgrade_command

# Universal Unicode fix — MUST be first import (before Rich, before typer)
# This reconfigures sys.stdout/stderr to UTF-8 on ALL platforms,
# preventing the cp1252 UnicodeEncodeError on Windows.
from graqle.cli.console import BRAND_NAME, create_console  # noqa: E402 — intentionally first
from graqle.intelligence.compile import compile_command
from graqle.intelligence.verify import verify_command


def _version_callback(value: bool) -> None:
    if value:
        from graqle.__version__ import __version__
        print(f"graQle v{__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="graq",
    help="graQle — Graphs that think. Turn any KG into a reasoning network.",
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
app.command(name="audit")(audit_command)
app.add_typer(learn_sub_app, name="learn")
app.command(name="learned")(learned_command)
app.add_typer(link_sub_app, name="link")
app.command(name="self-update")(selfupdate_command)
app.command(name="migrate")(migrate_command)
app.command(name="login")(login_command)
app.command(name="logout")(logout_command)
app.add_typer(sync_sub_app, name="sync")
app.add_typer(team_sub_app, name="team")
app.add_typer(cloud_app, name="cloud")
app.add_typer(scorch_app, name="scorch")
app.add_typer(compile_command, name="compile")
app.add_typer(verify_command, name="verify")

# Plugin ecosystem
from graqle.cli.commands.plugins import app as plugins_app
app.add_typer(plugins_app, name="plugins")
app.command(name="upgrade")(upgrade_command)
console = create_console()

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
    read_only: bool = typer.Option(
        False, "--read-only", help="Read-only mode: blocks mutation tools (graq_learn, graq_reload)"
    ),
) -> None:
    """Start the Graqle MCP development server (stdio transport).

    Exposes development intelligence tools over JSON-RPC stdio:
      graq_context, graq_inspect, graq_reason, graq_preflight,
      graq_lessons, graq_impact, graq_learn, graq_runtime,
      graq_route, graq_lifecycle

    Use --read-only to block all mutation tools (graq_learn, graq_reload).

    All tools are free for all users. Works with Claude Code, Cursor,
    VS Code, and Windsurf.

    Add to .mcp.json:
        { "mcpServers": { "graq": { "command": "graq", "args": ["mcp", "serve"] } } }
    """
    import asyncio
    import atexit
    from pathlib import Path

    from graqle.__version__ import __version__
    from graqle.plugins.mcp_dev_server import KogniDevServer

    # Write PID + version so self-update and other tools can detect running server
    graqle_dir = Path(".graqle")
    graqle_dir.mkdir(exist_ok=True)
    pid_file = graqle_dir / "mcp.pid"
    version_file = graqle_dir / "mcp.version"

    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    version_file.write_text(__version__, encoding="utf-8")

    def _cleanup_pid():
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup_pid)

    # Version mismatch detection: warn if a previous server was running a different version
    # (This helps catch the case where pip upgrade happened but MCP wasn't restarted)

    server = KogniDevServer(config_path=config, read_only=read_only)
    asyncio.run(server.run_stdio())


@mcp_app.command("restart")
def mcp_restart() -> None:
    """Restart the MCP server (kills running instance, starts new one).

    Use after `pip install --upgrade graqle` to pick up the new version.
    Reads .graqle/mcp.pid to find and stop the running server.
    """
    import signal
    from pathlib import Path

    pid_file = Path(".graqle/mcp.pid")
    version_file = Path(".graqle/mcp.version")

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            old_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "?"
            os.kill(pid, signal.SIGTERM)
            console.print(f"[yellow]Stopped MCP server (PID {pid}, v{old_version})[/yellow]")
            pid_file.unlink(missing_ok=True)
        except ProcessLookupError:
            console.print("[dim]No running MCP server found (stale PID file removed)[/dim]")
            pid_file.unlink(missing_ok=True)
        except (ValueError, OSError) as e:
            console.print(f"[yellow]Could not stop MCP server: {e}[/yellow]")
    else:
        console.print("[dim]No .graqle/mcp.pid found — MCP server may not be running[/dim]")

    from graqle.__version__ import __version__
    console.print(f"[cyan]Starting MCP server v{__version__}...[/cyan]")
    console.print("[dim]Tip: Your IDE (Claude Code/Cursor) will auto-reconnect.[/dim]")

    # Start new server in background
    import subprocess
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [sys.executable, "-m", "graqle.cli.main", "mcp", "serve"],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["graq", "mcp", "serve"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        console.print(f"[green]MCP server v{__version__} started.[/green]")
    except Exception as e:
        console.print(f"[red]Failed to start: {e}[/red]")
        console.print("[yellow]Run 'graq mcp serve' manually.[/yellow]")


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

    from pathlib import Path

    from graqle.config.settings import GraqleConfig

    # Load config
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()
        if verbose:
            console.print("[yellow]No config file found, using defaults[/yellow]")

    # Use config strategy if not overridden by CLI flag
    strategy = strategy or cfg.activation.strategy

    console.print(f"{BRAND_NAME} -- Graphs that think")
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
    console.print("\n[bold green]Answer:[/bold green]")
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
        console.print("\n[bold]Explanation Trace[/bold]")
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
    service: str = typer.Argument(None, help="Service/entity to get context for"),
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, yaml"),
    json_output: bool = typer.Option(False, "--json", help="Output clean JSON (no ANSI, no embeddings). Overrides --format."),
    task: str = typer.Option(None, "--task", "-t", help="Get task-based context (matches MCP graq_context). Overrides service arg."),
) -> None:
    """Get structured context for a service or task.

    Two modes:
      graq context auth_service           # node-focused context
      graq context --task "fix CORS bug"  # task-based context (MCP-style)

    Returns focused, 500-token context instead of loading 20-60K tokens
    of raw files. Use --json for machine-readable output.
    """
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

    # --json overrides --format
    if json_output:
        format = "json"

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)

    if graph is None:
        if format == "json":
            import json
            print(json.dumps({"error": "No graph loaded. Run 'graq scan --repo .' first."}, indent=2))
        else:
            console.print(f"# Context for: {task or service}")
            console.print("No graph loaded. Run 'graq scan --repo .' first.")
        return

    # Task-based context mode (matches MCP graq_context behavior)
    if task:
        import difflib
        task_lower = task.lower()
        scored = []
        for nid, n in graph.nodes.items():
            text = f"{n.id} {n.label} {n.entity_type} {n.description}".lower()
            # Simple keyword matching
            score = sum(1 for word in task_lower.split() if word in text)
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda x: -x[0])
        matches = [n for _, n in scored[:10]]

        if format == "json":
            import json
            print(json.dumps({
                "task": task,
                "nodes_matched": len(matches),
                "nodes": [
                    {"id": m.id, "label": m.label, "type": m.entity_type, "description": m.description[:200]}
                    for m in matches
                ],
            }, indent=2, default=str))
        else:
            console.print(f"[bold cyan]Context for task:[/bold cyan] {task}")
            if matches:
                for m in matches:
                    console.print(f"  [bold]{m.label}[/bold] ({m.entity_type}): {m.description[:120]}")
            else:
                console.print("  No matching nodes found.")
        return

    if not service:
        console.print("[red]Provide a service name or use --task 'description'[/red]")
        raise typer.Exit(1)

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
                if format == "json":
                    import json
                    print(json.dumps({"error": f"Service '{service}' not found", "suggestions": suggestions}, indent=2))
                else:
                    console.print(f"Service '{service}' not found in graph.")
                    console.print(f"Did you mean: {', '.join(suggestions)}")
            else:
                if format == "json":
                    import json
                    print(json.dumps({"error": f"Service '{service}' not found in graph."}, indent=2))
                else:
                    console.print(f"Service '{service}' not found in graph.")
            return

    # Build neighbor and relationship data
    neighbors = graph.get_neighbors(node.id)
    relationships = []
    for nid in neighbors[:10]:
        n = graph.nodes[nid]
        edges = graph.get_edges_between(node.id, nid)
        rel = edges[0].relationship if edges else "RELATED_TO"
        relationships.append({
            "target": nid,
            "target_label": n.label,
            "target_type": n.entity_type,
            "relationship": rel,
            "target_description": n.description[:200] if n.description else "",
        })

    # Filter properties: remove embeddings, chunks, and other large/binary data
    _HIDDEN_PROPS = {"_embedding_cache", "chunks", "_chunks", "_embeddings",
                     "embedding", "embeddings", "vector", "vectors"}
    filtered_props = {}
    if node.properties:
        for k, v in node.properties.items():
            if k in _HIDDEN_PROPS:
                continue
            # Skip large list/dict values that are likely embeddings
            if isinstance(v, list) and len(v) > 50:
                continue
            v_str = str(v)
            if len(v_str) > 500:
                v_str = v_str[:500] + "..."
            filtered_props[k] = v_str if len(str(v)) > 500 else v

    if format == "json":
        import json
        json_data = {
            "name": node.id,
            "label": node.label,
            "entity_type": node.entity_type,
            "description": node.description,
            "properties": filtered_props,
            "relationships": relationships,
        }
        # Use print() not console.print() to avoid ANSI codes
        print(json.dumps(json_data, indent=2, default=str))
    else:
        # Text output (original behavior)
        context_parts = [
            f"# {node.label} ({node.entity_type})",
            f"Description: {node.description}",
        ]

        if filtered_props:
            context_parts.append("Properties:")
            for k, v in filtered_props.items():
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                context_parts.append(f"  {k}: {v_str}")

        if neighbors:
            context_parts.append(f"Connected to: {', '.join(neighbors)}")
            for rel_info in relationships[:5]:
                context_parts.append(
                    f"  -> {rel_info['relationship']} -> {rel_info['target_label']}: "
                    f"{rel_info['target_description'][:100]}"
                )

        console.print("\n".join(context_parts))


@app.command()
def inspect(
    config: str = typer.Option("graqle.yaml", "--config", "-c"),
    stats: bool = typer.Option(False, "--stats", help="Show graph statistics"),
) -> None:
    """Inspect the Graqle — show nodes, edges, stats."""
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

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
        console.print(f"{BRAND_NAME} Stats")
        console.print(f"  Nodes: {s.total_nodes}")
        console.print(f"  Edges: {s.total_edges}")
        console.print(f"  Avg degree: {s.avg_degree:.1f}")
        console.print(f"  Density: {s.density:.3f}")
        console.print(f"  Components: {s.connected_components}")
        console.print(f"  Hub nodes: {', '.join(s.hub_nodes)}")
    else:
        console.print(f"{BRAND_NAME}: {graph}")
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
    read_only: bool = typer.Option(False, "--read-only", help="Read-only mode: disables /learn and /reload endpoints"),
) -> None:
    """Start the Graqle API server.

    Use --read-only to disable mutation endpoints (/learn, /reload).
    This is useful for multi-agent setups where only one agent should write.
    """
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

    # Set env var so create_app can pick it up
    if read_only:
        os.environ["GRAQLE_READ_ONLY"] = "1"

    console.print(f"{BRAND_NAME} Server starting on {host}:{port}")
    if read_only:
        console.print("[yellow]  Read-only mode: /learn and /reload endpoints disabled[/yellow]")
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

    console.print(f"{BRAND_NAME} Studio — Graphs that think")
    console.print()
    console.print("  [yellow]⚠  This is the lightweight built-in Studio (Jinja2/HTMX).[/yellow]")
    console.print("  [yellow]   For the full Studio experience with Intelligence, Governance,[/yellow]")
    console.print("  [yellow]   DRACE radar, and rich graph filters, use:[/yellow]")
    console.print()
    console.print("     [cyan]graq serve --port 8077[/cyan]   ← start the API backend")
    console.print("     [cyan]graqle.com/dashboard[/cyan]     ← open the modern Studio")
    console.print("     [dim]Or run npm run dev in graqle-studio/ for local development[/dim]")
    console.print()
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
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

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

    # Run queries sequentially with fail-fast: stop on first backend error
    start = time.perf_counter()
    results = []
    for i, q in enumerate(test_queries):
        try:
            r = asyncio.run(graph.areason(q, max_rounds=max_rounds))
            results.append(r)
        except Exception as e:
            console.print(f"\n[red]Query {i + 1}/{queries} failed: {e}[/red]")
            console.print(
                "[yellow]Stopping benchmark early — backend is misconfigured or unavailable.[/yellow]"
            )
            console.print("[yellow]Run 'graq doctor' to diagnose the issue.[/yellow]")
            raise typer.Exit(1)
    elapsed = time.perf_counter() - start

    if not results:
        console.print("[yellow]No results returned. Backend may have failed silently.[/yellow]")
        raise typer.Exit(1)

    # Report
    avg_conf = sum(r.confidence for r in results) / len(results)
    avg_rounds = sum(r.rounds_completed for r in results) / len(results)
    total_cost = sum(r.cost_usd for r in results)

    console.print("\n[bold green]Benchmark Results[/bold green]")
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
    from pathlib import Path

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

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
    console.print("\n[bold]KG Quality Report[/bold]")
    console.print(f"  Nodes: {report['total_nodes']} | Edges: {report['total_edges']}")
    console.print(f"  With descriptions: {report['nodes_with_descriptions']}")
    console.print(f"  Without descriptions: {report['nodes_without_descriptions']}")
    console.print(f"  Avg description length: {report['avg_description_length']} chars")

    # Chunk coverage (if available from updated validate())
    if "nodes_with_chunks" in report:
        chunk_pct = report.get("chunk_coverage_pct", 0)
        cc = "green" if chunk_pct >= 80 else "yellow" if chunk_pct >= 50 else "red"
        console.print(f"  With chunks: {report['nodes_with_chunks']} | "
                      f"Without chunks: {report['nodes_without_chunks']}")
        console.print(f"  Total chunks: {report['total_chunks']} | "
                      f"Chunk coverage: [{cc}]{chunk_pct}%[/{cc}]")

    console.print(f"  Quality score: [{color}]{score}/100[/{color}]")

    if report["warnings"]:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in report["warnings"]:
            console.print(f"  ! {w}")

    if fix and report["nodes_without_descriptions"] > 0:
        console.print("\n[cyan]Auto-enrichment already applied during load.[/cyan]")
        console.print("To improve quality further, add rich descriptions to your KG nodes.")

    if score >= 70:
        console.print("\n[green]KG is ready for reasoning.[/green]")
    elif score >= 40:
        console.print("\n[yellow]KG quality is moderate. Consider enriching node descriptions.[/yellow]")
    else:
        console.print("\n[red]KG quality is low. Agents will produce poor reasoning.[/red]")
        console.print("[red]Add descriptions to your nodes before running queries.[/red]")


@app.command()
def version() -> None:
    """Show Graqle version."""
    from graqle.__version__ import __version__
    console.print(f"{BRAND_NAME} v{__version__}")


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

    console.print("[bold cyan]Domain Profile[/bold cyan]")
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

    from graqle.ontology.domain_detector import auto_ontology
    from graqle.ontology.schema import get_all_edge_types, get_all_node_types

    root = Path(path).resolve()
    ont_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    console.print("[bold cyan]Generating Domain Ontology[/bold cyan]")

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

    console.print("[bold cyan]OntologyGenerator[/bold cyan] — Innovation #8")
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


@app.command("impact")
def impact_command(
    component: str = typer.Argument(..., help="Component/node to analyze impact for"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    change_type: str = typer.Option("modify", "--change-type", "-t", help="Type of change: modify, add, remove, deploy"),
    depth: int = typer.Option(3, "--depth", "-d", help="Max BFS depth for impact traversal"),
    code_only: bool = typer.Option(False, "--code-only", help="Filter out non-code nodes (DOCUMENT, SECTION, CHUNK, Directory, etc.)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trace downstream impact of changing a component.

    Shows which components are affected and their risk level.
    CLI equivalent of the graq_impact MCP tool.

    \b
    Examples:
        graq impact handler.py
        graq impact auth_service --change-type remove
        graq impact "graqle.core.graph" --json
    """
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[red]No graph found. Run 'graq scan repo .' first.[/red]")
        raise typer.Exit(1)

    # Find the component node (exact, substring, fuzzy)
    node = graph.nodes.get(component)
    if node is None:
        matches = [nid for nid in graph.nodes if component.lower() in nid.lower()]
        if matches:
            node = graph.nodes[matches[0]]
        else:
            import difflib
            close = difflib.get_close_matches(
                component.lower(), [nid.lower() for nid in graph.nodes], n=3, cutoff=0.4
            )
            if close:
                lower_to_orig = {nid.lower(): nid for nid in graph.nodes}
                suggestions = [lower_to_orig[c] for c in close]
                console.print(f"[yellow]'{component}' not found. Did you mean: {', '.join(suggestions)}[/yellow]")
            else:
                console.print(f"[red]Component '{component}' not found in graph.[/red]")
            raise typer.Exit(1)

    # BFS impact traversal
    visited: dict[str, int] = {node.id: 0}
    queue = [node.id]
    impact_nodes: list[dict] = []

    while queue:
        current_id = queue.pop(0)
        current_depth = visited[current_id]
        if current_depth >= depth:
            continue
        neighbors = graph.get_neighbors(current_id)
        for nid in neighbors:
            if nid not in visited:
                visited[nid] = current_depth + 1
                queue.append(nid)
                n = graph.nodes[nid]
                impact_nodes.append({
                    "id": nid, "label": n.label, "type": n.entity_type,
                    "depth": current_depth + 1,
                })

    # Filter non-code nodes if --code-only
    _NON_CODE_TYPES = frozenset({
        "Document", "DOCUMENT", "Section", "SECTION", "Chunk", "CHUNK",
        "Paragraph", "PARAGRAPH", "Directory", "Config", "EnvVar",
        "DatabaseModel", "DockerService", "CIPipeline",
    })
    total_before_filter = len(impact_nodes)
    if code_only:
        impact_nodes = [n for n in impact_nodes if n["type"] not in _NON_CODE_TYPES]

    # Risk assessment
    risk_scores = {"remove": 3, "deploy": 2, "modify": 1, "add": 0.5}
    base_risk = risk_scores.get(change_type, 1)
    risk_level = "low"
    if len(impact_nodes) > 10 or base_risk >= 2:
        risk_level = "high"
    elif len(impact_nodes) > 5 or base_risk >= 1.5:
        risk_level = "medium"

    if json_output:
        import json
        result = {
            "component": node.id,
            "change_type": change_type,
            "risk_level": risk_level,
            "impacted_count": len(impact_nodes),
            "impacted": impact_nodes,
        }
        if code_only:
            result["filtered_out"] = total_before_filter - len(impact_nodes)
        print(json.dumps(result, indent=2, default=str))
    else:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}[risk_level]
        console.print(f"[bold cyan]Impact Analysis[/bold cyan] — {node.label}")
        console.print(f"  Change type: {change_type} | Risk: [{risk_color}]{risk_level}[/{risk_color}]")
        console.print(f"  Affected components: {len(impact_nodes)}")
        if code_only and total_before_filter != len(impact_nodes):
            console.print(f"  [dim](filtered {total_before_filter - len(impact_nodes)} non-code nodes)[/dim]")
        if impact_nodes:
            console.print()
            for imp in impact_nodes[:20]:
                indent = "  " * imp["depth"]
                console.print(f"  {indent}{imp['label']} ({imp['type']}) — depth {imp['depth']}")
            if len(impact_nodes) > 20:
                console.print(f"  ... and {len(impact_nodes) - 20} more")


@app.command("preflight")
def preflight_command(
    action: str = typer.Argument(..., help="What you're about to do"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    files: list[str] = typer.Option(None, "--file", "-f", help="Files being changed (repeatable)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Run a governance preflight check before making changes.

    Returns relevant lessons, past mistakes, and safety warnings.
    CLI equivalent of the graq_preflight MCP tool.

    \b
    Examples:
        graq preflight "modify auth middleware"
        graq preflight "deploy to production" --file handler.py --file config.py
        graq preflight "database migration" --json
    """
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)

    report: dict = {
        "action": action,
        "files": files or [],
        "warnings": [],
        "lessons": [],
        "safety_boundaries": [],
        "risk_level": "low",
    }

    if graph is None:
        report["warnings"].append("No knowledge graph loaded — preflight is limited.")
    else:
        # Search for related lessons/safety nodes
        search_text = action + " " + " ".join(files or [])
        for node in graph.nodes.values():
            if node.entity_type not in ("LESSON", "MISTAKE", "SAFETY", "SAFETY_BOUNDARY", "ADR", "DECISION"):
                continue
            node_text = f"{node.id} {node.label} {node.description}".lower()
            if any(word in node_text for word in search_text.lower().split() if len(word) > 3):
                severity = node.properties.get("severity", "medium") if node.properties else "medium"
                hit_count = node.properties.get("hit_count", 0) if node.properties else 0
                entry = {
                    "id": node.id,
                    "label": node.label,
                    "type": node.entity_type,
                    "severity": severity,
                    "description": node.description[:200],
                    "hit_count": hit_count,
                }
                if node.entity_type in ("SAFETY", "SAFETY_BOUNDARY"):
                    report["safety_boundaries"].append(entry)
                elif node.entity_type in ("ADR", "DECISION"):
                    if "adrs" not in report:
                        report["adrs"] = []
                    report["adrs"].append(entry)
                else:
                    report["lessons"].append(entry)

        # Check changed files against graph nodes
        for fpath in (files or []):
            fname = Path(fpath).stem.lower()
            for n in graph.nodes.values():
                node_text = f"{n.id} {n.label}".lower()
                if fname in node_text:
                    neighbors = graph.get_neighbors(n.id)
                    if neighbors:
                        report["warnings"].append(
                            f"'{fpath}' relates to '{n.label}' ({len(neighbors)} connections)"
                        )
                    break

        # Risk level
        n_critical = sum(1 for l in report["lessons"] if l.get("severity") in ("CRITICAL", "critical"))
        n_safety = len(report["safety_boundaries"])
        if n_critical > 0 or n_safety > 0:
            report["risk_level"] = "high"
        elif len(report["lessons"]) > 2 or len(report["warnings"]) > 2:
            report["risk_level"] = "medium"

    if json_output:
        import json
        print(json.dumps(report, indent=2, default=str))
    else:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}[report["risk_level"]]
        console.print(f"[bold cyan]Preflight Check[/bold cyan] — {action}")
        console.print(f"  Risk level: [{risk_color}]{report['risk_level']}[/{risk_color}]")

        if report["safety_boundaries"]:
            console.print("\n  [bold red]Safety Boundaries:[/bold red]")
            for s in report["safety_boundaries"]:
                hit_info = f" (hit {s['hit_count']}x)" if s.get("hit_count") else ""
                console.print(f"    ! {s['label']}{hit_info}: {s['description']}")

        if report.get("adrs"):
            console.print("\n  [bold magenta]Relevant ADRs/Decisions:[/bold magenta]")
            for a in report["adrs"]:
                console.print(f"    [{a.get('severity', 'medium')}] {a['id']}: {a['label']}")
                if a.get("description"):
                    console.print(f"      {a['description']}")

        if report["lessons"]:
            console.print("\n  [bold yellow]Relevant Lessons:[/bold yellow]")
            for l in report["lessons"]:
                sev = l.get("severity", "medium")
                hit_info = f" (hit {l['hit_count']}x)" if l.get("hit_count") else ""
                sev_color = {"CRITICAL": "red", "HIGH": "red", "MEDIUM": "yellow"}.get(sev.upper(), "dim")
                console.print(f"    [{sev_color}]{sev}[/{sev_color}] {l['id']}: {l['label']}{hit_info}")
                if l.get("description"):
                    console.print(f"      {l['description']}")

        if report["warnings"]:
            console.print("\n  [bold]Warnings:[/bold]")
            for w in report["warnings"]:
                console.print(f"    {w}")

        if not report["lessons"] and not report["warnings"] and not report["safety_boundaries"] and not report.get("adrs"):
            console.print("  [green]No issues found. Proceed with caution.[/green]")


@app.command("safety-check")
def safety_check_command(
    component: str = typer.Argument(..., help="Component or file to safety-check"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    change_type: str = typer.Option("modify", "--change-type", "-t", help="Type of change"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    skip_reasoning: bool = typer.Option(False, "--skip-reasoning", help="Skip the reasoning step (faster, cheaper)"),
) -> None:
    """Combined safety check: impact → preflight → reasoning (if risk warrants).

    Chains three Graqle tools into a single pipeline to give a complete
    safety picture before making a change. Reasoning is only triggered
    if the preflight risk level is medium or high.

    \b
    Examples:
        graq safety-check graqle.cli.main
        graq safety-check handler.py --change-type remove
        graq safety-check "auth_middleware" --json
    """
    import asyncio
    from pathlib import Path

    from graqle.config.settings import GraqleConfig

    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    graph = _load_graph(cfg)
    if graph is None:
        console.print("[red]No graph found. Run 'graq scan repo .' first.[/red]")
        raise typer.Exit(1)

    combined: dict = {"component": component, "change_type": change_type}

    # ── Step 1: Impact Analysis ───────────────────────────────────────
    if not json_output:
        console.print("[bold cyan]Step 1/3:[/bold cyan] Impact Analysis...")

    node = graph.nodes.get(component)
    if node is None:
        matches = [nid for nid in graph.nodes if component.lower() in nid.lower()]
        if matches:
            node = graph.nodes[matches[0]]
    if node is None:
        console.print(f"[yellow]Component '{component}' not found in graph — skipping impact.[/yellow]")
        combined["impact"] = {"error": "component not found"}
    else:
        # BFS impact (code-only by default in safety-check)
        _NON_CODE = frozenset({
            "Document", "DOCUMENT", "Section", "SECTION", "Chunk", "CHUNK",
            "Paragraph", "PARAGRAPH", "Directory", "Config", "EnvVar",
            "DatabaseModel", "DockerService", "CIPipeline",
        })
        visited: dict[str, int] = {node.id: 0}
        queue = [node.id]
        impact_nodes: list[dict] = []
        while queue:
            current_id = queue.pop(0)
            current_depth = visited[current_id]
            if current_depth >= 3:
                continue
            neighbors = graph.get_neighbors(current_id)
            for nid in neighbors:
                if nid not in visited:
                    visited[nid] = current_depth + 1
                    queue.append(nid)
                    n = graph.nodes.get(nid)
                    if n and n.entity_type not in _NON_CODE:
                        impact_nodes.append({
                            "id": nid, "label": n.label, "type": n.entity_type,
                            "depth": current_depth + 1,
                        })
        combined["impact"] = {
            "affected_count": len(impact_nodes),
            "top_affected": impact_nodes[:10],
        }
        if not json_output:
            console.print(f"  Affected: {len(impact_nodes)} code components")

    # ── Step 2: Preflight Check ───────────────────────────────────────
    if not json_output:
        console.print("[bold cyan]Step 2/3:[/bold cyan] Preflight Check...")

    search_text = component
    lessons = []
    safety = []
    adrs = []
    for n in graph.nodes.values():
        if n.entity_type not in ("LESSON", "MISTAKE", "SAFETY", "SAFETY_BOUNDARY", "ADR", "DECISION"):
            continue
        node_text = f"{n.id} {n.label} {n.description}".lower()
        if any(word in node_text for word in search_text.lower().split() if len(word) > 3):
            entry = {
                "id": n.id, "label": n.label, "type": n.entity_type,
                "severity": n.properties.get("severity", "MEDIUM") if n.properties else "MEDIUM",
                "description": n.description[:200],
            }
            if n.entity_type in ("SAFETY", "SAFETY_BOUNDARY"):
                safety.append(entry)
            elif n.entity_type in ("ADR", "DECISION"):
                adrs.append(entry)
            else:
                lessons.append(entry)

    n_critical = sum(1 for l in lessons if l.get("severity", "").upper() in ("CRITICAL", "HIGH"))
    risk_level = "high" if n_critical > 0 or safety else "medium" if len(lessons) > 2 else "low"

    combined["preflight"] = {
        "risk_level": risk_level,
        "lessons": lessons[:5],
        "safety_boundaries": safety,
        "adrs": adrs[:3],
    }
    if not json_output:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}[risk_level]
        console.print(f"  Risk: [{risk_color}]{risk_level}[/{risk_color}] "
                      f"({len(lessons)} lessons, {len(safety)} safety, {len(adrs)} ADRs)")

    # ── Step 3: Reasoning (only if risk warrants it) ──────────────────
    combined["reasoning"] = None
    if not skip_reasoning and risk_level in ("medium", "high"):
        if not json_output:
            console.print("[bold cyan]Step 3/3:[/bold cyan] Reasoning (risk warrants deeper analysis)...")
        try:
            backend = _create_backend_from_config(cfg)
            graph.set_default_backend(backend)
            affected_labels = [n["label"] for n in impact_nodes[:5]] if "impact_nodes" in dir() else []
            question = (
                f"What are the risks of {change_type}ing {component}? "
                f"Affected components: {', '.join(affected_labels[:3]) if affected_labels else 'unknown'}. "
                f"Risk level: {risk_level}."
            )
            result = asyncio.run(graph.areason(question, max_rounds=2))
            combined["reasoning"] = {
                "answer": result.answer,
                "confidence": result.confidence,
                "cost_usd": result.cost_usd,
            }
            if not json_output:
                from rich.markup import escape as rich_escape
                console.print(f"  {rich_escape(result.answer[:300])}")
                console.print(f"  [dim]Confidence: {result.confidence:.0%} | Cost: ${result.cost_usd:.4f}[/dim]")
        except Exception as exc:
            combined["reasoning"] = {"error": str(exc)[:200]}
            if not json_output:
                console.print(f"  [yellow]Reasoning skipped: {exc}[/yellow]")
    elif not json_output:
        if skip_reasoning:
            console.print("[bold cyan]Step 3/3:[/bold cyan] Reasoning [dim](skipped by --skip-reasoning)[/dim]")
        else:
            console.print("[bold cyan]Step 3/3:[/bold cyan] Reasoning [green](skipped — low risk)[/green]")

    # ── Summary ───────────────────────────────────────────────────────
    combined["overall_risk"] = risk_level
    if json_output:
        import json
        print(json.dumps(combined, indent=2, default=str))
    else:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}[risk_level]
        console.print(f"\n[bold]Overall:[/bold] [{risk_color}]{risk_level.upper()}[/{risk_color}] risk")


@app.command("runtime")
def runtime_command(
    query: str = typer.Argument("", help="What to investigate (e.g., 'errors in BAMR-API')"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    source: str = typer.Option("auto", "--source", "-s", help="Log source: auto, cloudwatch, azure_monitor, cloud_logging, docker, file"),
    service: str = typer.Option(None, "--service", help="Filter to a specific service/Lambda name"),
    hours: float = typer.Option(6, "--hours", "-H", help="How far back to look"),
    severity: str = typer.Option("high", "--severity", help="Minimum severity: all, low, medium, high, critical"),
    ingest: bool = typer.Option(False, "--ingest", "-i", help="Ingest runtime events into the KG as RUNTIME_EVENT nodes"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    env_only: bool = typer.Option(False, "--detect", help="Only detect environment, don't fetch logs"),
) -> None:
    """Fetch and classify runtime logs from your cloud environment.

    Auto-detects AWS CloudWatch, Azure Monitor, GCP Cloud Logging,
    or local Docker/file logs. Classifies errors, timeouts, throttles,
    and auth failures with severity levels.

    \b
    Examples:
        graq runtime                               # auto-detect, last 6h, high+ severity
        graq runtime --service BAMR-API --hours 2  # specific Lambda, last 2 hours
        graq runtime --source cloudwatch --ingest  # fetch + add to KG
        graq runtime --detect                      # just show detected environment
        graq runtime "auth failures" --severity all
    """
    import asyncio
    from pathlib import Path

    from graqle.config.settings import GraqleConfig
    from graqle.runtime.detector import detect_environment

    env = detect_environment()

    # Load config for region overrides and log group settings
    log_groups: list[str] = []
    log_paths: list[str] = []
    config_region: str | None = None
    config_region_source: str | None = None
    cfg = None
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
        if hasattr(cfg, "runtime"):
            for src in cfg.runtime.sources:
                if src.log_group:
                    log_groups.append(src.log_group)
                if src.log_path:
                    log_paths.append(src.log_path)
                if src.region:
                    config_region = src.region
                    config_region_source = "runtime.sources[].region"
        # Fall back to model.region from graqle.yaml (user's configured region)
        if not config_region and cfg.model.region:
            config_region = cfg.model.region
            config_region_source = "model.region"

    # Region priority: runtime source config > model config > boto3 auto-detect
    effective_region = config_region or env.region
    region_source = config_region_source or "boto3_session"

    if env_only:
        console.print("[bold cyan]Runtime Environment Detection[/bold cyan]")
        console.print(f"  Provider: [bold]{env.provider}[/bold] (confidence: {env.confidence:.0%})")
        console.print(f"  Detected region: {env.region or 'N/A'} (boto3_session)")
        if config_region and config_region != env.region:
            console.print(f"  Config region: [bold]{config_region}[/bold] ({config_region_source})")
        console.print(f"  [bold]Effective region: {effective_region}[/bold] (source: {region_source})")
        console.print(f"  Log sources: {', '.join(env.log_sources) or 'none'}")
        if env.details:
            for k, v in env.details.items():
                console.print(f"  {k}: {v}")
        if config_region and env.region and config_region != env.region:
            console.print(f"\n  [yellow]Note: boto3 detected {env.region} but config says {config_region}. "
                          f"Using {config_region} from {config_region_source}.[/yellow]")
        return

    from graqle.runtime.fetcher import create_fetcher
    from graqle.runtime.kg_builder import RuntimeKGBuilder

    if config_region and env.region and config_region != env.region:
        console.print(f"[yellow]  Note: auto-detected region ({env.region}) differs from configured region ({config_region}). Using configured.[/yellow]")

    provider = source if source != "auto" else env.provider
    fetcher = create_fetcher(
        provider,
        region=effective_region,
        log_groups=log_groups or None,
        log_paths=log_paths or None,
    )

    # Health check
    health = fetcher.health_check()
    if health.get("status") == "error":
        console.print(f"[red]Runtime source unavailable: {health.get('error', 'unknown')}[/red]")
        if health.get("hint"):
            console.print(f"[yellow]  Hint: {health['hint']}[/yellow]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Graqle Runtime[/bold cyan] — {env.provider} ({env.region or 'local'})")
    console.print(f"  Fetching last {hours}h | severity >= {severity} | service: {service or 'all'}")

    result = asyncio.run(
        fetcher.fetch(hours=hours, service=service, severity_filter=severity, max_events=100)
    )

    summary = RuntimeKGBuilder.summary(result)

    if json_output:
        import json as json_lib
        print(json_lib.dumps(summary, indent=2, default=str))
        return

    # Display results
    status_color = {"critical": "red", "warning": "yellow", "info": "cyan", "clean": "green"}
    color = status_color.get(summary["status"], "white")
    console.print(f"\n  Status: [{color}]{summary['status'].upper()}[/{color}]")
    console.print(f"  Events: {summary['total_events']} | Fetch: {summary['fetch_duration_ms']:.0f}ms")

    if summary.get("by_severity"):
        sev_parts = [f"{k}: {v}" for k, v in summary["by_severity"].items()]
        console.print(f"  Severity: {' | '.join(sev_parts)}")

    if summary.get("by_category"):
        console.print("\n  [bold]Categories:[/bold]")
        for cat, count in sorted(summary["by_category"].items(), key=lambda x: -x[1]):
            console.print(f"    {cat}: {count}")

    if summary.get("top_events"):
        console.print("\n  [bold]Top Events:[/bold]")
        for evt in summary["top_events"]:
            sev_c = "red" if evt["severity"] == "CRITICAL" else "yellow" if evt["severity"] == "HIGH" else "white"
            console.print(f"    [{sev_c}][{evt['severity']}][/{sev_c}] {evt['category']} in {evt['service']} ({evt['hits']}x)")
            console.print(f"      {evt['message'][:120]}")

    if result.errors:
        console.print("\n  [yellow]Errors during fetch:[/yellow]")
        for err in result.errors:
            console.print(f"    ! {err}")

    # Ingest into KG if requested
    if ingest and result.events:
        graph_path = "graqle.json"
        builder = RuntimeKGBuilder(graph_path=graph_path)
        ingest_result = builder.ingest_into_graph(result)
        if "error" in ingest_result:
            console.print(f"\n  [red]Ingest failed: {ingest_result['error']}[/red]")
        else:
            console.print(f"\n  [green]Ingested: {ingest_result['nodes_added']} nodes, {ingest_result['edges_added']} edges into {graph_path}[/green]")


@app.command("route")
def route_command(
    question: str = typer.Argument(..., help="The question to route"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Classify a question and recommend Graqle vs external tools.

    Smart router that tells you whether to use graq_reason, graq_impact,
    CloudWatch logs, grep, or git for a given investigation.

    \b
    Examples:
        graq route "what depends on handler.py?"
        graq route "why is the Lambda timing out?"
        graq route "when did we add CORS headers?"
    """
    from graqle.runtime.router import route_question

    rec = route_question(question, has_runtime=True)

    if json_output:
        import json as json_lib
        print(json_lib.dumps(rec.to_dict(), indent=2))
        return

    priority_color = {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}
    p_color = priority_color.get(rec.graqle_priority, "white")

    console.print("[bold cyan]Query Router[/bold cyan]")
    console.print(f"  Category: [bold]{rec.category}[/bold]")
    console.print(f"  Graqle priority: [{p_color}]{rec.graqle_priority}[/{p_color}]")
    console.print(f"  Strategy: [bold]{rec.recommendation}[/bold] (confidence: {rec.confidence:.0%})")

    if rec.graqle_tools:
        console.print(f"  Graqle tools: {', '.join(rec.graqle_tools)}")
    if rec.external_tools:
        console.print(f"  External tools: {', '.join(rec.external_tools)}")

    console.print(f"\n  [dim]{rec.reasoning}[/dim]")


@app.command()
def reason(
    query: str = typer.Argument("", help="The reasoning query (or use --batch with queries file)"),
    config: str = typer.Option("graqle.yaml", "--config", "-c", help="Config file path"),
    graph_path: str = typer.Option(None, "--graph", "-g", help="Path to JSON graph file"),
    backend_name: str = typer.Option(None, "--backend", "-b", help="Backend: anthropic, bedrock, openai, ollama (default: from graqle.yaml)"),
    model: str = typer.Option(None, "--model", "-m", help="Model name (default: from graqle.yaml or qwen2.5:3b for ollama)"),
    region: str = typer.Option(None, "--region", help="AWS region for Bedrock (default: from graqle.yaml)"),
    host: str = typer.Option(None, "--host", help="Ollama/vLLM host URL"),
    max_rounds: int = typer.Option(3, "--max-rounds", "-r", help="Max message-passing rounds"),
    strategy: str = typer.Option(None, "--strategy", "-s", help="Activation strategy (default: from config, usually 'chunk')"),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text, json"),
    batch: str = typer.Option(None, "--batch", help="Path to queries file (one query per line) for parallel batch reasoning"),
    max_concurrent: int = typer.Option(5, "--max-concurrent", help="Max concurrent queries in batch mode"),
) -> None:
    """Run reasoning query on the knowledge graph.

    \b
    Uses the backend configured in graqle.yaml by default.
    Override with --backend to test a specific provider.

    \b
    Examples:
        graq reason "what calls auth?"                     # uses graqle.yaml backend
        graq reason "query" --backend bedrock --region eu-central-1
        graq reason --batch queries.txt --max-concurrent 3  # parallel batch mode
    """
    import asyncio
    from pathlib import Path

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

    if not query and not batch:
        console.print("[red]Provide a query argument or --batch <file>[/red]")
        raise typer.Exit(1)

    # Load config
    if Path(config).exists():
        cfg = GraqleConfig.from_yaml(config)
    else:
        cfg = GraqleConfig.default()

    # Load graph
    if graph_path and Path(graph_path).exists():
        graph = Graqle.from_json(graph_path, config=cfg)
    else:
        graph = _load_graph(cfg)
        if graph is None:
            console.print("[red]No graph found. Provide --graph path/to/graph.json[/red]")
            raise typer.Exit(1)

    # Use config strategy if not overridden by CLI flag
    strategy = strategy or cfg.activation.strategy

    # Resolve backend: CLI flags override graqle.yaml
    effective_backend = backend_name or cfg.model.backend
    effective_model = model or cfg.model.model
    effective_region = region or cfg.model.region

    if effective_backend == "ollama":
        effective_model = effective_model or "qwen2.5:3b"
        effective_host = host or cfg.model.host or "http://localhost:11434"

    # Create backend
    if effective_backend == "ollama":
        from graqle.backends.api import OllamaBackend
        backend = OllamaBackend(model=effective_model, host=effective_host)
    else:
        # Use the unified _create_backend_from_config with overrides
        if backend_name:
            cfg.model.backend = backend_name
        if model:
            cfg.model.model = model
        if region:
            cfg.model.region = region
        backend = _create_backend_from_config(cfg, verbose=True)

    graph.set_default_backend(backend)

    backend_label = getattr(backend, "name", effective_backend)
    console.print(f"{BRAND_NAME} reasoning with {backend_label}")
    console.print(f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # ── Batch mode ────────────────────────────────────────────────────
    if batch:
        batch_path = Path(batch)
        if not batch_path.exists():
            console.print(f"[red]Batch file not found: {batch}[/red]")
            raise typer.Exit(1)
        queries = [line.strip() for line in batch_path.read_text().splitlines() if line.strip()]
        if not queries:
            console.print("[red]Batch file is empty.[/red]")
            raise typer.Exit(1)

        console.print(f"Batch: [green]{len(queries)} queries[/green] (max_concurrent={max_concurrent})")
        results = asyncio.run(
            graph.areason_batch(
                queries, max_rounds=max_rounds, strategy=strategy,
                max_concurrent=max_concurrent,
            )
        )

        total_cost = sum(r.cost_usd for r in results)
        total_latency = sum(r.latency_ms for r in results)
        avg_confidence = sum(r.confidence for r in results) / len(results) if results else 0

        if output_format == "json":
            import json
            console.print(json.dumps({
                "batch_size": len(queries),
                "total_cost_usd": total_cost,
                "total_latency_ms": total_latency,
                "avg_confidence": round(avg_confidence, 3),
                "results": [
                    {
                        "question": q,
                        "answer": r.answer,
                        "confidence": r.confidence,
                        "rounds": r.rounds_completed,
                        "nodes": r.node_count,
                        "cost_usd": r.cost_usd,
                        "latency_ms": r.latency_ms,
                        "reasoning_mode": r.reasoning_mode,
                    }
                    for q, r in zip(queries, results)
                ],
            }, indent=2))
        else:
            from rich.markup import escape as rich_escape
            for i, (q, r) in enumerate(zip(queries, results), 1):
                console.print(f"\n[bold cyan]── Query {i}/{len(queries)} ──[/bold cyan]")
                console.print(f"Q: [green]{rich_escape(q)}[/green]")
                console.print(f"A: {rich_escape(r.answer[:500])}")
                mode_color = "green" if r.reasoning_mode == "full" else "yellow"
                console.print(f"[dim]Confidence: {r.confidence:.0%} | Cost: ${r.cost_usd:.4f} | "
                              f"Mode: [{mode_color}]{r.reasoning_mode}[/{mode_color}][/dim]")
            console.print(f"\n[bold]Batch Summary:[/bold] {len(queries)} queries | "
                          f"Avg confidence: {avg_confidence:.0%} | "
                          f"Total cost: ${total_cost:.4f} | "
                          f"Total latency: {total_latency:.0f}ms")
        return

    # ── Single query mode ─────────────────────────────────────────────
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
            "backend_status": result.backend_status,
            "reasoning_mode": result.reasoning_mode,
        }, indent=2))
    else:
        from rich.markup import escape as rich_escape
        console.print(f"\n[bold green]Answer:[/bold green] {rich_escape(result.answer)}")
        mode_color = "green" if result.reasoning_mode == "full" else "yellow"
        console.print(f"[dim]Confidence: {result.confidence:.0%} | Rounds: {result.rounds_completed} | "
                      f"Nodes: {result.node_count} | Cost: ${result.cost_usd:.4f} | "
                      f"Latency: {result.latency_ms:.0f}ms | "
                      f"Mode: [{mode_color}]{result.reasoning_mode}[/{mode_color}][/dim]")


def _load_graph(cfg):
    """Load graph from config or auto-discover. Returns Graqle or None."""
    from pathlib import Path

    from graqle.core.graph import Graqle

    # 1. Neo4j backend — primary production path (with JSON fallback)
    if cfg.graph.connector == "neo4j":
        try:
            return Graqle.from_neo4j(
                uri=cfg.graph.uri or "bolt://localhost:7687",
                username=cfg.graph.username or "neo4j",
                password=cfg.graph.password or "",
                database=cfg.graph.database or "neo4j",
                config=cfg,
            )
        except Exception as e:
            # Neo4j unavailable — fall through to JSON fallback
            json_fallback = Path(cfg.graph.path or "graqle.json")
            if json_fallback.exists():
                console.print(
                    f"[yellow]Neo4j unavailable ({type(e).__name__}), "
                    f"falling back to {json_fallback}[/yellow]"
                )
                return Graqle.from_json(str(json_fallback), config=cfg)
            # No JSON fallback available — re-raise with helpful message
            console.print(
                f"[red]Neo4j unavailable ({type(e).__name__}) and no JSON "
                f"fallback found. Run 'graq scan repo .' to build one.[/red]"
            )
            return None

    # 2. JSON/NetworkX fallback — local development / quick testing
    if cfg.graph.connector == "networkx":
        json_path = Path(cfg.graph.path or "graqle.json")
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
            region = getattr(cfg.model, "region", None) or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
            if not region:
                console.print("[yellow]No AWS region configured. Set 'region' in graqle.yaml or AWS_DEFAULT_REGION env var.[/yellow]")
                console.print("[yellow]Defaulting to us-east-1. Run 'graq init' to configure.[/yellow]")
                region = "us-east-1"
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
