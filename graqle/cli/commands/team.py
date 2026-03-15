"""graq team — team management commands.

Manage your Graqle team for shared knowledge graphs.
Team features require the Team plan ($29/dev/mo).

Commands:
    graq team create <name>     Create a new team
    graq team invite <email>    Invite a team member
    graq team members           List team members
    graq team leave             Leave the team
    graq team info              Show team details
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.team
# risk: LOW (impact radius: 2 modules)
# consumers: main, test_team
# dependencies: __future__, typer, console, panel, table
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

team_app = typer.Typer(
    name="team",
    help="Manage your Graqle team for shared knowledge graphs (Team plan).",
    no_args_is_help=True,
)


def _check_team_gate() -> bool:
    """Check if the current plan allows team features."""
    from graqle.cloud.plans import PLAN_PRICING, check_feature
    from graqle.licensing.manager import LicenseManager

    manager = LicenseManager()
    plan = manager.current_tier.value

    result = check_feature(plan, "shared_graph")
    if result.allowed:
        return True

    console.print(Panel(
        f"[bold yellow]Team features require Team plan[/bold yellow]\n\n"
        f"  Your plan: [bold]{plan.title()}[/bold]\n"
        f"  Required:  [bold cyan]Team[/bold cyan] ({PLAN_PRICING['team']['price']})\n\n"
        f"[green]Why teams love Graqle Cloud:[/green]\n"
        f"  * One developer teaches the graph, [bold]everyone benefits[/bold]\n"
        f"  * New team members onboard in seconds (not weeks)\n"
        f"  * Cloud observability — track graph health, usage, ROI\n"
        f"  * Cross-repo architecture views\n"
        f"  * Persistent graph — survives laptop wipes\n\n"
        f"  [bold]Upgrade:[/bold] graq billing\n"
        f"  [bold]Purchase:[/bold] https://graqle.dev/pricing",
        border_style="cyan",
        title="Upgrade to Team",
    ))
    return False


@team_app.command("create")
def team_create(
    name: str = typer.Argument(..., help="Team name"),
    email: str = typer.Option("", "--email", "-e", help="Owner email"),
) -> None:
    """Create a new team and get a team ID.

    \b
    Creates a team for shared knowledge graph collaboration.
    You become the team owner with full admin access.

    \b
    Examples:
        graq team create my-team
        graq team create my-team --email alice@company.com
    """
    if not _check_team_gate():
        raise typer.Exit(1)

    from graqle.cloud.credentials import load_credentials
    from graqle.cloud.team import create_team, load_team_config

    # Check if already in a team
    existing = load_team_config()
    if existing.is_configured:
        console.print(f"[yellow]Already in team:[/yellow] {existing.team_name} ({existing.team_id})")
        console.print("Leave first: [cyan]graq team leave[/cyan]")
        raise typer.Exit(1)

    # Use email from credentials if not provided
    if not email:
        creds = load_credentials()
        email = creds.email
    if not email:
        console.print("[yellow]Email required for team ownership.[/yellow]")
        import sys
        if sys.stdin.isatty():
            email = typer.prompt("Your email")
        else:
            console.print("Use --email flag: [cyan]graq team create my-team --email you@company.com[/cyan]")
            raise typer.Exit(1)

    config = create_team(name, email)

    console.print()
    console.print(Panel(
        f"[bold green]Team created![/bold green]\n\n"
        f"  Team:    [bold]{config.team_name}[/bold]\n"
        f"  ID:      [cyan]{config.team_id}[/cyan]\n"
        f"  Owner:   {email}\n\n"
        f"Next steps:\n"
        f"  1. Invite team members:  [cyan]graq team invite alice@company.com[/cyan]\n"
        f"  2. Push your graph:      [cyan]graq sync push[/cyan]\n"
        f"  3. Team members pull:    [cyan]graq sync pull[/cyan]\n\n"
        f"[dim]Your team's knowledge graph will be hosted on Graqle Cloud.[/dim]",
        border_style="green",
        title="Team Created",
    ))


@team_app.command("invite")
def team_invite(
    email: str = typer.Argument(..., help="Email of person to invite"),
    role: str = typer.Option("member", "--role", "-r", help="Role: member, admin, viewer"),
) -> None:
    """Invite a team member.

    \b
    Roles:
        owner  — Full control (auto-assigned to creator)
        admin  — Can manage members and settings
        member — Can teach/modify the graph (default)
        viewer — Read-only access to the graph

    \b
    Examples:
        graq team invite alice@company.com
        graq team invite bob@company.com --role viewer
    """
    if not _check_team_gate():
        raise typer.Exit(1)

    from graqle.cloud.team import invite_member

    if role not in ("member", "admin", "viewer"):
        console.print(f"[red]Invalid role: {role}[/red]. Must be: member, admin, or viewer.")
        raise typer.Exit(1)

    try:
        member = invite_member(email, role)
        console.print(f"[green]Invited[/green] {email} as [cyan]{role}[/cyan]")
        console.print("[dim]They'll receive an invitation to join the team.[/dim]")
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@team_app.command("members")
def team_members() -> None:
    """List team members and their roles.

    \b
    Examples:
        graq team members
    """
    from graqle.cloud.team import load_team_config

    config = load_team_config()
    if not config.is_configured:
        console.print("[yellow]No team configured.[/yellow]")
        console.print("Create a team: [cyan]graq team create <name>[/cyan]")
        return

    table = Table(title=f"Team: {config.team_name}")
    table.add_column("Email", style="bold")
    table.add_column("Role")
    table.add_column("Status")
    table.add_column("Last Sync")

    role_colors = {
        "owner": "magenta",
        "admin": "cyan",
        "member": "green",
        "viewer": "dim",
    }

    for member in config.members:
        color = role_colors.get(member.role, "white")
        table.add_row(
            member.email,
            f"[{color}]{member.role}[/{color}]",
            member.status,
            member.last_sync or "never",
        )

    console.print(table)
    console.print(f"\n[dim]{config.member_count} active member(s)[/dim]")


@team_app.command("leave")
def team_leave(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Leave the current team.

    \b
    Your local graph is preserved. Cloud sync will be disconnected.

    \b
    Examples:
        graq team leave
        graq team leave --yes
    """
    from graqle.cloud.team import TeamConfig, load_team_config, save_team_config

    config = load_team_config()
    if not config.is_configured:
        console.print("[yellow]Not in a team.[/yellow]")
        return

    if not confirm:
        import sys
        if sys.stdin.isatty():
            confirmed = typer.confirm(
                f"Leave team '{config.team_name}'? Your local graph is preserved."
            )
            if not confirmed:
                console.print("[dim]Cancelled.[/dim]")
                return
        else:
            console.print("Use --yes flag to confirm: [cyan]graq team leave --yes[/cyan]")
            raise typer.Exit(1)

    # Clear team config
    save_team_config(TeamConfig())
    console.print(f"[green]Left team:[/green] {config.team_name}")
    console.print("[dim]Your local graph is preserved. Cloud sync disconnected.[/dim]")


