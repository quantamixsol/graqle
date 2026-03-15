"""Studio Intelligence API — endpoints for intelligence dashboard data."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.intelligence
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_gds_intelligence
# dependencies: __future__, json, logging, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_graqle_root(request: Request) -> Path | None:
    """Resolve .graqle/ directory from studio state."""
    state = request.app.state.studio_state
    root = state.get("root")
    if root:
        p = Path(root) / ".graqle"
        if p.is_dir():
            return p
    # Fallback: walk up from CWD
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".graqle"
        if candidate.is_dir():
            return candidate
    return None


def _read_json(path: Path) -> dict | list | None:
    """Read a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ---------- Scorecard ----------


@router.get("/scorecard")
async def intelligence_scorecard(request: Request):
    """Return compiled intelligence scorecard."""
    root = _get_graqle_root(request)
    if not root:
        return {"error": "No .graqle directory found"}

    data = _read_json(root / "scorecard.json")
    if not data:
        return {"error": "No scorecard — run `graq compile` first"}
    return data


# ---------- Modules ----------


@router.get("/modules")
async def intelligence_modules(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    risk: str = Query("", description="Filter by risk level: LOW, MEDIUM, HIGH, CRITICAL"),
    search: str = Query("", description="Search module name"),
    sort: str = Query("risk_score", description="Sort field: risk_score, impact_radius, consumer_count, module"),
    order: str = Query("desc", description="Sort order: asc, desc"),
):
    """Return paginated module list from compiled intelligence."""
    root = _get_graqle_root(request)
    if not root:
        return {"modules": [], "total": 0, "error": "No .graqle directory found"}

    data = _read_json(root / "intelligence" / "module_index.json")
    if not data or "modules" not in data:
        return {"modules": [], "total": 0, "error": "No module index — run `graq compile` first"}

    modules = data["modules"]

    # Filter by risk level
    if risk:
        risk_upper = risk.upper()
        modules = [m for m in modules if m.get("risk_level", "").upper() == risk_upper]

    # Filter by search term
    if search:
        search_lower = search.lower()
        modules = [m for m in modules if search_lower in m.get("module", "").lower()]

    # Sort
    reverse = order.lower() != "asc"
    sort_key = sort if sort in ("risk_score", "impact_radius", "consumer_count", "function_count", "module") else "risk_score"
    if sort_key == "module":
        modules.sort(key=lambda m: m.get("module", ""), reverse=reverse)
    else:
        modules.sort(key=lambda m: m.get(sort_key, 0), reverse=reverse)

    total = len(modules)
    page = modules[offset:offset + limit]

    return {"modules": page, "total": total, "limit": limit, "offset": offset}


# ---------- Single Module ----------


@router.get("/module/{module_name:path}")
async def intelligence_module_detail(request: Request, module_name: str):
    """Return full module packet for a single module."""
    root = _get_graqle_root(request)
    if not root:
        return JSONResponse({"error": "No .graqle directory found"}, status_code=404)

    # Module packets are stored as dotted_name.json with dots replaced by __
    # e.g., graqle.core.graph -> graqle__core__graph.json
    safe_name = module_name.replace(".", "__").replace("/", "__")
    packet_path = root / "intelligence" / "modules" / f"{safe_name}.json"

    data = _read_json(packet_path)
    if not data:
        return JSONResponse({"error": f"Module '{module_name}' not found"}, status_code=404)

    # Enrich with impact data if available
    impact_data = _read_json(root / "intelligence" / "impact_matrix.json")
    if impact_data and module_name in impact_data:
        data["consumers"] = impact_data[module_name].get("consumers", [])

    return data


# ---------- Impact Matrix ----------


@router.get("/impact-matrix")
async def intelligence_impact_matrix(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    min_consumers: int = Query(0, ge=0, description="Minimum consumer count"),
):
    """Return impact matrix — module dependency relationships."""
    root = _get_graqle_root(request)
    if not root:
        return {"modules": {}, "error": "No .graqle directory found"}

    data = _read_json(root / "intelligence" / "impact_matrix.json")
    if not data:
        return {"modules": {}, "error": "No impact matrix — run `graq compile` first"}

    # Filter by min_consumers
    if min_consumers > 0:
        data = {
            mod: info for mod, info in data.items()
            if len(info.get("consumers", [])) >= min_consumers
        }

    # Sort by consumer count descending, limit
    sorted_items = sorted(
        data.items(),
        key=lambda x: len(x[1].get("consumers", [])),
        reverse=True,
    )[:limit]

    return {"modules": dict(sorted_items), "total": len(data)}


# ---------- Risk Distribution ----------


