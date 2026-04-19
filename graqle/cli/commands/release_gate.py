"""graq release-gate — pre-publish KG + multi-agent governance gate.

Blocks bad ships before PyPI or VS Code Marketplace publish.

Usage:
    graq release-gate --diff pr.diff --target pypi
    git diff main...HEAD | graq release-gate --diff - --target vscode-marketplace
    graq release-gate --diff pr.diff --target pypi --repo owner/repo --pr 42

Exit codes:
    0  CLEAR (and WARN if --strict is not set)
    1  BLOCK (always fails)
    2  WARN (only fails when --strict is set)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from graqle.cli.console import create_console

console = create_console()


def release_gate_command(
    diff: str = typer.Option(
        "",
        "--diff",
        "-d",
        help="Path to unified diff file, or '-' for stdin.",
    ),
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Publish target: pypi | vscode-marketplace.",
    ),
    min_confidence: Optional[float] = typer.Option(
        None,
        "--min-confidence",
        help=(
            "Optional confidence override (float between 0.0 and 1.0). "
            "Leave unset to use GraQle defaults."
        ),
    ),
    repo: str = typer.Option(
        "",
        "--repo",
        "-r",
        help="GitHub repository (owner/repo) for posting verdict as PR comment.",
    ),
    pr_number: int = typer.Option(
        0,
        "--pr",
        "-p",
        help="PR number to comment on. Requires --repo.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail process on WARN or BLOCK (default: only BLOCK fails).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit only JSON verdict to stdout (for CI parsing).",
    ),
):
    """Run the pre-publish governance gate."""
    # Read diff
    if diff == "-":
        diff_text = sys.stdin.read()
    elif diff:
        diff_path = Path(diff)
        if not diff_path.exists():
            console.print(f"[bold red]Diff file not found:[/bold red] {diff}")
            raise typer.Exit(1)
        diff_text = diff_path.read_text(encoding="utf-8")
    else:
        console.print(
            "[bold red]No diff provided.[/bold red] "
            "Use --diff <path> or --diff -"
        )
        raise typer.Exit(1)

    if not diff_text.strip():
        console.print("[yellow]Empty diff — nothing to gate.[/yellow]")
        raise typer.Exit(0)

    # Run the gate via MCP server (same path as graq_release_gate tool)
    from graqle.plugins.mcp_dev_server import KogniDevServer

    server = KogniDevServer()
    args = {"diff": diff_text, "target": target}
    if min_confidence is not None:
        args["min_confidence"] = min_confidence

    raw = asyncio.run(server._handle_release_gate(args))
    try:
        verdict = json.loads(raw)
    except (ValueError, TypeError):
        console.print("[bold red]Release Gate returned malformed result.[/bold red]")
        raise typer.Exit(1)

    # Render output
    if json_output:
        sys.stdout.write(json.dumps(verdict, indent=2) + "\n")
    else:
        _render_verdict_pretty(verdict)

    # Optional: post comment to PR
    if repo and pr_number:
        try:
            _post_github_comment(repo, pr_number, verdict)
        except Exception as exc:  # pylint: disable=broad-except
            console.print(f"[yellow]Could not post PR comment: {exc}[/yellow]")

    # Exit code
    v = verdict.get("verdict", "WARN")
    if v == "BLOCK":
        raise typer.Exit(1)
    if v == "WARN" and strict:
        raise typer.Exit(2)
    raise typer.Exit(0)


def _render_verdict_pretty(verdict: dict) -> None:
    v = verdict.get("verdict", "WARN")
    color = {"CLEAR": "green", "WARN": "yellow", "BLOCK": "red"}.get(v, "white")
    target = verdict.get("target", "?")
    console.print(f"[bold {color}]{v}[/bold {color}] — target: [bold]{target}[/bold]")

    blockers = verdict.get("blockers") or []
    majors = verdict.get("majors") or []
    if blockers:
        console.print(f"\n[bold red]Blockers ({len(blockers)}):[/bold red]")
        for b in blockers:
            console.print(f"  • {b}")
    if majors:
        console.print(f"\n[bold yellow]Majors ({len(majors)}):[/bold yellow]")
        for m in majors:
            console.print(f"  • {m}")

    summary = verdict.get("review_summary", "")
    if summary:
        console.print(f"\n[dim]{summary}[/dim]")


def _post_github_comment(repo: str, pr: int, verdict: dict) -> None:
    """Post verdict as a PR comment via gh CLI (best-effort)."""
    import subprocess
    v = verdict.get("verdict", "WARN")
    emoji = {"CLEAR": "✅", "WARN": "⚠️", "BLOCK": "⛔"}.get(v, "❓")
    target = verdict.get("target", "?")
    body_lines = [
        f"## {emoji} GraQle Release Gate — **{v}**",
        f"Target: `{target}`",
        "",
    ]
    for b in verdict.get("blockers") or []:
        body_lines.append(f"- 🛑 **BLOCKER:** {b}")
    for m in verdict.get("majors") or []:
        body_lines.append(f"- ⚠️ **MAJOR:** {m}")
    if verdict.get("review_summary"):
        body_lines.append(f"\n> {verdict['review_summary']}")
    body = "\n".join(body_lines)

    subprocess.run(
        ["gh", "pr", "comment", str(pr), "--repo", repo, "--body", body],
        check=False,
    )
