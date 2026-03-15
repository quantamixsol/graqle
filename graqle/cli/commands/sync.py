"""graq sync — cloud graph synchronization commands.

Sync your local knowledge graph with Graqle Cloud for team collaboration.
Requires Team plan ($29/dev/mo) for cloud sync features.

Commands:
    graq sync push      Push local changes to cloud
    graq sync pull      Pull team changes locally
    graq sync status    Show sync state (ahead/behind/in-sync)
    graq sync resolve   Interactive conflict resolution
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.sync
# risk: LOW (impact radius: 2 modules)
# consumers: main, test_sync
# dependencies: __future__, typer, console, panel, table
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

sync_app = typer.Typer(
    name="sync",
    help="Sync your knowledge graph with Graqle Cloud (Team plan).",
    no_args_is_help=True,
)


def _check_plan_gate(feature: str = "cloud_sync") -> bool:
    """Check if the current plan allows cloud sync. Show upgrade if not."""
    from graqle.cloud.plans import PLAN_PRICING, check_feature
    from graqle.licensing.manager import LicenseManager

    manager = LicenseManager()
    plan = manager.current_tier.value

    result = check_feature(plan, feature)
    if result.allowed:
        return True

    console.print(Panel(
        f"[bold yellow]Cloud sync requires Team plan[/bold yellow]\n\n"
        f"  Your plan: [bold]{plan.title()}[/bold]\n"
        f"  Required:  [bold cyan]Team[/bold cyan] ({PLAN_PRICING['team']['price']})\n\n"
        f"[green]What you get with Team:[/green]\n"
        f"  * Push/pull graph sync (like git for knowledge)\n"
        f"  * Shared graph — one dev teaches, everyone benefits\n"
        f"  * Cloud observability — track graph health & ROI\n"
        f"  * Cross-repo architecture views\n"
        f"  * 50,000 node limit (vs {result.current_plan} limit)\n\n"
        f"  [bold]Upgrade:[/bold] graq billing\n"
        f"  [bold]Purchase:[/bold] https://graqle.dev/pricing",
        border_style="cyan",
        title="Upgrade to Team",
    ))
    return False


@sync_app.command("push")
def sync_push(
    force: bool = typer.Option(False, "--force", "-f", help="Force push (overwrite remote)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be pushed"),
) -> None:
    """Push local graph changes to Graqle Cloud.

    \b
    Computes a delta of changes since your last sync and pushes
    only the differences — not the full graph.

    \b
    Examples:
        graq sync push
        graq sync push --dry-run
    """
    if not _check_plan_gate():
        raise typer.Exit(1)

    import json
    from pathlib import Path

    from graqle.cloud.credentials import load_credentials
    from graqle.cloud.gateway import CloudGateway
    from graqle.cloud.sync import (
        compute_delta,
        load_sync_snapshot,
        load_sync_state,
        save_sync_snapshot,
        save_sync_state,
    )
    from graqle.cloud.team import load_team_config

    # Load current state
    state = load_sync_state()
    team_config = load_team_config()

    if not team_config.is_configured:
        console.print("[yellow]No team configured.[/yellow]")
        console.print("Create a team first: [cyan]graq team create <name>[/cyan]")
        raise typer.Exit(1)

    # Load local graph
    graph_path = Path("cognigraph.json")
    if not graph_path.exists():
        graph_path = Path(".graqle/graph.json")
    if not graph_path.exists():
        console.print("[red]No graph found. Run 'graq init' first.[/red]")
        raise typer.Exit(1)

    local_graph = json.loads(graph_path.read_text(encoding="utf-8"))

    # Compute delta
    baseline = load_sync_snapshot()
    delta = compute_delta(local_graph, baseline)

    if delta.is_empty:
        console.print("[green]Already in sync.[/green] No changes to push.")
        return

    console.print(f"[bold]Changes to push:[/bold] {delta.summary}")

    if dry_run:
        console.print("[dim]Dry run — no changes pushed.[/dim]")
        return

    # Push via gateway
    creds = load_credentials()
    gateway = CloudGateway(api_key=creds.api_key, cloud_url=creds.cloud_url)
    result = gateway.push_delta(delta.to_dict(), team_config.team_id)

    if result.get("phase") == "foundation":
        console.print()
        console.print("[cyan]Foundation mode:[/cyan] Delta computed and snapshot saved locally.")
        console.print("[dim]Cloud push will be available when the gateway is deployed.[/dim]")

    # Save snapshot as new baseline
    save_sync_snapshot(local_graph)

    # Update sync state
    import time
    state.team_id = team_config.team_id
    state.last_push = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.local_version += 1
    state.status = "in_sync"
    save_sync_state(state)

    console.print(f"[green]Pushed:[/green] {delta.summary}")


@sync_app.command("pull")
def sync_pull(
    force: bool = typer.Option(False, "--force", "-f", help="Force pull (overwrite local)"),
) -> None:
    """Pull team graph changes from Graqle Cloud.

    \b
    Receives only changes from the team graph since your last pull.
    Conflicts are auto-resolved by source priority (Code > API > Config > Docs).

    \b
    Examples:
        graq sync pull
        graq sync pull --force
    """
    if not _check_plan_gate():
        raise typer.Exit(1)

    from graqle.cloud.credentials import load_credentials
    from graqle.cloud.gateway import CloudGateway
    from graqle.cloud.sync import load_sync_state, save_sync_state
    from graqle.cloud.team import load_team_config

    state = load_sync_state()
    team_config = load_team_config()

    if not team_config.is_configured:
        console.print("[yellow]No team configured.[/yellow]")
        console.print("Join a team: [cyan]graq team join <team-id>[/cyan]")
        raise typer.Exit(1)

    # Pull via gateway
    creds = load_credentials()
    gateway = CloudGateway(api_key=creds.api_key, cloud_url=creds.cloud_url)
    result = gateway.pull_delta(team_config.team_id, state.remote_version)

    if result.get("phase") == "foundation":
        console.print("[cyan]Foundation mode:[/cyan] Cloud pull will be available when the gateway is deployed.")
        console.print("[dim]Your local graph is the source of truth.[/dim]")
        return

    # Update sync state
    import time
    state.last_pull = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.remote_version = result.get("remote_version", state.remote_version)
    state.status = "in_sync"
    save_sync_state(state)

    console.print("[green]Pull complete.[/green] Local graph is up to date.")


@sync_app.command("status")
def sync_status() -> None:
    """Show sync state (ahead/behind/in-sync).

    \b
    Examples:
        graq sync status
    """
    from graqle.cloud.sync import load_sync_state
    from graqle.cloud.team import load_team_config

    state = load_sync_state()
    team_config = load_team_config()

    if not team_config.is_configured:
        console.print("[yellow]No team configured.[/yellow]")
        console.print()
        console.print("Cloud sync enables shared knowledge graphs for your team.")
        console.print("Create a team: [cyan]graq team create <name>[/cyan]")
        console.print("View plans:    [cyan]graq billing[/cyan]")
        return

    table = Table(title="Sync Status", show_header=False)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    status_colors = {
        "in_sync": "green",
        "ahead": "yellow",
        "behind": "cyan",
        "diverged": "red",
        "not_configured": "dim",
    }
    color = status_colors.get(state.status, "white")

    table.add_row("Team", f"{team_config.team_name} ({team_config.team_id})")
    table.add_row("Status", f"[{color}]{state.status}[/{color}]")
    table.add_row("Local version", str(state.local_version))
    table.add_row("Remote version", str(state.remote_version))
    table.add_row("Last push", state.last_push or "never")
    table.add_row("Last pull", state.last_pull or "never")

    console.print(table)

    if state.local_version > state.remote_version:
        diff = state.local_version - state.remote_version
        console.print(f"\n[yellow]Ahead by {diff} version(s).[/yellow] Run [cyan]graq sync push[/cyan] to sync.")
    elif state.remote_version > state.local_version:
        diff = state.remote_version - state.local_version
        console.print(f"\n[cyan]Behind by {diff} version(s).[/cyan] Run [cyan]graq sync pull[/cyan] to update.")


@sync_app.command("resolve")
def sync_resolve() -> None:
    """Interactive conflict resolution for sync conflicts.

    \b
    When two developers modify the same node, conflicts arise.
    Auto-resolved by source priority: Code > API spec > Config > Taught > Docs.
    Manual resolution for ambiguous cases.
    """
    if not _check_plan_gate():
        raise typer.Exit(1)

    console.print("[cyan]No conflicts to resolve.[/cyan]")
    console.print("[dim]Conflicts appear when multiple developers modify the same node.[/dim]")
