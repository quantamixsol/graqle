"""Studio API routes — JSON endpoints for dashboard data."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

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
    """Start reasoning and stream results via SSE."""
    body = await request.json()
    query = body.get("query", "")
    max_rounds = body.get("max_rounds", 5)
    strategy = body.get("strategy")

    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return JSONResponse({"error": "No graph loaded"}, status_code=400)

    config = state.get("config")
    if strategy is None and config:
        strategy = getattr(getattr(config, "activation", None), "strategy", "chunk")
    strategy = strategy or "chunk"

    async def event_generator():
        import json
        import time
        try:
            start = time.time()
            result = await graph.areason(query, max_rounds=max_rounds, strategy=strategy)
            latency = (time.time() - start) * 1000

            # Emit final answer
            yield f"data: {json.dumps({'type': 'final_answer', 'answer': result.answer, 'confidence': result.confidence, 'rounds': result.rounds_completed, 'node_count': result.node_count, 'cost_usd': result.cost_usd, 'latency_ms': latency, 'active_nodes': result.active_nodes})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
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
