"""graq activate — activate a Graqle license key.

Validates and stores the license key in ~/.graqle/license.key.
License keys are generated after Stripe payment and delivered via email.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
logger = logging.getLogger("graqle.cli.activate")


def activate_command(
    key: str = typer.Argument(..., help="License key from your purchase confirmation"),
    project_level: bool = typer.Option(
        False, "--project", "-p", help="Store key at project level (graqle.license) instead of user level"
    ),
) -> None:
    """Activate a Graqle Team or Enterprise license.

    License keys are delivered via email after purchase at
    https://graqle.dev/pricing. The key is verified offline
    using HMAC-SHA256 — no network calls needed.

    \b
    Examples:
        graq activate eyJ0aWVyIjoiLi4u.abc123def456
        graq activate --project eyJ0aWVyIjoiLi4u.abc123def456
    """
    from graqle.licensing.manager import LicenseManager

    # Validate the key
    manager = LicenseManager.__new__(LicenseManager)
    manager._license = None
    license_obj = manager._verify_key(key.strip())

    if license_obj is None:
        console.print(
            Panel(
                "[bold red]Invalid license key.[/bold red]\n\n"
                "The key could not be verified. Please check:\n"
                "  1. Copy the full key from your confirmation email\n"
                "  2. No extra spaces or line breaks\n"
                "  3. Key format: payload.signature (two parts separated by a dot)\n\n"
                "[dim]Need help? Email support@graqle.dev[/dim]",
                border_style="red",
                title="Activation Failed",
            )
        )
        raise typer.Exit(1)

    # Check expiry
    if not license_obj.is_valid:
        console.print(
            Panel(
                f"[bold yellow]License expired.[/bold yellow]\n\n"
                f"  Tier:    {license_obj.tier.value.title()}\n"
                f"  Holder:  {license_obj.holder}\n"
                f"  Expired: {license_obj.expires_at}\n\n"
                "[dim]Renew at https://graqle.dev/pricing[/dim]",
                border_style="yellow",
                title="Expired",
            )
        )
        raise typer.Exit(1)

    # Store the key
    if project_level:
        target = Path("graqle.license")
    else:
        target = Path.home() / ".graqle" / "license.key"
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(key.strip(), encoding="utf-8")

    # Show activation details
    expiry_str = (
        license_obj.expires_at.strftime("%Y-%m-%d")
        if license_obj.expires_at
        else "Perpetual"
    )

    tier_features = license_obj.all_features - set()  # copy
    team_features = {
        "shared_kg_sync": "Shared KG sync across team",
        "multi_instance_coordination": "Multi-developer coordination",
        "cross_dev_lessons": "Cross-developer lesson sharing",
        "team_analytics": "Team analytics & insights",
        "custom_ontologies": "Custom domain ontologies",
    }
    enterprise_features = {
        "private_deployment": "Private deployment",
        "compliance_reporting": "Compliance & audit trail",
        "sla_support": "SLA support",
        "custom_integrations": "Custom integrations",
        "audit_trail": "Full audit trail",
    }

    unlocked = []
    for feat, desc in {**team_features, **enterprise_features}.items():
        if feat in tier_features:
            unlocked.append(f"  [green]+[/green] {desc}")

    unlocked_str = "\n".join(unlocked) if unlocked else "  (no additional features)"

    console.print(
        Panel(
            f"[bold green]License activated![/bold green]\n\n"
            f"  Tier:    [bold cyan]{license_obj.tier.value.title()}[/bold cyan]\n"
            f"  Holder:  {license_obj.holder}\n"
            f"  Email:   {license_obj.email}\n"
            f"  Expires: {expiry_str}\n"
            f"  Stored:  {target}\n\n"
            f"[bold]Unlocked features:[/bold]\n"
            f"{unlocked_str}\n\n"
            f"[dim]View status: graq billing\n"
            f"All Community features remain free forever.[/dim]",
            border_style="green",
            title="Activated",
        )
    )

    # Link to profile if registered
    try:
        from graqle.leads.collector import load_profile, save_profile
        profile = load_profile()
        if not profile.get("email") and license_obj.email:
            profile["email"] = license_obj.email
            profile["name"] = license_obj.holder
            save_profile(profile)
            console.print(
                f"[dim]Profile linked to {license_obj.email}[/dim]"
            )
    except Exception:
        pass
