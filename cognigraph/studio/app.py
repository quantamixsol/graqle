"""CogniGraph Studio — mount studio routes onto FastAPI app."""

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
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from cognigraph.studio.routes.dashboard import router as dashboard_router
    from cognigraph.studio.routes.api import router as api_router

    # Mount static files
    app.mount("/studio/static", StaticFiles(directory=str(STATIC_DIR)), name="studio-static")

    # Store templates and state on app
    app.state.studio_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.studio_state = state

    # Include routers
    app.include_router(dashboard_router, prefix="/studio")
    app.include_router(api_router, prefix="/studio/api")

    logger.info("CogniGraph Studio mounted at /studio/")
