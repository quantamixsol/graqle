"""Phase 2: Extract CSS metrics (fonts, contrast, touch targets, overflow)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.css_metrics")


_EXTRACT_JS = """
() => {
    const results = { fonts: [], touchTargets: [], overflow: false, contrast: [] };

    // Font sizes below threshold
    document.querySelectorAll('*').forEach(el => {
        const style = window.getComputedStyle(el);
        const text = el.textContent?.trim();
        if (text && text.length > 0 && text.length < 500) {
            const size = parseFloat(style.fontSize);
            if (size > 0 && size < 14) {
                results.fonts.push({
                    tag: el.tagName,
                    text: text.substring(0, 50),
                    size: size,
                    selector: el.className ? `.${el.className.split(' ')[0]}` : el.tagName,
                });
            }
        }
    });

    // Touch targets (interactive elements smaller than 44px)
    document.querySelectorAll('a, button, input, select, textarea, [role="button"], [onclick]').forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            const minDim = Math.min(rect.width, rect.height);
            if (minDim < 44) {
                results.touchTargets.push({
                    tag: el.tagName,
                    text: (el.textContent || el.getAttribute('aria-label') || '').substring(0, 50),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                });
            }
        }
    });

    // Horizontal overflow
    results.overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;

    return results;
}
"""


async def extract_css_metrics(config: Any) -> list[dict[str, Any]]:
    """Extract CSS metrics for all pages x viewports.

    Returns list of:
        {"page": str, "viewport": str, "fonts": [...], "touchTargets": [...], "overflow": bool}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("SCORCH requires playwright. Install with: pip install graqle[scorch]")

    metrics: list[dict[str, Any]] = []

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
                logger.info("Extracting CSS metrics: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    result = await page.evaluate(_EXTRACT_JS)
                    result["page"] = page_path
                    result["viewport"] = vp.name
                    metrics.append(result)
                except Exception as exc:
                    logger.error("CSS metrics failed for %s @ %s: %s", url, vp.name, exc)
                    metrics.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Phase 2 complete: %d metric sets extracted", len(metrics))
    return metrics
