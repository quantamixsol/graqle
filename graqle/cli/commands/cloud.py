"""graq cloud — cloud graph management commands.

Upload your knowledge graph to Graqle Cloud so it appears on graqle.com/dashboard.

Commands:
    graq cloud push      Upload graph + intelligence to cloud
    graq cloud pull      Download graph from cloud
    graq cloud status    Show cloud connection status
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.cloud
# risk: LOW (impact radius: 0 modules)
# consumers: main
# dependencies: __future__, typer, rich, pathlib, json, hashlib, httpx
# constraints: requires valid API key
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

cloud_app = typer.Typer(
    name="cloud",
    help="Upload and manage your knowledge graph on Graqle Cloud.",
    no_args_is_help=True,
)

# Cloud endpoint for presigned URL generation
CLOUD_URL = "https://graqle.com"
GRAPHS_BUCKET = "graqle-graphs-eu"
GRAPHS_REGION = "eu-central-1"


def _get_credentials():
    """Load and validate credentials."""
    from graqle.cloud.credentials import load_credentials

    creds = load_credentials()
    if not creds.is_authenticated:
        console.print(Panel(
            "[bold red]Not logged in to Graqle Cloud[/bold red]\n\n"
            "  Log in with your API key:\n"
            "  [bold cyan]graq login --api-key grq_your_key_here[/bold cyan]\n\n"
            "  Generate a key at: [bold]https://graqle.com/dashboard/account[/bold]",
            title="Authentication Required",
            border_style="red",
        ))
        raise typer.Exit(1)
    return creds


def _email_hash(email: str) -> str:
    """SHA-256 hash of email for S3 path (matches Studio's getUserGraphKey)."""
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _detect_project_name(root: Path) -> str:
    """Detect project name from graqle.yaml, package.json, or directory name."""
    # Try graqle.yaml
    yaml_path = root / "graqle.yaml"
    if yaml_path.exists():
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if data and data.get("project", {}).get("name"):
                return data["project"]["name"]
        except Exception:
            pass

    # Try package.json
    pkg_path = root / "package.json"
    if pkg_path.exists():
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
            if data.get("name"):
                return data["name"]
        except Exception:
            pass

    # Try pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.strip().startswith("name") and "=" in line:
                    name = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if name:
                        return name
        except Exception:
            pass

    # Fallback to directory name
    return root.resolve().name


def _request_presigned_urls(
    api_key: str, project: str, files: list[str]
) -> dict:
    """Request presigned S3 PUT URLs from graqle.com.

    Args:
        api_key: The grq_ API key
        project: Project name
        files: List of relative file paths (e.g. ["graqle.json", "scorecard.json"])

    Returns:
        Dict with 'urls' (path→presigned_url), 'prefix', 'email', 'plan'
    """
    import httpx

    # Batch into chunks of 500 (server limit)
    all_urls: dict[str, str] = {}
    result_meta: dict = {}

    for i in range(0, len(files), 500):
        batch = files[i:i + 500]
        resp = httpx.post(
            f"{CLOUD_URL}/api/cloud/presign",
            json={"project": project, "files": batch},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        if resp.status_code == 401:
            console.print(Panel(
                "[bold red]API key rejected[/bold red]\n\n"
                "  Your API key is invalid or revoked.\n"
                "  Generate a new one at: [bold cyan]https://graqle.com/dashboard/account[/bold cyan]\n"
                "  Then: [bold cyan]graq login --api-key grq_your_new_key[/bold cyan]",
                title="Authentication Failed",
                border_style="red",
            ))
            raise typer.Exit(1)
        if resp.status_code != 200:
            error = resp.json().get("error", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            console.print(f"[red]Cloud error: {error}[/red]")
            raise typer.Exit(1)

        data = resp.json()
        all_urls.update(data.get("urls", {}))
        if not result_meta:
            result_meta = {
                "prefix": data.get("prefix", ""),
                "email": data.get("email", ""),
                "plan": data.get("plan", "free"),
            }

    result_meta["urls"] = all_urls
    return result_meta


def _upload_via_presigned(url: str, data: bytes) -> bool:
    """Upload data to S3 via presigned PUT URL."""
    import httpx

    resp = httpx.put(
        url,
        content=data,
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    return resp.status_code == 200


def _collect_upload_files(root_path: Path, proj_name: str) -> dict[str, bytes]:
    """Collect all files to upload and return {relative_path: bytes}."""
    files: dict[str, bytes] = {}

    # Graph
    graph_path = root_path / "graqle.json"
    if graph_path.exists():
        files["graqle.json"] = graph_path.read_bytes()

    # Scorecard
    scorecard_path = root_path / ".graqle" / "scorecard.json"
    if scorecard_path.exists():
        files["scorecard.json"] = scorecard_path.read_bytes()

    # Compiled insights
    insights_path = root_path / ".graqle" / "intelligence" / "compiled_insights.json"
    if insights_path.exists():
        files["compiled_insights.json"] = insights_path.read_bytes()

    # Module index
    module_index_path = root_path / ".graqle" / "intelligence" / "module_index.json"
    if module_index_path.exists():
        files["module_index.json"] = module_index_path.read_bytes()

    # Impact matrix
    impact_path = root_path / ".graqle" / "intelligence" / "impact_matrix.json"
    if impact_path.exists():
        files["impact_matrix.json"] = impact_path.read_bytes()

    # Module packets
    modules_dir = root_path / ".graqle" / "intelligence" / "modules"
    if modules_dir.is_dir():
        for mf in modules_dir.glob("*.json"):
            files[f"modules/{mf.name}"] = mf.read_bytes()

    # Governance
    governance_dir = root_path / ".graqle" / "governance"
    if governance_dir.is_dir():
        for gf in governance_dir.rglob("*.json"):
            rel = gf.relative_to(governance_dir)
            files[f"governance/{rel.as_posix()}"] = gf.read_bytes()

    return files


@cloud_app.command(name="push")
def cloud_push(
    project: str = typer.Option(
        "", "--project", "-p",
        help="Project name (auto-detected from graqle.yaml/package.json if omitted).",
    ),
    root: str = typer.Option(
        ".", "--root", "-r",
        help="Project root directory.",
    ),
) -> None:
    """Upload knowledge graph + intelligence to Graqle Cloud.

    Your graph will appear on graqle.com/dashboard under your projects.
    """
    creds = _get_credentials()
    root_path = Path(root).resolve()

    # Detect project name
    proj_name = project or _detect_project_name(root_path)

    console.print(f"\n[bold cyan]Pushing[/bold cyan] [bold]{proj_name}[/bold] to Graqle Cloud...")

    # Check graph exists
    graph_path = root_path / "graqle.json"
    if not graph_path.exists():
        console.print(Panel(
            f"[bold red]No graqle.json found in {root_path}[/bold red]\n\n"
            "  Build your knowledge graph first:\n"
            "  [bold cyan]graq scan repo .[/bold cyan]",
            title="Graph Not Found",
            border_style="red",
        ))
        raise typer.Exit(1)

    # Parse graph for stats
    graph_data = graph_path.read_text(encoding="utf-8")
    graph_json = json.loads(graph_data)
    node_count = len(graph_json.get("nodes", []))
    edge_count = len(graph_json.get("links", graph_json.get("edges", [])))

    # Plan-aware warnings
    try:
        from graqle.cloud.plans import get_plan_limits, check_node_limit
        limits = get_plan_limits(creds.plan)
        check = check_node_limit(creds.plan, node_count)
        if not check.allowed:
            console.print(Panel(
                f"[bold yellow]Plan limit reached[/bold yellow]\n\n"
                f"  Your graph has [bold]{node_count:,}[/bold] nodes but the "
                f"[bold]{creds.plan.title()}[/bold] plan allows [bold]{limits.max_nodes:,}[/bold].\n"
                f"  Cloud viewers will only see the first {limits.max_nodes:,} nodes.\n\n"
                f"  Upgrade: [bold cyan]graqle.com/pricing[/bold cyan]",
                title="Plan Limit Warning",
                border_style="yellow",
            ))
        elif limits.max_nodes > 0 and node_count > limits.max_nodes * 0.8:
            pct = int(node_count / limits.max_nodes * 100)
            console.print(f"  [yellow]⚠ {pct}% of {creds.plan.title()} plan node limit ({node_count:,}/{limits.max_nodes:,})[/yellow]")
    except Exception:
        pass  # Plan checks are non-blocking

    # Collect all files to upload
    upload_files = _collect_upload_files(root_path, proj_name)

    # Add metadata.json
    import time
    scorecard_path = root_path / ".graqle" / "scorecard.json"
    governance_dir = root_path / ".graqle" / "governance"
    module_count = sum(1 for k in upload_files if k.startswith("modules/"))
    has_governance = any(k.startswith("governance/") for k in upload_files)

    metadata = {
        "project": proj_name,
        "email": creds.email,
        "nodeCount": node_count,
        "edgeCount": edge_count,
        "lastPush": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "health": "HEALTHY" if scorecard_path.exists() else "UNKNOWN",
        "hasIntelligence": scorecard_path.exists(),
        "hasGovernance": has_governance,
        "moduleCount": module_count,
    }
    upload_files["metadata.json"] = json.dumps(metadata, indent=2).encode("utf-8")

    console.print(f"  Uploading {len(upload_files)} files ({node_count} nodes, {edge_count} edges)...")

    # Get presigned URLs from graqle.com
    try:
        presign_result = _request_presigned_urls(
            creds.api_key, proj_name, list(upload_files.keys())
        )
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Failed to get upload URLs: {e}[/red]")
        console.print("  [dim]Check your internet connection and try again.[/dim]")
        raise typer.Exit(1)

    urls = presign_result["urls"]
    s3_prefix = presign_result["prefix"]

    # Upload each file via presigned URL
    failed = []
    for file_path, file_data in upload_files.items():
        url = urls.get(file_path)
        if not url:
            failed.append(file_path)
            continue
        if not _upload_via_presigned(url, file_data):
            failed.append(file_path)

    if failed:
        console.print(f"  [yellow]⚠ {len(failed)} files failed to upload: {', '.join(failed[:5])}[/yellow]")

    uploaded = len(upload_files) - len(failed)

    # Neptune sync (Team/Enterprise plan)
    neptune_synced = False
    if creds.plan in ("team", "enterprise"):
        try:
            from graqle.connectors.neptune import upsert_nodes, upsert_edges, check_neptune_available
            available, _ = check_neptune_available()
            if available:
                console.print("  Syncing to Neptune (Team feature)...")
                nodes = graph_json.get("nodes", [])
                edges = graph_json.get("links", graph_json.get("edges", []))
                n_count = upsert_nodes(proj_name, nodes)
                e_count = upsert_edges(proj_name, edges)
                console.print(f"  Neptune: {n_count} nodes, {e_count} edges synced")
                neptune_synced = True
            else:
                console.print("  [dim]Neptune not available in this environment[/dim]")
        except Exception as e:
            console.print(f"  [dim]Neptune sync skipped: {e}[/dim]")

    console.print(Panel(
        f"[bold green]Pushed successfully![/bold green]\n\n"
        f"  Project:  [bold]{proj_name}[/bold]\n"
        f"  Nodes:    {node_count}\n"
        f"  Edges:    {edge_count}\n"
        f"  Files:    {uploaded}/{len(upload_files)}\n"
        f"  Storage:  s3://{GRAPHS_BUCKET}/{s3_prefix}/\n"
        f"  Neptune:  {'[green]Synced[/green]' if neptune_synced else '[dim]Skipped (Team plan)[/dim]'}\n\n"
        f"  View at:  [bold cyan]https://graqle.com/dashboard[/bold cyan]",
        title="Cloud Push Complete",
        border_style="green",
    ))


@cloud_app.command(name="pull")
def cloud_pull(
    project: str = typer.Option(
        "", "--project", "-p",
        help="Project name to pull.",
    ),
    root: str = typer.Option(
        ".", "--root", "-r",
        help="Target directory.",
    ),
) -> None:
    """Download knowledge graph from Graqle Cloud."""
    creds = _get_credentials()
    root_path = Path(root).resolve()

    proj_name = project or _detect_project_name(root_path)
    email_h = _email_hash(creds.email)

    console.print(f"\n[bold cyan]Pulling[/bold cyan] [bold]{proj_name}[/bold] from Graqle Cloud...")

    # Download via public-facing API (no AWS creds needed)
    import httpx

    try:
        resp = httpx.get(
            f"{CLOUD_URL}/api/intelligence/scorecard",
            params={"project": proj_name},
            headers={
                "Authorization": f"Bearer {creds.api_key}",
                "X-User-Email": creds.email,
            },
            timeout=30,
        )
        # For now, pull the graph via the graphs list API to verify project exists
        list_resp = httpx.get(
            f"{CLOUD_URL}/api/graphs/list",
            headers={"X-User-Email": creds.email},
            timeout=30,
        )
        if list_resp.status_code != 200:
            console.print("[red]Failed to connect to Graqle Cloud[/red]")
            raise typer.Exit(1)

        projects_data = list_resp.json().get("projects", [])
        matching = [p for p in projects_data if p.get("name") == proj_name]
        if not matching:
            console.print(Panel(
                f"[bold red]Project '{proj_name}' not found in cloud[/bold red]\n\n"
                "  Push your graph first: [bold cyan]graq cloud push[/bold cyan]",
                title="Not Found",
                border_style="red",
            ))
            raise typer.Exit(1)

        # Download graph.json via presigned GET (request a read URL)
        # For now, use the direct download endpoint
        console.print(Panel(
            f"[bold green]Project '{proj_name}' exists in cloud[/bold green]\n\n"
            f"  Nodes:  {matching[0].get('nodeCount', '?')}\n"
            f"  Edges:  {matching[0].get('edgeCount', '?')}\n\n"
            f"  [dim]Full cloud pull coming in v0.30 — use graq cloud push to sync.[/dim]",
            title="Cloud Pull",
            border_style="green",
        ))
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Pull failed: {e}[/red]")
        raise typer.Exit(1)


@cloud_app.command(name="status")
def cloud_status() -> None:
    """Show cloud connection status and projects."""
    from graqle.cloud.credentials import load_credentials

    creds = load_credentials()

    table = Table(title="Graqle Cloud Status", border_style="dim")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Connected", "[green]Yes[/green]" if creds.is_authenticated else "[red]No[/red]")
    table.add_row("Email", creds.email or "—")
    table.add_row("Plan", creds.plan.title())
    table.add_row("Cloud URL", CLOUD_URL)

    console.print(table)

    if not creds.is_authenticated:
        console.print(
            "\n  [bold]Connect:[/bold] graq login --api-key grq_your_key\n"
            "  [bold]Get key:[/bold] https://graqle.com/dashboard/account"
        )
        return

    # List projects via cloud API (no AWS creds needed)
    try:
        import httpx
        resp = httpx.get(
            f"{CLOUD_URL}/api/graphs/list",
            headers={"X-User-Email": creds.email},
            timeout=15,
        )
        if resp.status_code == 200:
            projects = resp.json().get("projects", [])
            if projects:
                projects_table = Table(title="Cloud Projects", border_style="dim")
                projects_table.add_column("Project", style="cyan")
                projects_table.add_column("Nodes", justify="right")
                projects_table.add_column("Edges", justify="right")
                projects_table.add_column("Health")
                projects_table.add_column("Last Push")

                for p in projects:
                    projects_table.add_row(
                        p.get("name", "?"),
                        str(p.get("nodeCount", "?")),
                        str(p.get("edgeCount", "?")),
                        f"[green]{p.get('health', '?')}[/green]",
                        p.get("lastPush", "?")[:10],
                    )

                console.print(projects_table)
            else:
                console.print("\n  No projects pushed yet. Run [bold cyan]graq cloud push[/bold cyan]")
        else:
            console.print(f"\n  [dim]Could not list projects (HTTP {resp.status_code})[/dim]")
    except Exception as e:
        console.print(f"\n  [dim]Could not list projects: {e}[/dim]")
