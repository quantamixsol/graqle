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
