"""kogni doctor — comprehensive health check for CogniGraph installation.

Validates everything a user needs for good reasoning results:
1. Python version & core dependencies
2. Backend packages (anthropic, openai, boto3, ollama)
3. API keys & environment variables
4. Embedding models (Titan V2, sentence-transformers)
5. Graph file & quality
6. Config file validity
7. MCP server registration
8. Skill system readiness

Designed to be the FIRST command a user runs after install.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import List, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Check result types
PASS = "pass"
WARN = "warn"
FAIL = "fail"
INFO = "info"

CheckResult = Tuple[str, str, str]  # (status, label, detail)


def _check_python_version() -> CheckResult:
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if v.major == 3 and v.minor >= 10:
        return (PASS, "Python version", ver_str)
    elif v.major == 3 and v.minor >= 8:
        return (WARN, "Python version", f"{ver_str} (3.10+ recommended)")
    return (FAIL, "Python version", f"{ver_str} (requires 3.8+)")


def _check_core_deps() -> List[CheckResult]:
    results = []
    core = ["networkx", "numpy", "pydantic", "pyyaml", "typer", "rich"]
    for pkg in core:
        mod_name = pkg.replace("-", "_").replace("pyyaml", "yaml")
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "installed")
            results.append((PASS, f"Core: {pkg}", ver))
        except ImportError:
            results.append((FAIL, f"Core: {pkg}", "NOT INSTALLED"))
    return results


def _check_backend_packages() -> List[CheckResult]:
    """Check which backend packages are available."""
    results = []
    backends = {
        "anthropic": ("anthropic", "ANTHROPIC_API_KEY", "Claude (Anthropic)"),
        "openai": ("openai", "OPENAI_API_KEY", "GPT (OpenAI)"),
        "boto3": ("boto3", None, "Bedrock (AWS)"),  # checked via boto3 credentials
        "httpx": ("httpx", None, "Ollama (local)"),
    }
    any_backend = False
    for pkg, (mod_name, env_var, label) in backends.items():
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "installed")
            has_key = True
            key_status = ""
            if env_var:
                has_key = bool(os.environ.get(env_var))
                key_status = f" | {env_var}: {'set' if has_key else 'NOT SET'}"
            elif mod_name == "boto3":
                # Check boto3 credentials (env vars, ~/.aws/credentials, SSO, etc.)
                try:
                    import boto3
                    session = boto3.Session()
                    creds = session.get_credentials()
                    if creds is not None:
                        has_key = True
                        key_status = " | AWS credentials: found"
                    else:
                        has_key = False
                        key_status = " | AWS credentials: NOT FOUND"
                except Exception:
                    has_key = False
                    key_status = " | AWS credentials: check failed"
            if has_key:
                results.append((PASS, f"Backend: {label}", f"{ver}{key_status}"))
                any_backend = True
            else:
                results.append((WARN, f"Backend: {label}", f"{ver}{key_status}"))
        except ImportError:
            results.append((INFO, f"Backend: {label}", f"{pkg} not installed"))

    if not any_backend:
        results.append((
            FAIL,
            "No working backend",
            "Install one: pip install cognigraph[api]  OR  pip install ollama httpx",
        ))
    return results


def _check_api_keys() -> List[CheckResult]:
    """Check API key availability and basic validity."""
    results = []
    keys = {
        "ANTHROPIC_API_KEY": ("sk-ant-", "Anthropic"),
        "OPENAI_API_KEY": ("sk-", "OpenAI"),
        "AWS_ACCESS_KEY_ID": ("AKIA", "AWS Bedrock"),
    }
    for var, (prefix, label) in keys.items():
        val = os.environ.get(var, "")
        if val:
            # Basic format check (don't log the key!)
            masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
            if prefix and not val.startswith(prefix):
                results.append((WARN, f"Key: {var}", f"{masked} (unexpected format)"))
            else:
                results.append((PASS, f"Key: {var}", masked))
        else:
            results.append((INFO, f"Key: {var}", "not set"))
    return results


def _check_embedding_models() -> List[CheckResult]:
    """Check embedding model availability for skill assignment."""
    results = []

    # Check Titan V2 (best quality)
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name="eu-central-1")
        # Don't actually call — just check credentials
        sts = boto3.client("sts")
        sts.get_caller_identity()
        results.append((PASS, "Embeddings: Titan V2", "AWS credentials valid (best quality, 1024-dim)"))
    except Exception as e:
        err = str(e)[:60]
        results.append((INFO, "Embeddings: Titan V2", f"not available ({err})"))

    # Check sentence-transformers (good fallback)
    try:
        import sentence_transformers
        ver = getattr(sentence_transformers, "__version__", "installed")
        results.append((PASS, "Embeddings: sentence-transformers", f"{ver} (384-dim, local)"))
    except ImportError:
        results.append((WARN, "Embeddings: sentence-transformers",
                        "NOT INSTALLED — pip install sentence-transformers"))

    # Summary
    has_titan = any(r[0] == PASS and "Titan" in r[1] for r in results)
    has_st = any(r[0] == PASS and "sentence" in r[1] for r in results)
    if has_titan:
        results.append((PASS, "Skill matching mode", "hybrid (regex + Titan V2 semantic)"))
    elif has_st:
        results.append((PASS, "Skill matching mode", "hybrid (regex + sentence-transformers semantic)"))
    else:
        results.append((WARN, "Skill matching mode", "regex-only (install sentence-transformers for better skills)"))

    return results


def _check_config_file() -> List[CheckResult]:
    """Check cognigraph.yaml validity."""
    results = []
    config_path = Path("cognigraph.yaml")

    if not config_path.exists():
        results.append((WARN, "Config: cognigraph.yaml", "not found — run 'kogni init'"))
        return results

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            results.append((FAIL, "Config: cognigraph.yaml", "empty file"))
            return results

        results.append((PASS, "Config: cognigraph.yaml", "valid YAML"))

        # Check for unresolved env var references
        model_cfg = data.get("model", {})
        api_key = model_cfg.get("api_key", "")
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            if os.environ.get(env_var):
                results.append((PASS, f"Config: api_key ref", f"${{{env_var}}} -> set"))
            else:
                results.append((FAIL, f"Config: api_key ref",
                                f"${{{env_var}}} -> NOT SET! Reasoning will fail"))

        backend = model_cfg.get("backend", "mock")
        model = model_cfg.get("model", "unknown")
        results.append((INFO, "Config: backend", f"{backend} / {model}"))

    except Exception as e:
        results.append((FAIL, "Config: cognigraph.yaml", f"parse error: {e}"))

    return results


def _check_graph_file() -> List[CheckResult]:
    """Check knowledge graph file existence and quality."""
    results = []

    candidates = ["cognigraph.json", "knowledge_graph.json", "graph.json"]
    found = None
    for c in candidates:
        if Path(c).exists():
            found = c
            break

    if not found:
        results.append((WARN, "Graph file", "not found — run 'kogni init' or 'kogni scan'"))
        return results

    try:
        import json
        size = Path(found).stat().st_size
        with open(found, "r", encoding="utf-8") as f:
            data = json.load(f)

        nodes = data.get("nodes", [])
        edges = data.get("links", data.get("edges", []))

        results.append((PASS, "Graph file", f"{found} ({size:,} bytes)"))
        results.append((INFO, "Graph: nodes", str(len(nodes))))
        results.append((INFO, "Graph: edges", str(len(edges))))

        if len(nodes) == 0:
            results.append((FAIL, "Graph: quality", "0 nodes — graph is empty"))
        else:
            # Check description coverage
            with_desc = sum(1 for n in nodes if n.get("description", "").strip())
            pct = with_desc / len(nodes) * 100
            if pct >= 80:
                results.append((PASS, "Graph: descriptions", f"{pct:.0f}% nodes have descriptions"))
            elif pct >= 50:
                results.append((WARN, "Graph: descriptions", f"{pct:.0f}% — run 'kogni validate --fix'"))
            else:
                results.append((FAIL, "Graph: descriptions", f"Only {pct:.0f}% — reasoning quality will be poor"))

    except Exception as e:
        results.append((FAIL, "Graph file", f"{found} — parse error: {e}"))

    return results


def _check_mcp_registration() -> List[CheckResult]:
    """Check if MCP server is registered for any supported IDE.

    Bug 17 fix: checks all IDE-specific MCP config paths, not just .mcp.json.
    """
    import json as _json

    results = []

    # All known MCP config paths (IDE → path)
    mcp_paths = {
        "Claude Code": Path(".mcp.json"),
        "Cursor": Path(".cursor") / "mcp.json",
        "VS Code": Path(".vscode") / "mcp.json",
    }

    found_any = False
    for ide_name, mcp_path in mcp_paths.items():
        if not mcp_path.exists():
            continue

        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            servers = data.get("mcpServers", {})
            # Check both "kogni" and "cognigraph" server names (Bug 17)
            mcp_key = None
            for key in ("kogni", "cognigraph"):
                if key in servers:
                    mcp_key = key
                    break

            if mcp_key is not None:
                cmd = servers[mcp_key].get("command", "?")
                args = servers[mcp_key].get("args", [])
                results.append((
                    PASS,
                    f"MCP: {ide_name}",
                    f"{cmd} {' '.join(args)} ({mcp_path})",
                ))
                found_any = True
            else:
                results.append((
                    WARN,
                    f"MCP: {ide_name}",
                    f"{mcp_path} exists but 'kogni'/'cognigraph' server not registered",
                ))
        except Exception as e:
            results.append((FAIL, f"MCP: {ide_name}", f"{mcp_path} parse error: {e}"))

    if not found_any:
        results.append((
            WARN,
            "MCP: registration",
            "not found in any IDE config — run 'kogni init' to configure",
        ))

    return results


def _check_skill_system() -> List[CheckResult]:
    """Check skill admin readiness."""
    results = []
    try:
        from cognigraph.ontology.skill_admin import SkillAdmin, SKILL_LIBRARY
        results.append((PASS, "Skills: library", f"{len(SKILL_LIBRARY)} skills across 9 domains"))

        # Test that SkillAdmin can be instantiated
        admin = SkillAdmin(use_titan=False)
        results.append((PASS, "Skills: admin mode", admin.mode))

    except Exception as e:
        results.append((FAIL, "Skills: import error", str(e)[:80]))

    return results


def doctor_command(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all checks including passed"),
    fix: bool = typer.Option(False, "--fix", help="Show fix commands for failures"),
) -> None:
    """Health check for your CogniGraph installation.

    Validates dependencies, API keys, config, graph, embeddings,
    skills, and MCP server registration. Run this after install.

    \b
    Examples:
        kogni doctor
        kogni doctor --fix     (show fix commands)
        kogni doctor --verbose (show all checks)
    """
    from cognigraph.__version__ import __version__

    console.print(Panel.fit(
        f"[bold cyan]CogniGraph Doctor[/bold cyan] v{__version__}\n"
        f"Checking your installation...",
        border_style="cyan",
    ))

    all_results: List[CheckResult] = []

    # Run all checks
    all_results.append(_check_python_version())
    all_results.extend(_check_core_deps())
    all_results.extend(_check_backend_packages())
    all_results.extend(_check_api_keys())
    all_results.extend(_check_embedding_models())
    all_results.extend(_check_config_file())
    all_results.extend(_check_graph_file())
    all_results.extend(_check_mcp_registration())
    all_results.extend(_check_skill_system())

    # Count results
    passes = sum(1 for r in all_results if r[0] == PASS)
    warns = sum(1 for r in all_results if r[0] == WARN)
    fails = sum(1 for r in all_results if r[0] == FAIL)
    infos = sum(1 for r in all_results if r[0] == INFO)

    # Build table
    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=4)
    table.add_column("Check", min_width=30)
    table.add_column("Detail")

    icons = {PASS: "[green]OK[/green]", WARN: "[yellow]!![/yellow]",
             FAIL: "[red]FAIL[/red]", INFO: "[dim]--[/dim]"}

    for status, label, detail in all_results:
        if not verbose and status in (PASS, INFO):
            continue
        table.add_row(icons[status], label, detail)

    # If verbose, show all
    if verbose:
        for status, label, detail in all_results:
            pass  # Already added above
    else:
        # Show passes count
        if passes > 0:
            table.add_row(
                icons[PASS],
                f"[dim]{passes} checks passed[/dim]",
                "[dim]use --verbose to see all[/dim]",
            )

    console.print(table)

    # Summary
    console.print()
    if fails == 0 and warns == 0:
        console.print("[bold green]All checks passed! CogniGraph is ready.[/bold green]")
    elif fails == 0:
        console.print(f"[bold yellow]{warns} warning(s) — CogniGraph will work but with reduced quality.[/bold yellow]")
    else:
        console.print(f"[bold red]{fails} failure(s), {warns} warning(s) — fix failures before using CogniGraph.[/bold red]")

    # Fix suggestions
    if fix and (fails > 0 or warns > 0):
        console.print()
        console.print(Panel.fit(
            "[bold]Suggested fixes:[/bold]",
            border_style="yellow",
        ))

        for status, label, detail in all_results:
            if status not in (FAIL, WARN):
                continue

            if "not installed" in detail.lower() or "NOT INSTALLED" in detail:
                pkg = label.split(":")[-1].strip().lower()
                if "anthropic" in label.lower() or "openai" in label.lower():
                    console.print(f"  pip install cognigraph[api]")
                elif "sentence" in label.lower():
                    console.print(f"  pip install sentence-transformers")
                elif "titan" in label.lower():
                    console.print(f"  pip install boto3  # + configure AWS credentials")
                else:
                    console.print(f"  pip install {pkg}")

            elif "NOT SET" in detail:
                env_var = label.split(":")[-1].strip()
                if "ANTHROPIC" in detail or "ANTHROPIC" in label:
                    console.print(f"  export ANTHROPIC_API_KEY=sk-ant-your-key-here")
                elif "OPENAI" in detail or "OPENAI" in label:
                    console.print(f"  export OPENAI_API_KEY=sk-your-key-here")
                elif "AWS" in detail or "AWS" in label:
                    console.print(f"  aws configure  # or export AWS_ACCESS_KEY_ID=...")

            elif "not found" in detail.lower() and "kogni init" in detail:
                console.print(f"  kogni init")

            elif "empty" in detail.lower() and "graph" in label.lower():
                console.print(f"  kogni scan --repo .")

            elif "regex-only" in detail.lower():
                console.print(f"  pip install sentence-transformers  # enables hybrid skill matching")

            elif ".mcp.json" in label and "not" in detail.lower():
                console.print(f"  kogni init  # auto-registers MCP server")

    # Readiness score
    total = passes + warns + fails
    score = int((passes / total * 100)) if total > 0 else 0
    color = "green" if score >= 80 else "yellow" if score >= 50 else "red"
    console.print(f"\n[{color}]Readiness: {score}%[/{color}] ({passes}/{total} checks passed)")

    # Always show setup-guide hint if no backend is working
    has_working_backend = any(
        r[0] == PASS and "Backend:" in r[1] and ("Anthropic" in r[1] or "OpenAI" in r[1]
            or "Bedrock" in r[1] or "Ollama" in r[1])
        for r in all_results
    )
    if not has_working_backend:
        console.print()
        console.print(Panel.fit(
            "[bold]No working LLM backend detected.[/bold]\n\n"
            "CogniGraph needs an AI model to reason over your knowledge graph.\n"
            "You have several options (including FREE local models):\n\n"
            "  [bold cyan]kogni setup-guide[/bold cyan]            — see all options with setup steps\n"
            "  [bold cyan]kogni setup-guide ollama[/bold cyan]     — free, local, no API key\n"
            "  [bold cyan]kogni setup-guide anthropic[/bold cyan]  — best quality, $5 free credits\n",
            border_style="yellow",
            title="Get Started",
        ))
