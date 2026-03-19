"""Phase 1: Capture full-page screenshots at configured viewports."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scorch.screenshot")


async def capture_screenshots(config: Any) -> list[dict[str, Any]]:
    """Launch Playwright and capture screenshots for all pages x viewports.

    Returns list of:
        {"page": str, "viewport": str, "path": str, "width": int, "height": int}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError(
            "SCORCH requires playwright. Install with: "
            "pip install graqle[scorch] && python -m playwright install chromium"
        )

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    screenshots: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for vp in config.viewports:
            context = await browser.new_context(
                viewport={"width": vp.width, "height": vp.height},
                device_scale_factor=vp.device_scale_factor,
                storage_state=config.auth_state if config.auth_state else None,
            )
            page = await context.new_page()

            for page_path in config.pages:
                url = f"{config.base_url.rstrip('/')}{page_path}"
                logger.info("Capturing %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    filename = f"{page_path.strip('/').replace('/', '-') or 'home'}-{vp.name}.png"
                    filepath = output_dir / filename

                    await page.screenshot(
                        path=str(filepath),
                        full_page=config.full_page,
                    )

                    screenshots.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "path": str(filepath),
                        "width": vp.width,
                        "height": vp.height,
                        "url": url,
                    })
                except Exception as exc:
                    logger.error("Failed to capture %s @ %s: %s", url, vp.name, exc)
                    screenshots.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "path": None,
                        "error": str(exc),
                    })

            await context.close()

        await browser.close()

    logger.info("Phase 1 complete: %d screenshots captured", len(screenshots))
    return screenshots