@router.get("/risk-distribution")
async def intelligence_risk_distribution(request: Request):
    """Return risk level distribution for heatmap rendering."""
    root = _get_graqle_root(request)
    if not root:
        return {"distribution": {}, "error": "No .graqle directory found"}

    data = _read_json(root / "intelligence" / "module_index.json")
    if not data or "modules" not in data:
        return {"distribution": {}, "error": "No module index"}

    distribution: dict[str, int] = {}
    for m in data["modules"]:
        level = m.get("risk_level", "UNKNOWN")
        distribution[level] = distribution.get(level, 0) + 1

    return {
        "distribution": distribution,
        "total_modules": len(data["modules"]),
    }


# ---------- Insights (derived from module data) ----------


@router.get("/insights")
async def intelligence_insights(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    category: str = Query("", description="Filter: superlative, warning, suggestion, connection"),
):
    """Return derived insights from compiled intelligence data."""
    root = _get_graqle_root(request)
    if not root:
        return {"insights": [], "error": "No .graqle directory found"}

    data = _read_json(root / "intelligence" / "module_index.json")
    if not data or "modules" not in data:
        return {"insights": [], "error": "No module index"}

    modules = data["modules"]
    insights: list[dict[str, Any]] = []

    # Sort modules by various metrics for insight generation
    by_risk = sorted(modules, key=lambda m: m.get("risk_score", 0), reverse=True)
    by_impact = sorted(modules, key=lambda m: m.get("impact_radius", 0), reverse=True)
    by_consumers = sorted(modules, key=lambda m: m.get("consumer_count", 0), reverse=True)
    by_functions = sorted(modules, key=lambda m: m.get("function_count", 0), reverse=True)

    # SUPERLATIVE insights
    if by_impact and by_impact[0].get("impact_radius", 0) > 0:
        top = by_impact[0]
        insights.append({
            "category": "superlative",
            "title": "Highest Impact Module",
            "message": f"**{top['module']}** has an impact radius of {top['impact_radius']} modules. Changes here cascade widely.",
            "module": top["module"],
            "severity": "info",
            "metric": top["impact_radius"],
        })

    if by_consumers and by_consumers[0].get("consumer_count", 0) > 10:
        top = by_consumers[0]
        insights.append({
            "category": "superlative",
            "title": "Most Depended-On Module",
            "message": f"**{top['module']}** is consumed by {top['consumer_count']} modules. This is a hub module — treat changes with care.",
            "module": top["module"],
            "severity": "info",
            "metric": top["consumer_count"],
        })

    if by_functions and by_functions[0].get("function_count", 0) > 30:
        top = by_functions[0]
        insights.append({
            "category": "superlative",
            "title": "Most Complex Module",
            "message": f"**{top['module']}** has {top['function_count']} functions. Consider splitting if complexity grows.",
            "module": top["module"],
            "severity": "info",
            "metric": top["function_count"],
        })

    # WARNING insights — high/critical risk modules
    for m in by_risk:
        if m.get("risk_level") == "CRITICAL":
            insights.append({
                "category": "warning",
                "title": f"Critical Risk: {m['module']}",
                "message": f"**{m['module']}** is CRITICAL risk (score: {m.get('risk_score', 0):.2f}) with {m.get('impact_radius', 0)} module impact radius.",
                "module": m["module"],
                "severity": "critical",
                "metric": m.get("risk_score", 0),
            })
        elif m.get("risk_level") == "HIGH" and m.get("impact_radius", 0) > 20:
            insights.append({
                "category": "warning",
                "title": f"High Risk Hub: {m['module']}",
                "message": f"**{m['module']}** is HIGH risk with {m.get('impact_radius', 0)} consumers. Changes need preflight checks.",
                "module": m["module"],
                "severity": "high",
                "metric": m.get("risk_score", 0),
            })

    # SUGGESTION insights — modules with high function count but low test coverage
    for m in by_functions[:10]:
        if m.get("function_count", 0) > 40:
            insights.append({
                "category": "suggestion",
                "title": f"Consider Splitting: {m['module']}",
                "message": f"**{m['module']}** has {m['function_count']} functions. Large modules increase cognitive load and merge conflicts.",
                "module": m["module"],
                "severity": "suggestion",
                "metric": m.get("function_count", 0),
            })

    # CONNECTION insights — hub modules (high consumers AND high dependencies)
    impact_data = _read_json(root / "intelligence" / "impact_matrix.json")
    if impact_data:
        for m in by_consumers[:10]:
            mod_name = m["module"]
            if mod_name in impact_data:
                consumers = len(impact_data[mod_name].get("consumers", []))
                if consumers > 15:
                    insights.append({
                        "category": "connection",
                        "title": f"Hub Module: {mod_name}",
                        "message": f"**{mod_name}** connects {consumers} consumers. This is a central connector in the codebase.",
                        "module": mod_name,
                        "severity": "info",
                        "metric": consumers,
                    })

    # Filter by category
    if category:
        cat_lower = category.lower()
        insights = [i for i in insights if i["category"] == cat_lower]

    # Deduplicate by module+category
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for i in insights:
        key = f"{i['module']}:{i['category']}"
        if key not in seen:
            seen.add(key)
            unique.append(i)

    return {"insights": unique[:limit], "total": len(unique)}
