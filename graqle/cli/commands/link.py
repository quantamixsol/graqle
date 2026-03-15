"""graq link — Multi-project graph operations.

Merge multiple project KGs into a unified graph and create cross-project
edges. This enables Graqle reasoning across your entire ecosystem.

Examples:
    graq link merge project1/graqle.json project2/graqle.json -o merged.json
    graq link infer merged.json
    graq link edge crawlq/tamr_sdk frictionmelt/retrieval --relation POWERS
    graq link stats merged.json
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.link
# risk: MEDIUM (impact radius: 2 modules)
# consumers: main, test_link
# dependencies: __future__, json, re, pathlib, typing +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from graqle.cli.console import ARROW, CHECK

link_app = typer.Typer(
    name="link",
    help="Multi-project graph operations — merge KGs and create cross-project edges.",
    no_args_is_help=True,
)

console = Console()


@link_app.command("merge")
def link_merge(
    graphs: list[str] = typer.Argument(..., help="Paths to graph JSON files to merge"),
    output: str = typer.Option("merged.json", "--output", "-o", help="Output merged graph path"),
    prefix_ids: bool = typer.Option(True, "--prefix/--no-prefix", help="Prefix node IDs with project name to avoid collisions"),
    names: list[str] = typer.Option(
        None, "--names", "-n",
        help="Explicit project names for each graph file (in order). "
             "E.g. --names crawlq --names graqle. Falls back to graph metadata or parent dir.",
    ),
) -> None:
    """Merge multiple project KGs into a single unified graph.

    Each graph's nodes are optionally prefixed with the project name
    to prevent ID collisions (e.g. 'auth-lambda' → 'crawlq/auth-lambda').

    By default, project names are derived from the parent directory.
    Use --names to override (e.g. when graphs are in temp directories).

    \b
    Examples:
        graq link merge project1/graqle.json project2/graqle.json
        graq link merge a.json b.json --names crawlq --names graqle
        graq link merge *.json --output unified.json --no-prefix
    """
    if len(graphs) < 2:
        console.print("[red]Need at least 2 graph files to merge.[/red]")
        raise typer.Exit(1)

    if names and len(names) != len(graphs):
        console.print(f"[red]--names count ({len(names)}) must match graph file count ({len(graphs)})[/red]")
        raise typer.Exit(1)

    merged_nodes: list[dict] = []
    merged_links: list[dict] = []
    sources: list[dict] = []

    for idx, gpath in enumerate(graphs):
        p = Path(gpath)
        if not p.exists():
            console.print(f"[yellow]Skipping {gpath} — file not found[/yellow]")
            continue

        data = json.loads(p.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        links = data.get("links", data.get("edges", []))

        # Project name priority: --names > graph metadata > parent dir > filename
        if names and idx < len(names):
            project_name = names[idx]
        elif isinstance(data.get("graph"), dict) and data["graph"].get("project_name"):
            project_name = data["graph"]["project_name"]
        else:
            project_name = p.parent.name if p.parent.name != "." else p.stem
        if project_name in (".", ""):
            project_name = p.stem.replace("graqle", "default")

        node_id_map: dict[str, str] = {}

        for node in nodes:
            old_id = node.get("id", "")
            if prefix_ids and "/" not in old_id:
                new_id = f"{project_name}/{old_id}"
            else:
                new_id = old_id
            node_id_map[old_id] = new_id

            new_node = {**node, "id": new_id}
            # Tag with source project
            props = new_node.get("properties", {})
            if isinstance(props, dict):
                props["source_project"] = project_name
                new_node["properties"] = props
            merged_nodes.append(new_node)

        for link in links:
            src = link.get("source", "")
            tgt = link.get("target", "")
            new_link = {
                **link,
                "source": node_id_map.get(src, src),
                "target": node_id_map.get(tgt, tgt),
            }
            merged_links.append(new_link)

        sources.append({
            "project": project_name,
            "file": str(p),
            "nodes": len(nodes),
            "links": len(links),
        })

    # Deduplicate nodes by ID (last wins)
    seen_ids: dict[str, int] = {}
    deduped_nodes: list[dict] = []
    for node in merged_nodes:
        nid = node.get("id", "")
        if nid in seen_ids:
            deduped_nodes[seen_ids[nid]] = node
        else:
            seen_ids[nid] = len(deduped_nodes)
            deduped_nodes.append(node)

    merged_data = {
        "directed": True,
        "multigraph": False,
        "graph": {"merged_from": [s["project"] for s in sources]},
        "nodes": deduped_nodes,
        "links": merged_links,
    }

    Path(output).write_text(
        json.dumps(merged_data, indent=2, default=str), encoding="utf-8"
    )

    console.print(f"\n[bold green]{CHECK} Merged {len(sources)} projects[/bold green]")
    table = Table(title="Merge Summary")
    table.add_column("Project", style="cyan")
    table.add_column("Nodes", justify="right")
    table.add_column("Links", justify="right")
    for s in sources:
        table.add_row(s["project"], str(s["nodes"]), str(s["links"]))
    table.add_row("[bold]Total[/bold]", f"[bold]{len(deduped_nodes)}[/bold]", f"[bold]{len(merged_links)}[/bold]")
    console.print(table)
    console.print(f"  Output: [bold]{output}[/bold]")


@link_app.command("edge")
def link_edge(
    source: str = typer.Argument(..., help="Source node ID (can use project/node format)"),
    target: str = typer.Argument(..., help="Target node ID (can use project/node format)"),
    relation: str = typer.Option("POWERS", "--relation", "-r", help="Edge relation type"),
    weight: float = typer.Option(1.0, "--weight", "-w", help="Edge weight"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a cross-project edge between two nodes.

    Use project/node notation for clarity.

    \b
    Examples:
        graq link edge crawlq/tamr_sdk frictionmelt/retrieval --relation POWERS
        graq link edge graqle/reasoning tracegov/compliance --relation ENABLES
    """
    from graqle.core.graph import Graqle
    from graqle.config.settings import GraqleConfig

    p = Path(graph_path)
    if not p.exists():
        console.print(f"[red]Graph not found: {graph_path}[/red]")
        raise typer.Exit(1)

    config = GraqleConfig.default()
    config_file = Path("graqle.yaml")
    if config_file.exists():
        config = GraqleConfig.from_yaml(str(config_file))

    graph = Graqle.from_json(str(p), config=config)

    # Fuzzy-find source and target
    def _find(name: str) -> str | None:
        if name in graph.nodes:
            return name
        name_lower = name.lower()
        for nid in graph.nodes:
            if name_lower in nid.lower():
                return nid
        return None

    src_id = _find(source)
    tgt_id = _find(target)

    if not src_id:
        console.print(f"[red]Source node '{source}' not found in graph[/red]")
        raise typer.Exit(1)
    if not tgt_id:
        console.print(f"[red]Target node '{target}' not found in graph[/red]")
        raise typer.Exit(1)

    graph.add_edge_simple(src_id, tgt_id, relation=relation.upper(), weight=weight)
    graph.to_json(str(p))

    console.print(f"[green]{CHECK} Cross-project edge:[/green] {src_id} --[{relation}]{ARROW} {tgt_id}")
    console.print(f"  Weight: {weight}")


