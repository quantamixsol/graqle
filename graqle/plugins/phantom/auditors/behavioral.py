"""Behavioral UX auditor — detects interaction friction patterns."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.behavioral")

_BEHAVIORAL_JS = """
() => {
    const f = {};

    // 1. Dead clicks (buttons/links with no action)
    f.dead_clicks = 0;
    document.querySelectorAll('a, button, [role="button"]').forEach(el => {
        const href = el.getAttribute('href');
        const onclick = el.getAttribute('onclick');
        if (
            (!href || href === '#' || href === 'javascript:void(0)') &&
            !onclick && !el.closest('[data-action]') &&
            el.offsetParent !== null
        ) f.dead_clicks++;
    });

    // 2. Silent submissions (forms without feedback)
    f.silent_submissions = 0;
    document.querySelectorAll('form').forEach(form => {
        const hasSpinner = form.querySelector('[class*="spinner"], [class*="loading"], [role="progressbar"]');
        const hasLive = form.querySelector('[aria-live]');
        if (!hasSpinner && !hasLive) f.silent_submissions++;
    });

    // 3. Ghost elements (visible containers with minimal content)
    f.ghost_elements = 0;
    document.querySelectorAll('div, section, article').forEach(el => {
        const style = window.getComputedStyle(el);
        const hasBorder = style.border !== 'none' && style.border !== '';
        const hasBg = style.backgroundColor !== 'rgba(0, 0, 0, 0)' && style.backgroundColor !== 'transparent';
        const text = (el.textContent || '').trim();
        if ((hasBorder || hasBg) && text.length < 5 && el.children.length === 0) {
            f.ghost_elements++;
        }
    });

    // 4. Abbreviations without explanation
    f.abbreviations = [];
    const jargonPattern = /\\b[A-Z]{2,6}\\b/g;
    const allowList = new Set(['AI', 'UI', 'UX', 'API', 'CEO', 'CTO', 'URL', 'CSS', 'HTML', 'PDF', 'FAQ']);
    document.querySelectorAll('p, h1, h2, h3, h4, li, span, td').forEach(el => {
        const text = el.textContent || '';
        const matches = text.match(jargonPattern);
        if (matches) {
            matches.forEach(m => {
                if (!allowList.has(m) && !el.getAttribute('title') && !el.getAttribute('aria-describedby')) {
                    if (!f.abbreviations.includes(m)) f.abbreviations.push(m);
                }
            });
        }
    });

    // 5. Missing next-step CTA
    const lastSection = document.querySelector('main > :last-child, #content > :last-child, .content > :last-child');
    f.missing_next_step_cta = lastSection ? !lastSection.querySelector('a, button') : false;

    // 6. Flow continuity
    f.flow_continuity = {
        hasNav: !!document.querySelector('nav, [role="navigation"]'),
        hasBack: !!document.querySelector('a[href*="back"], button[class*="back"], [aria-label*="back"]'),
        hasBreadcrumbs: !!document.querySelector('[aria-label*="breadcrumb"], .breadcrumb'),
    };

    return f;
}
"""


class BehavioralAuditor:
    """Detects behavioral UX friction patterns on any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        """Run behavioral audit via JavaScript evaluation."""
        try:
            return await page.evaluate(_BEHAVIORAL_JS)
        except Exception as exc:
            logger.error("Behavioral audit failed: %s", exc)
            return {"error": str(exc)}
