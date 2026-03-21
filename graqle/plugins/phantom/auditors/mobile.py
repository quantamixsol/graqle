"""Mobile auditor — touch targets, viewport, text readability."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.mobile")

_MOBILE_JS = """
() => {
    const r = {};

    // Small touch targets (< 44x44 px)
    r.small_touch_targets = 0;
    document.querySelectorAll('a, button, [role="button"], input, select').forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44)) {
            r.small_touch_targets++;
        }
    });

    // Small text (< 14px)
    r.small_text_elements = 0;
    document.querySelectorAll('p, span, a, li, td, th, label').forEach(el => {
        const size = parseFloat(window.getComputedStyle(el).fontSize);
        if (size < 14 && el.textContent.trim().length > 0) {
            r.small_text_elements++;
        }
    });

    // Horizontal scroll check
    r.horizontal_scroll = document.documentElement.scrollWidth > document.documentElement.clientWidth;

    // Viewport meta tag
    const viewportMeta = document.querySelector('meta[name="viewport"]');
    r.viewport_ok = !!viewportMeta && viewportMeta.content.includes('width=device-width');

    // Pinch zoom disabled
    r.pinch_zoom_disabled = viewportMeta ?
        (viewportMeta.content.includes('user-scalable=no') ||
         viewportMeta.content.includes('maximum-scale=1')) : false;

    return r;
}
"""


class MobileAuditor:
    """Mobile-specific audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_MOBILE_JS)
        except Exception as exc:
            logger.error("Mobile audit failed: %s", exc)
            return {"error": str(exc)}
