"""Studio API routes — JSON endpoints for dashboard data."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.api
# risk: HIGH (impact radius: 19 modules)
# consumers: providers, benchmark_runner, run_multigov_v2, run_multigov_v3, init +14 more
# dependencies: __future__, asyncio, logging, math, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------- Per-Project Graph Loading ----------

# Cache loaded project graphs to avoid re-downloading on every request
_project_graph_cache: dict[str, object] = {}


async def _load_project_graph(request: Request, project: str):
    """Load a user's project graph from S3 for per-project reasoning.

    The Lambda loads ONE default graph at cold start. When a user selects
    a specific project (e.g. "Brand_Collaboration"), we need to load THAT
    project's graph from S3 instead.

    Uses in-memory cache to avoid re-downloading on every request.
    """
    import hashlib
    import json
    import os

    # Check cache first
    if project in _project_graph_cache:
        return _project_graph_cache[project]

    # Get user email from request headers (set by Studio frontend)
    email = None
    auth_header = request.headers.get("authorization", "")
    user_email_header = request.headers.get("x-user-email", "")

    if user_email_header:
        email = user_email_header
    elif auth_header:
        # Try to extract email from JWT payload (base64 decode middle segment)
        try:
            import base64
            token = auth_header.replace("Bearer ", "")
            payload = token.split(".")[1]
            # Add padding
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            email = decoded.get("email", "")
        except Exception:
            pass

    if not email:
        logger.debug("No email found for project graph loading")
        return None

    # Compute S3 key
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()
    bucket = os.environ.get("GRAQLE_GRAPHS_BUCKET", "graqle-graphs-eu")
    s3_key = f"graphs/{email_hash}/{project}/graqle.json"

    try:
        import boto3
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
        resp = s3.get_object(Bucket=bucket, Key=s3_key)
        graph_data = json.loads(resp["Body"].read().decode("utf-8"))

        nodes = graph_data.get("nodes", [])
        links = graph_data.get("links", graph_data.get("edges", []))

        if not nodes:
            logger.info("Project %s has empty graph", project)
            return None

        # Build a Graqle instance from the loaded data
        # Copy config and backend from the Lambda's default graph
        from graqle.core.graph import Graqle

        state = request.app.state.studio_state
        default_graph = state.get("graph")
        default_config = state.get("config")

        g = Graqle(config=default_config)
        # Copy the default backend so reasoning has an LLM
        if default_graph and hasattr(default_graph, '_default_backend') and default_graph._default_backend:
            g._default_backend = default_graph._default_backend
        for node in nodes:
            g.add_node_simple(
                node.get("id", ""),
                label=node.get("label", ""),
                entity_type=node.get("type", "CONCEPT"),
                description=node.get("description", ""),
            )
        for link in links:
            src = link.get("source", "")
            tgt = link.get("target", "")
            if isinstance(src, dict):
                src = src.get("id", "")
            if isinstance(tgt, dict):
                tgt = tgt.get("id", "")
            if src and tgt:
                try:
                    g.add_edge_simple(src, tgt, relation=link.get("type", "RELATED_TO"))
                except Exception:
                    pass

        logger.info("Loaded project graph: %s (%d nodes, %d edges)", project, len(g), len(links))

        # Cache for warm invocations (max 5 projects to limit memory)
        if len(_project_graph_cache) >= 5:
            _project_graph_cache.pop(next(iter(_project_graph_cache)))
        _project_graph_cache[project] = g

        return g

    except Exception as e:
        logger.warning("Failed to load project graph %s: %s", project, e)
        return None


# ---------- Cross-project federation ----------


@router.get("/projects")
async def list_projects(request: Request):
    """List all projects belonging to the authenticated user.

    Scans S3 prefix graphs/{email_hash}/ to discover available projects.
    Returns project names with node/edge counts from last push metadata.
    Team plan only — free users get an empty list.
    """
    import hashlib
    import os

    auth_header = request.headers.get("authorization", "")
    user_email_header = request.headers.get("x-user-email", "")

    email = user_email_header
    if not email and auth_header:
        try:
            import base64
            token = auth_header.replace("Bearer ", "")
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            email = decoded.get("email", "")
        except Exception:
            pass

    if not email:
        return JSONResponse({"projects": [], "error": "Not authenticated"}, status_code=401)

    try:
        import json as _json
        import boto3
        email_hash = hashlib.sha256(email.lower().encode()).hexdigest()
        bucket = os.environ.get("GRAQLE_GRAPHS_BUCKET", "graqle-graphs-eu")
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

        prefix = f"graphs/{email_hash}/"
        paginator = s3.get_paginator("list_objects_v2")
        project_prefixes: list[str] = []

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                project_prefixes.append(cp.get("Prefix", ""))

        projects = []
        for proj_prefix in sorted(project_prefixes):
            parts = proj_prefix.rstrip("/").split("/")
            proj_name = parts[2] if len(parts) >= 3 else proj_prefix
            # Try to read metadata.json for rich project info
            try:
                meta_obj = s3.get_object(Bucket=bucket, Key=f"{proj_prefix}metadata.json")
                meta = _json.loads(meta_obj["Body"].read().decode("utf-8"))
                projects.append({
                    "name": meta.get("project", proj_name),
                    "lastPush": meta.get("lastPush", ""),
                    "nodeCount": meta.get("nodeCount", 0),
                    "edgeCount": meta.get("edgeCount", 0),
                    "health": meta.get("health", "UNKNOWN"),
                    "hasIntelligence": meta.get("hasIntelligence", False),
                })
            except Exception:
                projects.append({
                    "name": proj_name,
                    "lastPush": "",
                    "nodeCount": 0,
                    "edgeCount": 0,
                    "health": "UNKNOWN",
                    "hasIntelligence": False,
                })

        # Sort newest push first
        projects.sort(key=lambda p: p.get("lastPush", ""), reverse=True)

        return JSONResponse({
            "projects": projects,
            "count": len(projects),
        })

    except Exception as e:
        logger.warning("list_projects failed: %s", e)
        return JSONResponse({"projects": [], "error": str(e)[:200]}, status_code=200)


# ---------- Project Context ----------


@router.get("/project-context")
async def project_context(request: Request):
    """Return the active project identity and graph stats for the Studio UI.

    Used by TopBar badge and Dashboard project card to show which graph is loaded.
    """
    state = request.app.state.studio_state
    graph = state.get("graph")
    if graph is not None:
        ctx = graph.project_context()
        ctx["graph_loaded"] = True
        return JSONResponse(ctx)
    from pathlib import Path as _Path
    return JSONResponse({
        "project_name": _Path.cwd().name,
        "source_mode": "local",
        "graph_path": None,
        "node_count": 0,
        "edge_count": 0,
        "graph_loaded": False,
    })


# ---------- Metrics ----------


@router.get("/metrics/summary")
async def metrics_summary(request: Request):
    """Return metrics engine summary."""
    state = request.app.state.studio_state
    metrics = state.get("metrics")
    if not metrics:
        return {"error": "No metrics engine loaded"}
    try:
        return metrics.get_summary()
    except Exception as e:
        return {"error": str(e)}


@router.get("/metrics/sessions")
async def metrics_sessions(request: Request):
    """Return session history."""
    state = request.app.state.studio_state
    metrics = state.get("metrics")
    if not metrics:
        return {"sessions": []}
    try:
        data = metrics._data if hasattr(metrics, "_data") else {}
        return {"sessions": data.get("sessions", [])[-20:]}
    except Exception:
        return {"sessions": []}


@router.get("/metrics/roi")
async def metrics_roi(request: Request):
    """Return ROI report data."""
    state = request.app.state.studio_state
    metrics = state.get("metrics")
    if not metrics:
        return {"error": "No metrics engine loaded"}
    try:
        return {"report": metrics.get_roi_report()}
    except Exception as e:
        return {"error": str(e)}


# ---------- Graph ----------


@router.get("/graph/visualization")
async def graph_visualization(request: Request):
    """Return D3-compatible {nodes, links} JSON."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return {"nodes": [], "links": []}

    # Precompute degree map in one pass (avoids O(N×E) nested loop)
    degree_map: dict = {}
    for eid, edge in graph.edges.items():
        degree_map[edge.source_id] = degree_map.get(edge.source_id, 0) + 1
        degree_map[edge.target_id] = degree_map.get(edge.target_id, 0) + 1

    nodes = []
    for nid, node in graph.nodes.items():
        chunk_count = len(node.properties.get("chunks", []))
        degree = degree_map.get(nid, 0)
        nodes.append({
            "id": nid,
            "label": node.label,
            "type": node.entity_type,
            "description": (node.description or "")[:200],
            "chunks": chunk_count,
            "degree": degree,
            "size": max(8, min(40, 8 + math.sqrt(degree) * 6)),
            "color": _type_color(node.entity_type),
        })

    links = []
    for eid, edge in graph.edges.items():
        links.append({
            "id": eid,
            "source": edge.source_id,
            "target": edge.target_id,
            "relationship": edge.relationship,
            "weight": getattr(edge, "weight", 1.0),
        })

    return {"nodes": nodes, "links": links}


