"""graq login / graq logout — GraQle Cloud authentication.

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
    """Connect to GraQle Cloud (optional — local features work without login).

    \b
    Cloud features:
      - Graph backup and sync
      - Team collaboration (shared graphs)
      - Usage analytics and insights

    \b
    Get an API key at https://graqle.com/dashboard/account
    All local features (Studio, CLI, MCP) work without an account.

    \b
    Alternative (CI/Docker): set GRAQLE_API_KEY=grq_your_key in your environment.
    """
    from graqle.cloud.credentials import (
        CloudCredentials,
        get_cloud_status,
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
            console.print("[yellow]Not connected to GraQle Cloud[/yellow]")
            console.print("  Local features work without login.")
            console.print("  Run [cyan]graq login --api-key <key>[/cyan] to connect.")
        return

    # Interactive mode if no key provided
    if not api_key:
        console.print("[bold cyan]GraQle Cloud Login[/bold cyan]")
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
        console.print("Get a key at [cyan]https://graqle.com/dashboard/account[/cyan]")
        raise typer.Exit(1)

    # A-001: Validate key against cloud API and sync plan tier
    validated_email = email
    # Preserve existing plan tier if re-login fails to reach cloud
    try:
        _existing = load_credentials()
        validated_plan = _existing.plan if _existing.plan else "free"
    except Exception:
        validated_plan = "free"

    try:
        import httpx
        response = httpx.post(
            "https://graqle.com/api/keys/validate",
            json={"apiKey": api_key},
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("valid"):
                validated_email = data.get("email", email)
                validated_plan = data.get("plan", "free")
                console.print("[green]API key validated![/green]")
                console.print(f"  Plan synced: [cyan]{validated_plan.title()}[/cyan]")
            else:
                console.print("[red]Invalid API key. Generate a new one at graqle.com/dashboard/account[/red]")
                raise typer.Exit(1)
        else:
            console.print("[yellow]Could not validate key online. Saving locally.[/yellow]")
    except ImportError:
        console.print("[dim]httpx not installed — skipping online validation. Key saved locally.[/dim]")
    except Exception:
        console.print("[yellow]Could not reach GraQle Cloud. Key saved locally.[/yellow]")

    # Save credentials
    creds = CloudCredentials(
        api_key=api_key,
        email=validated_email,
        plan=validated_plan,
        connected=True,
    )
    save_credentials(creds)

    console.print()
    console.print("[green]Connected to GraQle Cloud![/green]")
    if validated_email:
        console.print(f"  Email: {validated_email}")
    console.print(f"  Plan:  {validated_plan.title()}")
    console.print(f"  Key:   {api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else f"  Key: {api_key}")
    console.print()
    console.print("Cloud features now available:")
    console.print("  - Push graph:    [cyan]graq cloud push[/cyan]")
    console.print("  - Pull graph:    [cyan]graq cloud pull[/cyan]")
    console.print("  - Cloud status:  [cyan]graq cloud status[/cyan]")
    console.print("  - Team sync:     [cyan]graq sync push[/cyan] (Team plan)")


def logout_command() -> None:
    """Disconnect from GraQle Cloud. Local features continue to work."""
    from graqle.cloud.credentials import clear_credentials, load_credentials

    creds = load_credentials()
    if not creds.is_authenticated:
        console.print("[yellow]Not currently connected to GraQle Cloud.[/yellow]")
        return

    clear_credentials()
    console.print("[green]Logged out of GraQle Cloud.[/green]")
    console.print("Local features (Studio, CLI, MCP) continue to work.")
