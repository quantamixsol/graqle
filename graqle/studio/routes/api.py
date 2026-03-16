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

    nodes = []
    for nid, node in graph.nodes.items():
        chunk_count = len(node.properties.get("chunks", []))
        neighbors = []
        for eid, edge in graph.edges.items():
            if edge.source_id == nid:
                neighbors.append(edge.target_id)
            elif edge.target_id == nid:
                neighbors.append(edge.source_id)

        nodes.append({
            "id": nid,
            "label": node.label,
            "type": node.entity_type,
            "description": (node.description or "")[:200],
            "chunks": chunk_count,
            "degree": len(neighbors),
            "size": max(8, min(40, 8 + math.sqrt(len(neighbors)) * 6)),
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

    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return JSONResponse({"error": "No graph loaded"}, status_code=400)

    config = state.get("config")
    if strategy is None and config:
        strategy = getattr(getattr(config, "activation", None), "strategy", "chunk")
    strategy = strategy or "chunk"

    # Fast mode: 1 round, cap nodes for speed
    if mode == "fast":
        max_rounds = max_rounds or 1
        # Temporarily reduce max_nodes for fast activation
        original_max = graph.config.activation.max_nodes
        graph.config.activation.max_nodes = min(original_max, 8)
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

            yield f"data: {json.dumps({'type': 'activation', 'nodes': activated_nodes, 'count': len(node_ids), 'latency_ms': round(activation_ms, 1), 'mode': mode})}\n\n"

            # Run reasoning with pre-activated nodes
            result = await graph.areason(
                query,
                max_rounds=max_rounds,
                strategy=strategy,
                node_ids=node_ids,
            )
            latency = (time.time() - start) * 1000

            # Emit final answer
            yield f"data: {json.dumps({'type': 'final_answer', 'answer': result.answer, 'confidence': result.confidence, 'rounds': result.rounds_completed, 'node_count': result.node_count, 'cost_usd': result.cost_usd, 'latency_ms': round(latency, 1), 'active_nodes': result.active_nodes, 'mode': mode})}\n\n"
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
            # Restore original max_nodes if we changed it
            if mode == "fast":
                graph.config.activation.max_nodes = original_max
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
    savings_usd = tokens_saved * 0.000015  # $0.015 per 1K tokens

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
    """Connect to Graqle Cloud with API key."""
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
    """Disconnect from Graqle Cloud."""
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
