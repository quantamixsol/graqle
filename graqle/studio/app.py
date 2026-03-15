"""Graqle Studio — mount studio routes onto FastAPI app."""

# ── graqle:intelligence ──
# module: graqle.studio.app
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, logging, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STUDIO_DIR = Path(__file__).parent
TEMPLATES_DIR = STUDIO_DIR / "templates"
STATIC_DIR = STUDIO_DIR / "static"


def mount_studio(app: Any, state: dict) -> None:
    """Mount studio routes onto an existing FastAPI app.

    Args:
        app: FastAPI application instance.
        state: Shared state dict with 'graph', 'config', etc.
    """
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from graqle.studio.routes.api import router as api_router
    from graqle.studio.routes.control import router as control_router
    from graqle.studio.routes.dashboard import router as dashboard_router
    from graqle.studio.routes.governance import router as governance_router
    from graqle.studio.routes.health import router as health_router
    from graqle.studio.routes.intelligence import router as intelligence_router
    from graqle.studio.routes.learning import router as learning_router
    from graqle.studio.routes.traversal import router as traversal_router

    # Mount static files
    app.mount("/studio/static", StaticFiles(directory=str(STATIC_DIR)), name="studio-static")

    # Store templates and state on app
    app.state.studio_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.studio_state = state

    # Include routers
    app.include_router(dashboard_router, prefix="/studio")
    app.include_router(api_router, prefix="/studio/api")
    app.include_router(intelligence_router, prefix="/studio/api/intelligence")
    app.include_router(governance_router, prefix="/studio/api/governance")
    app.include_router(health_router, prefix="/studio/api/health")
    app.include_router(traversal_router, prefix="/studio/api/traversal")
    app.include_router(control_router, prefix="/studio/api/control")
    app.include_router(learning_router, prefix="/studio/api/learning")

    logger.info("Graqle Studio mounted at /studio/")
