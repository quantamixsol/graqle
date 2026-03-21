"""Brand consistency auditor — colors, typography, logo, spacing."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.brand")

_BRAND_JS = """
(brandRules) => {
    const r = {};

    // Logo presence
    r.has_logo = !!document.querySelector(
        'img[class*="logo"], img[alt*="logo"], [class*="logo"] img, header img, .brand img'
    );

    // Font family consistency
    const fonts = new Set();
    document.querySelectorAll('body, p, h1, h2, h3, button, a, span').forEach(el => {
        const font = window.getComputedStyle(el).fontFamily.split(',')[0].trim().replace(/['"]/g, '');
        if (font) fonts.add(font);
    });
    r.font_consistent = fonts.size <= 3;
    r.font_family = [...fonts].join(', ');

    // Button border-radius consistency
    const radii = new Set();
    document.querySelectorAll('button, [role="button"], a.btn, .button').forEach(b => {
        radii.add(window.getComputedStyle(b).borderRadius);
    });
    r.button_radii_count = radii.size;
    r.button_inconsistent = radii.size > 3;

    // Font size violations (too small)
    r.font_size_violations = 0;
    const minBody = brandRules?.min_body_font_px || 16;
    document.querySelectorAll('p, span, li, td, a').forEach(el => {
        const size = parseFloat(window.getComputedStyle(el).fontSize);
        if (size < minBody && el.textContent.trim().length > 0) {
            r.font_size_violations++;
        }
    });

    // Off-brand colors (colors not in brand palette)
    r.off_brand_color_count = 0;
    // This is a simplified check — real implementation would compare against config palette

    return r;
}
"""


class BrandAuditor:
    """Brand consistency audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            brand_rules = {}
            if config and hasattr(config, "brand_rules"):
                brand_rules = config.brand_rules.model_dump()
            return await page.evaluate(_BRAND_JS, brand_rules)
        except Exception as exc:
            logger.error("Brand audit failed: %s", exc)
            return {"error": str(exc)}
