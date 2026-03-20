"""SCORCH CLI commands — graq scorch run/config/report."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

scorch_app = typer.Typer(
    name="scorch",
    help="SCORCH v3 — AI-powered UX friction auditing (Visual + Behavioral + Journey Psychology).",
    no_args_is_help=True,
)


@scorch_app.command("run")
def scorch_run(
    url: str = typer.Option("http://localhost:3000", "--url", "-u", help="Base URL to audit"),
    pages: list[str] = typer.Option(["/"], "--page", "-p", help="Page paths to audit (repeatable)"),
    config_path: str = typer.Option(None, "--config", "-c", help="Path to SCORCH config JSON"),
    output: str = typer.Option("./scorch-output", "--output", "-o", help="Output directory"),
    skip_behavioral: bool = typer.Option(False, "--skip-behavioral", help="Skip Phase 2.5 behavioral tests"),
    skip_vision: bool = typer.Option(False, "--skip-vision", help="Skip Phase 3 Claude Vision (saves AI cost)"),
    enrich_kg: bool = typer.Option(True, "--enrich-kg/--no-enrich-kg", help="Auto-add findings to knowledge graph"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Knowledge graph file for enrichment"),
) -> None:
    """Run a full SCORCH v3 audit pipeline."""
    try:
        from graqle.plugins.scorch import ScorchEngine, ScorchConfig
    except ImportError:
        console.print(
            "[red]SCORCH plugin not available.[/red]\n"
            "Install with: [cyan]pip install graqle\\[scorch] && python -m playwright install chromium[/cyan]"
        )
        raise typer.Exit(1)

    if config_path:
        config = ScorchConfig.from_json(config_path)
    else:
        config = ScorchConfig(
            base_url=url,
            pages=pages,
            output_dir=output,
            skip_behavioral=skip_behavioral,
            skip_vision=skip_vision,
        )

    console.print(f"\n[bold cyan]SCORCH v3[/bold cyan] — Auditing {config.base_url}")
    console.print(f"  Pages: {', '.join(config.pages)}")
    console.print(f"  Viewports: {', '.join(v.name for v in config.viewports)}")
    console.print(f"  Behavioral: {'skip' if config.skip_behavioral else 'enabled'}")
    console.print(f"  Vision: {'skip' if config.skip_vision else 'enabled'}")
    console.print()

    report = asyncio.run(_run_audit(config))

    # KG enrichment
    if enrich_kg and report.get("issues"):
        gp = Path(graph_path)
        if gp.is_file():
            try:
                from graqle.plugins.scorch.kg_enrichment import enrich_graph
                graph_data = json.loads(gp.read_text(encoding="utf-8"))
                graph_data, added = enrich_graph(graph_data, report)
                if added > 0:
                    gp.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    console.print(f"\n[green]KG enriched with {added} friction findings[/green]")
            except Exception as exc:
                console.print(f"\n[yellow]KG enrichment failed: {exc}[/yellow]")

    # Summary
    _print_summary(report)


async def _run_audit(config):
    from graqle.plugins.scorch import ScorchEngine
    engine = ScorchEngine(config=config)
    return await engine.run()


@scorch_app.command("behavioral")
def scorch_behavioral(
    url: str = typer.Option("http://localhost:3000", "--url", "-u", help="Base URL to test"),
    pages: list[str] = typer.Option(["/"], "--page", "-p", help="Page paths to test (repeatable)"),
    output: str = typer.Option("./scorch-output", "--output", "-o", help="Output directory"),
) -> None:
    """Run only the 12 behavioral UX friction tests (fast, no AI cost)."""
    try:
        from graqle.plugins.scorch import ScorchEngine, ScorchConfig
    except ImportError:
        console.print(
            "[red]SCORCH plugin not available.[/red]\n"
            "Install with: [cyan]pip install graqle\\[scorch][/cyan]"
        )
        raise typer.Exit(1)

    config = ScorchConfig(base_url=url, pages=pages, output_dir=output)
    console.print(f"\n[bold cyan]SCORCH v3[/bold cyan] — Behavioral-only audit of {url}")

    results = asyncio.run(_run_behavioral(config))

    # Write results
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "behavioral.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Print summary
    total_findings = 0
    for entry in results:
        if "findings" in entry:
            for _test_name, findings in entry["findings"].items():
                if isinstance(findings, list):
                    total_findings += len(findings)
                elif isinstance(findings, bool) and findings:
                    total_findings += 1

    console.print(f"\n[bold]Results:[/bold] {total_findings} findings across {len(results)} page/viewport combos")
    console.print(f"[dim]Written to {out_file}[/dim]")


async def _run_behavioral(config):
    from graqle.plugins.scorch import ScorchEngine
    engine = ScorchEngine(config=config)
    return await engine.run_behavioral_only()


# ── Extended SCORCH Skills ──

def _scorch_skill_cmd(skill_name: str, engine_method: str, description: str):
    """Factory for simple SCORCH skill CLI commands."""

    @scorch_app.command(skill_name)
    def cmd(
        url: str = typer.Option("http://localhost:3000", "--url", "-u", help="Base URL to audit"),
        pages: list[str] = typer.Option(["/"], "--page", "-p", help="Page paths to audit (repeatable)"),
        output: str = typer.Option("./scorch-output", "--output", "-o", help="Output directory"),
    ) -> None:
        try:
            from graqle.plugins.scorch import ScorchEngine, ScorchConfig
        except ImportError:
            console.print(
                "[red]SCORCH plugin not available.[/red]\n"
                "Install with: [cyan]pip install graqle\\[scorch][/cyan]"
            )
            raise typer.Exit(1)

        config = ScorchConfig(base_url=url, pages=pages, output_dir=output)
        console.print(f"\n[bold cyan]SCORCH v3[/bold cyan] — {description} of {url}")

        async def _run():
            engine = ScorchEngine(config=config)
            return await getattr(engine, engine_method)()

        results = asyncio.run(_run())

        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{skill_name}.json"
        out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        console.print(f"\n[bold]Results written to {out_file}[/bold]")

    cmd.__doc__ = description
    return cmd


_scorch_skill_cmd("a11y", "run_a11y", "WCAG 2.1 AA/AAA accessibility audit")
_scorch_skill_cmd("perf", "run_perf", "Core Web Vitals performance audit")
_scorch_skill_cmd("seo", "run_seo", "SEO audit (meta tags, structured data, Open Graph)")
_scorch_skill_cmd("mobile", "run_mobile", "Mobile-specific audit (touch targets, viewport, readability)")
_scorch_skill_cmd("i18n", "run_i18n", "Internationalization audit (lang, RTL, date/currency)")
_scorch_skill_cmd("security", "run_security", "Frontend security audit (CSP, exposed keys, XSS)")
_scorch_skill_cmd("conversion", "run_conversion", "Conversion funnel analysis (CTAs, forms, trust signals)")
_scorch_skill_cmd("brand", "run_brand", "Brand consistency audit (colors, typography, spacing)")
_scorch_skill_cmd("auth-flow", "run_auth_flow", "Authenticated user journey audit")


@scorch_app.command("diff")
def scorch_diff(
    previous: str = typer.Option(None, "--previous", help="Path to previous report.json"),
    current: str = typer.Option("./scorch-output/report.json", "--current", help="Path to current report.json"),
) -> None:
    """Compare two SCORCH reports (before/after diff)."""
    try:
        from graqle.plugins.scorch import ScorchEngine, ScorchConfig
    except ImportError:
        console.print("[red]SCORCH plugin not available.[/red]")
        raise typer.Exit(1)

    import os
    config = ScorchConfig(output_dir=os.path.dirname(current) or "./scorch-output")
    console.print("\n[bold cyan]SCORCH v3[/bold cyan] — Before/after comparison")

    async def _run():
        engine = ScorchEngine(config=config)
        return await engine.run_diff(previous_report_path=previous)

    results = asyncio.run(_run())

    # Print summary
    if isinstance(results, dict):
        resolved = results.get("resolved_count", 0)
        new_issues = results.get("new_count", 0)
        improvement = results.get("improvement_pct", 0)

        color = "green" if improvement > 0 else "red" if improvement < 0 else "yellow"
        console.print(f"\n[bold]Resolved:[/bold] [green]{resolved}[/green] issues")
        console.print(f"[bold]New:[/bold] [red]{new_issues}[/red] issues")
        console.print(f"[bold]Improvement:[/bold] [{color}]{improvement:+.1f}%[/{color}]")

    out_file = Path(config.output_dir) / "diff.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    console.print(f"\n[dim]Written to {out_file}[/dim]")


@scorch_app.command("config")
def scorch_config(
    init: bool = typer.Option(False, "--init", help="Create default scorch.json config file"),
    show: bool = typer.Option(False, "--show", help="Show current config"),
    path: str = typer.Option("scorch.json", "--path", help="Config file path"),
) -> None:
    """Manage SCORCH configuration."""
    from graqle.plugins.scorch.config import ScorchConfig

    if init:
        if Path(path).exists():
            console.print(f"[yellow]Config already exists: {path}[/yellow]")
            raise typer.Exit(1)
        config = ScorchConfig()
        config.to_json(path)
        console.print(f"[green]Created default SCORCH config: {path}[/green]")
    elif show:
        if not Path(path).exists():
            console.print(f"[yellow]No config found at {path}. Run: graq scorch config --init[/yellow]")
            raise typer.Exit(1)
        config = ScorchConfig.from_json(path)
        console.print_json(json.dumps(config.model_dump(), indent=2))
    else:
        console.print("Use --init to create config or --show to display it.")


@scorch_app.command("report")
def scorch_report(
    path: str = typer.Option("./scorch-output/report.json", "--path", help="Path to report.json"),
) -> None:
    """View a SCORCH audit report summary."""
    report_path = Path(path)
    if not report_path.exists():
        console.print(f"[red]No report found at {path}[/red]")
        console.print("Run [cyan]graq scorch run[/cyan] first.")
        raise typer.Exit(1)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    _print_summary(report)


def _print_summary(report: dict) -> None:
    """Pretty-print a SCORCH report summary."""
    passed = report.get("pass", False)
    journey_passed = report.get("journeyPass", False)

    status = "[bold green]PASS[/bold green]" if passed else "[bold red]FAIL[/bold red]"
    journey_status = "[green]PASS[/green]" if journey_passed else "[yellow]ADVISORY[/yellow]"

    console.print(f"\n{'='*50}")
    console.print(f"[bold]SCORCH v3 Audit Result:[/bold] {status} | Journey: {journey_status}")
    console.print(f"{'='*50}")

    # Severity table
    severity = report.get("severityCounts", {})
    if any(v > 0 for v in severity.values()):
        table = Table(title="Issues by Severity")
        table.add_column("Severity", style="bold")
        table.add_column("Count", justify="right")
        for sev, count in severity.items():
            style = {"critical": "red", "major": "yellow", "minor": "cyan", "cosmetic": "dim"}.get(sev, "")
            table.add_row(sev, str(count), style=style)
        console.print(table)

    # Journey score
    journey = report.get("journeyAnalysis", {})
    if journey.get("journeyScore"):
        console.print(f"\n[bold]Journey Score:[/bold] {journey['journeyScore']}/10")

    # Summary
    if report.get("summary"):
        console.print(f"\n[bold]Summary:[/bold] {report['summary']}")

    console.print()
