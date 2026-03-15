"""Studio Governance API — endpoints for governance dashboard data."""

# ── graqle:intelligence ──
# module: graqle.studio.routes.governance
# risk: MEDIUM (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, test_router, test_skill_resolver, test_governance_routes
# dependencies: __future__, json, logging, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

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


# ---------- DRACE Scores ----------


@router.get("/drace/current")
async def drace_current(request: Request):
    """Return DRACE score for the most recent completed session."""
    root = _get_graqle_root(request)
    if not root:
        return {"error": "No .graqle directory found"}

    audit_dir = root / "governance" / "audit"
    if not audit_dir.exists():
        return {"error": "No audit data — run governance tools first"}

    # Find most recent completed session
    for fpath in sorted(audit_dir.glob("*.json"), reverse=True):
        data = _read_json(fpath)
        if data and data.get("status") == "completed" and data.get("drace_score") is not None:
            # Compute pillar breakdown from entries
            pillars = _compute_drace_pillars(data)
            return {
                "session_id": data.get("session_id"),
                "task": data.get("task"),
                "started": data.get("started"),
                "drace_score": data.get("drace_score"),
                "pillars": pillars,
                "grade": _drace_grade(data.get("drace_score", 0)),
                "entry_count": len(data.get("entries", [])),
            }

    return {"error": "No completed sessions with DRACE scores"}


@router.get("/drace/history")
async def drace_history(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
):
    """Return DRACE score history over sessions."""
    root = _get_graqle_root(request)
    if not root:
        return {"sessions": [], "error": "No .graqle directory found"}

    audit_dir = root / "governance" / "audit"
    if not audit_dir.exists():
        return {"sessions": []}

    sessions = []
    for fpath in sorted(audit_dir.glob("*.json"), reverse=True)[:limit]:
        data = _read_json(fpath)
        if not data:
            continue
        entry = {
            "session_id": data.get("session_id"),
            "task": data.get("task"),
            "started": data.get("started"),
            "status": data.get("status"),
            "drace_score": data.get("drace_score"),
            "entry_count": len(data.get("entries", [])),
        }
        if data.get("drace_score") is not None:
            entry["grade"] = _drace_grade(data["drace_score"])
            entry["pillars"] = _compute_drace_pillars(data)
        sessions.append(entry)

    return {"sessions": sessions}


# ---------- Audit Trail ----------


@router.get("/audit/sessions")
async def audit_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """Return list of audit sessions."""
    root = _get_graqle_root(request)
    if not root:
        return {"sessions": [], "error": "No .graqle directory found"}

    audit_dir = root / "governance" / "audit"
    if not audit_dir.exists():
        return {"sessions": []}

    sessions = []
    for fpath in sorted(audit_dir.glob("*.json"), reverse=True)[:limit]:
        data = _read_json(fpath)
        if not data:
            continue
        sessions.append({
            "session_id": data.get("session_id"),
            "task": data.get("task"),
            "status": data.get("status"),
            "started": data.get("started"),
            "entry_count": len(data.get("entries", [])),
            "drace_score": data.get("drace_score"),
            "total_evidence": sum(e.get("evidence_count", 0) for e in data.get("entries", [])),
            "total_nodes": sum(e.get("nodes_consulted", 0) for e in data.get("entries", [])),
        })

    return {"sessions": sessions}


@router.get("/audit/session/{session_id}")
async def audit_session_detail(request: Request, session_id: str):
    """Return full audit session with all entries."""
    root = _get_graqle_root(request)
    if not root:
        return JSONResponse({"error": "No .graqle directory found"}, status_code=404)

    audit_dir = root / "governance" / "audit"
    data = _read_json(audit_dir / f"{session_id}.json")
    if not data:
        return JSONResponse({"error": f"Session '{session_id}' not found"}, status_code=404)

    return data


@router.get("/audit/verify/{session_id}")
async def audit_verify_chain(request: Request, session_id: str):
    """Verify SHA-256 hash chain integrity for a session."""
    root = _get_graqle_root(request)
    if not root:
        return JSONResponse({"error": "No .graqle directory found"}, status_code=404)

    audit_dir = root / "governance" / "audit"
    data = _read_json(audit_dir / f"{session_id}.json")
    if not data:
        return JSONResponse({"error": f"Session '{session_id}' not found"}, status_code=404)

    entries = data.get("entries", [])
    chain_results: list[dict[str, Any]] = []
    all_valid = True

    for i, entry in enumerate(entries):
        import hashlib
        # Recompute hash
        content = json.dumps({
            "timestamp": entry.get("timestamp", ""),
            "action": entry.get("action", ""),
            "tool": entry.get("tool", ""),
            "module": entry.get("module", ""),
            "input_summary": entry.get("input_summary", ""),
            "output_summary": entry.get("output_summary", ""),
            "prev_hash": entry.get("prev_hash", ""),
        }, sort_keys=True)
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        hash_valid = entry.get("entry_hash") == expected_hash
        chain_valid = True
        if i > 0:
            chain_valid = entry.get("prev_hash") == entries[i - 1].get("entry_hash")

        if not hash_valid or not chain_valid:
            all_valid = False

        chain_results.append({
            "index": i,
            "action": entry.get("action"),
            "module": entry.get("module"),
            "entry_hash": entry.get("entry_hash"),
            "expected_hash": expected_hash,
            "prev_hash": entry.get("prev_hash"),
            "hash_valid": hash_valid,
            "chain_valid": chain_valid,
        })

    return {
        "session_id": session_id,
        "chain_valid": all_valid,
        "entry_count": len(entries),
        "entries": chain_results,
    }


