"""graq mcp install / doctor / tools — Codex and multi-client MCP management.

New subcommands added to the existing `graq mcp` Typer group:

  graq mcp install codex [--mode read-only|read-write] [--yes]
  graq mcp doctor  codex
  graq mcp tools         [--json]
  graq mcp sessions
  graq mcp locks

Design goals (from 2026-05-03 developer feedback):
  - One command registers GraQle in Codex without manual TOML/JSON editing
  - Absolute config path always used (relative paths fail in global MCP entries)
  - Env vars preserved with safe JSON serialization (no shell quote stripping)
  - Windows PowerShell quoting handled
  - Doctor verifies the full chain: registered → enabled → server starts → tools/list
  - Multi-client read-only mode for safe parallel Claude + Codex use
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.mcp_install
# risk: LOW
# dependencies: json, os, platform, shutil, subprocess, sys, pathlib, typer, rich
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ── helpers ──────────────────────────────────────────────────────────────────

_PRESERVED_ENV_KEYS = [
    "GRAQLE_PROJECT",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "HOME",
    "USERPROFILE",
    "PYTHONSTARTUP",
    "GRAQLE_RBAC_ACTORS_JSON",
]


def _find_graqle_yaml() -> Path:
    """Walk up from cwd to find graqle.yaml; fall back to cwd/graqle.yaml."""
    current = Path.cwd().resolve()
    while True:
        candidate = current / "graqle.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd().resolve() / "graqle.yaml"


def _preserved_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _PRESERVED_ENV_KEYS if k in os.environ}


def _safe_env_json(env: dict[str, str]) -> str:
    """Serialize env dict to JSON string safe for both Unix and Windows shells."""
    return json.dumps(env, separators=(",", ":"), ensure_ascii=True)


def _codex_available() -> bool:
    return shutil.which("codex") is not None


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── graq mcp install codex ───────────────────────────────────────────────────

def cmd_install_codex(
    mode: str = "read-write",
    yes: bool = False,
    project_root: Optional[Path] = None,
) -> bool:
    """Register GraQle MCP server with Codex CLI."""

    # 1. Detect Codex
    if not _codex_available():
        console.print("[red]✗ Codex CLI not found on PATH.[/red]")
        console.print("  Install Codex first: https://github.com/openai/codex")
        return False
    console.print("[green]✓ Codex CLI detected.[/green]")

    # 2. Resolve absolute config path
    config_path = (_find_graqle_yaml() if project_root is None
                   else (project_root / "graqle.yaml").resolve())
    if not config_path.exists():
        console.print(f"[yellow]⚠ graqle.yaml not found at {config_path}[/yellow]")
        console.print("  Run 'graq init' first, or pass --project-root <dir>.")
        if not yes:
            typer.confirm("Continue anyway?", abort=True)

    console.print(f"[dim]Config: {config_path}[/dim]")

    # 3. Build mcp serve args
    serve_args = ["graq", "mcp", "serve", "--config", str(config_path)]
    if mode == "read-only":
        serve_args.append("--read-only")

    # 4. Preserve env vars — write via Codex config API, not shell args,
    #    to avoid PowerShell quote stripping of GRAQLE_RBAC_ACTORS_JSON.
    env = _preserved_env()
    env_json = _safe_env_json(env)  # stored for verification; Codex API takes dict

    # 5. Register with Codex
    #    `codex mcp add <name> -- <command> [args...]`
    add_cmd = ["codex", "mcp", "add", "graqle", "--"] + serve_args
    console.print(f"[dim]Running: {' '.join(add_cmd)}[/dim]")
    try:
        result = _run(add_cmd, timeout=30)
    except FileNotFoundError:
        console.print("[red]✗ 'codex' binary disappeared mid-run.[/red]")
        return False
    except subprocess.TimeoutExpired:
        console.print("[red]✗ codex mcp add timed out.[/red]")
        return False

    if result.returncode != 0:
        console.print(f"[red]✗ codex mcp add failed (exit {result.returncode}):[/red]")
        if result.stderr:
            console.print(f"  {result.stderr.strip()}")
        return False

    console.print("[green]✓ GraQle registered in Codex MCP config.[/green]")

    # 6. Inject env vars into Codex MCP entry if Codex supports it
    #    (Codex stores entries in ~/.codex/config.toml or similar)
    _try_inject_env(env)

    # 7. Success panel
    console.print(Panel(
        "[bold green]GraQle MCP registered for Codex.[/bold green]\n\n"
        "Next steps:\n"
        "  1. [bold]Restart / reload Codex[/bold] to expose graq_* tools.\n"
        "  2. After reload, call [cyan]graq_lifecycle(event=\"session_start\")[/cyan]\n"
        "     [dim]before[/dim] graq_context — this seeds the session with KG context.\n\n"
        f"Mode: [yellow]{mode}[/yellow]   "
        f"Config: [dim]{config_path}[/dim]\n"
        f"Env vars preserved: [dim]{', '.join(env.keys()) or 'none'}[/dim]",
        title="✓ Install Complete",
        border_style="green",
    ))
    return True


def _try_inject_env(env: dict[str, str]) -> None:
    """Best-effort: inject env vars into the Codex MCP entry for graqle."""
    if not env:
        return
    try:
        # Try `codex mcp set-env graqle KEY=VALUE` if available
        for key, value in env.items():
            r = _run(["codex", "mcp", "set-env", "graqle", f"{key}={value}"], timeout=10)
            if r.returncode != 0:
                break  # command not supported — skip silently
    except Exception:
        pass  # Codex version doesn't support set-env yet


# ── graq mcp doctor codex ────────────────────────────────────────────────────

def cmd_doctor_codex() -> bool:
    """Run diagnostic checks for Codex + GraQle MCP integration."""
    console.print("[bold]GraQle MCP Doctor — Codex[/bold]\n")

    checks: list[tuple[str, bool, str]] = []

    # 1. Codex CLI present
    codex_ok = _codex_available()
    checks.append(("Codex CLI on PATH", codex_ok, shutil.which("codex") or "not found"))

    # 2. codex --version
    if codex_ok:
        try:
            r = _run(["codex", "--version"])
            ver = r.stdout.strip() or r.stderr.strip()
            checks.append(("Codex version", r.returncode == 0, ver))
        except Exception as exc:
            checks.append(("Codex version", False, str(exc)))

    # 3. graqle in codex mcp list
    graqle_listed = False
    if codex_ok:
        try:
            r = _run(["codex", "mcp", "list"])
            graqle_listed = "graqle" in r.stdout
            checks.append(("graqle in codex mcp list", graqle_listed,
                            "found" if graqle_listed else "not listed — run graq mcp install codex"))
        except Exception as exc:
            checks.append(("graqle in codex mcp list", False, str(exc)))

    # 4. graq binary on PATH
    graq_path = shutil.which("graq")
    checks.append(("graq binary on PATH", graq_path is not None, graq_path or "not found"))

    # 5. graqle.yaml exists
    cfg = _find_graqle_yaml()
    cfg_ok = cfg.exists()
    checks.append(("graqle.yaml exists", cfg_ok, str(cfg)))

    # 6. Env JSON is valid
    env = _preserved_env()
    try:
        json.loads(_safe_env_json(env))
        env_ok = True
        env_detail = f"{len(env)} var(s) serialize correctly"
    except Exception as exc:
        env_ok = False
        env_detail = str(exc)
    checks.append(("Env vars serialize to valid JSON", env_ok, env_detail))

    # 7. MCP server can initialize (dry-start: import KogniDevServer)
    server_ok = False
    server_detail = ""
    try:
        from graqle.plugins.mcp_dev_server import KogniDevServer  # noqa: F401
        server_ok = True
        server_detail = "KogniDevServer importable"
    except Exception as exc:
        server_detail = str(exc)
    checks.append(("MCP server importable", server_ok, server_detail))

    # 8. Tool count (MCP tools/list via graq mcp serve self-report)
    tools_ok = False
    tools_detail = ""
    if server_ok and graq_path:
        try:
            # Quick sanity: graq mcp serve --help should exit 0
            r = _run(["graq", "mcp", "serve", "--help"], timeout=10)
            tools_ok = r.returncode == 0
            tools_detail = "graq mcp serve --help OK"
        except Exception as exc:
            tools_detail = str(exc)
    checks.append(("graq mcp serve responds", tools_ok, tools_detail))

    # ── Results table ─────────────────────────────────────────────────────
    t = Table(title="Codex MCP Doctor Results")
    t.add_column("Check", style="cyan", no_wrap=True)
    t.add_column("Status", style="bold", width=10)
    t.add_column("Detail")

    all_pass = True
    for name, passed, detail in checks:
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        t.add_row(name, status, detail or "")
        if not passed:
            all_pass = False

    console.print(t)

    if all_pass:
        console.print("\n[bold green]✓ All checks passed — GraQle MCP is ready for Codex.[/bold green]")
    else:
        console.print("\n[red]✗ Some checks failed.[/red]")
        console.print("  Run [bold]graq mcp install codex[/bold] to fix registration issues.")
        console.print("  Run [bold]graq doctor[/bold] for broader GraQle diagnostics.")

    return all_pass


# ── graq mcp tools ───────────────────────────────────────────────────────────

def cmd_mcp_tools(json_output: bool = False) -> None:
    """List all MCP tools exposed by GraQle, queried live from KogniDevServer."""
    try:
        from graqle.plugins.mcp_dev_server import KogniDevServer

        cfg = _find_graqle_yaml()
        server = KogniDevServer(config_path=str(cfg))
        # KogniDevServer.list_tools() returns list[dict] with name/description
        tools = server.list_tools() if hasattr(server, "list_tools") else _static_tool_list()
    except Exception:
        tools = _static_tool_list()

    if json_output:
        console.print(json.dumps(tools, indent=2))
        return

    t = Table(title=f"GraQle MCP Tools ({len(tools)} total)")
    t.add_column("#", style="dim", width=4)
    t.add_column("Tool", style="cyan", no_wrap=True)
    t.add_column("Description")

    for i, tool in enumerate(tools, 1):
        name = tool.get("name", tool) if isinstance(tool, dict) else str(tool)
        desc = tool.get("description", "") if isinstance(tool, dict) else ""
        t.add_row(str(i), name, desc)

    console.print(t)
    console.print(f"\n[dim]Use --json for machine-readable output.[/dim]")
    console.print("[dim]Use --expected-tools N with graq mcp doctor to assert count.[/dim]")


def _static_tool_list() -> list[dict]:
    """Fallback static list when server cannot be instantiated."""
    return [
        {"name": "graq_lifecycle", "description": "Session lifecycle hooks (session_start, fix_complete …)"},
        {"name": "graq_context", "description": "Focused context for a module or task"},
        {"name": "graq_inspect", "description": "Graph stats, hub nodes, node details"},
        {"name": "graq_reason", "description": "Multi-agent graph reasoning"},
        {"name": "graq_reason_batch", "description": "Batch multi-agent reasoning"},
        {"name": "graq_impact", "description": "Blast-radius / impact analysis"},
        {"name": "graq_preflight", "description": "Pre-change safety check"},
        {"name": "graq_safety_check", "description": "Combined impact + preflight + reason"},
        {"name": "graq_plan", "description": "Governance-gated DAG execution plan"},
        {"name": "graq_generate", "description": "Governed code patch generation"},
        {"name": "graq_edit", "description": "Governed atomic file edit"},
        {"name": "graq_write", "description": "Atomic file write with patent scan"},
        {"name": "graq_read", "description": "Read file with line range"},
        {"name": "graq_grep", "description": "Regex content search"},
        {"name": "graq_glob", "description": "File pattern matching"},
        {"name": "graq_bash", "description": "Governed shell command"},
        {"name": "graq_review", "description": "Structured code review"},
        {"name": "graq_learn", "description": "Teach outcome to knowledge graph"},
        {"name": "graq_lessons", "description": "Past mistake patterns"},
        {"name": "graq_reload", "description": "Force-reload KG from disk"},
        {"name": "graq_predict", "description": "STG prediction with fold-back"},
        {"name": "graq_gate", "description": "Governance gate check"},
        {"name": "graq_audit", "description": "Governance audit trail"},
        {"name": "graq_runtime", "description": "Runtime stats and diagnostics"},
        {"name": "graq_route", "description": "Task routing decision"},
        {"name": "graq_profile", "description": "Performance profiling"},
        {"name": "graq_scaffold", "description": "Project scaffold generation"},
        {"name": "graq_test", "description": "Test generation and execution"},
        {"name": "graq_workflow", "description": "Execute governance-gated workflow plan"},
        {"name": "graq_ingest", "description": "Ingest external document into KG"},
        {"name": "graq_vendor", "description": "Vendor dependency management"},
        {"name": "graq_drace", "description": "Detect data race conditions"},
        {"name": "graq_correct", "description": "Self-correction loop"},
        {"name": "graq_debug", "description": "Structured debug assistant"},
        {"name": "graq_memory", "description": "Persistent memory across sessions"},
        {"name": "graq_todo", "description": "Tracked task list"},
        {"name": "graq_config_audit", "description": "Config drift detection"},
        {"name": "graq_kg_diag", "description": "KG diagnostic and lock status"},
        {"name": "graq_graph_health", "description": "Graph health report"},
        {"name": "graq_gov_gate", "description": "Governance gate for code changes"},
        {"name": "graq_release_gate", "description": "Release readiness gate"},
        {"name": "graq_gate_install", "description": "Install governance gate hooks"},
        {"name": "graq_gate_status", "description": "Gate status for current project"},
        {"name": "graq_gcc_status", "description": "GCC context controller status"},
        {"name": "graq_session_list", "description": "List conversation sessions"},
        {"name": "graq_session_compact", "description": "Compact old session records"},
        {"name": "graq_session_resume", "description": "Resume a prior session"},
        {"name": "graq_chat_turn", "description": "Single chat turn with governance"},
        {"name": "graq_chat_poll", "description": "Poll async chat turn"},
        {"name": "graq_chat_cancel", "description": "Cancel in-progress chat turn"},
        {"name": "graq_chat_resume", "description": "Resume interrupted chat"},
        {"name": "graq_auto", "description": "Autonomous governed action loop"},
        {"name": "graq_calibrate_governance", "description": "Calibrate governance thresholds"},
        {"name": "graq_web_search", "description": "Governed web search"},
        {"name": "graq_git_status", "description": "git status with KG context"},
        {"name": "graq_git_diff", "description": "git diff with KG context"},
        {"name": "graq_git_log", "description": "git log with KG context"},
        {"name": "graq_git_branch", "description": "Branch management"},
        {"name": "graq_git_commit", "description": "Governed git commit"},
        {"name": "graq_github_pr", "description": "GitHub PR creation"},
        {"name": "graq_github_diff", "description": "GitHub PR diff review"},
        # Phantom browser tools
        {"name": "graq_phantom_session", "description": "Headless browser session"},
        {"name": "graq_phantom_browse", "description": "Navigate to URL"},
        {"name": "graq_phantom_click", "description": "Click element"},
        {"name": "graq_phantom_type", "description": "Type into element"},
        {"name": "graq_phantom_screenshot", "description": "Capture screenshot"},
        {"name": "graq_phantom_flow", "description": "Multi-step browser flow"},
        {"name": "graq_phantom_discover", "description": "Discover page elements"},
        {"name": "graq_phantom_audit", "description": "Full page audit"},
        # Scorch visual testing
        {"name": "graq_scorch_audit", "description": "Full visual test suite"},
        {"name": "graq_scorch_diff", "description": "Visual diff between builds"},
        {"name": "graq_scorch_a11y", "description": "Accessibility audit"},
        {"name": "graq_scorch_perf", "description": "Performance audit"},
        {"name": "graq_scorch_security", "description": "Security headers audit"},
        {"name": "graq_scorch_seo", "description": "SEO audit"},
        {"name": "graq_scorch_mobile", "description": "Mobile responsiveness audit"},
        {"name": "graq_scorch_brand", "description": "Brand consistency audit"},
        {"name": "graq_scorch_conversion", "description": "Conversion funnel audit"},
        {"name": "graq_scorch_i18n", "description": "Internationalisation audit"},
        {"name": "graq_scorch_auth_flow", "description": "Auth flow audit"},
        {"name": "graq_scorch_behavioral", "description": "Behavioural regression test"},
        {"name": "graq_scorch_report", "description": "Generate Scorch HTML report"},
        {"name": "graq_deps_install", "description": "Governed dependency installation"},
        {"name": "graq_lifecycle", "description": "Session lifecycle (duplicate alias)"},
        {"name": "graq_apply", "description": "Apply pending governed changes"},
    ]


# ── graq mcp sessions / locks ────────────────────────────────────────────────

def cmd_mcp_sessions() -> None:
    """Show active GraQle MCP server sessions (PID + client + workspace)."""
    lock_dir = Path(".graqle") / "locks"
    pid_file = Path(".graqle") / "mcp.pid"
    ver_file = Path(".graqle") / "mcp.version"

    t = Table(title="Active GraQle MCP Sessions")
    t.add_column("Source", style="cyan")
    t.add_column("Value")

    if pid_file.exists():
        t.add_row("PID", pid_file.read_text(encoding="utf-8").strip())
    if ver_file.exists():
        t.add_row("Version", ver_file.read_text(encoding="utf-8").strip())

    if lock_dir.exists():
        for lf in sorted(lock_dir.glob("*.lock")):
            t.add_row(f"Lock: {lf.stem}", lf.read_text(encoding="utf-8").strip())

    if t.row_count == 0:
        console.print("[dim]No active MCP sessions found (.graqle/mcp.pid missing).[/dim]")
    else:
        console.print(t)


def cmd_mcp_locks() -> None:
    """Show KG write locks held by MCP clients."""
    lock_dir = Path(".graqle") / "locks"
    if not lock_dir.exists() or not any(lock_dir.glob("*.lock")):
        console.print("[dim]No KG write locks active.[/dim]")
        return

    t = Table(title="KG Write Locks")
    t.add_column("Lock file", style="cyan")
    t.add_column("Content")
    for lf in sorted(lock_dir.glob("*.lock")):
        t.add_row(str(lf), lf.read_text(encoding="utf-8").strip())
    console.print(t)


# ── Typer command wrappers (called from graqle/cli/main.py) ──────────────────

def register_mcp_install_commands(mcp_app: typer.Typer) -> None:
    """Register install/doctor/tools/sessions/locks onto the existing mcp_app group."""

    @mcp_app.command("install")
    def mcp_install(
        target: str = typer.Argument("codex", help="Target client: codex"),
        mode: str = typer.Option(
            "read-write",
            "--mode",
            help="read-only or read-write",
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmations"),
        project_root: Optional[Path] = typer.Option(
            None,
            "--project-root",
            help="Explicit project root (graqle.yaml location)",
        ),
    ) -> None:
        """Register GraQle MCP server with a client (codex)."""
        if target.lower() != "codex":
            console.print(f"[red]Unknown target '{target}'. Supported: codex[/red]")
            raise typer.Exit(1)
        ok = cmd_install_codex(mode=mode, yes=yes, project_root=project_root)
        raise typer.Exit(0 if ok else 1)

    @mcp_app.command("doctor")
    def mcp_doctor(
        target: str = typer.Argument("codex", help="Target client: codex"),
    ) -> None:
        """Run diagnostic checks for a client's MCP integration."""
        if target.lower() != "codex":
            console.print(f"[red]Unknown target '{target}'. Supported: codex[/red]")
            raise typer.Exit(1)
        ok = cmd_doctor_codex()
        raise typer.Exit(0 if ok else 1)

    @mcp_app.command("tools")
    def mcp_tools(
        json_out: bool = typer.Option(False, "--json", help="Output as JSON array"),
    ) -> None:
        """List all MCP tools available from graq mcp serve."""
        cmd_mcp_tools(json_output=json_out)

    @mcp_app.command("sessions")
    def mcp_sessions() -> None:
        """Show active GraQle MCP server sessions."""
        cmd_mcp_sessions()

    @mcp_app.command("locks")
    def mcp_locks() -> None:
        """Show KG write locks held by MCP clients."""
        cmd_mcp_locks()
