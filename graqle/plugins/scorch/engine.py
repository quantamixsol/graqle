"""SCORCH Engine — orchestrates the 5-phase audit pipeline."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from graqle.plugins.scorch.config import ScorchConfig

logger = logging.getLogger("graqle.scorch")


class ScorchEngine:
    """Orchestrates the SCORCH v3 5-phase pipeline.

    Usage:
        engine = ScorchEngine(config)
        report = await engine.run()              # Full pipeline
        report = await engine.run_behavioral()   # Phase 2.5 only
    """

    def __init__(self, config: ScorchConfig | None = None, config_path: str | None = None):
        if config_path:
            self.config = ScorchConfig.from_json(config_path)
        elif config:
            self.config = config
        else:
            self.config = ScorchConfig()

    async def run(self) -> dict[str, Any]:
        """Execute the full 5-phase SCORCH pipeline."""
        from graqle.plugins.scorch.phases.screenshot import capture_screenshots
        from graqle.plugins.scorch.phases.css_metrics import extract_css_metrics
        from graqle.plugins.scorch.phases.behavioral import extract_behavioral_ux
        from graqle.plugins.scorch.phases.vision import analyze_with_vision
        from graqle.plugins.scorch.phases.report import generate_report

        logger.info("SCORCH v3 — Starting full audit of %s", self.config.base_url)

        # Phase 1: Screenshots
        logger.info("Phase 1: Capturing screenshots...")
        screenshots = await capture_screenshots(self.config)

        # Phase 2: CSS Metrics
        logger.info("Phase 2: Extracting CSS metrics...")
        metrics = await extract_css_metrics(self.config)

        # Phase 2.5: Behavioral UX (unless skipped)
        behavioral: list[dict[str, Any]] = []
        if not self.config.skip_behavioral:
            logger.info("Phase 2.5: Running 12 behavioral UX tests...")
            behavioral = await extract_behavioral_ux(self.config)
        else:
            logger.info("Phase 2.5: Skipped (--skip-behavioral)")

        # Phase 3: Claude Vision (unless skipped)
        vision_analysis: dict[str, Any] = {
            "issues": [], "journeyAnalysis": {}, "summary": "Vision analysis skipped.",
        }
        if not self.config.skip_vision:
            logger.info("Phase 3: Claude Vision + Journey Psychology analysis...")
            vision_analysis = await analyze_with_vision(
                screenshots, metrics, behavioral, self.config
            )
        else:
            logger.info("Phase 3: Skipped (--skip-vision)")

        # Phase 4: Report
        logger.info("Phase 4: Generating combined report...")
        report = generate_report(screenshots, metrics, behavioral, vision_analysis, self.config)

        logger.info(
            "SCORCH v3 complete — %s | Critical: %d | Major: %d | Journey: %s/10",
            "PASS" if report["pass"] else "FAIL",
            report["severityCounts"]["critical"],
            report["severityCounts"]["major"],
            report.get("journeyAnalysis", {}).get("journeyScore", "N/A"),
        )

        return report

    async def run_behavioral_only(self) -> list[dict[str, Any]]:
        """Run only Phase 2.5 (behavioral UX tests) — fast, no AI cost."""
        from graqle.plugins.scorch.phases.behavioral import extract_behavioral_ux

        logger.info("SCORCH — Behavioral-only audit of %s", self.config.base_url)
        return await extract_behavioral_ux(self.config)

    async def run_css_only(self) -> list[dict[str, Any]]:
        """Run only Phase 2 (CSS metrics) — fastest, no AI cost."""
        from graqle.plugins.scorch.phases.css_metrics import extract_css_metrics

        logger.info("SCORCH — CSS-only audit of %s", self.config.base_url)
        return await extract_css_metrics(self.config)

    async def run_a11y(self) -> list[dict[str, Any]]:
        """Run WCAG 2.1 AA/AAA accessibility audit."""
        from graqle.plugins.scorch.phases.a11y import audit_accessibility

        logger.info("SCORCH — Accessibility audit of %s", self.config.base_url)
        return await audit_accessibility(self.config)

    async def run_perf(self) -> list[dict[str, Any]]:
        """Run Core Web Vitals performance audit."""
        from graqle.plugins.scorch.phases.perf import audit_performance

        logger.info("SCORCH — Performance audit of %s", self.config.base_url)
        return await audit_performance(self.config)

    async def run_seo(self) -> list[dict[str, Any]]:
        """Run SEO audit (meta tags, structured data, Open Graph)."""
        from graqle.plugins.scorch.phases.seo import audit_seo

        logger.info("SCORCH — SEO audit of %s", self.config.base_url)
        return await audit_seo(self.config)

    async def run_mobile(self) -> list[dict[str, Any]]:
        """Run mobile-specific audit (touch targets, viewport, text readability)."""
        from graqle.plugins.scorch.phases.mobile import audit_mobile

        logger.info("SCORCH — Mobile audit of %s", self.config.base_url)
        return await audit_mobile(self.config)

    async def run_i18n(self) -> list[dict[str, Any]]:
        """Run internationalization audit (hardcoded strings, RTL, locale formatting)."""
        from graqle.plugins.scorch.phases.i18n import audit_i18n

        logger.info("SCORCH — i18n audit of %s", self.config.base_url)
        return await audit_i18n(self.config)

    async def run_security(self) -> list[dict[str, Any]]:
        """Run frontend security audit (CSP, XSS vectors, exposed keys)."""
        from graqle.plugins.scorch.phases.security import audit_security

        logger.info("SCORCH — Security audit of %s", self.config.base_url)
        return await audit_security(self.config)

    async def run_conversion(self) -> list[dict[str, Any]]:
        """Run conversion funnel analysis (CTAs, forms, trust signals)."""
        from graqle.plugins.scorch.phases.conversion import audit_conversion

        logger.info("SCORCH — Conversion audit of %s", self.config.base_url)
        return await audit_conversion(self.config)

    async def run_brand(self) -> list[dict[str, Any]]:
        """Run brand consistency audit (colors, typography, logo, spacing)."""
        from graqle.plugins.scorch.phases.brand import audit_brand

        logger.info("SCORCH — Brand audit of %s", self.config.base_url)
        return await audit_brand(self.config)

    async def run_auth_flow(self) -> list[dict[str, Any]]:
        """Run authenticated user journey audit (login/signup/dashboard flows)."""
        from graqle.plugins.scorch.phases.auth_flow import audit_auth_flow

        logger.info("SCORCH — Auth flow audit of %s", self.config.base_url)
        return await audit_auth_flow(self.config)

    async def run_diff(self, previous_report_path: str | None = None) -> dict[str, Any]:
        """Run before/after comparison against a previous SCORCH report."""
        from graqle.plugins.scorch.phases.diff import audit_diff

        logger.info("SCORCH — Diff comparison for %s", self.config.base_url)
        return await audit_diff(self.config, previous_report_path)
