"""Studio Learning API — endpoints for learning metrics, skill counts, recompile history."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.learning
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, logging, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_root(request: Request) -> Path:
    """Resolve project root from studio state."""
    state = request.app.state.studio_state
    root = state.get("root")
    if root:
        return Path(root)
    return Path.cwd()


@router.get("/summary")
async def learning_summary(request: Request) -> JSONResponse:
    """Full learning summary: events, domains, skills, recompiles."""
    root = _get_root(request)
    try:
        from graqle.intelligence.learning_tracker import LearningTracker
        tracker = LearningTracker(root)
        summary = tracker.get_summary()
        return JSONResponse(summary)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/skills")
async def skill_counts(request: Request) -> JSONResponse:
    """Skill activation counts grouped by domain."""
    root = _get_root(request)

    # Get available skills from ontology
    try:
        from graqle.ontology.domains import collect_all_skills
        all_skills = collect_all_skills()
        total_available = len(all_skills)
    except Exception:
        total_available = 201  # Known count

    # Get activated skill counts
    try:
        from graqle.intelligence.learning_tracker import LearningTracker
        tracker = LearningTracker(root)
        domain_counts = tracker.get_skill_counts_by_domain()
        activated = sum(domain_counts.values())
    except Exception:
        domain_counts = {}
        activated = 0

    # Domain skill availability
    domain_available = {
        "engineering": 45,
        "governance": 56,  # v1 + v3
        "financial": 22,
        "marketing": 20,
        "legal": 15,
        "data_analytics": 15,
        "security": 4,
        "testing": 3,
        "general": 25,
    }

    return JSONResponse({
        "total_available": total_available,
        "total_activated": activated,
        "domain_available": domain_available,
        "domain_activated": domain_counts,
    })


@router.get("/activation-memory")
async def activation_memory_stats(request: Request) -> JSONResponse:
    """Activation memory stats: most/least useful nodes."""
    root = _get_root(request)
    memory_path = root / ".graqle" / "activation_memory.json"

    if not memory_path.exists():
        return JSONResponse({"nodes": [], "total_queries": 0})

    try:
        data = json.loads(memory_path.read_text(encoding="utf-8"))
        records = data.get("records", {})

        # Build node stats sorted by usefulness
        nodes = []
        for nid, rec in records.items():
            activations = rec.get("activations", 0)
            useful = rec.get("useful_activations", 0)
            ratio = useful / activations if activations > 0 else 0.0
            nodes.append({
                "node_id": nid,
                "short_name": nid.rsplit("/", 1)[-1] if "/" in nid else nid,
                "activations": activations,
                "useful_activations": useful,
                "usefulness_ratio": round(ratio, 2),
                "avg_confidence": round(rec.get("avg_confidence", 0.0), 2),
            })

        nodes.sort(key=lambda x: x["usefulness_ratio"], reverse=True)

        return JSONResponse({
            "total_queries": data.get("total_queries", 0),
            "total_nodes_tracked": len(nodes),
            "most_useful": nodes[:10],
            "least_useful": sorted(nodes, key=lambda x: x["usefulness_ratio"])[:5],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/recompile-history")
async def recompile_history(request: Request) -> JSONResponse:
    """Recompile events: manual + auto-staleness."""
    root = _get_root(request)
    try:
        from graqle.intelligence.learning_tracker import LearningTracker
        tracker = LearningTracker(root)
        data = tracker._load()
        recompiles = [
            e for e in data.get("events", [])
            if e.get("type") == "recompile"
        ]
        return JSONResponse({
            "total_recompiles": data.get("total_recompiles", 0),
            "recent": recompiles[-20:],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
