"""Capturer — screenshots, DOM snapshots, network HAR."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.phantom.capturer")


class Capturer:
    """Captures page state: screenshots, DOM summaries, network data."""

    def __init__(self, output_dir: str = "./scorch-output/phantom"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def screenshot(
        self,
        page: Any,
        prefix: str = "capture",
        full_page: bool = True,
        region: str | None = None,
        mask: list[str] | None = None,
    ) -> Path:
        """Take a screenshot and return the file path."""
        timestamp = int(time.time())
        filename = f"{prefix}_{timestamp}.png"
        path = self.output_dir / filename

        screenshot_kwargs: dict[str, Any] = {
            "path": str(path),
            "full_page": full_page,
            "type": "png",
        }

        if region:
            # Screenshot a specific element
            element = page.locator(region)
            if await element.count() > 0:
                await element.first.screenshot(path=str(path))
                logger.info("Element screenshot saved: %s", path)
                return path

        if mask:
            # Mask sensitive elements
            mask_locators = []
            for selector in mask:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    mask_locators.append(loc)
            if mask_locators:
                screenshot_kwargs["mask"] = mask_locators

        await page.screenshot(**screenshot_kwargs)
        logger.info("Screenshot saved: %s", path)
        return path

    async def dom_snapshot(self, page: Any) -> dict[str, Any]:
        """Extract a summarized DOM structure (not the full DOM — just key elements)."""
        return await page.evaluate("""
            () => {
                const snapshot = {
                    title: document.title,
                    h1: '',
                    headings: [],
                    buttons: [],
                    links: [],
                    forms: 0,
                    inputs: [],
                    images: 0,
                    landmarks: {main: false, nav: false, banner: false, footer: false},
                    dom_nodes: document.querySelectorAll('*').length,
                    word_count: 0,
                };

                // H1
                const h1 = document.querySelector('h1');
                if (h1) snapshot.h1 = h1.textContent.trim().substring(0, 100);

                // Headings
                document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
                    snapshot.headings.push({
                        level: parseInt(h.tagName[1]),
                        text: h.textContent.trim().substring(0, 100)
                    });
                });

                // Buttons (limit to 50)
                let btnCount = 0;
                document.querySelectorAll('button, [role="button"], input[type="submit"]').forEach(b => {
                    if (btnCount++ < 50) {
                        const rect = b.getBoundingClientRect();
                        snapshot.buttons.push({
                            text: (b.textContent || b.value || '').trim().substring(0, 60),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        });
                    }
                });

                // Links (limit to 50)
                let linkCount = 0;
                document.querySelectorAll('a[href]').forEach(a => {
                    if (linkCount++ < 50) {
                        snapshot.links.push({
                            text: a.textContent.trim().substring(0, 60),
                            href: a.getAttribute('href'),
                        });
                    }
                });

                // Forms
                snapshot.forms = document.querySelectorAll('form').length;

                // Inputs (limit to 30)
                let inputCount = 0;
                document.querySelectorAll('input, textarea, select').forEach(i => {
                    if (inputCount++ < 30) {
                        snapshot.inputs.push({
                            type: i.type || i.tagName.toLowerCase(),
                            placeholder: i.placeholder || '',
                            name: i.name || '',
                        });
                    }
                });

                // Images
                snapshot.images = document.querySelectorAll('img').length;

                // Landmarks
                snapshot.landmarks.main = !!document.querySelector('main, [role="main"]');
                snapshot.landmarks.nav = !!document.querySelector('nav, [role="navigation"]');
                snapshot.landmarks.banner = !!document.querySelector('header, [role="banner"]');
                snapshot.landmarks.footer = !!document.querySelector('footer, [role="contentinfo"]');

                // Word count
                const text = document.body ? document.body.innerText : '';
                snapshot.word_count = text.split(/\\s+/).filter(w => w.length > 0).length;

                return snapshot;
            }
        """)
