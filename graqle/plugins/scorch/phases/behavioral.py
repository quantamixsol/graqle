"""Phase 2.5: 12 behavioral UX friction pattern tests."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.behavioral")


BEHAVIORAL_TESTS = {
    "dead_clicks": "Buttons/links with empty href, no onclick, or pointer-events:none",
    "silent_submissions": "Forms that submit without visible feedback (spinner, toast, redirect)",
    "unexplained_jargon": "Acronyms/abbreviations without title or aria-describedby tooltip",
    "ghost_elements": "Visible containers (border/bg) with <5 chars of content",
    "missing_next_step_cta": "Pages that end without a clear call-to-action or next step",
    "copy_paste_friction": "Content in non-selectable elements or user-select:none",
    "missing_inline_editor": "AI-generated text blocks without edit/copy affordance",
    "incomplete_generation": "Truncated outputs with no 'show more' or continuation",
    "feature_discoverability": "Hidden features requiring specific knowledge to find",
    "flow_continuity": "Dead-end pages with no back link or navigation to continue",
    "upsell_integrity": "Upgrade prompts shown for already-owned features/tiers",
    "action_response_feedback": "Actions lacking loading states or outcome confirmation",
}

_BEHAVIORAL_JS = """
() => {
    const findings = {};

    // 1. Dead clicks
    findings.deadClicks = [];
    document.querySelectorAll('a, button, [role="button"]').forEach(el => {
        const href = el.getAttribute('href');
        const onclick = el.getAttribute('onclick');
        const style = window.getComputedStyle(el);
        if (
            (!href || href === '#' || href === 'javascript:void(0)') &&
            !onclick &&
            !el.closest('[data-action]') &&
            style.pointerEvents !== 'none' &&
            el.offsetParent !== null
        ) {
            findings.deadClicks.push({
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 60),
                href: href,
            });
        }
    });

    // 2. Silent submissions
    findings.silentSubmissions = [];
    document.querySelectorAll('form').forEach(form => {
        const hasSpinner = form.querySelector('[class*="spinner"], [class*="loading"], [role="progressbar"]');
        const hasAriaLive = form.querySelector('[aria-live]');
        const hasAlert = form.querySelector('[role="alert"]');
        if (!hasSpinner && !hasAriaLive && !hasAlert) {
            findings.silentSubmissions.push({
                action: form.getAttribute('action') || '(inline)',
                fields: form.querySelectorAll('input, textarea, select').length,
            });
        }
    });

    // 3. Unexplained jargon
    findings.unexplainedJargon = [];
    const jargonPattern = /\\b[A-Z]{2,6}\\b/g;
    const allowList = new Set(['AI', 'UI', 'UX', 'API', 'CEO', 'CTO', 'URL', 'CSS', 'HTML', 'PDF', 'FAQ', 'ROI', 'KPI', 'SLA', 'CRM', 'ERP']);
    document.querySelectorAll('p, h1, h2, h3, h4, li, span, td, th').forEach(el => {
        const text = el.textContent || '';
        const matches = text.match(jargonPattern);
        if (matches) {
            matches.forEach(m => {
                if (!allowList.has(m) && !el.getAttribute('title') && !el.getAttribute('aria-describedby')) {
                    findings.unexplainedJargon.push({ term: m, context: text.substring(0, 80) });
                }
            });
        }
    });

    // 4. Ghost elements
    findings.ghostElements = [];
    document.querySelectorAll('div, section, article, aside').forEach(el => {
        const style = window.getComputedStyle(el);
        const hasBorderOrBg = style.border !== 'none' || style.backgroundColor !== 'rgba(0, 0, 0, 0)';
        const text = (el.textContent || '').trim();
        if (hasBorderOrBg && text.length < 5 && el.children.length === 0 && el.offsetParent !== null) {
            findings.ghostElements.push({
                tag: el.tagName,
                class: el.className?.substring(0, 60),
                size: `${el.offsetWidth}x${el.offsetHeight}`,
            });
        }
    });

    // 5. Missing next-step CTA (check last 20% of page)
    findings.missingNextStepCta = false;
    const pageHeight = document.documentElement.scrollHeight;
    const threshold = pageHeight * 0.8;
    const bottomCtas = document.querySelectorAll('a[href], button');
    let hasBottomCta = false;
    bottomCtas.forEach(el => {
        const rect = el.getBoundingClientRect();
        const absTop = rect.top + window.scrollY;
        if (absTop > threshold) hasBottomCta = true;
    });
    findings.missingNextStepCta = !hasBottomCta;

    // 6. Copy-paste friction
    findings.copyPasteFriction = [];
    document.querySelectorAll('[style*="user-select: none"], [style*="user-select:none"]').forEach(el => {
        if (el.textContent?.trim().length > 20) {
            findings.copyPasteFriction.push({
                text: el.textContent.trim().substring(0, 60),
            });
        }
    });

    // 7. Missing inline editor (AI-generated content without edit affordance)
    findings.missingInlineEditor = [];
    document.querySelectorAll('[data-ai-generated], [class*="ai-output"], [class*="generated"]').forEach(el => {
        const hasEdit = el.querySelector('[class*="edit"], button[aria-label*="edit"], [contenteditable]');
        const hasCopy = el.querySelector('[class*="copy"], button[aria-label*="copy"]');
        if (!hasEdit && !hasCopy) {
            findings.missingInlineEditor.push({
                text: (el.textContent || '').trim().substring(0, 60),
            });
        }
    });

    // 8. Incomplete generation
    findings.incompleteGeneration = [];
    document.querySelectorAll('[data-ai-generated], [class*="ai-output"], [class*="generated"]').forEach(el => {
        const text = el.textContent || '';
        if (text.endsWith('...') || text.endsWith('\\u2026') || text.includes('[truncated]')) {
            const hasShowMore = el.querySelector('[class*="more"], [class*="expand"]');
            if (!hasShowMore) {
                findings.incompleteGeneration.push({
                    text: text.substring(Math.max(0, text.length - 80)),
                });
            }
        }
    });

    // 9. Feature discoverability (hidden interactive elements)
    findings.featureDiscoverability = [];
    document.querySelectorAll('[hidden], [style*="display: none"], [style*="display:none"], [aria-hidden="true"]').forEach(el => {
        if (el.querySelector('button, a, input, select')) {
            findings.featureDiscoverability.push({
                tag: el.tagName,
                class: el.className?.substring(0, 60),
            });
        }
    });

    // 10. Flow continuity (dead-end check)
    findings.flowContinuity = {
        hasNavigation: !!document.querySelector('nav, [role="navigation"]'),
        hasBackLink: !!document.querySelector('a[href*="back"], [class*="back"], [aria-label*="back"]'),
        hasBreadcrumbs: !!document.querySelector('[class*="breadcrumb"], [aria-label*="breadcrumb"], nav ol'),
    };

    // 11. Upsell integrity (flag for cross-reference with tier context)
    findings.upsellIntegrity = [];
    document.querySelectorAll('[class*="upgrade"], [class*="upsell"], a[href*="pricing"], a[href*="upgrade"]').forEach(el => {
        findings.upsellIntegrity.push({
            text: (el.textContent || '').trim().substring(0, 80),
            href: el.getAttribute('href'),
        });
    });

    // 12. Action-response feedback
    findings.actionResponseFeedback = [];
    document.querySelectorAll('button[type="submit"], button:not([type]), [role="button"]').forEach(el => {
        const form = el.closest('form');
        const hasLoadingState = el.querySelector('[class*="spinner"], [class*="loading"]');
        const hasAriaLive = el.closest('[aria-live]');
        if (!hasLoadingState && !hasAriaLive && !form) {
            findings.actionResponseFeedback.push({
                text: (el.textContent || '').trim().substring(0, 60),
            });
        }
    });

    return findings;
}
"""


async def extract_behavioral_ux(config: Any) -> list[dict[str, Any]]:
    """Run 12 behavioral UX tests across all pages x viewports.

    Returns list of:
        {"page": str, "viewport": str, "url": str, "findings": {...}}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("SCORCH requires playwright. Install with: pip install graqle[scorch]")

    results: list[dict[str, Any]] = []

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
                logger.info("Behavioral UX tests: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    findings = await page.evaluate(_BEHAVIORAL_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("Behavioral tests failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Phase 2.5 complete: %d behavioral test sets", len(results))
    return results
