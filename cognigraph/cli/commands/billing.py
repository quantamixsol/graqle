"""kogni billing — show license tier, usage, and upgrade options.

Displays current license status, feature availability, usage stats,
and clear upgrade paths with pricing.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
logger = logging.getLogger("cognigraph.cli.billing")


def billing_command(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all features"),
) -> None:
    """Show your CogniGraph license tier, usage stats, and upgrade options.

    \b
    Examples:
        kogni billing
        kogni billing --verbose
    """
    from cognigraph.licensing.manager import (
        TIER_FEATURES,
        LicenseManager,
        LicenseTier,
    )
    from cognigraph.leads.collector import load_profile

    manager = LicenseManager()
    tier = manager.current_tier
    license_obj = manager.license
    profile = load_profile()

    # ── Current tier ──────────────────────────────────────────────
    tier_colors = {
        LicenseTier.FREE: "white",
        LicenseTier.PRO: "cyan",
        LicenseTier.TEAM: "blue",
        LicenseTier.ENTERPRISE: "magenta",
    }
    color = tier_colors.get(tier, "white")

    if license_obj and license_obj.is_valid:
        expiry = (
            license_obj.expires_at.strftime("%Y-%m-%d")
            if license_obj.expires_at
            else "Perpetual"
        )
        tier_info = (
            f"  Tier:    [bold {color}]{tier.value.title()}[/bold {color}]\n"
            f"  Holder:  {license_obj.holder}\n"
            f"  Email:   {license_obj.email}\n"
            f"  Expires: {expiry}"
        )
    else:
        tier_info = (
            f"  Tier:    [bold {color}]Community (Free)[/bold {color}]\n"
            f"  All 13 innovations included\n"
            f"  All 7 MCP tools included\n"
            f"  No limits, no expiry"
        )

    console.print(
        Panel(tier_info, border_style=color, title="Current License")
    )

    # ── Usage stats ───────────────────────────────────────────────
    counters = profile.get("usage_counters", {})
    projects = profile.get("projects", [])

    if counters or projects:
        console.print("\n[bold]Usage[/bold]")
        if counters:
            total = sum(counters.values())
            console.print(f"  Total events: [cyan]{total}[/cyan]")
            for event_type, count in sorted(counters.items(), key=lambda x: -x[1]):
                console.print(f"    {event_type}: {count}")
        if projects:
            console.print(f"  Projects initialized: [cyan]{len(projects)}[/cyan]")
            for p in projects[-3:]:  # show last 3
                console.print(
                    f"    {p.get('path_hash', '?')[:8]}... "
                    f"({p.get('node_count', 0)} nodes, {p.get('backend', '?')})"
                )

    # ── Feature comparison table ──────────────────────────────────
    console.print()
    table = Table(title="Feature Tiers", show_header=True, header_style="bold")
    table.add_column("Feature", style="bold")
    table.add_column("Community\n$0/forever", justify="center", style="green")
    table.add_column("Team\n$29/dev/mo", justify="center", style="blue")
    table.add_column("Enterprise\nCustom", justify="center", style="magenta")

    # Community features (summary)
    community_highlights = [
        ("All 13 innovations (PCST, SHACL, etc.)", True, True, True),
        ("All 7 MCP tools", True, True, True),
        ("CLI + Python SDK + REST API", True, True, True),
        ("Unlimited queries", True, True, True),
        ("Auto-growing knowledge graph", True, True, True),
        ("Multi-backend (Ollama, Claude, GPT, Bedrock)", True, True, True),
        ("Multi-IDE (Claude Code, Cursor, VS Code, etc.)", True, True, True),
        ("Session continuity workspace", True, True, True),
        ("Commercial use", True, True, True),
    ]

    team_only = [
        ("Shared KG sync across team", False, True, True),
        ("Multi-developer coordination", False, True, True),
        ("Cross-developer lesson sharing", False, True, True),
        ("Team analytics & insights", False, True, True),
        ("Custom domain ontologies", False, True, True),
    ]

    enterprise_only = [
        ("Private deployment", False, False, True),
        ("Compliance & audit trail", False, False, True),
        ("SLA support", False, False, True),
        ("Custom integrations", False, False, True),
    ]

    rows = community_highlights + team_only + enterprise_only
    if not verbose:
        # Show abbreviated list
        rows = community_highlights[:4] + team_only[:2] + enterprise_only[:1]
        rows.append(("... use --verbose for full list", None, None, None))

    for feature, free, team, ent in rows:
        if free is None:
            table.add_row(f"[dim]{feature}[/dim]", "", "", "")
        else:
            table.add_row(
                feature,
                "[green]included[/green]" if free else "[dim]—[/dim]",
                "[blue]included[/blue]" if team else "[dim]—[/dim]",
                "[magenta]included[/magenta]" if ent else "[dim]—[/dim]",
            )

    console.print(table)

    # ── Upgrade CTA ───────────────────────────────────────────────
    if tier in (LicenseTier.FREE, LicenseTier.PRO):
        console.print(
            Panel(
                "[bold]Ready to share your knowledge graph with your team?[/bold]\n\n"
                "  Team plan: [bold cyan]$29/dev/month[/bold cyan]\n"
                "  Includes shared KG sync, team analytics, and multi-dev coordination.\n\n"
                "  [bold]Purchase:[/bold] https://cognigraph.dev/pricing\n"
                "  [bold]Activate:[/bold] kogni activate <license-key>\n\n"
                "[dim]Enterprise: Contact sales@cognigraph.dev[/dim]",
                border_style="cyan",
                title="Upgrade",
            )
        )
    elif tier == LicenseTier.TEAM:
        console.print(
            Panel(
                "[bold]Need private deployment or compliance features?[/bold]\n\n"
                "  Contact: [bold]sales@cognigraph.dev[/bold]\n\n"
                "[dim]Your Team license is active and all Team features are unlocked.[/dim]",
                border_style="blue",
                title="Enterprise",
            )
        )
