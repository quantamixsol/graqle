"""Studio compliance routes — HTTP wrappers for EU AI Act subsystem status.

Surface the `graq compliance switch status` CLI output as JSON endpoints
so the graqle.com /security page and Studio dashboard can show the
live armed/disarmed state of every EU AI Act subsystem.

Backs the canonical capability statement on graqle.com:
"EU AI Act-aligned by design - every shipped capability traces to a
specific Article. One switch flips every subsystem at once."

Module: graqle.studio.routes.compliance
Risk: LOW (read-only, no graph state, no LLM calls)
"""

# graqle:intelligence
# module: graqle.studio.routes.compliance
# risk: LOW (impact radius: 0 modules)
# constraints: none
# /graqle:intelligence

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/switch/status")
async def switch_status() -> JSONResponse:
    """Return the EU AI Act master-switch + 7-subsystem envelope.

    Wraps graqle.compliance.switch_status.build_switch_status(). Every
    probe is fail-closed inside the module - this endpoint must never raise.
    """
    try:
        from graqle.compliance.switch_status import build_switch_status
        envelope = build_switch_status()
        return JSONResponse(envelope)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("switch_status failed unexpectedly")
        return JSONResponse(
            {
                "schema_version": "1.0",
                "error": "switch_status_unavailable",
                "detail": str(exc)[:200],
            },
            status_code=500,
        )


@router.get("/status")
async def compliance_status() -> JSONResponse:
    """Return the consolidated compliance status envelope.

    Currently mirrors switch_status. Reserved for future expansion to
    include baseline-doc / periodic-assessment / feedback-trend recent
    activity summaries (per CG-MKT roadmap).
    """
    try:
        from graqle.compliance.switch_status import build_switch_status
        envelope = build_switch_status()
        return JSONResponse({
            "schema_version": "1",
            "eu_ai_act_subsystems": envelope,
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("compliance_status failed unexpectedly")
        return JSONResponse(
            {
                "schema_version": "1",
                "error": "compliance_status_unavailable",
                "detail": str(exc)[:200],
            },
            status_code=500,
        )
