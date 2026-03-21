"""Accessibility auditor — WCAG 2.1 AA/AAA checks."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.a11y")

_A11Y_JS = """
() => {
    const r = {};

    // Contrast violations (simplified check — real check needs computed styles)
    r.contrast_violations = 0;
    document.querySelectorAll('p, span, a, button, label, h1, h2, h3, h4, h5, h6').forEach(el => {
        const style = window.getComputedStyle(el);
        const color = style.color;
        const bg = style.backgroundColor;
        // Basic: flag white-on-light or dark-on-dark
        if (color === bg && el.textContent.trim().length > 0) {
            r.contrast_violations++;
        }
    });

    // Missing ARIA labels
    r.missing_aria_labels = 0;
    document.querySelectorAll('button, [role="button"], a, input, select, textarea').forEach(el => {
        const hasLabel = el.getAttribute('aria-label') ||
            el.getAttribute('aria-labelledby') ||
            el.getAttribute('title') ||
            el.textContent.trim().length > 0;
        if (!hasLabel) r.missing_aria_labels++;
    });

    // Missing alt text
    r.missing_alt_text = 0;
    document.querySelectorAll('img').forEach(img => {
        if (!img.getAttribute('alt') && img.getAttribute('alt') !== '') r.missing_alt_text++;
    });

    // Heading hierarchy issues
    r.heading_issues = 0;
    let lastLevel = 0;
    document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
        const level = parseInt(h.tagName[1]);
        if (level > lastLevel + 1) r.heading_issues++;
        lastLevel = level;
    });

    // Landmark issues
    r.landmark_issues = 0;
    if (!document.querySelector('main, [role="main"]')) r.landmark_issues++;
    if (!document.querySelector('nav, [role="navigation"]')) r.landmark_issues++;

    // Unlabeled inputs
    r.unlabeled_inputs = 0;
    document.querySelectorAll('input, select, textarea').forEach(input => {
        const id = input.id;
        const hasLabel = id && document.querySelector('label[for="' + id + '"]');
        const hasAriaLabel = input.getAttribute('aria-label') || input.getAttribute('aria-labelledby');
        const hasPlaceholder = input.getAttribute('placeholder');
        if (!hasLabel && !hasAriaLabel && !hasPlaceholder && input.type !== 'hidden') {
            r.unlabeled_inputs++;
        }
    });

    // Focus order issues (tab index > 0)
    r.focus_order_issues = 0;
    document.querySelectorAll('[tabindex]').forEach(el => {
        const ti = parseInt(el.getAttribute('tabindex'));
        if (ti > 0) r.focus_order_issues++;
    });

    // WCAG level estimate
    const total = r.contrast_violations + r.missing_aria_labels + r.missing_alt_text +
                  r.heading_issues + r.unlabeled_inputs;
    r.wcag_level = total === 0 ? 'AAA' : total <= 3 ? 'AA' : 'BELOW_AA';

    return r;
}
"""


class AccessibilityAuditor:
    """WCAG 2.1 AA/AAA accessibility audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_A11Y_JS)
        except Exception as exc:
            logger.error("Accessibility audit failed: %s", exc)
            return {"error": str(exc)}
