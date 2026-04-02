"""graq pr-guardian — AI-powered blast radius analysis for PRs.

Wraps existing governance infrastructure (GovernanceMiddleware, graq_impact)
to produce governed PR reviews with blast radius visualization.

Usage:
    graq pr-guardian --diff pr.diff                   # Local analysis
    graq pr-guardian --diff pr.diff --repo owner/repo  # Post to GitHub PR
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from graqle.cli.console import create_console

console = create_console()


def pr_guardian_command(
    diff: str = typer.Option(
        "",
        "--diff",
        "-d",
        help="Path to unified diff file, or '-' for stdin.",
    ),
    repo: str = typer.Option(
        "",
        "--repo",
        "-r",
        help="GitHub repository (owner/repo). Auto-detected in GitHub Actions.",
    ),
    pr_number: int = typer.Option(
        0,
        "--pr-number",
        "-p",
        help="PR number to comment on. Auto-detected in GitHub Actions.",
    ),
    fail_on: str = typer.Option(
        "fail",
        "--fail-on",
        help="Exit non-zero on: 'fail', 'warn', or 'never'.",
    ),
    max_depth: int = typer.Option(
        3,
        "--max-depth",
        help="Max BFS depth for blast radius traversal.",
    ),
    output_format: str = typer.Option(
        "terminal",
        "--output-format",
        "-f",
        help="Output format: 'terminal', 'json', 'github-action'.",
    ),
    api_key: str = typer.Option(
        "",
        "--api-key",
        help="GraQle API key for Pro tier (empty = free tier, 10 PRs/month).",
    ),
    custom_shacl: str = typer.Option(
        "",
        "--custom-shacl",
        help="Path to custom SHACL rules file (Pro tier only).",
    ),
    sarif: str = typer.Option(
        "",
        "--sarif",
        help="Write SARIF output to this path.",
    ),
    badge_path: str = typer.Option(
        "",
        "--badge-path",
        help="Write badge SVG to this path.",
    ),
    actor: str = typer.Option(
        "ci-bot",
        "--actor",
        help="Actor identity for RBAC checks.",
    ),
    approved_by: str = typer.Option(
        "",
        "--approved-by",
        help="Approver identity for T3 gates.",
    ),
) -> None:
    """Run PR Guardian — AI-powered blast radius analysis & governance for PRs."""
    import os

    from graqle.guardian.tier import check_tier, record_scan

    # -- Tier check --
    tier_status = check_tier(api_key)
    if not tier_status.can_scan:
        console.print(
            f"[bold red]Free tier limit reached:[/bold red] "
            f"{tier_status.scans_used}/{tier_status.scans_limit} scans this month.\n"
            f"Upgrade to Pro ($19/mo) for unlimited scans: https://graqle.com/pricing"
        )
        raise typer.Exit(code=1)

    if custom_shacl and not tier_status.custom_shacl_allowed:
        console.print(
            "[bold yellow]Custom SHACL rules require Pro tier.[/bold yellow]\n"
            "Running with default governance rules."
        )
        custom_shacl = ""

    # -- Read diff --
    diff_text = ""
    if diff == "-":
        diff_text = sys.stdin.read()
    elif diff:
        diff_path = Path(diff)
        if diff_path.exists():
            diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
        else:
            console.print(f"[bold red]Diff file not found:[/bold red] {diff}")
            raise typer.Exit(code=1)
    else:
        console.print("[bold red]No diff provided.[/bold red] Use --diff <path> or --diff -")
        raise typer.Exit(code=1)

    # -- Parse diff into entries --
    diff_entries = _parse_diff(diff_text)
    if not diff_entries:
        console.print("[yellow]No file changes found in diff.[/yellow]")
        raise typer.Exit(code=0)

    # -- Load graph if available --
    graph = _load_graph()

    # -- Run engine --
    from graqle.core.governance import GovernanceConfig, GovernanceMiddleware
    from graqle.guardian.engine import PRGuardianEngine

    config = GovernanceConfig()
    middleware = GovernanceMiddleware(config)
    engine = PRGuardianEngine(config=config, middleware=middleware, graph=graph)

    report = engine.evaluate(
        diff_entries,
        actor=actor,
        approved_by=approved_by,
    )

    # -- Record usage --
    record_scan(api_key)

    # -- Output --
    if output_format == "json" or output_format == "github-action":
        result_json = json.dumps(report.to_dict(), indent=2)
        print(result_json)
    else:
        _print_terminal(report)

    # -- Badge --
    if badge_path:
        from graqle.guardian.badge import render_badge

        svg = render_badge(report.verdict.value, report.total_impact_radius)
        badge_p = Path(badge_path)
        badge_p.parent.mkdir(parents=True, exist_ok=True)
        badge_p.write_text(svg, encoding="utf-8")
        console.print(f"[dim]Badge written to {badge_path}[/dim]")

    # -- GitHub PR comment --
    github_token = os.environ.get("GITHUB_TOKEN", "")
    effective_repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    if github_token and effective_repo and pr_number > 0:
        from graqle.guardian.comment import render_comment
        from graqle.guardian.github_client import GitHubClient

        comment_body = render_comment(report, badge_url="")
        client = GitHubClient(token=github_token, repo=effective_repo)
        comment_id = client.upsert_pr_comment(pr_number, comment_body)
        if comment_id:
            console.print(f"[green]PR comment posted/updated (id: {comment_id})[/green]")
        else:
            console.print("[yellow]Failed to post PR comment[/yellow]")

    # -- SARIF output --
    if sarif:
        _write_sarif(report, sarif)

    # -- Exit code --
    if fail_on == "fail" and report.verdict.value == "FAIL":
        raise typer.Exit(code=1)
    elif fail_on == "warn" and report.verdict.value in ("FAIL", "WARN"):
        raise typer.Exit(code=1)


def _parse_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse a unified diff into per-file entries."""
    entries: list[dict[str, str]] = []
    current_file = ""
    current_diff_lines: list[str] = []

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git"):
            # Flush previous
            if current_file:
                entries.append({
                    "file_path": current_file,
                    "diff": "".join(current_diff_lines),
                    "content": "",
                })
            # Parse new file path
            parts = line.split(" b/", 1)
            current_file = parts[1].strip() if len(parts) > 1 else ""
            current_diff_lines = [line]
        else:
            current_diff_lines.append(line)

    # Flush last file
    if current_file:
        entries.append({
            "file_path": current_file,
            "diff": "".join(current_diff_lines),
            "content": "",
        })

    return entries