@router.get("/graph/visualization/filtered")
async def graph_visualization_filtered(
    request: Request,
    strategy: str = Query(
        "intelligence",
        description="Filter strategy: intelligence, risk, hub, architecture",
    ),
    limit: int = Query(200, ge=10, le=1000, description="Max nodes to return"),
    min_risk: str = Query("", description="Minimum risk level: LOW, MEDIUM, HIGH, CRITICAL"),
    include_neighbors: bool = Query(True, description="Include 1-hop neighbors of selected nodes"),
):
    """Return a pre-filtered graph optimized for large KGs (500+ nodes).

    Strategies:
    - intelligence: Top modules by risk_score * impact_radius (intelligence data)
    - risk: Only CRITICAL/HIGH risk modules + their direct dependencies
    - hub: Top hub nodes by degree centrality (most connected)
    - architecture: Module-level architecture view (collapses functions into modules)
    """
    import json as _json
    from pathlib import Path

    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return {"nodes": [], "links": [], "strategy": strategy, "total_before": 0}

    total_before = len(graph.nodes)

    # Build degree map
    degree_map: dict[str, int] = {}
    for eid, edge in graph.edges.items():
        degree_map[edge.source_id] = degree_map.get(edge.source_id, 0) + 1
        degree_map[edge.target_id] = degree_map.get(edge.target_id, 0) + 1

    selected_ids: set[str] = set()

    if strategy == "intelligence":
        # Use compiled intelligence to pick highest-impact modules
        root = Path(state.get("root", "."))
        modules_dir = root / ".graqle" / "intelligence" / "modules"
        scored: list[tuple[str, float]] = []

        if modules_dir.is_dir():
            for mf in modules_dir.glob("*.json"):
                try:
                    mod = _json.loads(mf.read_text(encoding="utf-8"))
                    risk_score = mod.get("risk_score", 0)
                    impact = mod.get("impact_radius", 0)
                    consumers = mod.get("consumer_count", 0)
                    funcs = mod.get("function_count", 0)
                    risk_level = mod.get("risk_level", "LOW")
                    # Composite score: risk * impact * (1 + log(consumers+1))
                    composite = risk_score * (impact + 1) * (1 + math.log(consumers + 1))
                    # Boost CRITICAL/HIGH
                    if risk_level == "CRITICAL":
                        composite *= 5
                    elif risk_level == "HIGH":
                        composite *= 2
                    # Match module to graph nodes by file paths
                    files = mod.get("files", [])
                    for fp in files:
                        # Node ID is typically the file path without extension
                        base = fp.replace("\\", "/")
                        candidates = [base, base.replace(".py", ""), base.replace("/", ".")]
                        for nid in graph.nodes:
                            nlabel = graph.nodes[nid].label or ""
                            if nid in candidates or base in nid or nlabel == Path(base).stem:
                                scored.append((nid, composite))
                                break
                except Exception:
                    continue

        # Sort by composite score, take top N
        scored.sort(key=lambda x: x[1], reverse=True)
        for nid, _ in scored[:limit]:
            selected_ids.add(nid)

        # If intelligence didn't yield enough, fall back to hub strategy
        if len(selected_ids) < limit // 2:
            hub_sorted = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
            for nid, _ in hub_sorted:
                if len(selected_ids) >= limit:
                    break
                selected_ids.add(nid)

    elif strategy == "risk":
        # Only CRITICAL and HIGH risk modules
        root = Path(state.get("root", "."))
        modules_dir = root / ".graqle" / "intelligence" / "modules"
        min_levels = {"CRITICAL", "HIGH"}
        if min_risk:
            level_order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            idx = level_order.index(min_risk) if min_risk in level_order else 0
            min_levels = set(level_order[idx:])

        if modules_dir.is_dir():
            for mf in modules_dir.glob("*.json"):
                try:
                    mod = _json.loads(mf.read_text(encoding="utf-8"))
                    if mod.get("risk_level") in min_levels:
                        for fp in mod.get("files", []):
                            base = fp.replace("\\", "/")
                            for nid in graph.nodes:
                                if base in nid or nid.endswith(base.replace(".py", "")):
                                    selected_ids.add(nid)
                                    break
                except Exception:
                    continue

    elif strategy == "hub":
        # Top N by degree centrality
        hub_sorted = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
        for nid, _ in hub_sorted[:limit]:
            selected_ids.add(nid)

    elif strategy == "architecture":
        # Module-level view: only PythonModule, JavaScriptModule, Class, Directory, Package
        arch_types = {"PythonModule", "JavaScriptModule", "Class", "Directory", "Package"}
        scored_arch = []
        for nid, node in graph.nodes.items():
            if node.entity_type in arch_types:
                scored_arch.append((nid, degree_map.get(nid, 0)))
        scored_arch.sort(key=lambda x: x[1], reverse=True)
        for nid, _ in scored_arch[:limit]:
            selected_ids.add(nid)

    # Include 1-hop neighbors of selected nodes (keeps context)
    if include_neighbors and len(selected_ids) < limit * 2:
        neighbor_ids: set[str] = set()
        for eid, edge in graph.edges.items():
            if edge.source_id in selected_ids:
                neighbor_ids.add(edge.target_id)
            elif edge.target_id in selected_ids:
                neighbor_ids.add(edge.source_id)
        # Add neighbors up to 2x limit
        remaining = limit * 2 - len(selected_ids)
        # Prioritize neighbors by degree
        neighbor_scored = [(nid, degree_map.get(nid, 0)) for nid in neighbor_ids - selected_ids]
        neighbor_scored.sort(key=lambda x: x[1], reverse=True)
        for nid, _ in neighbor_scored[:remaining]:
            selected_ids.add(nid)

    # Build filtered graph
    # Load intelligence data for risk coloring
    root = Path(state.get("root", "."))
    risk_map: dict[str, str] = {}  # file path -> risk level
    modules_dir = root / ".graqle" / "intelligence" / "modules"
    if modules_dir.is_dir():
        for mf in modules_dir.glob("*.json"):
            try:
                mod = _json.loads(mf.read_text(encoding="utf-8"))
                rl = mod.get("risk_level", "LOW")
                for fp in mod.get("files", []):
                    risk_map[fp.replace("\\", "/")] = rl
            except Exception:
                continue

    risk_colors = {
        "CRITICAL": "#ef4444",
        "HIGH": "#f97316",
        "MEDIUM": "#eab308",
        "LOW": "#22c55e",
    }

    nodes_out = []
    for nid in selected_ids:
        if nid not in graph.nodes:
            continue
        node = graph.nodes[nid]
        deg = degree_map.get(nid, 0)

        # Determine risk level for this node
        node_risk = "LOW"
        for fp, rl in risk_map.items():
            if fp.replace(".py", "") in nid or nid.endswith(Path(fp).stem):
                node_risk = rl
                break

        nodes_out.append({
            "id": nid,
            "label": node.label,
            "type": node.entity_type,
            "description": (node.description or "")[:200],
            "degree": deg,
            "size": max(10, min(50, 10 + math.sqrt(deg) * 8)),
            "color": risk_colors.get(node_risk, _type_color(node.entity_type)),
            "risk": node_risk,
        })

    links_out = []
    selected_set = selected_ids
    for eid, edge in graph.edges.items():
        if edge.source_id in selected_set and edge.target_id in selected_set:
            links_out.append({
                "id": eid,
                "source": edge.source_id,
                "target": edge.target_id,
                "relationship": edge.relationship,
                "weight": getattr(edge, "weight", 1.0),
            })

    return {
        "nodes": nodes_out,
        "links": links_out,
        "strategy": strategy,
        "total_before": total_before,
        "total_after": len(nodes_out),
    }


