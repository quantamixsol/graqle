"""graq migrate — Rename legacy cognigraph files to graqle branding."""

# ── graqle:intelligence ──
# module: graqle.cli.commands.migrate
# risk: LOW (impact radius: 2 modules)
# dependencies: __future__, pathlib, re, typer, rich
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console

console = Console()

# Pairs: (old_name, new_name)
_FILE_RENAMES = [
    ("cognigraph.yaml", "graqle.yaml"),
    ("cognigraph.json", "graqle.json"),
]

_KOGNI_TOOL_RE = re.compile(r"\bkogni_(reason|impact|preflight|context|lessons|learn|inspect|gate|drace|runtime|route|lifecycle|reason_batch|safety_check)\b")


def _rename_file(cwd: Path, old: str, new: str, dry_run: bool) -> str | None:
    """Rename old -> new if old exists and new does not. Returns action string or None."""
    old_path = cwd / old
    new_path = cwd / new
    if not old_path.exists():
        return None
    if new_path.exists():
        return f"SKIP {old} → {new} (target already exists)"
    if dry_run:
        return f"WOULD RENAME {old} → {new}"
    old_path.rename(new_path)
    return f"RENAMED {old} → {new}"


def _update_claude_md(cwd: Path, dry_run: bool) -> str | None:
    """Rewrite CLAUDE.md: kogni_* tool refs → graq_*."""
    claude_md = cwd / "CLAUDE.md"
    if not claude_md.exists():
        return None
    content = claude_md.read_text(encoding="utf-8")
    new_content = _KOGNI_TOOL_RE.sub(lambda m: f"graq_{m.group(1)}", content)
    if new_content == content:
        return None
    count = len(_KOGNI_TOOL_RE.findall(content))
    if dry_run:
        return f"WOULD UPDATE CLAUDE.md ({count} kogni_* → graq_* replacements)"
    claude_md.write_text(new_content, encoding="utf-8")
    return f"UPDATED CLAUDE.md ({count} kogni_* → graq_* replacements)"


def _update_mcp_json(cwd: Path, dry_run: bool) -> str | None:
    """Rewrite .mcp.json: rename 'cognigraph' server key to 'graqle'."""
    mcp_json = cwd / ".mcp.json"
    if not mcp_json.exists():
        return None
    try:
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    servers = data.get("mcpServers", {})
    if "cognigraph" not in servers:
        return None
    if "graqle" in servers:
        return "SKIP .mcp.json cognigraph → graqle (graqle key already exists)"

    if dry_run:
        return "WOULD UPDATE .mcp.json (cognigraph → graqle server key)"
    servers["graqle"] = servers.pop("cognigraph")
    mcp_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "UPDATED .mcp.json (cognigraph → graqle server key)"


def migrate_command(
    cwd: str = typer.Option(".", "--cwd", help="Working directory to migrate"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without applying"),
) -> None:
    """Migrate legacy cognigraph/kogni_ references to graqle/graq_ branding."""
    target = Path(cwd).resolve()
    if not target.is_dir():
        console.print(f"[red]Directory not found:[/red] {target}")
        raise typer.Exit(1)

    actions: list[str] = []

    # File renames
    for old, new in _FILE_RENAMES:
        result = _rename_file(target, old, new, dry_run)
        if result:
            actions.append(result)

    # CLAUDE.md tool refs
    result = _update_claude_md(target, dry_run)
    if result:
        actions.append(result)

    # .mcp.json server key
    result = _update_mcp_json(target, dry_run)
    if result:
        actions.append(result)

    if not actions:
        console.print("[green]✓[/green] Nothing to migrate — already using graqle branding.")
        return

    prefix = "[bold yellow]DRY RUN[/bold yellow] " if dry_run else ""
    console.print(f"\n{prefix}[bold]Migration results:[/bold]")
    for action in actions:
        console.print(f"  • {action}")
    console.print()

    if dry_run:
        console.print("[dim]Run without --dry-run to apply changes.[/dim]")
    else:
        console.print(f"[green]✓[/green] Migrated {len(actions)} item(s) to graqle branding.")