def _load_graph() -> dict | None:
    """Load graqle.json if it exists in the current directory."""
    graph_path = Path("graqle.json")
    if graph_path.exists():
        try:
            return json.loads(graph_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _print_terminal(report: "GuardianReport") -> None:
    """Pretty-print report to terminal."""
    from graqle.guardian.engine import Verdict

    verdict_colors = {
        Verdict.PASS: "green",
        Verdict.WARN: "yellow",
        Verdict.FAIL: "red",
    }
    color = verdict_colors.get(report.verdict, "white")

    console.print()
    console.print(f"[bold]🛡️ GraQle PR Guardian[/bold]")
    console.print()
    console.print(f"  Verdict:        [{color} bold]{report.verdict.value}[/{color} bold]")
    console.print(f"  Blast Radius:   {report.total_impact_radius} modules")
    console.print(f"  Files Analyzed: {len(report.gate_results)}")
    console.print(f"  Blocked:        {report.breaking_count}")
    console.print(f"  SHACL Issues:   {len(report.shacl_violations)}")
    console.print()

    for reason in report.verdict_reasons:
        console.print(f"  • {reason}")

    if report.blast_radius:
        console.print()
        console.print("  [bold]Blast Radius Breakdown:[/bold]")
        for entry in report.blast_radius:
            icon = {"TS-BLOCK": "🔴", "T3": "🟠", "T2": "🟡", "T1": "🟢"}.get(
                entry.risk_level, "⚪"
            )
            console.print(
                f"    {icon} {entry.module}: "
                f"{entry.files_changed} files, "
                f"radius {entry.impact_radius}, "
                f"{entry.risk_level}"
            )

    console.print()


def _write_sarif(report: "GuardianReport", path: str) -> None:
    """Write a minimal SARIF 2.1.0 output for GitHub Code Scanning."""
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "GraQle PR Guardian",
                        "version": report.version,
                        "informationUri": "https://github.com/quantamixsol/graqle",
                    }
                },
                "results": [
                    {
                        "ruleId": f"guardian/rule-{i:03d}",
                        "level": "error" if gr.blocked else "warning" if gr.tier != "T1" else "note",
                        "message": {
                            "text": (
                                "Governance check: blocked. Manual review required."
                                if gr.blocked
                                else "Governance check: advisory. Review recommended."
                                if gr.tier != "T1"
                                else "Governance check: passed."
                            )
                        },
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": gr.file_path}
                                }
                            }
                        ]
                        if gr.file_path
                        else [],
                    }
                    for i, gr in enumerate(report.gate_results, 1)
                ],
            }
        ],
    }

    sarif_path = Path(path)
    sarif_path.parent.mkdir(parents=True, exist_ok=True)
    sarif_path.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    console.print(f"[dim]SARIF written to {path}[/dim]")