@link_app.command("stats")
def link_stats(
    graph_path: str = typer.Argument("graqle.json", help="Path to merged graph file"),
) -> None:
    """Show multi-project statistics for a merged graph.

    Displays per-project node counts, cross-project edges, and
    overall graph health.
    """
    p = Path(graph_path)
    if not p.exists():
        console.print(f"[red]Graph not found: {graph_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))

    # Count per-project nodes
    project_counts: dict[str, int] = {}
    for node in nodes:
        nid = node.get("id", "")
        if "/" in nid:
            project = nid.split("/")[0]
        else:
            props = node.get("properties", {})
            project = props.get("source_project", "unknown") if isinstance(props, dict) else "unknown"
        project_counts[project] = project_counts.get(project, 0) + 1

    # Count cross-project edges
    cross_edges = 0
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        src_proj = src.split("/")[0] if "/" in src else "default"
        tgt_proj = tgt.split("/")[0] if "/" in tgt else "default"
        if src_proj != tgt_proj:
            cross_edges += 1

    console.print(f"\n[bold]Multi-Project Graph Stats[/bold]")
    console.print(f"  File: {graph_path} ({p.stat().st_size / 1024 / 1024:.1f} MB)")
    console.print(f"  Total nodes: {len(nodes)}")
    console.print(f"  Total edges: {len(links)}")
    console.print(f"  Cross-project edges: {cross_edges}")

    if project_counts:
        table = Table(title="Per-Project Breakdown")
        table.add_column("Project", style="cyan")
        table.add_column("Nodes", justify="right")
        table.add_column("Share", justify="right")
        for proj, count in sorted(project_counts.items(), key=lambda x: -x[1]):
            pct = count / len(nodes) * 100 if nodes else 0
            table.add_row(proj, str(count), f"{pct:.1f}%")
        console.print(table)


# ---------------------------------------------------------------------------
# Edge Inference Engine
# ---------------------------------------------------------------------------


def _get_project(node_id: str) -> str:
    """Extract project prefix from a node ID (e.g. 'crawlq/auth.py' -> 'crawlq')."""
    return node_id.split("/", 1)[0] if "/" in node_id else ""


def _infer_api_edges(
    nodes: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Infer cross-project edges from API endpoint patterns.

    Strategy:
    1. Build index of backend APIEndpoint nodes: path -> node_id
    2. Scan frontend function/module nodes for fetch URLs, query keys, route patterns
    3. Create CALLS edges: frontend function -> backend endpoint

    Patterns detected:
    - fetch('/api/onboarding/state') or fetch(`/bamr/onboarding/state`)
    - useQuery(['onboarding', 'state'], ...) -> matches /onboarding/state
    - axios.get('/api/users') or api.post('/auth/login')
    """
    new_edges: list[dict[str, Any]] = []

    # 1. Index APIEndpoint nodes by their path
    endpoint_index: dict[str, str] = {}  # normalized_path -> node_id
    for node in nodes:
        if node.get("type") == "APIEndpoint" or node.get("entity_type") == "APIEndpoint":
            nid = node.get("id", "")
            label = node.get("label", "")
            # Normalize: /api/users/:id -> /api/users
            # Also index without leading /api prefix
            for path in [label, label.lstrip("/")]:
                path_clean = re.sub(r"/:[^/]+", "", path)  # remove path params
                path_clean = path_clean.rstrip("/")
                if path_clean:
                    endpoint_index[path_clean.lower()] = nid
                    # Also index without common prefixes
                    for prefix in ("/api/", "/bamr/", "api/", "bamr/"):
                        if path_clean.lower().startswith(prefix):
                            short = path_clean[len(prefix):].lower()
                            if short:
                                endpoint_index[short] = nid

    if not endpoint_index:
        return new_edges

    # 2. Build index of all existing edges to avoid duplicates
    existing_edges: set[tuple[str, str, str]] = set()
    for link in links:
        existing_edges.add((
            link.get("source", ""),
            link.get("target", ""),
            link.get("relationship", ""),
        ))

    # 3. Scan all nodes for URL references in descriptions and chunks
    url_patterns = [
        # fetch('/api/...'), axios.get('/...')
        re.compile(r"""(?:fetch|axios|api|http|get|post|put|delete|patch)\s*[.(]\s*['"`/]([^'"`\s)]+)""", re.IGNORECASE),
        # useQuery(['key', 'subkey'])
        re.compile(r"""useQuery\s*\(\s*\[([^\]]+)\]"""),
        # useMutation / useQueryClient with URL
        re.compile(r"""(?:useMutation|useInfiniteQuery)\s*[({]\s*.*?(?:url|path|endpoint)\s*[:=]\s*['"`]([^'"`]+)""", re.IGNORECASE),
    ]

    for node in nodes:
        nid = node.get("id", "")
        node_project = _get_project(nid)
        node_type = node.get("type", node.get("entity_type", ""))

        # Only scan frontend-like nodes (functions, modules)
        if node_type not in ("Function", "JavaScriptModule", "TestFile", "PythonModule"):
            continue

        # Gather all text to scan: description + chunk texts
        texts_to_scan = [node.get("description", "")]
        for chunk in node.get("chunks", node.get("properties", {}).get("chunks", [])):
            if isinstance(chunk, dict):
                texts_to_scan.append(chunk.get("text", ""))
            elif isinstance(chunk, str):
                texts_to_scan.append(chunk)

        full_text = " ".join(texts_to_scan)
        if not full_text:
            continue

        # Search for URL patterns
        found_paths: set[str] = set()
        for pattern in url_patterns:
            for match in pattern.finditer(full_text):
                raw = match.group(1).strip().strip("'\"` ")
                # For useQuery arrays: ['onboarding', 'state'] -> onboarding/state
                if "," in raw:
                    parts = [p.strip().strip("'\"` ") for p in raw.split(",")]
                    raw = "/".join(p for p in parts if p and p.isalnum())
                # Clean path
                path = raw.split("?")[0].split("#")[0].rstrip("/")
                if path and len(path) > 2:
                    found_paths.add(path.lower())
                    # Also try without leading slash or prefix
                    bare = path.lstrip("/")
                    for prefix in ("api/", "bamr/", "v1/", "v2/"):
                        if bare.startswith(prefix):
                            found_paths.add(bare[len(prefix):])

        # Match found paths against endpoint index
        for path in found_paths:
            endpoint_nid = endpoint_index.get(path)
            if endpoint_nid and _get_project(endpoint_nid) != node_project:
                edge_key = (nid, endpoint_nid, "CALLS")
                if edge_key not in existing_edges:
                    new_edges.append({
                        "source": nid,
                        "target": endpoint_nid,
                        "relationship": "CALLS",
                        "properties": {"inferred": True, "method": "api_pattern"},
                    })
                    existing_edges.add(edge_key)

    return new_edges


def _infer_env_var_edges(
    nodes: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Infer SHARES_ENV edges between nodes in different projects that use the same env var."""
    new_edges: list[dict[str, Any]] = []

    # Index env var nodes by label
    env_nodes: dict[str, list[str]] = {}  # env_name -> [node_ids]
    for node in nodes:
        if node.get("type") == "EnvVar" or node.get("entity_type") == "EnvVar":
            label = node.get("label", "")
            env_nodes.setdefault(label, []).append(node.get("id", ""))

    # Find env vars that appear in multiple projects
    existing_edges: set[tuple[str, str, str]] = set()
    for link in links:
        existing_edges.add((
            link.get("source", ""), link.get("target", ""),
            link.get("relationship", ""),
        ))

    for env_name, node_ids in env_nodes.items():
        projects = set(_get_project(nid) for nid in node_ids)
        if len(projects) > 1:
            # Connect the first env var node from each project pair
            for i, nid_a in enumerate(node_ids):
                for nid_b in node_ids[i + 1:]:
                    if _get_project(nid_a) != _get_project(nid_b):
                        edge_key = (nid_a, nid_b, "SHARES_ENV")
                        if edge_key not in existing_edges:
                            new_edges.append({
                                "source": nid_a,
                                "target": nid_b,
                                "relationship": "SHARES_ENV",
                                "properties": {"inferred": True, "env_var": env_name},
                            })
                            existing_edges.add(edge_key)

    return new_edges


def _infer_name_similarity_edges(
    nodes: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Infer RELATED_TO edges between nodes in different projects with similar names.

    E.g., 'frontend/useOnboardingState' <-> 'backend/onboarding_service::OnboardingService'
    """
    new_edges: list[dict[str, Any]] = []

    # Build name tokens index: project -> {token -> [node_ids]}
    project_tokens: dict[str, dict[str, list[str]]] = {}
    for node in nodes:
        nid = node.get("id", "")
        project = _get_project(nid)
        if not project:
            continue
        label = node.get("label", "")
        ntype = node.get("type", node.get("entity_type", ""))
        if ntype not in ("Function", "Class", "PythonModule", "JavaScriptModule"):
            continue

        # Extract meaningful tokens from label
        # camelCase -> ['camel', 'case'], snake_case -> ['snake', 'case']
        tokens = set()
        for part in re.split(r"[_\-./\\:]+", label):
            # Split camelCase
            subtokens = re.findall(r"[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z]|$)", part)
            for t in subtokens:
                t_lower = t.lower()
                if len(t_lower) >= 4 and t_lower not in {
                    "test", "spec", "index", "main", "util", "utils", "helper",
                    "helpers", "types", "type", "config", "const", "model",
                    "component", "service", "module", "init", "base", "abstract",
                }:
                    tokens.add(t_lower)

        if not tokens:
            continue

        if project not in project_tokens:
            project_tokens[project] = {}
        for token in tokens:
            project_tokens[project].setdefault(token, []).append(nid)

    # Find cross-project token matches
    existing_edges: set[tuple[str, str, str]] = set()
    for link in links:
        existing_edges.add((
            link.get("source", ""), link.get("target", ""),
            link.get("relationship", ""),
        ))

    projects = list(project_tokens.keys())
    for i, proj_a in enumerate(projects):
        for proj_b in projects[i + 1:]:
            # Find shared tokens
            shared_tokens = set(project_tokens[proj_a].keys()) & set(project_tokens[proj_b].keys())
            for token in shared_tokens:
                nodes_a = project_tokens[proj_a][token][:5]
                nodes_b = project_tokens[proj_b][token][:5]
                for nid_a in nodes_a:
                    for nid_b in nodes_b:
                        edge_key = (nid_a, nid_b, "RELATED_TO")
                        if edge_key not in existing_edges:
                            new_edges.append({
                                "source": nid_a,
                                "target": nid_b,
                                "relationship": "RELATED_TO",
                                "properties": {
                                    "inferred": True,
                                    "method": "name_similarity",
                                    "shared_token": token,
                                },
                            })
                            existing_edges.add(edge_key)

    return new_edges


@link_app.command("infer")
def link_infer(
    graph_path: str = typer.Argument("graqle.json", help="Path to merged graph file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show inferred edges without saving"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show each inferred edge"),
) -> None:
    """Infer cross-project edges in a merged graph.

    Automatically detects relationships between projects:
    - API endpoints: frontend fetch() / useQuery() → backend route handlers
    - Shared env vars: same environment variable used across projects
    - Name similarity: functions/classes with matching domain tokens across projects

    Run this after `graq link merge` to dramatically improve cross-project reasoning.

    \b
    Examples:
        graq link infer merged.json
        graq link infer merged.json --dry-run --verbose
    """
    p = Path(graph_path)
    if not p.exists():
        console.print(f"[red]Graph not found: {graph_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))

    console.print(f"[bold]Inferring cross-project edges...[/bold]")
    console.print(f"  Graph: {len(nodes)} nodes, {len(links)} edges")

    # Run all inference strategies
    api_edges = _infer_api_edges(nodes, links)
    env_edges = _infer_env_var_edges(nodes, links)
    name_edges = _infer_name_similarity_edges(nodes, links)

    all_new = api_edges + env_edges + name_edges

    if verbose and all_new:
        table = Table(title="Inferred Edges")
        table.add_column("Source", style="cyan", max_width=45)
        table.add_column("Relation", style="green")
        table.add_column("Target", style="cyan", max_width=45)
        table.add_column("Method", style="dim")
        for edge in all_new[:50]:
            method = edge.get("properties", {}).get("method", edge["relationship"])
            table.add_row(
                edge["source"][-45:], edge["relationship"],
                edge["target"][-45:], method,
            )
        if len(all_new) > 50:
            table.add_row("...", "", f"(+{len(all_new) - 50} more)", "")
        console.print(table)

    console.print(f"\n  [green]API endpoint edges:[/green] {len(api_edges)}")
    console.print(f"  [green]Shared env var edges:[/green] {len(env_edges)}")
    console.print(f"  [green]Name similarity edges:[/green] {len(name_edges)}")
    console.print(f"  [bold green]Total inferred:[/bold green] {len(all_new)}")

    if not dry_run and all_new:
        links.extend(all_new)
        data["links"] = links
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        console.print(f"\n  {CHECK} Saved to {graph_path}")
        console.print(f"  Total edges now: {len(links)}")
    elif dry_run:
        console.print(f"\n  [dim]Dry run — no changes saved. Remove --dry-run to apply.[/dim]")
    else:
        console.print(f"\n  [dim]No new edges to infer.[/dim]")
