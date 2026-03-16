"""graq plugins — discover and integrate companion Claude Code plugins.

Graqle works alongside other Claude Code plugins/skills via MCP.
This command helps users discover, install, and configure plugins
that complement Graqle's intelligence layer.

Usage:
    graq plugins list          # Show available companion plugins
    graq plugins install <id>  # Install a companion plugin
    graq plugins status        # Show installed plugins
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
logger = logging.getLogger("graqle.cli.plugins")

# ──────────────────────────────────────────────────────────────────────
# Plugin registry — companion tools that work alongside Graqle
# ──────────────────────────────────────────────────────────────────────

COMPANION_PLUGINS: dict[str, dict[str, Any]] = {
    "superpowers": {
        "name": "Superpowers",
        "repo": "obra/superpowers",
        "description": "Structured dev methodology — spec-before-code, TDD, code review",
        "install_type": "claude-plugin",
        "install_cmd": "git clone https://github.com/obra/superpowers.git",
        "install_dir": "superpowers",
        "synergy": "Combines with Graqle's impact analysis for safer refactoring workflows",
        "category": "methodology",
        "bridge": "superpowers_bridge.md",
    },
    "ui-ux-promax": {
        "name": "UI UX Pro Max",
        "repo": "nextlevelbuilder/ui-ux-pro-max-skill",
        "description": "Design intelligence — 57 UI styles, 95 palettes, dashboard generators",
        "install_type": "claude-skill",
        "install_cmd": "git clone https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git",
        "install_dir": "ui-ux-pro-max-skill",
        "synergy": "Uses Graqle's graph data to inform UI layout decisions for dashboards",
        "category": "design",
        "bridge": "uiux_bridge.md",
    },
    "claude-mem": {
        "name": "Claude Memory",
        "repo": "thedotmack/claude-mem",
        "description": "Persistent session memory with vector search and 3-layer retrieval",
        "install_type": "mcp-server",
        "install_cmd": "curl -fsSL https://install.cmem.ai/openclaw.sh | bash",
        "install_dir": None,
        "synergy": "Structural memory (Graqle KG) + temporal memory (Claude-Mem) = complete context",
        "category": "memory",
    },
}


# ──────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="plugins",
    help="Discover and integrate companion Claude Code plugins.",
    no_args_is_help=True,
)


@app.command("list")
def list_plugins():
    """Show available companion plugins that work with Graqle."""
    table = Table(title="Companion Plugins for Graqle", show_lines=True)
    table.add_column("ID", style="cyan", width=16)
    table.add_column("Name", style="bold")
    table.add_column("Category", style="dim")
    table.add_column("Description")
    table.add_column("Installed", justify="center", width=10)

    for pid, plugin in COMPANION_PLUGINS.items():
        installed = _is_installed(pid)
        status = "[green]Yes[/green]" if installed else "[dim]No[/dim]"
        table.add_row(
            pid,
            plugin["name"],
            plugin["category"],
            plugin["description"],
            status,
        )

    console.print(table)
    console.print()
    console.print("[dim]Install with:[/dim] graq plugins install <id>")
    console.print("[dim]These plugins complement Graqle — they are NOT bundled.[/dim]")
    console.print("[dim]Each plugin has its own license and maintainer.[/dim]")


@app.command("status")
def status():
    """Show installed companion plugins and their integration status."""
    installed_any = False

    for pid, plugin in COMPANION_PLUGINS.items():
        if _is_installed(pid):
            installed_any = True
            console.print(
                Panel(
                    f"[bold]{plugin['name']}[/bold] ({plugin['repo']})\n"
                    f"[dim]{plugin['description']}[/dim]\n\n"
                    f"[cyan]Synergy:[/cyan] {plugin['synergy']}",
                    title=f"[green]● {pid}[/green]",
                    border_style="green",
                )
            )

    if not installed_any:
        console.print("[dim]No companion plugins installed.[/dim]")
        console.print("Run [cyan]graq plugins list[/cyan] to see available plugins.")


@app.command("install")
def install_plugin(
    plugin_id: str = typer.Argument(..., help="Plugin ID to install"),
):
    """Install a companion plugin."""
    if plugin_id not in COMPANION_PLUGINS:
        console.print(f"[red]Unknown plugin: {plugin_id}[/red]")
        console.print(f"Available: {', '.join(COMPANION_PLUGINS.keys())}")
        raise typer.Exit(1)

    plugin = COMPANION_PLUGINS[plugin_id]
    console.print(f"\n[bold]Installing {plugin['name']}...[/bold]")
    console.print(f"[dim]Repository: {plugin['repo']}[/dim]")
    console.print(f"[dim]Type: {plugin['install_type']}[/dim]")
    console.print()

    if _is_installed(plugin_id):
        console.print(f"[yellow]{plugin['name']} is already installed.[/yellow]")
        return

    install_type = plugin["install_type"]

    if install_type == "claude-plugin":
        _install_claude_plugin(plugin_id, plugin)
    elif install_type == "claude-skill":
        _install_claude_skill(plugin_id, plugin)
    elif install_type == "mcp-server":
        _install_mcp_server(plugin_id, plugin)
    else:
        console.print(f"[red]Unknown install type: {install_type}[/red]")
        raise typer.Exit(1)


# ──────────────────────────────────────────────────────────────────────
# Installation helpers
# ──────────────────────────────────────────────────────────────────────

def _claude_dir() -> Path:
    """Return the .claude directory path."""
    return Path.home() / ".claude"


def _is_installed(plugin_id: str) -> bool:
    """Check if a companion plugin is installed."""
    plugin = COMPANION_PLUGINS[plugin_id]
    install_dir = plugin.get("install_dir")

    if not install_dir:
        return False

    install_type = plugin["install_type"]

    if install_type == "claude-plugin":
        return (_claude_dir() / "plugins" / install_dir).is_dir()
    elif install_type == "claude-skill":
        # Check both global and project-level skills
        return (
            (_claude_dir() / "skills" / install_dir).is_dir()
            or (Path.cwd() / ".claude" / "skills" / install_dir).is_dir()
        )

    return False


def _deploy_bridge(plugin_id: str, plugin: dict):
    """Deploy the Graqle bridge skill that makes the plugin Graqle-aware.

    Bridge skills are .md files shipped inside the graqle SDK package.
    They get copied into the user's .claude/skills/ so Claude Code reads them
    alongside the plugin's own skills — enabling automatic complementary workflows.
    """
    bridge_file = plugin.get("bridge")
    if not bridge_file:
        return

    # Locate the bridge file inside the installed graqle package
    bridges_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "bridges"
    source = bridges_dir / bridge_file

    if not source.exists():
        logger.warning("Bridge file not found: %s", source)
        return

    # Deploy to project-level .claude/skills/ if project has .claude, else global
    if (Path.cwd() / ".claude").is_dir() or (Path.cwd() / "CLAUDE.md").exists():
        target_dir = Path.cwd() / ".claude" / "skills" / "graqle-bridges"
    else:
        target_dir = _claude_dir() / "skills" / "graqle-bridges"

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / bridge_file
    shutil.copy2(str(source), str(target))

    console.print(f"[green]Graqle bridge deployed:[/green] {target}")
    console.print(f"  [dim]Claude Code will now combine {plugin['name']} with Graqle's intelligence[/dim]")


def _install_claude_plugin(plugin_id: str, plugin: dict):
    """Install a Claude Code plugin (goes into ~/.claude/plugins/)."""
    plugins_dir = _claude_dir() / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    target = plugins_dir / plugin["install_dir"]
    repo_url = f"https://github.com/{plugin['repo']}.git"

    console.print(f"Cloning [cyan]{plugin['repo']}[/cyan] into {target}...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print(f"[green]✓ {plugin['name']} installed successfully![/green]")
        console.print(f"[dim]Location: {target}[/dim]")
        _deploy_bridge(plugin_id, plugin)
        console.print(f"\n[cyan]Synergy with Graqle:[/cyan] {plugin['synergy']}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Installation failed: {e.stderr}[/red]")
        raise typer.Exit(1)


def _install_claude_skill(plugin_id: str, plugin: dict):
    """Install a Claude Code skill (goes into ~/.claude/skills/ or project)."""
    # Prefer project-level skills
    project_skills = Path.cwd() / ".claude" / "skills"
    global_skills = _claude_dir() / "skills"

    # Use project-level if .claude exists in project
    if (Path.cwd() / ".claude").is_dir() or (Path.cwd() / "CLAUDE.md").exists():
        skills_dir = project_skills
    else:
        skills_dir = global_skills

    skills_dir.mkdir(parents=True, exist_ok=True)
    target = skills_dir / plugin["install_dir"]
    repo_url = f"https://github.com/{plugin['repo']}.git"

    console.print(f"Cloning [cyan]{plugin['repo']}[/cyan] into {target}...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print(f"[green]✓ {plugin['name']} installed successfully![/green]")
        console.print(f"[dim]Location: {target}[/dim]")
        _deploy_bridge(plugin_id, plugin)
        console.print(f"\n[cyan]Synergy with Graqle:[/cyan] {plugin['synergy']}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Installation failed: {e.stderr}[/red]")
        raise typer.Exit(1)


def _install_mcp_server(plugin_id: str, plugin: dict):
    """Install an MCP server companion (user follows external instructions)."""
    console.print(
        Panel(
            f"[bold]{plugin['name']}[/bold] is an MCP server that runs alongside Graqle.\n\n"
            f"Install it by following their instructions:\n"
            f"  [cyan]{plugin['install_cmd']}[/cyan]\n\n"
            f"After installation, both MCP servers will be available in Claude Code:\n"
            f"  • [cyan]graqle[/cyan] — architecture intelligence (your KG)\n"
            f"  • [cyan]{plugin_id}[/cyan] — {plugin['description']}\n\n"
            f"[dim]Repository: https://github.com/{plugin['repo']}[/dim]",
            title=f"Install {plugin['name']}",
            border_style="cyan",
        )
    )
