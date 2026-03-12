"""kogni register — opt-in developer registration for updates and support.

Captures email + optional info for the CogniGraph lead pipeline.
All data stored locally in ~/.cognigraph/profile.json and synced
to the CogniGraph API for updates, tips, and priority support.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()
logger = logging.getLogger("cognigraph.cli.register")


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
    """Register for CogniGraph updates, tips, and priority support.

    Your email is used for product updates and support only.
    Anonymous telemetry (opt-in) helps us improve CogniGraph.
    No code, queries, or secrets are ever collected.

    \b
    Examples:
        kogni register
        kogni register --email dev@company.com --name "Jane Doe"
        kogni register --email dev@company.com --no-telemetry
    """
    from cognigraph.leads.collector import (
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
                "[bold cyan]CogniGraph — Developer Registration[/bold cyan]\n\n"
                "Register for:\n"
                "  [green]+[/green] Product updates and new features\n"
                "  [green]+[/green] Tips for getting more from your knowledge graph\n"
                "  [green]+[/green] Priority support\n"
                "  [green]+[/green] Early access to Team features\n\n"
                "[dim]No code, queries, or secrets are ever collected.\n"
                "Unsubscribe anytime. Data stored in ~/.cognigraph/profile.json[/dim]",
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
                "Send anonymous usage telemetry to help improve CogniGraph?",
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
            f"[dim]Profile: ~/.cognigraph/profile.json\n"
            f"Manage: kogni register --help | kogni billing[/dim]",
            border_style="green",
            title="Welcome",
        )
    )
