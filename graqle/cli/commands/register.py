"""graq register — opt-in developer registration for updates and support.

Captures email + optional info for the GraQle lead pipeline.
All data stored locally in ~/.graqle/profile.json and synced
to the GraQle API for updates, tips, and priority support.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.register
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, logging, typer, console, panel +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()
logger = logging.getLogger("graqle.cli.register")


def register_command(
    email: str | None = typer.Option(
        None, "--email", "-e", help="Your email address"
    ),
    name: str = typer.Option("", "--name", "-n", help="Your name"),
    company: str = typer.Option("", "--company", "-c", help="Company/organisation"),
    no_telemetry: bool = typer.Option(
        False, "--no-telemetry", help="Opt out of anonymous usage telemetry"
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Skip interactive prompts"
    ),
) -> None:
    """Register for GraQle updates, tips, and priority support.

    Your email is used for product updates and support only.
    Anonymous telemetry (opt-in) helps us improve Graqle.
    No code, queries, or secrets are ever collected.

    \b
    Examples:
        graq register
        graq register --email dev@company.com --name "Jane Doe"
        graq register --email dev@company.com --no-telemetry
    """
    from graqle.leads.collector import (
        is_registered,
        load_profile,
        register,
    )

    # Check if already registered
    if is_registered():
        profile = load_profile()
        console.print(
            f"[green]Already registered as {profile.get('email')}[/green]"
        )
        if not non_interactive:
            update = Confirm.ask("Update your registration?", default=False)
            if not update:
                return
        else:
            return

    # Interactive prompts
    if not email and not non_interactive:
        console.print(
            Panel(
                "[bold cyan]GraQle — Developer Registration[/bold cyan]\n\n"
                "Register for:\n"
                "  [green]+[/green] Product updates and new features\n"
                "  [green]+[/green] Tips for getting more from your knowledge graph\n"
                "  [green]+[/green] Priority support\n"
                "  [green]+[/green] Early access to Team features\n\n"
                "[dim]No code, queries, or secrets are ever collected.\n"
                "Unsubscribe anytime. Data stored in ~/.graqle/profile.json[/dim]",
                border_style="cyan",
            )
        )
        email = Prompt.ask("[bold]Email address[/bold]")
        if not name:
            name = Prompt.ask("Name (optional)", default="")
        if not company:
            company = Prompt.ask("Company (optional)", default="")
        if not no_telemetry:
            no_telemetry = not Confirm.ask(
                "Send anonymous usage telemetry to help improve GraQle?",
                default=True,
            )

    if not email:
        console.print("[red]Email is required. Use --email or run interactively.[/red]")
        raise typer.Exit(1)

    # Validate email (basic)
    if "@" not in email or "." not in email.split("@")[-1]:
        console.print("[red]Invalid email address.[/red]")
        raise typer.Exit(1)

    # Register
    profile = register(
        email=email,
        name=name,
        company=company,
        telemetry_opt_in=not no_telemetry,
        source="cli",
    )

    console.print(
        Panel(
            f"[bold green]Registered![/bold green]\n\n"
            f"  Email:     {profile.get('email')}\n"
            f"  Name:      {profile.get('name') or '(not set)'}\n"
            f"  Company:   {profile.get('company') or '(not set)'}\n"
            f"  Telemetry: {'enabled' if profile.get('telemetry_opt_in') else 'disabled'}\n\n"
            f"[dim]Profile: ~/.graqle/profile.json\n"
            f"Manage: graq register --help | graq billing[/dim]",
            border_style="green",
            title="Welcome",
        )
    )

    if not non_interactive:
        from graqle.cloud.credentials import load_credentials
        creds = load_credentials()
        if not creds.is_authenticated:
            console.print()
            console.print(
                Panel(
                    "[bold]Next: Connect to GraQle Cloud (optional)[/bold]\n\n"
                    "  1. Get your API key at:\n"
                    "     [bold cyan]https://graqle.com/dashboard/account[/bold cyan]\n\n"
                    "  2. Run:\n"
                    "     [bold cyan]graq login --api-key grq_your_key_here[/bold cyan]\n\n"
                    "  [dim]Or set env var: export GRAQLE_API_KEY=grq_your_key[/dim]\n\n"
                    "  Cloud enables: graph backup, team sync, Studio access.\n"
                    "  Local features (CLI, MCP) work without it.",
                    border_style="dim",
                    title="[dim]Cloud setup (optional)[/dim]",
                )
            )
