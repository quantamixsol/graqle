"""Conversion auditor — CTAs, forms, trust signals."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.conversion")

_CONVERSION_JS = """
() => {
    const r = {};

    // CTAs above the fold
    r.ctas_above_fold = 0;
    const foldHeight = window.innerHeight;
    document.querySelectorAll('a, button, [role="button"]').forEach(el => {
        const rect = el.getBoundingClientRect();
        const text = (el.textContent || '').trim().toLowerCase();
        const isCta = ['sign up', 'get started', 'try', 'start', 'buy', 'subscribe',
                       'register', 'create account', 'join', 'download', 'free trial'].some(
            kw => text.includes(kw)
        );
        if (isCta && rect.top < foldHeight) r.ctas_above_fold++;
    });

    // Trust signals
    r.trust_signals = 0;
    const trustPatterns = ['trusted by', 'as seen', 'certified', 'secure',
                           'ssl', 'verified', 'rating', 'review', 'testimonial'];
    const bodyText = (document.body.innerText || '').toLowerCase();
    trustPatterns.forEach(p => { if (bodyText.includes(p)) r.trust_signals++; });

    // Form count
    r.form_count = document.querySelectorAll('form').length;

    // Weak CTAs
    r.weak_cta_count = 0;
    const weakPatterns = ['click here', 'submit', 'learn more', 'read more'];
    document.querySelectorAll('a, button').forEach(el => {
        const text = (el.textContent || '').trim().toLowerCase();
        if (weakPatterns.some(p => text === p)) r.weak_cta_count++;
    });

    return r;
}
"""


class ConversionAuditor:
    """Conversion funnel audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_CONVERSION_JS)
        except Exception as exc:
            logger.error("Conversion audit failed: %s", exc)
            return {"error": str(exc)}
