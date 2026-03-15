"""Studio Health API — endpoints for health streaks and improvement suggestions."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.health
# risk: LOW (impact radius: 1 modules)
# consumers: test_health_routes
# dependencies: __future__, json, logging, datetime, pathlib +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request

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


# ---------- Health Streak ----------


def _build_streak_calendar(audit_dir: Path, days: int = 365) -> list[dict]:
    """Build a day-by-day health calendar from audit session timestamps.

    Each day gets a health level based on number of governance sessions:
      0 = no activity, 1 = light, 2 = moderate, 3 = active, 4 = intense
    """
    # Collect all session dates
    session_dates: dict[str, int] = {}  # "YYYY-MM-DD" -> count
    if audit_dir.is_dir():
        for f in audit_dir.glob("*.json"):
            data = _read_json(f)
            if not data or not isinstance(data, dict):
                continue
            started = data.get("started", "")
            if not started:
                # Fallback: parse date from filename like 20260315_120609.json
                stem = f.stem
                if len(stem) >= 8 and stem[:8].isdigit():
                    try:
                        d = datetime.strptime(stem[:8], "%Y%m%d")
                        started = d.strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            if started:
                day_str = started[:10]  # "YYYY-MM-DD"
                session_dates[day_str] = session_dates.get(day_str, 0) + 1

    # Build calendar grid
    today = datetime.now(timezone.utc).date()
    calendar: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        day_str = d.isoformat()
        count = session_dates.get(day_str, 0)
        level = min(4, count)  # 0-4 scale
        calendar.append({
            "date": day_str,
            "count": count,
            "level": level,
        })

    return calendar


def _compute_streak(calendar: list[dict]) -> int:
    """Compute current consecutive-day streak from calendar (most recent first)."""
    streak = 0
    for entry in reversed(calendar):
        if entry["count"] > 0:
            streak += 1
        else:
            # Allow today to be zero (day not over yet) but break on past zeros
            if entry == calendar[-1]:
                continue
            break
    return streak


@router.get("/streak")
async def health_streak(
    request: Request,
    days: int = Query(365, ge=7, le=365),
):
    """Return health streak calendar and current streak count."""
    root = _get_graqle_root(request)
    if not root:
        return {"error": "No .graqle directory found"}

    audit_dir = root / "governance" / "audit"
    calendar = _build_streak_calendar(audit_dir, days=days)
    streak = _compute_streak(calendar)

    # Compute summary stats
    active_days = sum(1 for d in calendar if d["count"] > 0)
    total_sessions = sum(d["count"] for d in calendar)

    return {
        "calendar": calendar,
        "streak": streak,
        "active_days": active_days,
        "total_sessions": total_sessions,
        "period_days": days,
    }


# ---------- Improvement Suggestions ----------


@router.get("/suggestions")
async def improvement_suggestions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """Return actionable improvement suggestions from intelligence data."""
    root = _get_graqle_root(request)
    if not root:
        return {"error": "No .graqle directory found"}

    suggestions: list[dict] = []

    # Source 1: Module index — find modules with HIGH/CRITICAL risk
    module_index = _read_json(root / "intelligence" / "module_index.json")
    if isinstance(module_index, list):
        for mod in module_index:
            if not isinstance(mod, dict):
                continue
            risk = mod.get("risk", "").upper()
            if risk in ("HIGH", "CRITICAL"):
                name = mod.get("module", mod.get("name", "unknown"))
                impact = mod.get("impact_radius", 0)
                suggestions.append({
                    "id": f"risk-{name}",
                    "category": "risk",
                    "severity": risk,
                    "title": f"Reduce risk in {name}",
                    "description": f"Module {name} has {risk} risk with impact radius {impact}. "
                                   f"Consider adding tests, reducing coupling, or breaking into smaller modules.",
                    "module": name,
                    "command": f"graq inspect --node {name}",
                    "priority": 1 if risk == "CRITICAL" else 2,
                })

    # Source 2: Scorecard — check for low coverage
    scorecard = _read_json(root / "scorecard.json")
    if isinstance(scorecard, dict):
        chunk_cov = scorecard.get("chunk_coverage", 100)
        desc_cov = scorecard.get("description_coverage", scorecard.get("desc_coverage", 100))
        if isinstance(chunk_cov, (int, float)) and chunk_cov < 95:
            suggestions.append({
                "id": "coverage-chunks",
                "category": "coverage",
                "severity": "MEDIUM",
                "title": "Improve chunk coverage",
                "description": f"Chunk coverage is {chunk_cov:.1f}%. "
                               f"Run `graq compile` to improve documentation coverage.",
                "module": None,
                "command": "graq compile",
                "priority": 3,
            })
        if isinstance(desc_cov, (int, float)) and desc_cov < 95:
            suggestions.append({
                "id": "coverage-descriptions",
                "category": "coverage",
                "severity": "MEDIUM",
                "title": "Improve description coverage",
                "description": f"Description coverage is {desc_cov:.1f}%. "
                               f"Add docstrings to undocumented modules.",
                "module": None,
                "command": "graq compile",
                "priority": 3,
            })

    # Source 3: DRACE scores — find weak pillars
    audit_dir = root / "governance" / "audit"
    if audit_dir.is_dir():
        sessions = sorted(audit_dir.glob("*.json"), reverse=True)
        if sessions:
            latest = _read_json(sessions[0])
            if isinstance(latest, dict):
                drace = latest.get("drace_score")
                if isinstance(drace, (int, float)) and drace < 0.7:
                    suggestions.append({
                        "id": "drace-low",
                        "category": "governance",
                        "severity": "HIGH",
                        "title": "Improve DRACE score",
                        "description": f"Latest DRACE score is {drace:.2f}. "
                                       f"Use `graq gate` and `graq drace` to improve governance.",
                        "module": None,
                        "command": "graq drace",
                        "priority": 1,
                    })

    # Sort by priority, then limit
    suggestions.sort(key=lambda s: s["priority"])
    return {
        "suggestions": suggestions[:limit],
        "total": len(suggestions),
    }


# ---------- Impact Blast Radius ----------


@router.get("/impact/{node_id:path}")
async def impact_blast_radius(
    request: Request,
    node_id: str,
    hops: int = Query(2, ge=1, le=5),
):
    """Return impact blast radius for a node — concentric rings of affected nodes.

    Uses Neo4j-native Cypher traversal when available (~5ms).
    Falls back to Python BFS over in-memory graph.
    """
    state = request.app.state.studio_state
    graph = state.get("graph")
    if not graph:
        return {"error": "No graph loaded"}

    if node_id not in graph.nodes:
        return {"error": f"Node '{node_id}' not found"}

    # Fast path: Neo4j-native blast radius
    neo4j_traversal = state.get("neo4j_traversal")
    if neo4j_traversal is not None:
        try:
            result = neo4j_traversal.blast_radius(node_id, max_hops=hops)
            center = graph.nodes[node_id]
            return {
                "center": {
                    "id": node_id,
                    "label": center.label,
                    "type": center.entity_type,
                },
                "rings": result["rings"],
                "total_affected": result["total_affected"],
                "hops": hops,
            }
        except Exception:
            pass  # Fall through to Python BFS

    # Fallback: Python BFS
    visited: dict[str, int] = {node_id: 0}  # node_id -> depth
    queue = [node_id]
    rings: list[list[dict]] = [[] for _ in range(hops + 1)]

    while queue:
        current = queue.pop(0)
        depth = visited[current]
        if depth >= hops:
            continue

        # Find neighbors
        for edge in graph.edges.values():
            neighbor = None
            direction = None
            if edge.source_id == current:
                neighbor = edge.target_id
                direction = "outgoing"
            elif edge.target_id == current:
                neighbor = edge.source_id
                direction = "incoming"

            if neighbor and neighbor not in visited:
                visited[neighbor] = depth + 1
                queue.append(neighbor)
                n = graph.nodes.get(neighbor)
                if n:
                    rings[depth + 1].append({
                        "id": neighbor,
                        "label": n.label,
                        "type": n.entity_type,
                        "depth": depth + 1,
                        "direction": direction,
                        "relationship": edge.relationship,
                    })

    # Center node info
    center = graph.nodes[node_id]
    return {
        "center": {
            "id": node_id,
            "label": center.label,
            "type": center.entity_type,
        },
        "rings": [ring for ring in rings[1:]],  # Skip ring 0 (center)
        "total_affected": sum(len(r) for r in rings[1:]),
        "hops": hops,
    }
