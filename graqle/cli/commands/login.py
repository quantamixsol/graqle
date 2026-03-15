"""graq login / graq logout — Graqle Cloud authentication.

Cloud features are optional. Local features (Studio, CLI, MCP) work
without any account. Cloud enables: graph backup, team sync, usage analytics.

Examples:
    graq login                          # Interactive login
    graq login --api-key grq_abc123     # Non-interactive with key
    graq logout                         # Remove stored credentials
    graq login --status                 # Check connection status
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.login
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, typer, console
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def login_command(
    api_key: str = typer.Option(
        "", "--api-key", "-k", help="API key (starts with grq_)"
    ),
    email: str = typer.Option(
        "", "--email", "-e", help="Email address for account"
    ),
    status: bool = typer.Option(
        False, "--status", "-s", help="Check current cloud connection status"
    ),
) -> None:
    """Connect to Graqle Cloud (optional — local features work without login).

    \b
    Cloud features:
      - Graph backup and sync
      - Team collaboration (shared graphs)
      - Usage analytics and insights

    \b
    Get an API key at https://graqle.com/account
    All local features (Studio, CLI, MCP) work without an account.
    """
    from graqle.cloud.credentials import (
        CloudCredentials,
        get_cloud_status,
        load_credentials,
        save_credentials,
    )

    # Status check
    if status:
        cloud = get_cloud_status()
        if cloud["connected"]:
            console.print(f"[green]Connected[/green] as {cloud['email']}")
            console.print(f"  Plan: {cloud['plan']}")
            console.print(f"  Cloud: {cloud['cloud_url']}")
        else:
            console.print("[yellow]Not connected to Graqle Cloud[/yellow]")
            console.print("  Local features work without login.")
            console.print("  Run [cyan]graq login --api-key <key>[/cyan] to connect.")
        return

    # Interactive mode if no key provided
    if not api_key:
        console.print("[bold cyan]Graqle Cloud Login[/bold cyan]")
        console.print()
        console.print("Cloud features are [bold]optional[/bold]. Your graph, your machine, your data.")
        console.print("Cloud adds: backup, team sync, usage analytics.")
        console.print()
        console.print("Get an API key at [cyan]https://graqle.com/account[/cyan]")
        console.print()

        import sys
        if sys.stdin.isatty():
            api_key = typer.prompt("API key (starts with grq_)", default="")
            if not api_key:
                console.print("[yellow]No key provided. Skipping cloud setup.[/yellow]")
                console.print("Local features continue to work without login.")
                return
            if not email:
                email = typer.prompt("Email (optional)", default="")
        else:
            console.print("[yellow]Non-interactive mode. Use --api-key flag.[/yellow]")
            return

    # Validate key format
    if not api_key.startswith("grq_"):
        console.print("[red]Invalid API key format. Keys start with 'grq_'.[/red]")
        console.print("Get a key at [cyan]https://graqle.com/account[/cyan]")
        raise typer.Exit(1)

    # Save credentials
    creds = CloudCredentials(
        api_key=api_key,
        email=email,
        plan="free",  # Will be updated when cloud validates
        connected=True,
    )
    save_credentials(creds)

    console.print()
    console.print("[green]Connected to Graqle Cloud![/green]")
    if email:
        console.print(f"  Email: {email}")
    console.print(f"  Key: {api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else f"  Key: {api_key}")
    console.print()
    console.print("Cloud features now available:")
    console.print("  - Graph backup:  [cyan]graq cloud backup[/cyan]")
    console.print("  - Team sync:     [cyan]graq cloud sync[/cyan] (Team plan)")
    console.print("  - Status:        [cyan]graq login --status[/cyan]")


def logout_command() -> None:
    """Disconnect from Graqle Cloud. Local features continue to work."""
    from graqle.cloud.credentials import clear_credentials, load_credentials

    creds = load_credentials()
    if not creds.is_authenticated:
        console.print("[yellow]Not currently connected to Graqle Cloud.[/yellow]")
        return

    clear_credentials()
    console.print("[green]Logged out of Graqle Cloud.[/green]")
    console.print("Local features (Studio, CLI, MCP) continue to work.")
