"""Phantom CLI commands — graq phantom browse/audit/flow/discover."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

phantom_app = typer.Typer(
    name="phantom",
    help="Phantom — AI-powered browser automation + visual audit engine. Works on any website.",
    no_args_is_help=True,
)


def _ensure_phantom():
    """Lazy import with friendly error."""
    try:
        from graqle.plugins.phantom import PhantomEngine, PhantomConfig
        return PhantomEngine, PhantomConfig
    except ImportError:
        console.print(
            "[red]Phantom plugin not available.[/red]\n"
            "Install with: [cyan]pip install graqle\\[phantom] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)


@phantom_app.command("browse")
def phantom_browse(
    url: str = typer.Argument(..., help="URL to navigate to"),
    viewport: str = typer.Option("desktop", "--viewport", "-v", help="Viewport: mobile, tablet, desktop"),
    auth_profile: str = typer.Option(None, "--auth", "-a", help="Auth profile to use"),
) -> None:
    """Open browser, navigate to URL, capture screenshot + DOM summary."""
    PhantomEngine, PhantomConfig = _ensure_phantom()
    engine = PhantomEngine(PhantomConfig())

    console.print(f"\n[bold cyan]Phantom[/bold cyan] — Browsing {url}")

    try:
        result = asyncio.run(engine.browse(url, viewport=viewport, auth_profile=auth_profile))
    except ModuleNotFoundError:
        console.print(
            "[red]Playwright not installed.[/red]\n"
            "Install with: [cyan]pip install graqle\\[phantom] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)

    console.print(f"  Session: {result['session_id']}")
    console.print(f"  Screenshot: {result['screenshot_path']}")
    console.print(f"  DOM nodes: {result['dom_summary'].get('dom_nodes', 'N/A')}")
    console.print(f"  Load time: {result['load_time_ms']}ms")


@phantom_app.command("audit")
def phantom_audit(
    url: str = typer.Argument(..., help="URL to audit"),
    dimensions: list[str] = typer.Option(["all"], "--dim", "-d", help="Audit dimensions (repeatable)"),
    viewport: str = typer.Option("desktop", "--viewport", "-v", help="Viewport: mobile, tablet, desktop"),
    teach_kg: bool = typer.Option(True, "--teach-kg/--no-teach-kg", help="Auto-teach findings to KG"),
) -> None:
    """Run SCORCH audit dimensions on a URL. Works on any website."""
    PhantomEngine, PhantomConfig = _ensure_phantom()
    engine = PhantomEngine(PhantomConfig())

    console.print(f"\n[bold cyan]Phantom Audit[/bold cyan] — {url}")
    console.print(f"  Dimensions: {', '.join(dimensions)}")

    async def _run():
        result = await engine.browse(url, viewport=viewport)
        session_id = result["session_id"]
        audit_result = await engine.audit(session_id, dimensions=dimensions, teach_kg=teach_kg)
        await engine.sessions.close_all()
        return audit_result

    try:
        result = asyncio.run(_run())
    except ModuleNotFoundError:
        console.print(
            "[red]Playwright not installed.[/red]\n"
            "Install with: [cyan]pip install graqle\\[phantom] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)

    # Summary table
    summary = result.get("summary", {})
    table = Table(title="Audit Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Grade", summary.get("grade", "N/A"))
    table.add_row("Total Issues", str(summary.get("total_issues", 0)))
    table.add_row("Critical", str(summary.get("critical", 0)))
    table.add_row("High", str(summary.get("high", 0)))
    table.add_row("Medium", str(summary.get("medium", 0)))
    table.add_row("Low", str(summary.get("low", 0)))
    console.print(table)


@phantom_app.command("discover")
def phantom_discover(
    url: str = typer.Argument(..., help="Starting URL"),
    auth_profile: str = typer.Option(None, "--auth", "-a", help="Auth profile for protected pages"),
    max_depth: int = typer.Option(3, "--depth", help="Max navigation depth"),
    max_pages: int = typer.Option(50, "--max-pages", help="Max pages to discover"),
) -> None:
    """Auto-discover all navigable pages from a starting URL."""
    PhantomEngine, PhantomConfig = _ensure_phantom()
    engine = PhantomEngine(PhantomConfig())

    console.print(f"\n[bold cyan]Phantom Discovery[/bold cyan] — {url}")

    try:
        result = asyncio.run(engine.discover(url, auth_profile=auth_profile, max_depth=max_depth, max_pages=max_pages))
    except ModuleNotFoundError:
        console.print(
            "[red]Playwright not installed.[/red]\n"
            "Install with: [cyan]pip install graqle\\[phantom] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)

    table = Table(title=f"Discovered {result['pages_discovered']} pages")
    table.add_column("Path", style="cyan")
    table.add_column("Title")
    table.add_column("Auth", style="yellow")
    table.add_column("Source")

    for page in result.get("route_map", []):
        table.add_row(
            page["path"],
            page.get("title", ""),
            "Yes" if page.get("auth_required") else "No",
            page.get("nav_source", ""),
        )
    console.print(table)


@phantom_app.command("flow")
def phantom_flow(
    flow_file: str = typer.Argument(..., help="Path to flow JSON file"),
    viewport: str = typer.Option("desktop", "--viewport", "-v"),
    stop_on_failure: bool = typer.Option(False, "--stop-on-failure"),
) -> None:
    """Execute a multi-step user journey from a JSON file."""
    PhantomEngine, PhantomConfig = _ensure_phantom()
    engine = PhantomEngine(PhantomConfig())

    with open(flow_file, "r", encoding="utf-8") as f:
        flow_def = json.load(f)

    name = flow_def.get("name", Path(flow_file).stem)
    steps = flow_def.get("steps", [])

    console.print(f"\n[bold cyan]Phantom Flow[/bold cyan] — {name}")
    console.print(f"  Steps: {len(steps)}")

    try:
        result = asyncio.run(engine.flow(
            name=name,
            steps=steps,
            viewport=flow_def.get("viewport", viewport),
            auth_profile=flow_def.get("auth_profile"),
            stop_on_failure=stop_on_failure,
        ))
    except ModuleNotFoundError:
        console.print(
            "[red]Playwright not installed.[/red]\n"
            "Install with: [cyan]pip install graqle\\[phantom] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)

    status = "[green]PASS[/green]" if result["failed"] == 0 else "[red]FAIL[/red]"
    console.print(f"\n  Result: {status} ({result['passed']}/{result['total_steps']} passed)")
    console.print(f"  Duration: {result['duration_ms']}ms")

    if result["failures"]:
        console.print("\n[red]Failures:[/red]")
        for f in result["failures"]:
            console.print(f"  Step {f['step']}: {f.get('description', '')} — {f.get('error', '')}")
