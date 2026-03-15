"""Studio dashboard page routes — serve Jinja2 templates."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.dashboard
# risk: LOW (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, logging, fastapi, responses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_ctx(request: Request) -> dict:
    """Build common template context."""
    state = request.app.state.studio_state
    graph = state.get("graph")
    config = state.get("config")
    metrics = state.get("metrics")

    node_count = len(graph.nodes) if graph else 0
    edge_count = len(graph.edges) if graph else 0

    # Collect node types
    node_types: dict[str, int] = {}
    if graph:
        for node in graph.nodes.values():
            t = getattr(node, "entity_type", "UNKNOWN")
            node_types[t] = node_types.get(t, 0) + 1

    # Metrics summary
    metrics_summary = {}
    if metrics:
        try:
            metrics_summary = metrics.get_summary()
        except Exception:
            pass

    # Version
    try:
        from graqle.__version__ import __version__
        version = __version__
    except Exception:
        version = "unknown"

    return {
        "request": request,
        "node_count": node_count,
        "edge_count": edge_count,
        "node_types": node_types,
        "metrics": metrics_summary,
        "config": config,
        "graph_loaded": graph is not None,
        "version": version,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    templates = request.app.state.studio_templates
    ctx = _get_ctx(request)
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/graph", response_class=HTMLResponse)
async def graph_explorer(request: Request):
    """Graph explorer with D3 force-directed visualization."""
    templates = request.app.state.studio_templates
    ctx = _get_ctx(request)
    return templates.TemplateResponse("graph.html", ctx)


@router.get("/reasoning", response_class=HTMLResponse)
async def reasoning(request: Request):
    """Live reasoning view."""
    templates = request.app.state.studio_templates
    ctx = _get_ctx(request)
    return templates.TemplateResponse("reasoning.html", ctx)


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    """Detailed metrics page."""
    templates = request.app.state.studio_templates
    ctx = _get_ctx(request)
    return templates.TemplateResponse("metrics.html", ctx)


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    """Settings page."""
    templates = request.app.state.studio_templates
    ctx = _get_ctx(request)
    return templates.TemplateResponse("settings.html", ctx)
