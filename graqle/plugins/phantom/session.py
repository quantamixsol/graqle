"""Phantom session manager — Playwright browser lifecycle + auth profiles."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.phantom.session")

VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "tablet": {"width": 768, "height": 1024},
    "desktop": {"width": 1920, "height": 1080},
}


@dataclass
class PhantomSession:
    """A single browser session with page, context, and state tracking."""

    id: str
    browser: Any  # playwright Browser
    context: Any  # playwright BrowserContext
    page: Any  # playwright Page
    viewport_name: str
    viewport_dict: dict[str, int]
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    last_load_time: int = 0

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text[:200])

    def _on_request_failed(self, request: Any) -> None:
        self.network_errors.append(f"{request.method} {request.url}: {request.failure}")


class SessionManager:
    """Manage Playwright browser sessions with auth profile support.

    Sessions persist browser context (cookies, localStorage) across
    tool calls within a conversation. Auth profiles are saved/loaded
    from disk as Playwright storage states.
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._sessions: dict[str, PhantomSession] = {}
        self._playwright: Any = None
        self._browser: Any = None

    async def _ensure_browser(self) -> None:
        """Lazily start Playwright + Chromium."""
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            headless = self.config.headless if self.config else True
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            logger.info("Playwright browser launched (headless=%s)", headless)

    async def create(
        self,
        viewport: str = "desktop",
        auth_profile: str | None = None,
    ) -> PhantomSession:
        """Create a new browser session."""
        await self._ensure_browser()

        vp = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])
        session_id = f"phantom_{uuid.uuid4().hex[:8]}"

        context_kwargs: dict[str, Any] = {
            "viewport": vp,
            "user_agent": (
                self.config.user_agent
                if self.config
                else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
        }

        # Load auth profile if specified
        if auth_profile:
            profile_path = self._auth_profile_path(auth_profile)
            if profile_path.exists():
                context_kwargs["storage_state"] = str(profile_path)
                logger.info("Loaded auth profile: %s", auth_profile)

        context = await self._browser.new_context(**context_kwargs)
        page = await context.new_page()

        session = PhantomSession(
            id=session_id,
            browser=self._browser,
            context=context,
            page=page,
            viewport_name=viewport,
            viewport_dict=vp,
        )

        # Wire up console error capture
        page.on("console", session._on_console)
        page.on("requestfailed", session._on_request_failed)

        self._sessions[session_id] = session
        logger.info("Session created: %s (viewport=%s)", session_id, viewport)
        return session

    async def get_or_create(
        self,
        session_id: str | None = None,
        viewport: str = "desktop",
        auth_profile: str | None = None,
    ) -> PhantomSession:
        """Get existing session or create new one."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return await self.create(viewport=viewport, auth_profile=auth_profile)

    def get(self, session_id: str) -> PhantomSession:
        """Get an existing session. Raises KeyError if not found."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found. Active: {list(self._sessions.keys())}")
        return self._sessions[session_id]

    async def save_auth(self, session_id: str, profile_name: str) -> str:
        """Save current session's auth state as a named profile."""
        session = self.get(session_id)
        profile_path = self._auth_profile_path(profile_name)
        profile_path.parent.mkdir(parents=True, exist_ok=True)

        state = await session.context.storage_state()
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        logger.info("Auth profile saved: %s -> %s", profile_name, profile_path)
        return str(profile_path)

    async def close(self, session_id: str) -> None:
        """Close a session and clean up resources."""
        session = self._sessions.pop(session_id, None)
        if session:
            await session.context.close()
            logger.info("Session closed: %s", session_id)

    async def close_all(self) -> int:
        """Close all sessions."""
        count = len(self._sessions)
        for sid in list(self._sessions.keys()):
            await self.close(sid)
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("All %d sessions closed, browser stopped", count)
        return count

    def list_sessions(self) -> list[dict[str, Any]]:
        """List active sessions."""
        return [
            {
                "session_id": s.id,
                "viewport": s.viewport_name,
                "url": s.page.url if s.page else None,
                "console_errors": len(s.console_errors),
            }
            for s in self._sessions.values()
        ]

    def _auth_profile_path(self, name: str) -> Path:
        base = self.config.auth_profiles_dir if self.config else "./scorch-output/phantom/auth_profiles"
        return Path(base) / f"{name}.json"