@team_app.command("info")
def team_info() -> None:
    """Show team details including configuration and linked repos.

    \b
    Examples:
        graq team info
    """
    from graqle.cloud.team import load_team_config

    config = load_team_config()
    if not config.is_configured:
        console.print("[yellow]No team configured.[/yellow]")
        console.print()
        console.print(
            Panel(
                "[bold]Share your knowledge graph with your team[/bold]\n\n"
                "One developer teaches the graph, everyone benefits.\n"
                "New team members onboard in seconds, not weeks.\n\n"
                "  Create a team: [cyan]graq team create <name>[/cyan]\n"
                "  View plans:    [cyan]graq billing[/cyan]",
                border_style="cyan",
                title="Team Features",
            )
        )
        return

    console.print(Panel(
        f"  Team:      [bold]{config.team_name}[/bold]\n"
        f"  ID:        {config.team_id}\n"
        f"  Owner:     {config.owner_email}\n"
        f"  Plan:      {config.plan.title()}\n"
        f"  Members:   {config.member_count}\n"
        f"  Repos:     {len(config.repos)}\n"
        f"  Created:   {config.created_at}",
        border_style="cyan",
        title="Team Info",
    ))

    if config.repos:
        console.print("\n[bold]Linked Repos:[/bold]")
        for repo in config.repos:
            console.print(f"  * {repo}")

    # Show cloud features status
    console.print()
    console.print("[bold]Cloud Features:[/bold]")
    console.print("  Sync:           [cyan]graq sync status[/cyan]")
    console.print("  Observability:  [dim]Coming soon[/dim]")
    console.print("  Metrics:        [dim]Coming soon[/dim]")
    console.print("  Cross-repo:     [dim]Coming soon[/dim]")
