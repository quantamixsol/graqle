# ── graqle:intelligence ──
# module: graqle.studio.routes.auto
# risk: MEDIUM
# phase: P4.1-4.3 — Autonomous Execution Monitor

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

# ── Defensive imports ──────────────────────────────────────────────────
try:
    from graqle.workflow.loop_controller import LoopController
except Exception:
    LoopController = None

try:
    from graqle.workflow.loop_observer import LoopObserver
except Exception:
    LoopObserver = None

try:
    from graqle.reasoning.memory import ReasoningMemory
except Exception:
    ReasoningMemory = None

try:
    from graqle.reasoning.semaphore import BudgetAwareSemaphore
except Exception:
    BudgetAwareSemaphore = None

# ── Router + templates ─────────────────────────────────────────────────
router = APIRouter(prefix="/auto", tags=["auto"])

try:
    import pathlib
    _TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
except Exception:
    templates = None


def _state(request: Request) -> dict:
    try:
        return request.app.state.studio_state
    except AttributeError:
        return {}


# ── GET /auto ──────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def auto_page(request: Request):
    try:
        if templates is None:
            raise RuntimeError("templates_unavailable")
        return templates.TemplateResponse("auto.html", {"request": request})
    except Exception as exc:
        return HTMLResponse(f"<h1>Auto Monitor</h1><p>Template unavailable: {exc}</p>")


# ── GET /api/auto/status ───────────────────────────────────────────────

@router.get("/api/auto/status")
async def auto_status(request: Request):
    s = _state(request)
    ctx = s.get("loop_context")
    observer = s.get("loop_observer")
    sem = s.get("budget_semaphore")

    result = {
        "state": "idle",
        "attempt": 0,
        "max_retries": 0,
        "budget_used_usd": 0.0,
        "last_decay_at": None,
        "modified_files": [],
        "test_result": {"pass_count": 0, "fail_count": 0, "error": None},
    }

    try:
        if ctx is not None:
            result["state"] = str(getattr(ctx, "state", "idle"))
            result["attempt"] = int(getattr(ctx, "attempt", 0))
            result["max_retries"] = int(getattr(ctx, "max_retries", 0))
            result["modified_files"] = list(getattr(ctx, "modified_files", []) or [])
            tr = getattr(ctx, "test_result", None)
            if tr:
                result["test_result"] = {
                    "pass_count": int(getattr(tr, "pass_count", 0)),
                    "fail_count": int(getattr(tr, "fail_count", 0)),
                    "error": getattr(tr, "error", None),
                }
    except Exception:
        pass

    try:
        if sem is not None:
            result["budget_used_usd"] = float(getattr(sem, "budget_used_usd", 0.0))
    except Exception:
        pass

    try:
        result["last_decay_at"] = s.get("last_decay_at")
    except Exception:
        pass

    return JSONResponse(result)


# ── POST /api/auto/start ──────────────────────────────────────────────

@router.post("/api/auto/start")
async def auto_start(request: Request):
    if LoopController is None:
        return JSONResponse({"error": "LoopController unavailable"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        body = {}

    task = str(body.get("task", ""))
    max_retries = int(body.get("max_retries", 3))
    s = _state(request)

    try:
        controller = LoopController(task=task, max_retries=max_retries)
        s["loop_controller"] = controller
        s["loop_context"] = getattr(controller, "context", None)
        asyncio.create_task(controller.run())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({"started": True, "task": task})


# ── POST /api/auto/stop ───────────────────────────────────────────────

@router.post("/api/auto/stop")
async def auto_stop(request: Request):
    s = _state(request)
    controller = s.get("loop_controller")
    if controller is None:
        return JSONResponse({"stopped": False, "reason": "no active controller"})
    try:
        controller.force_stop()
    except Exception as exc:
        return JSONResponse({"stopped": False, "reason": str(exc)}, status_code=500)
    return JSONResponse({"stopped": True})


# ── GET /api/auto/events (SSE) ────────────────────────────────────────

@router.get("/api/auto/events")
async def auto_events(request: Request):
    async def gen():
        s = _state(request)
        observer = s.get("loop_observer")
        if observer is None and LoopObserver is not None:
            try:
                observer = LoopObserver()
                s["loop_observer"] = observer
            except Exception:
                observer = None

        if observer is None:
            yield f"data: {json.dumps({'type': 'idle', 'timestamp': time.time()})}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            async for event in observer:
                if await request.is_disconnected():
                    break
                gov_score = None
                try:
                    gov_score = float(observer.governance_score)
                except Exception:
                    pass
                payload = {
                    "round": int(getattr(event, "round", 0)),
                    "state": str(getattr(event, "state", "unknown")),
                    "node_ids": list(getattr(event, "node_ids", []) or []),
                    "answer_preview": getattr(event, "answer_preview", None),
                    "memory_decay": bool(getattr(event, "memory_decay", False)),
                    "governance_score": gov_score,
                    "timestamp": time.time(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300], 'timestamp': time.time()})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
