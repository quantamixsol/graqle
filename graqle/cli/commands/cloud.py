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

# S3 bucket and paths
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


def _get_s3_client():
    """Create S3 client (lazy import boto3)."""
    import boto3
    return boto3.client("s3", region_name=GRAPHS_REGION)


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
    email_h = _email_hash(creds.email)
    s3_prefix = f"graphs/{email_h}/{proj_name}"

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

    s3 = _get_s3_client()

    # Upload graph
    graph_data = graph_path.read_text(encoding="utf-8")
    graph_json = json.loads(graph_data)
    node_count = len(graph_json.get("nodes", []))
    edge_count = len(graph_json.get("edges", []))

    console.print(f"  Uploading graph ({node_count} nodes, {edge_count} edges)...")
    s3.put_object(
        Bucket=GRAPHS_BUCKET,
        Key=f"{s3_prefix}/graqle.json",
        Body=graph_data.encode("utf-8"),
        ContentType="application/json",
        Metadata={
            "project": proj_name,
            "email": creds.email,
            "node_count": str(node_count),
            "edge_count": str(edge_count),
        },
    )

    # Upload scorecard if exists
    scorecard_path = root_path / ".graqle" / "scorecard.json"
    if scorecard_path.exists():
        console.print("  Uploading intelligence scorecard...")
        s3.put_object(
            Bucket=GRAPHS_BUCKET,
            Key=f"{s3_prefix}/scorecard.json",
            Body=scorecard_path.read_bytes(),
            ContentType="application/json",
        )

    # Upload compiled insights if exist
    insights_path = root_path / ".graqle" / "intelligence" / "compiled_insights.json"
    if insights_path.exists():
        console.print("  Uploading compiled insights...")
        s3.put_object(
            Bucket=GRAPHS_BUCKET,
            Key=f"{s3_prefix}/compiled_insights.json",
            Body=insights_path.read_bytes(),
            ContentType="application/json",
        )

    # Write project metadata
    import time
    metadata = {
        "project": proj_name,
        "email": creds.email,
        "nodeCount": node_count,
        "edgeCount": edge_count,
        "lastPush": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "health": "HEALTHY" if scorecard_path.exists() else "UNKNOWN",
        "hasIntelligence": scorecard_path.exists(),
    }
    s3.put_object(
        Bucket=GRAPHS_BUCKET,
        Key=f"{s3_prefix}/metadata.json",
        Body=json.dumps(metadata, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    # Neptune sync (Team plan and above)
    neptune_synced = False
    try:
        from graqle.cloud.plans import check_feature
        from graqle.licensing.manager import LicenseManager
        manager = LicenseManager()
        plan = manager.current_tier.value
        neptune_ok = check_feature(plan, "cloud_sync")
        if neptune_ok.allowed:
            try:
                from graqle.connectors.neptune import upsert_nodes, upsert_edges, check_neptune_available
                available, _ = check_neptune_available()
                if available:
                    console.print("  Syncing to Neptune (Team feature)...")
                    nodes = graph_json.get("nodes", [])
                    edges = graph_json.get("edges", []) + graph_json.get("links", [])
                    n_count = upsert_nodes(proj_name, nodes)
                    e_count = upsert_edges(proj_name, edges)
                    console.print(f"  Neptune: {n_count} nodes, {e_count} edges synced")
                    neptune_synced = True
            except Exception as e:
                console.print(f"  [dim]Neptune sync skipped: {e}[/dim]")
    except Exception:
        pass  # Plan check failed — skip Neptune

    console.print(Panel(
        f"[bold green]Pushed successfully![/bold green]\n\n"
        f"  Project:  [bold]{proj_name}[/bold]\n"
        f"  Nodes:    {node_count}\n"
        f"  Edges:    {edge_count}\n"
        f"  S3:       s3://{GRAPHS_BUCKET}/{s3_prefix}/\n"
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
    s3_prefix = f"graphs/{email_h}/{proj_name}"

    console.print(f"\n[bold cyan]Pulling[/bold cyan] [bold]{proj_name}[/bold] from Graqle Cloud...")

    s3 = _get_s3_client()

    try:
        response = s3.get_object(Bucket=GRAPHS_BUCKET, Key=f"{s3_prefix}/graqle.json")
        graph_data = response["Body"].read().decode("utf-8")

        graph_path = root_path / "graqle.json"
        graph_path.write_text(graph_data, encoding="utf-8")

        graph_json = json.loads(graph_data)
        node_count = len(graph_json.get("nodes", []))

        console.print(Panel(
            f"[bold green]Pulled successfully![/bold green]\n\n"
            f"  Project:  [bold]{proj_name}[/bold]\n"
            f"  Nodes:    {node_count}\n"
            f"  Saved to: {graph_path}",
            title="Cloud Pull Complete",
            border_style="green",
        ))
    except s3.exceptions.NoSuchKey:
        console.print(Panel(
            f"[bold red]Project '{proj_name}' not found in cloud[/bold red]\n\n"
            "  Push your graph first: [bold cyan]graq cloud push[/bold cyan]",
            title="Not Found",
            border_style="red",
        ))
        raise typer.Exit(1)
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
    table.add_row("Cloud URL", creds.cloud_url)

    console.print(table)

    if not creds.is_authenticated:
        console.print(
            "\n  [bold]Connect:[/bold] graq login --api-key grq_your_key\n"
            "  [bold]Get key:[/bold] https://graqle.com/dashboard/account"
        )
        return

    # List projects
    try:
        email_h = _email_hash(creds.email)
        s3 = _get_s3_client()
        response = s3.list_objects_v2(
            Bucket=GRAPHS_BUCKET,
            Prefix=f"graphs/{email_h}/",
            Delimiter="/",
        )

        prefixes = response.get("CommonPrefixes", [])
        if prefixes:
            projects_table = Table(title="Cloud Projects", border_style="dim")
            projects_table.add_column("Project", style="cyan")
            projects_table.add_column("Status")

            for prefix in prefixes:
                proj = prefix["Prefix"].split("/")[-2]
                projects_table.add_row(proj, "[green]Synced[/green]")

            console.print(projects_table)
        else:
            console.print("\n  No projects pushed yet. Run [bold cyan]graq cloud push[/bold cyan]")
    except Exception as e:
        console.print(f"\n  [dim]Could not list projects: {e}[/dim]")
