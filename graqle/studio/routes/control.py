"""Graqle Studio — Control Plane & Share API routes.

Sprint 4: Multi-instance management and shareable badges.

Routes:
- GET  /instances        → List detected Graqle instances
- GET  /instance/{name}  → Instance detail (health, nodes, DRACE)
- GET  /badges/drace     → Shareable DRACE badge (SVG)
- GET  /badges/health    → Shareable health badge (SVG)
- GET  /badges/nodes     → Shareable node count badge (SVG)
- GET  /share/config     → Markdown snippets for badge embedding
"""

# ── graqle:intelligence ──
# module: graqle.studio.routes.control
# risk: LOW (impact radius: 1 modules)
# consumers: test_control_routes
# dependencies: json, logging, pathlib, typing, fastapi +1 more
# constraints: none
# ── /graqle:intelligence ──

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

logger = logging.getLogger("graqle.studio.control")

router = APIRouter(tags=["control"])


def _get_root(request: Request) -> Path:
    state = getattr(request.app.state, "studio_state", {})
    return Path(state.get("root", "."))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Instance Discovery ───────────────────────────────────────────────


def _discover_instances(root: Path) -> list[dict[str, Any]]:
    """Discover Graqle instances in current and parent directories."""
    instances = []

    # Current instance
    graqle_dir = root / ".graqle"
    if graqle_dir.is_dir():
        instances.append(_build_instance_info(root))

    # Sibling directories (same parent)
    parent = root.parent
    if parent.is_dir():
        for sibling in parent.iterdir():
            if sibling.is_dir() and sibling != root:
                if (sibling / ".graqle").is_dir() or (sibling / "graqle.yaml").exists():
                    instances.append(_build_instance_info(sibling))

    return instances


def _build_instance_info(path: Path) -> dict[str, Any]:
    """Build instance summary from a Graqle project directory."""
    graqle_dir = path / ".graqle"
    name = path.name

    info: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "active": False,
        "health": "UNKNOWN",
        "nodes": 0,
        "edges": 0,
        "drace_score": None,
        "last_scan": None,
        "connector": "networkx",
    }

    # Read scorecard
    scorecard = _read_json(graqle_dir / "scorecard.json")
    if scorecard:
        info["health"] = scorecard.get("health", "UNKNOWN")
        info["nodes"] = scorecard.get("nodes", 0)
        info["active"] = True

    # Read config for connector type
    config_path = path / "graqle.yaml"
    if config_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            info["connector"] = cfg.get("graph", {}).get("connector", "networkx")
        except Exception:
            pass

    # Latest DRACE score
    audit_dir = graqle_dir / "governance" / "audit"
    if audit_dir.is_dir():
        sessions = sorted(audit_dir.glob("*.json"), reverse=True)
        if sessions:
            latest = _read_json(sessions[0])
            if isinstance(latest, dict):
                info["drace_score"] = latest.get("drace_score")
                info["last_scan"] = latest.get("started")

    return info


@router.get("/instances")
async def list_instances(request: Request):
    """List all detected Graqle instances."""
    root = _get_root(request)
    instances = _discover_instances(root)
    return {
        "instances": instances,
        "total": len(instances),
        "current": root.name,
    }


@router.get("/instance/{name}")
async def instance_detail(request: Request, name: str):
    """Get detailed info for a specific instance."""
    root = _get_root(request)
    instances = _discover_instances(root)
    for inst in instances:
        if inst["name"] == name:
            return inst
    return {"error": f"Instance '{name}' not found"}


# ── Shareable Badges (SVG) ───────────────────────────────────────────


def _badge_svg(label: str, value: str, color: str) -> str:
    """Generate a shields.io-style SVG badge."""
    label_width = len(label) * 6.5 + 12
    value_width = len(value) * 6.5 + 12
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11">
    <text x="{label_width/2}" y="14">{label}</text>
    <text x="{label_width + value_width/2}" y="14">{value}</text>
  </g>
</svg>"""


def _drace_color(score: float | None) -> str:
    if score is None:
        return "#9f9f9f"
    if score >= 0.8:
        return "#4c1"
    if score >= 0.6:
        return "#dfb317"
    return "#e05d44"


def _health_color(health: str) -> str:
    colors = {
        "HEALTHY": "#4c1",
        "MODERATE": "#dfb317",
        "WARNING": "#fe7d37",
        "CRITICAL": "#e05d44",
    }
    return colors.get(health, "#9f9f9f")


@router.get("/badges/drace")
async def drace_badge(request: Request):
    """Shareable DRACE score badge (SVG)."""
    root = _get_root(request)
    graqle_dir = root / ".graqle"

    score = None
    audit_dir = graqle_dir / "governance" / "audit"
    if audit_dir.is_dir():
        sessions = sorted(audit_dir.glob("*.json"), reverse=True)
        if sessions:
            latest = _read_json(sessions[0])
            if isinstance(latest, dict):
                score = latest.get("drace_score")

    value = f"{score:.2f}" if score is not None else "N/A"
    label_text = "DRACE"
    if score is not None and score >= 0.8:
        label_text = "DRACE GOOD"
    elif score is not None and score >= 0.6:
        label_text = "DRACE OK"

    svg = _badge_svg("Graqle", f"{label_text} {value}", _drace_color(score))
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/badges/health")
async def health_badge(request: Request):
    """Shareable health status badge (SVG)."""
    root = _get_root(request)
    scorecard = _read_json(root / ".graqle" / "scorecard.json")
    health = scorecard.get("health", "UNKNOWN") if scorecard else "UNKNOWN"

    svg = _badge_svg("Graqle", health, _health_color(health))
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/badges/nodes")
async def nodes_badge(request: Request):
    """Shareable node count badge (SVG)."""
    root = _get_root(request)
    scorecard = _read_json(root / ".graqle" / "scorecard.json")
    nodes = scorecard.get("nodes", 0) if scorecard else 0

    svg = _badge_svg("Graqle Nodes", str(nodes), "#007ec6")
    return Response(content=svg, media_type="image/svg+xml")


# ── Share Config ─────────────────────────────────────────────────────


@router.get("/share/config")
async def share_config(request: Request):
    """Get markdown snippets for embedding badges in READMEs."""
    base_url = str(request.base_url).rstrip("/")
    prefix = f"{base_url}/studio/api/control"

    return {
        "badges": {
            "drace": {
                "url": f"{prefix}/badges/drace",
                "markdown": f"![DRACE]({prefix}/badges/drace)",
                "html": f'<img src="{prefix}/badges/drace" alt="DRACE Score"/>',
            },
            "health": {
                "url": f"{prefix}/badges/health",
                "markdown": f"![Health]({prefix}/badges/health)",
                "html": f'<img src="{prefix}/badges/health" alt="Health Status"/>',
            },
            "nodes": {
                "url": f"{prefix}/badges/nodes",
                "markdown": f"![Nodes]({prefix}/badges/nodes)",
                "html": f'<img src="{prefix}/badges/nodes" alt="Node Count"/>',
            },
        },
        "embed_tip": "Add these to your README.md for live-updating Graqle badges.",
    }