@router.get("/graph/nodes")
async def graph_nodes(
    request: Request,
    q: str = Query("", description="Search query"),
    type: str = Query("", description="Filter by entity type"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """Paginated node list with search and type filter."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return {"nodes": [], "total": 0}

    filtered = []
    for nid, node in graph.nodes.items():
        if type and node.entity_type != type:
            continue
        if q:
            q_lower = q.lower()
            searchable = f"{node.label} {node.entity_type} {node.description or ''}".lower()
            if q_lower not in searchable:
                continue
        chunk_count = len(node.properties.get("chunks", []))
        filtered.append({
            "id": nid,
            "label": node.label,
            "type": node.entity_type,
            "description": (node.description or "")[:300],
            "chunks": chunk_count,
        })

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    return {"nodes": filtered[start:end], "total": total, "page": page, "size": size}


@router.get("/graph/node/{node_id:path}")
async def graph_node_detail(request: Request, node_id: str):
    """Single node detail with neighbors."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph or node_id not in graph.nodes:
        return {"error": "Node not found"}

    node = graph.nodes[node_id]
    chunks = node.properties.get("chunks", [])

    neighbors = []
    for eid, edge in graph.edges.items():
        if edge.source_id == node_id:
            target = graph.nodes.get(edge.target_id)
            if target:
                neighbors.append({
                    "id": edge.target_id,
                    "label": target.label,
                    "type": target.entity_type,
                    "relationship": edge.relationship,
                    "direction": "outgoing",
                })
        elif edge.target_id == node_id:
            source = graph.nodes.get(edge.source_id)
            if source:
                neighbors.append({
                    "id": edge.source_id,
                    "label": source.label,
                    "type": source.entity_type,
                    "relationship": edge.relationship,
                    "direction": "incoming",
                })

    return {
        "id": node_id,
        "label": node.label,
        "type": node.entity_type,
        "description": node.description,
        "chunks": [
            {"text": c.get("text", "")[:500], "type": c.get("type", "unknown")}
            for c in chunks[:10]
            if isinstance(c, dict)
        ],
        "chunk_count": len(chunks),
        "neighbors": neighbors,
        "properties": {
            k: v for k, v in node.properties.items()
            if k != "chunks" and not callable(v)
        },
    }


# ---------- Reasoning (SSE) ----------


@router.post("/reason")
async def reason_stream(request: Request):
    """Start reasoning and stream results via SSE.

    Supports two modes:
    - mode="fast" (default): 1 round, fewer nodes — answers in 5-15s
    - mode="deep": multi-round orchestration — thorough but 30-120s
    """
    body = await request.json()
    query = body.get("query", "")
    mode = body.get("mode", "fast")
    max_rounds = body.get("max_rounds")
    strategy = body.get("strategy")
    ring_fence = body.get("ring_fence", "read-only")  # Default: graph protected
    project = body.get("project")  # User's selected project

    state = request.app.state.studio_state
    graph = state.get("graph")

    # Per-project graph loading: if a project is specified and we have S3 access,
    # load that project's graph instead of the default Lambda graph.
    if project:
        project_graph = await _load_project_graph(request, project)
        if project_graph is not None:
            graph = project_graph

    if not graph:
        return JSONResponse({"error": "No graph loaded"}, status_code=400)

    config = state.get("config")
    if strategy is None and config:
        strategy = getattr(getattr(config, "activation", None), "strategy", "chunk")
    strategy = strategy or "chunk"

    # Fast mode: 1 round, cap nodes for speed
    fast_max_nodes = None
    if mode == "fast":
        max_rounds = max_rounds or 1
        fast_max_nodes = min(getattr(getattr(graph.config, "activation", None), "max_nodes", 8), 8)
    else:
        max_rounds = max_rounds or 3  # deep mode: 3 rounds max (was 5)

    async def event_generator():
        import json
        import time
        try:
            start = time.time()

            # Emit activation event
            activation_start = time.time()
            node_ids = graph._activate_subgraph(query, strategy)
            node_ids = [nid for nid in node_ids if nid in graph.nodes]
            # Fast mode: cap activated nodes for speed (no shared state mutation)
            if fast_max_nodes and len(node_ids) > fast_max_nodes:
                node_ids = node_ids[:fast_max_nodes]
            activation_ms = (time.time() - activation_start) * 1000

            activated_nodes = []
            for nid in node_ids:
                node = graph.nodes.get(nid)
                if node:
                    activated_nodes.append({
                        "id": nid,
                        "label": node.label,
                        "type": node.entity_type,
                    })

            yield f"data: {json.dumps({'type': 'activation', 'nodes': activated_nodes, 'count': len(node_ids), 'latency_ms': round(activation_ms, 1), 'mode': mode, 'ring_fence': ring_fence})}\n\n"

            # Run reasoning with pre-activated nodes
            result = await graph.areason(
                query,
                max_rounds=max_rounds,
                strategy=strategy,
                node_ids=node_ids,
            )
            latency = (time.time() - start) * 1000

            # Emit final answer
            yield f"data: {json.dumps({'type': 'final_answer', 'answer': result.answer, 'confidence': result.confidence, 'rounds': result.rounds_completed, 'node_count': result.node_count, 'cost_usd': result.cost_usd, 'latency_ms': round(latency, 1), 'active_nodes': result.active_nodes, 'mode': mode, 'ring_fence': ring_fence})}\n\n"
        except Exception as e:
            logger.exception("Reasoning failed")
            error_msg = str(e)
            # Provide clear message for common failures
            if "credit balance is too low" in error_msg:
                error_msg = "Anthropic API credits depleted. Add credits at console.anthropic.com/settings/billing or switch to a free backend (Ollama, Groq) in graqle.yaml."
            elif "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                error_msg = "API key missing or invalid. Set ANTHROPIC_API_KEY environment variable or configure a backend in graqle.yaml."
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
        finally:
            pass
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------- HTMX Partials ----------


@router.get("/partials/metrics-cards", response_class=HTMLResponse)
async def partial_metrics_cards(request: Request):
    """Auto-refreshing metrics cards fragment."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    metrics = state.get("metrics")

    node_count = len(graph.nodes) if graph else 0
    edge_count = len(graph.edges) if graph else 0

    m = {}
    if metrics:
        try:
            m = metrics.get_summary()
        except Exception:
            pass

    tokens_saved = m.get("tokens_saved", 0)
    queries = m.get("queries", 0)
    context_loads = m.get("context_loads", 0)
    savings_usd = tokens_saved * 0.000003  # ~$3 per 1M tokens (Claude Sonnet input pricing)

    return f"""
    <div class="grid-4">
        <div class="metric-card blue">
            <div class="icon">&#9673;</div>
            <div class="label">Nodes</div>
            <div class="value">{node_count}</div>
        </div>
        <div class="metric-card green">
            <div class="icon">&#8596;</div>
            <div class="label">Edges</div>
            <div class="value">{edge_count}</div>
        </div>
        <div class="metric-card purple">
            <div class="icon">&#9889;</div>
            <div class="label">Tokens Saved</div>
            <div class="value">{_format_number(tokens_saved)}</div>
        </div>
        <div class="metric-card yellow">
            <div class="icon">$</div>
            <div class="label">Cost Saved</div>
            <div class="value">${savings_usd:,.2f}</div>
        </div>
    </div>
    """


@router.get("/partials/node-detail/{node_id:path}", response_class=HTMLResponse)
async def partial_node_detail(request: Request, node_id: str):
    """Node detail panel for HTMX."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph or node_id not in graph.nodes:
        return "<div class='node-detail'><p>Node not found</p></div>"

    node = graph.nodes[node_id]
    chunks = node.properties.get("chunks", [])
    desc = node.description or "No description"

    # Count neighbors
    neighbor_count = 0
    for edge in graph.edges.values():
        if edge.source_id == node_id or edge.target_id == node_id:
            neighbor_count += 1

    chunk_html = ""
    for c in chunks[:5]:
        if isinstance(c, dict):
            ctype = c.get("type", "unknown")
            ctext = c.get("text", "")[:200]
            chunk_html += f'<div class="chunk"><span class="chunk-type">{ctype}</span> {ctext}</div>'

    return f"""
    <div class="node-detail">
        <h3>{node.label}</h3>
        <span class="badge" style="background:{_type_color(node.entity_type)}">{node.entity_type}</span>
        <p class="description">{desc}</p>
        <div class="stats">
            <span>{len(chunks)} chunks</span> &middot;
            <span>{neighbor_count} connections</span>
        </div>
        <div class="chunks">{chunk_html}</div>
    </div>
    """


# ---------- Cloud ----------


@router.get("/cloud/status")
async def cloud_status():
    """Return cloud connection status."""
    from graqle.cloud.credentials import get_cloud_status
    return get_cloud_status()


@router.post("/cloud/connect")
async def cloud_connect(request: Request):
    """Connect to GraQle Cloud with API key."""
    body = await request.json()
    api_key = body.get("api_key", "")
    email = body.get("email", "")

    if not api_key.startswith("grq_"):
        return {"success": False, "error": "Invalid API key format"}

    from graqle.cloud.credentials import CloudCredentials, save_credentials
    creds = CloudCredentials(
        api_key=api_key,
        email=email,
        plan="free",
        connected=True,
    )
    save_credentials(creds)
    return {"success": True, "plan": "free"}


@router.post("/cloud/disconnect")
async def cloud_disconnect():
    """Disconnect from GraQle Cloud."""
    from graqle.cloud.credentials import clear_credentials
    clear_credentials()
    return {"success": True}


# ---------- Settings ----------


@router.get("/settings")
async def settings_view(request: Request):
    """Return read-only config for the Studio settings page."""
    state = request.app.state.studio_state
    config = state.get("config")
    graph = state.get("graph")

    node_count = len(getattr(graph, "nodes", {})) if graph else 0
    edge_count = len(getattr(graph, "edges", {})) if graph else 0

    config_dict = {}
    if config:
        try:
            config_dict = config.model_dump() if hasattr(config, "model_dump") else {}
        except Exception:
            config_dict = {"error": "Could not serialize config"}

    return {
        "graph": {
            "node_count": node_count,
            "edge_count": edge_count,
            "loaded": graph is not None,
        },
        "config": config_dict,
    }


# ---------- Helpers ----------

_TYPE_COLORS = {
    "SERVICE": "#8b5cf6", "COMPONENT": "#a78bfa", "MODULE": "#7c3aed",
    "FUNCTION": "#6d28d9", "CLASS": "#5b21b6", "METHOD": "#4c1d95",
    "FILE": "#3b82f6", "DIRECTORY": "#2563eb", "PACKAGE": "#1d4ed8",
    "CONFIG": "#f59e0b", "ENVIRONMENT": "#d97706", "VARIABLE": "#b45309",
    "DATABASE": "#10b981", "TABLE": "#059669", "SCHEMA": "#047857",
    "MODEL": "#065f46", "REGULATION": "#f97316", "POLICY": "#ea580c",
    "CONTROL": "#dc2626", "RISK": "#ef4444", "STANDARD": "#f87171",
    "ADR": "#06b6d4", "LESSON": "#ec4899", "MISTAKE": "#f43f5e",
    "PAPER": "#d946ef", "PATENT": "#c026d3", "TEST": "#22c55e",
    "BENCHMARK": "#16a34a", "PERSON": "#f472b6", "ORGANIZATION": "#e879f9",
}
_DEFAULT_COLOR = "#64748b"


def _type_color(entity_type: str) -> str:
    return _TYPE_COLORS.get(entity_type.upper(), _DEFAULT_COLOR)


def _format_number(n: int | float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


# ---------- Neptune ----------


@router.get("/lessons")
async def lessons(
    request: Request,
    operation: str = Query("", description="Filter lessons by operation/topic"),
    severity: str = Query("all", description="Minimum severity: all, high, critical"),
):
    """Return LESSON / MISTAKE / SAFETY / ADR nodes from the knowledge graph.

    Team plan: lessons are shared across all synced projects via Neptune.
    Free plan: lessons from local graph only.
    """
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return JSONResponse({"lessons": [], "count": 0, "source": "no_graph"})

    _LESSON_TYPES = frozenset({"LESSON", "MISTAKE", "SAFETY", "ADR", "DECISION"})
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    filter_threshold = {"critical": 0, "high": 1, "all": 99}.get(severity.lower(), 99)
    tokens = operation.lower().split() if operation else []

    results = []
    for node in graph.nodes.values():
        if node.entity_type.upper() not in _LESSON_TYPES:
            continue
        sev = node.properties.get("severity", "MEDIUM").upper()
        if severity_order.get(sev, 2) > filter_threshold:
            continue
        haystack = f"{node.id} {node.label} {node.description[:300]}".lower()
        score = sum(1.0 for t in tokens if t in haystack) if tokens else 1.0
        if score > 0:
            results.append({
                "id": node.id,
                "label": node.label,
                "entity_type": node.entity_type,
                "severity": sev,
                "description": node.description[:300],
                "hit_count": node.properties.get("hit_count", 0),
                "score": score,
            })

    results.sort(key=lambda x: (severity_order.get(x["severity"], 2), -x["score"]))
    return JSONResponse({
        "lessons": results[:50],
        "count": len(results),
        "source": "local_graph",
        "filter": {"operation": operation, "severity": severity},
    })


@router.get("/neptune/health")
async def neptune_health_check():
    """Check Neptune connectivity from Lambda."""
    try:
        from graqle.connectors.neptune import neptune_health, reset_availability
        reset_availability()  # Clear any cached unavailability from previous timeout
        return neptune_health()
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


@router.get("/neptune/stats")
async def neptune_stats():
    """Get Neptune graph stats."""
    try:
        from graqle.connectors.neptune import get_graph_stats
        return get_graph_stats("graqle-sdk")
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


@router.post("/neptune/upload")
async def neptune_upload(request: Request):
    """Upload current in-memory graph to Neptune.

    This reads the graph from Lambda's in-memory state (loaded from S3)
    and pushes all nodes + edges to Neptune. Designed to run once.
    """
    import time
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return JSONResponse({"error": "No graph loaded in memory"}, status_code=400)

    try:
        from graqle.connectors.neptune import (
            upsert_nodes, upsert_edges, get_graph_stats, neptune_health,
            reset_availability,
        )
        reset_availability()

        # Check connectivity first
        health = neptune_health()
        if health.get("status") != "connected":
            return JSONResponse(
                {"error": f"Neptune not reachable: {health.get('error', '?')}"},
                status_code=503,
            )

        project_id = "graqle-sdk"
        start = time.time()

        # Transform nodes
        nodes = []
        for nid, node in graph.nodes.items():
            # Count degree
            degree = 0
            for eid, edge in graph.edges.items():
                if edge.source_id == nid or edge.target_id == nid:
                    degree += 1
            nodes.append({
                "id": nid,
                "label": node.label,
                "type": node.entity_type,
                "description": (node.description or "")[:500],
                "size": max(8, min(40, 8 + (degree ** 0.5) * 6)),
                "degree": degree,
                "color": _type_color(node.entity_type),
            })

        # Transform edges
        edges = []
        for eid, edge in graph.edges.items():
            edges.append({
                "source": edge.source_id,
                "target": edge.target_id,
                "relationship": edge.relationship,
                "weight": getattr(edge, "weight", 1.0),
            })

        # Upload in batches
        uploaded_nodes = 0
        batch_size = 50
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            uploaded_nodes += upsert_nodes(project_id, batch)

        uploaded_edges = 0
        for i in range(0, len(edges), batch_size):
            batch = edges[i:i + batch_size]
            uploaded_edges += upsert_edges(project_id, batch)

        elapsed = time.time() - start

        # Verify
        stats = get_graph_stats(project_id)

        return {
            "status": "ok",
            "uploaded_nodes": uploaded_nodes,
            "uploaded_edges": uploaded_edges,
            "elapsed_seconds": round(elapsed, 1),
            "neptune_stats": stats,
        }

    except Exception as e:
        logger.exception("Neptune upload failed")
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


# ── CLI/MCP Tool Bridge ───────────────────────────────────────────────────────

_ALLOWED_TOOLS = frozenset({
    "graq_context", "kogni_context",
    "graq_reason", "kogni_reason",
    "graq_inspect", "kogni_inspect",
    "graq_lessons", "kogni_lessons",
    "graq_impact", "kogni_impact",
    "graq_preflight", "kogni_preflight",
    "graq_learn", "kogni_learn",
    "graq_predict", "kogni_predict",
    "graq_safety_check", "kogni_safety_check",
})


@router.post("/cli/exec")
async def cli_exec(request: Request):
    """Execute a graq MCP tool from Studio chat and stream the result as SSE.

    Request body:
        {"tool": "graq_reason", "arguments": {"query": "..."}}

    SSE stream:
        data: {"type": "chunk", "text": "..."}
        data: {"type": "done", "text": "<full result>"}
        data: {"type": "error", "message": "..."}
    """
    import json as _json

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    tool_name = body.get("tool", "")
    arguments = body.get("arguments", {})

    if not tool_name:
        return JSONResponse({"error": "Missing 'tool' field"}, status_code=400)

    if tool_name not in _ALLOWED_TOOLS:
        return JSONResponse(
            {"error": f"Tool '{tool_name}' not allowed. Allowed: {sorted(_ALLOWED_TOOLS)}"},
            status_code=400,
        )

    async def event_generator():
        try:
            from graqle.plugins.mcp_dev_server import KogniDevServer
            server = KogniDevServer()
            result = await server.handle_tool(tool_name, arguments)
            # Emit full result as a single done event (tools return a complete string)
            yield f"data: {_json.dumps({'type': 'done', 'text': result})}\n\n"
        except Exception as e:
            logger.warning("cli/exec tool '%s' failed: %s", tool_name, e)
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)[:500]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Studio Chat with Slash Commands + Plain Language Routing ─────────────────

# Slash command → (tool_name, argument_key) mapping
_SLASH_COMMANDS: dict[str, tuple[str, str]] = {
    "reason":     ("graq_reason",     "question"),
    "r":          ("graq_reason",     "question"),
    "context":    ("graq_context",    "name"),
    "ctx":        ("graq_context",    "name"),
    "inspect":    ("graq_inspect",    "query"),
    "lessons":    ("graq_lessons",    "topic"),
    "learn":      ("graq_lessons",    "topic"),
    "impact":     ("graq_impact",     "node_name"),
    "preflight":  ("graq_preflight",  "change_description"),
    "pre":        ("graq_preflight",  "change_description"),
    "predict":    ("graq_predict",    "question"),
    "safety":     ("graq_safety_check", "change_description"),
}

# Keywords that indicate intent — map to the best tool
_INTENT_KEYWORDS: list[tuple[set[str], str]] = [
    ({"impact", "affects", "downstream", "depends", "blast"}, "graq_impact"),
    ({"lesson", "mistake", "pitfall", "warn", "issue"}, "graq_lessons"),
    ({"preflight", "safe", "risk", "before", "should i"}, "graq_preflight"),
    ({"predict", "forecast", "will", "next", "future"}, "graq_predict"),
    ({"inspect", "show", "list", "stats", "count", "how many"}, "graq_inspect"),
    ({"context", "about", "what is", "explain", "describe"}, "graq_context"),
]


def _route_chat_message(message: str) -> tuple[str, dict]:
    """Route a plain-language or slash-command message to the best graq tool.

    Returns (tool_name, arguments_dict).
    """
    msg = message.strip()

    # Slash command: /reason <text>, /context <name>, etc.
    if msg.startswith("/"):
        parts = msg[1:].split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if cmd in _SLASH_COMMANDS:
            tool, arg_key = _SLASH_COMMANDS[cmd]
            return tool, {arg_key: rest}

    # Plain-language routing: keyword matching
    lower = msg.lower()
    for keywords, tool in _INTENT_KEYWORDS:
        if any(kw in lower for kw in keywords):
            _TOOL_ARG_MAP = {
                "graq_impact": "node_name",
                "graq_lessons": "topic",
                "graq_preflight": "change_description",
                "graq_safety_check": "change_description",
                "graq_predict": "question",
                "graq_inspect": "query",
                "graq_context": "name",
            }
            return tool, {_TOOL_ARG_MAP.get(tool, "question"): msg}

    # Default: graq_reason handles everything else
    return "graq_reason", {"question": msg}


@router.post("/chat")
async def studio_chat(request: Request):
    """Studio chat with slash-command support and plain-language routing.

    Accepts natural language or slash commands. Routes to the appropriate
    graq tool and streams the result as SSE.

    Request body:
        {"message": "/reason how does AuthService work?"}
        {"message": "what lessons are there about CORS?"}
        {"message": "/context JwtModule"}

    Slash commands available:
        /reason <question>     → graq_reason
        /context <name>        → graq_context
        /lessons <topic>       → graq_lessons
        /impact <node>         → graq_impact
        /preflight <change>    → graq_preflight
        /predict <question>    → graq_predict
        /inspect <query>       → graq_inspect
        /safety <change>       → graq_safety_check
    """
    import json as _json

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "Missing 'message' field"}, status_code=400)

    tool_name, arguments = _route_chat_message(message)

    async def event_generator():
        # Emit routing decision so the UI can show which tool was invoked
        yield f"data: {_json.dumps({'type': 'routing', 'tool': tool_name, 'arguments': arguments})}\n\n"

        try:
            from graqle.plugins.mcp_dev_server import KogniDevServer
            server = KogniDevServer()
            result = await server.handle_tool(tool_name, arguments)
            yield f"data: {_json.dumps({'type': 'done', 'tool': tool_name, 'text': result})}\n\n"
        except Exception as e:
            logger.warning("studio_chat tool '%s' failed: %s", tool_name, e)
            yield f"data: {_json.dumps({'type': 'error', 'tool': tool_name, 'message': str(e)[:500]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