# ---------- Evidence Chains ----------


@router.get("/evidence/chains")
async def evidence_chains(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """Return list of evidence chains."""
    root = _get_graqle_root(request)
    if not root:
        return {"chains": [], "error": "No .graqle directory found"}

    evidence_dir = root / "governance" / "evidence"
    if not evidence_dir.exists():
        return {"chains": []}

    chains = []
    for fpath in sorted(evidence_dir.glob("*.json"), reverse=True)[:limit]:
        data = _read_json(fpath)
        if not data:
            continue
        decisions = data.get("decisions", [])
        chains.append({
            "chain_id": data.get("chain_id"),
            "task": data.get("task"),
            "status": data.get("status"),
            "started": data.get("started"),
            "decision_count": len(decisions),
            "total_evidence": sum(len(d.get("evidence", [])) for d in decisions),
            "evidence_ratio": _evidence_ratio(decisions),
            "final_drace_score": data.get("final_drace_score"),
            "final_outcome": data.get("final_outcome", ""),
        })

    return {"chains": chains}


@router.get("/evidence/chain/{chain_id}")
async def evidence_chain_detail(request: Request, chain_id: str):
    """Return full evidence chain with decisions and evidence items."""
    root = _get_graqle_root(request)
    if not root:
        return JSONResponse({"error": "No .graqle directory found"}, status_code=404)

    evidence_dir = root / "governance" / "evidence"
    data = _read_json(evidence_dir / f"{chain_id}.json")
    if not data:
        return JSONResponse({"error": f"Chain '{chain_id}' not found"}, status_code=404)

    return data


# ---------- DRACE Badge (SVG) ----------


@router.get("/badge.svg")
async def drace_badge(request: Request):
    """Generate shareable DRACE badge SVG."""
    root = _get_graqle_root(request)
    score = 0.0
    grade = "N/A"

    if root:
        audit_dir = root / "governance" / "audit"
        if audit_dir.exists():
            for fpath in sorted(audit_dir.glob("*.json"), reverse=True):
                data = _read_json(fpath)
                if data and data.get("status") == "completed" and data.get("drace_score") is not None:
                    score = data["drace_score"]
                    grade = _drace_grade(score)
                    break

    color = _badge_color(score)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="210" height="20" role="img" aria-label="DRACE: {score:.2f} {grade}">
  <title>DRACE: {score:.2f} {grade}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="210" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="90" height="20" fill="#555"/>
    <rect x="90" width="120" height="20" fill="{color}"/>
    <rect width="210" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="45" y="14" fill="#010101" fill-opacity=".3">DRACE</text>
    <text x="45" y="13">DRACE</text>
    <text x="150" y="14" fill="#010101" fill-opacity=".3">{score:.2f} {grade}</text>
    <text x="150" y="13">{score:.2f} {grade}</text>
  </g>
</svg>"""

    return Response(content=svg, media_type="image/svg+xml")


# ---------- Helpers ----------


def _drace_grade(score: float) -> str:
    if score >= 0.9:
        return "EXCELLENT"
    if score >= 0.75:
        return "GOOD"
    if score >= 0.5:
        return "ADEQUATE"
    if score >= 0.25:
        return "POOR"
    return "CRITICAL"


def _badge_color(score: float) -> str:
    if score >= 0.9:
        return "#4c1"
    if score >= 0.75:
        return "#97ca00"
    if score >= 0.5:
        return "#dfb317"
    if score >= 0.25:
        return "#fe7d37"
    return "#e05d44"


def _evidence_ratio(decisions: list[dict]) -> float:
    if not decisions:
        return 0.0
    evidenced = sum(1 for d in decisions if len(d.get("evidence", [])) >= 2)
    return round(evidenced / len(decisions), 3)


def _compute_drace_pillars(session_data: dict) -> dict[str, float]:
    """Compute DRACE pillar breakdown from session data.

    Uses the same DRACEScorer pipeline as the backend —
    extracts typed inputs from raw entries and evaluates each pillar.
    """
    try:
        from graqle.intelligence.governance.drace import DRACEScorer
        scorer = DRACEScorer()
        entries = [e for e in session_data.get("entries", [])]
        if not entries:
            return {"D": 0, "R": 0, "A": 0, "C": 0, "E": 0}
        score = scorer.score_session(entries)
        return {
            "D": score.dependency,
            "R": score.reasoning,
            "A": score.auditability,
            "C": score.constraint,
            "E": score.explainability,
        }
    except Exception:
        return {"D": 0, "R": 0, "A": 0, "C": 0, "E": 0}
