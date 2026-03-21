"""Phantom Engine — main orchestrator for browser automation + audit.

Product-agnostic: works on any URL. Not tied to any specific application.

Usage:
    from graqle.plugins.phantom import PhantomEngine, PhantomConfig

    engine = PhantomEngine(PhantomConfig())
    result = await engine.browse("https://example.com")
    result = await engine.audit(session_id, dimensions=["all"])
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.plugins.phantom.config import PhantomConfig

logger = logging.getLogger("graqle.phantom")


class PhantomEngine:
    """Main orchestrator for GraQle Phantom computer skill.

    Manages browser sessions, coordinates audit dimensions,
    runs feedback loops, and generates reports.
    All methods are product-agnostic — they work on any URL.
    """

    def __init__(self, config: PhantomConfig | None = None):
        self.config = config or PhantomConfig()
        self._sessions: Any = None  # Lazy-loaded SessionManager
        self._navigator: Any = None
        self._interactor: Any = None
        self._capturer: Any = None
        self._analyzer: Any = None
        self._reporter: Any = None
        self._cost_total: float = 0.0

    # ------------------------------------------------------------------
    # Lazy component initialization
    # ------------------------------------------------------------------

    @property
    def sessions(self) -> Any:
        if self._sessions is None:
            from graqle.plugins.phantom.session import SessionManager
            self._sessions = SessionManager(config=self.config)
        return self._sessions

    @property
    def navigator(self) -> Any:
        if self._navigator is None:
            from graqle.plugins.phantom.core.navigator import Navigator
            self._navigator = Navigator()
        return self._navigator

    @property
    def interactor(self) -> Any:
        if self._interactor is None:
            from graqle.plugins.phantom.core.interactor import Interactor
            self._interactor = Interactor()
        return self._interactor

    @property
    def capturer(self) -> Any:
        if self._capturer is None:
            from graqle.plugins.phantom.core.capturer import Capturer
            self._capturer = Capturer(output_dir=self.config.output_dir)
        return self._capturer

    @property
    def analyzer(self) -> Any:
        if self._analyzer is None:
            from graqle.plugins.phantom.core.analyzer import VisionAnalyzer
            self._analyzer = VisionAnalyzer(config=self.config)
        return self._analyzer

    @property
    def reporter(self) -> Any:
        if self._reporter is None:
            from graqle.plugins.phantom.core.reporter import Reporter
            self._reporter = Reporter()
        return self._reporter

    # ------------------------------------------------------------------
    # MCP Tool implementations
    # ------------------------------------------------------------------

    async def browse(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Navigate to URL and return page state (screenshot + DOM summary)."""
        session = await self.sessions.get_or_create(
            session_id=kwargs.get("session_id"),
            viewport=kwargs.get("viewport", "desktop"),
            auth_profile=kwargs.get("auth_profile"),
        )

        page = session.page
        nav_result = await self.navigator.goto(
            page, url, wait_for=kwargs.get("wait_for", "networkidle"),
        )
        await page.wait_for_timeout(kwargs.get("wait_after", 2000))
        session.last_load_time = nav_result["load_time_ms"]

        screenshot_path = await self.capturer.screenshot(
            page,
            prefix="browse",
            full_page=kwargs.get("full_page_screenshot", True),
        )

        dom_summary = await self.capturer.dom_snapshot(page)

        return {
            "session_id": session.id,
            "url": url,
            "actual_url": page.url,
            "redirected": page.url != url,
            "authenticated": "/login" not in page.url and "/signin" not in page.url,
            "screenshot_path": str(screenshot_path),
            "dom_summary": dom_summary,
            "viewport": session.viewport_dict,
            "load_time_ms": session.last_load_time,
        }

    async def click(self, session_id: str, target: str, **kwargs: Any) -> dict[str, Any]:
        """Click an element and return result."""
        session = self.sessions.get(session_id)
        page = session.page

        url_before = page.url
        element = await self.interactor.find_element(page, target)

        if not element:
            return {"clicked": False, "target_found": False, "error": f"Element '{target}' not found"}

        element_info = await self.interactor.get_element_info(element)

        click_type = kwargs.get("click_type", "click")
        if click_type == "hover":
            await element.hover()
        elif click_type == "dblclick":
            await element.dblclick()
        elif click_type == "right_click":
            await element.click(button="right")
        else:
            if kwargs.get("expect_navigation"):
                async with page.expect_navigation(timeout=10000):
                    await element.click()
            else:
                await element.click()

        await page.wait_for_timeout(kwargs.get("wait_after", 2000))

        result: dict[str, Any] = {
            "clicked": True,
            "target_found": True,
            "target_element": element_info,
            "url_before": url_before,
            "url_after": page.url,
            "navigated": page.url != url_before,
            "modals_detected": await self._detect_modals(page),
            "console_errors": session.console_errors[-5:],
        }

        if kwargs.get("screenshot_after", True):
            result["screenshot_path"] = str(await self.capturer.screenshot(page, prefix="click"))

        return result

    async def type_text(self, session_id: str, target: str, text: str, **kwargs: Any) -> dict[str, Any]:
        """Type text into an input element."""
        session = self.sessions.get(session_id)
        page = session.page

        element = await self.interactor.find_input(page, target)

        if not element:
            return {"typed": False, "target_found": False, "error": f"Input '{target}' not found"}

        element_info = await self.interactor.get_element_info(element)

        if kwargs.get("clear_first", True):
            await element.fill("")

        delay = kwargs.get("type_delay", 0)
        if delay > 0:
            await element.type(text, delay=delay)
        else:
            await element.fill(text)

        if kwargs.get("submit", False):
            await element.press("Enter")
            await page.wait_for_timeout(2000)

        result: dict[str, Any] = {
            "typed": True,
            "target_found": True,
            "target_element": element_info,
            "text_entered": text,
            "submitted": kwargs.get("submit", False),
        }

        if kwargs.get("screenshot_after", True):
            result["screenshot_path"] = str(await self.capturer.screenshot(page, prefix="type"))

        return result

    async def screenshot(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        """Take screenshot with optional Vision analysis."""
        session = self.sessions.get(session_id)
        page = session.page

        screenshot_path = await self.capturer.screenshot(
            page,
            prefix="screenshot",
            full_page=kwargs.get("full_page", True),
            region=kwargs.get("region"),
            mask=kwargs.get("mask"),
        )

        result: dict[str, Any] = {
            "screenshot_path": str(screenshot_path),
            "viewport": session.viewport_dict,
            "page_height": await page.evaluate("() => document.body.scrollHeight"),
            "url": page.url,
        }

        if kwargs.get("analyze", False):
            analysis = await self.analyzer.analyze_screenshot(
                screenshot_path,
                prompt=kwargs.get("analysis_prompt"),
                model=kwargs.get("analysis_model", "sonnet"),
            )
            result["analysis"] = analysis
            self._cost_total += analysis.get("cost_usd", 0)

        return result

    async def audit(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        """Run SCORCH audit dimensions on current page."""
        session = self.sessions.get(session_id)
        page = session.page

        dimensions = kwargs.get("dimensions", ["all"])
        if "all" in dimensions:
            dimensions = [
                "behavioral", "accessibility", "mobile", "security",
                "brand", "conversion", "performance", "seo",
                "i18n", "content",
            ]

        results: dict[str, Any] = {}
        for dim in dimensions:
            auditor = self._get_auditor(dim)
            results[dim] = await auditor.audit(page, self.config)

        # Vision analysis (optional, costs money)
        if "visual" in kwargs.get("dimensions", []) or "all" in kwargs.get("dimensions", []):
            screenshot_path = await self.capturer.screenshot(page, prefix="audit")
            results["visual"] = await self.analyzer.analyze_screenshot(screenshot_path)

        summary = self._calculate_summary(results)

        # Teach KG if requested
        kg_nodes = 0
        if kwargs.get("teach_kg", True):
            try:
                from graqle.plugins.phantom.feedback.learner import KGLearner
                learner = KGLearner()
                kg_nodes = await learner.record_audit(
                    page_url=page.url, findings=results, summary=summary,
                )
            except Exception as exc:
                logger.warning("KG learning failed: %s", exc)

        return {
            "page": page.url,
            "url": page.url,
            "viewport": session.viewport_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dimensions": results,
            "summary": summary,
            "kg_nodes_created": kg_nodes,
        }

    async def flow(self, name: str, steps: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Execute a multi-step user journey with auto-screenshots."""
        session = await self.sessions.create(
            viewport=kwargs.get("viewport", "desktop"),
            auth_profile=kwargs.get("auth_profile"),
        )

        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for i, step in enumerate(steps):
            step_result: dict[str, Any] = {
                "step": i + 1,
                "action": step["action"],
                "description": step.get("description", ""),
            }

            start = time.time()

            try:
                params = step.get("params", {})

                if step["action"] == "navigate":
                    await self.navigator.goto(session.page, params["url"])
                elif step["action"] == "click":
                    r = await self.click(session.id, params.get("target", ""), **params)
                    if not r.get("clicked"):
                        raise RuntimeError(r.get("error", "Click failed"))
                elif step["action"] == "type":
                    r = await self.type_text(session.id, params.get("target", ""), params.get("text", ""), **params)
                    if not r.get("typed"):
                        raise RuntimeError(r.get("error", "Type failed"))
                elif step["action"] == "wait":
                    await session.page.wait_for_timeout(params.get("ms", 2000))
                elif step["action"] == "screenshot":
                    r = await self.screenshot(session.id, **params)
                    step_result["screenshot"] = r["screenshot_path"]
                elif step["action"] == "assert":
                    await self._run_assertion(session.page, params)
                elif step["action"] == "scroll":
                    await self.interactor.scroll(session.page, **params)
                elif step["action"] == "audit":
                    r = await self.audit(session.id, **params)
                    step_result["audit"] = r

                step_result["status"] = "pass"

            except Exception as e:
                step_result["status"] = "fail"
                step_result["error"] = str(e)
                step_result["screenshot"] = str(
                    await self.capturer.screenshot(session.page, prefix=f"flow_fail_step{i+1}")
                )
                failures.append(step_result)

                if kwargs.get("stop_on_failure", False):
                    step_result["duration_ms"] = int((time.time() - start) * 1000)
                    results.append(step_result)
                    break

            step_result["duration_ms"] = int((time.time() - start) * 1000)

            # Auto-screenshot at each step
            if "screenshot" not in step_result:
                step_result["screenshot"] = str(
                    await self.capturer.screenshot(session.page, prefix=f"flow_step{i+1:02d}")
                )

            results.append(step_result)

        await self.sessions.close(session.id)

        return {
            "flow_name": name,
            "total_steps": len(steps),
            "passed": sum(1 for r in results if r["status"] == "pass"),
            "failed": len(failures),
            "duration_ms": sum(r.get("duration_ms", 0) for r in results),
            "steps": results,
            "failures": failures,
        }

    async def discover(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Auto-discover all navigable pages from a starting URL."""
        session = await self.sessions.create(
            viewport="desktop",
            auth_profile=kwargs.get("auth_profile"),
        )

        discovered = await self.navigator.discover_routes(
            session.page,
            start_url=url,
            max_depth=kwargs.get("max_depth", 3),
            max_pages=kwargs.get("max_pages", 50),
            exclude_patterns=kwargs.get("exclude_patterns", []),
        )

        await self.sessions.close(session.id)
        return discovered

    async def session_action(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Session management dispatcher."""
        if action == "create":
            session = await self.sessions.create(
                viewport=kwargs.get("viewport", "desktop"),
                auth_profile=kwargs.get("auth_profile"),
            )
            return {"session_id": session.id, "viewport": session.viewport_name}

        elif action == "login":
            login_url = kwargs.get("login_url", "")
            creds = kwargs.get("credentials", {})
            if not login_url or not creds:
                return {"error": "login_url and credentials required"}

            session = await self.sessions.create(viewport=kwargs.get("viewport", "desktop"))
            await self.navigator.goto(session.page, login_url)
            await session.page.wait_for_timeout(2000)

            # Auto-fill email + password
            if creds.get("email"):
                email_el = await self.interactor.find_input(session.page, "type:email")
                if email_el:
                    await email_el.fill(creds["email"])
            if creds.get("password"):
                pw_el = await self.interactor.find_input(session.page, "type:password")
                if pw_el:
                    await pw_el.fill(creds["password"])

            return {"session_id": session.id, "url": session.page.url}

        elif action == "save_auth":
            path = await self.sessions.save_auth(
                kwargs["session_id"], kwargs["profile_name"],
            )
            return {"saved": True, "path": path}

        elif action == "load_auth":
            session = await self.sessions.create(
                viewport=kwargs.get("viewport", "desktop"),
                auth_profile=kwargs["profile_name"],
            )
            return {"session_id": session.id, "profile": kwargs["profile_name"]}

        elif action == "list":
            return {"sessions": self.sessions.list_sessions()}

        elif action == "close":
            await self.sessions.close(kwargs["session_id"])
            return {"closed": True}

        elif action == "close_all":
            count = await self.sessions.close_all()
            return {"closed": count}

        return {"error": f"Unknown session action: {action}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_auditor(self, dimension: str) -> Any:
        """Get auditor instance for a dimension (lazy import)."""
        from graqle.plugins.phantom.auditors import (
            behavioral, accessibility, mobile, security,
            brand, conversion, performance, seo, i18n, content,
        )
        auditors = {
            "behavioral": behavioral.BehavioralAuditor(),
            "accessibility": accessibility.AccessibilityAuditor(),
            "mobile": mobile.MobileAuditor(),
            "security": security.SecurityAuditor(),
            "brand": brand.BrandAuditor(),
            "conversion": conversion.ConversionAuditor(),
            "performance": performance.PerformanceAuditor(),
            "seo": seo.SEOAuditor(),
            "i18n": i18n.I18nAuditor(),
            "content": content.ContentAuditor(),
        }
        return auditors[dimension]

    def _calculate_summary(self, results: dict[str, Any]) -> dict[str, Any]:
        """Calculate overall audit summary from dimension results."""
        critical = 0
        high = 0
        medium = 0
        low = 0

        # Security headers
        missing_headers = len(results.get("security", {}).get("missing_headers", []))
        if missing_headers >= 4:
            critical += 1
        elif missing_headers >= 2:
            high += 1

        # Contrast violations
        contrast = results.get("accessibility", {}).get("contrast_violations", 0)
        if contrast > 0:
            critical += 1

        # Touch targets
        small_targets = results.get("mobile", {}).get("small_touch_targets", 0)
        if small_targets > 20:
            high += 1
        elif small_targets > 5:
            medium += 1

        # Missing labels
        missing_aria = results.get("accessibility", {}).get("missing_aria_labels", 0)
        unlabeled = results.get("accessibility", {}).get("unlabeled_inputs", 0)
        if missing_aria + unlabeled > 5:
            high += 1
        elif missing_aria + unlabeled > 0:
            medium += 1

        # Dead clicks
        dead = results.get("behavioral", {}).get("dead_clicks", 0)
        if dead > 5:
            high += 1
        elif dead > 0:
            medium += 1

        # SEO gaps
        seo = results.get("seo", {})
        if not seo.get("title_ok", True) or not seo.get("meta_description_ok", True):
            medium += 1

        # Brand inconsistency
        brand = results.get("brand", {})
        if brand.get("button_inconsistent", False):
            low += 1
        if brand.get("off_brand_color_count", 0) > 3:
            medium += 1

        total = critical + high + medium + low

        grade = (
            "A" if total == 0 else
            "A-" if total <= 2 else
            "B+" if total <= 5 else
            "B" if total <= 8 else
            "B-" if total <= 12 else
            "C+" if total <= 18 else
            "C" if total <= 25 else
            "D"
        )

        return {
            "total_issues": total,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "grade": grade,
        }

    async def _detect_modals(self, page: Any) -> list[dict[str, Any]]:
        """Detect any visible modals/dialogs on the page."""
        return await page.evaluate("""
            () => {
                const modals = [];
                document.querySelectorAll(
                    'dialog[open], [role="dialog"], [role="alertdialog"], ' +
                    '.modal.show, .modal.active, [class*="modal"][class*="visible"]'
                ).forEach(el => {
                    modals.push({
                        tag: el.tagName,
                        role: el.getAttribute('role') || '',
                        text: (el.textContent || '').trim().substring(0, 200),
                    });
                });
                return modals;
            }
        """)

    async def _run_assertion(self, page: Any, params: dict[str, Any]) -> None:
        """Run an assertion against the current page state."""
        if "url_contains" in params:
            if params["url_contains"] not in page.url:
                raise AssertionError(
                    f"URL '{page.url}' does not contain '{params['url_contains']}'"
                )

        if "selector" in params:
            el = page.locator(params["selector"])
            if await el.count() == 0:
                raise AssertionError(f"Element '{params['selector']}' not found")

            if "text_contains" in params:
                text = await el.first.text_content()
                if params["text_contains"] not in (text or ""):
                    raise AssertionError(
                        f"Element text '{text}' does not contain '{params['text_contains']}'"
                    )

        if "visible" in params:
            el = page.locator(params["visible"])
            if await el.count() == 0 or not await el.first.is_visible():
                raise AssertionError(f"Element '{params['visible']}' is not visible")

        if "not_visible" in params:
            el = page.locator(params["not_visible"])
            if await el.count() > 0 and await el.first.is_visible():
                raise AssertionError(f"Element '{params['not_visible']}' should not be visible")
