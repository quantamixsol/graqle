"""SCORCH Phase: Mobile-specific audit.

Checks touch target sizes, viewport meta, font readability, horizontal
scroll, input types, intrusive fixed elements, and pinch-zoom availability.
Only runs on mobile viewports (skips desktop viewports automatically).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.mobile")

_MOBILE_JS = """
() => {
    const findings = {};

    // 1. Touch target size (interactive elements must be >= 44x44 CSS px)
    findings.smallTouchTargets = [];
    const TOUCH_MIN = 44;
    document.querySelectorAll(
        'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="radio"]'
    ).forEach(el => {
        if (el.offsetParent === null) return; // hidden element
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 || rect.height > 0) {
            const tooSmall = rect.width < TOUCH_MIN || rect.height < TOUCH_MIN;
            if (tooSmall) {
                findings.smallTouchTargets.push({
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    text: (el.textContent || el.getAttribute('aria-label') || el.getAttribute('value') || '').trim().substring(0, 40),
                });
            }
        }
    });
    // Cap at 30 worst offenders
    findings.smallTouchTargets = findings.smallTouchTargets.slice(0, 30);

    // 2. Viewport meta tag
    const viewportEl = document.querySelector('meta[name="viewport"]');
    const viewportContent = viewportEl ? (viewportEl.getAttribute('content') || '') : '';
    findings.viewport = {
        exists: !!viewportEl,
        content: viewportContent,
        hasWidthDeviceWidth: viewportContent.includes('width=device-width'),
        hasInitialScale: viewportContent.includes('initial-scale'),
    };

    // 3. Text readability — font-size < 16px on body text elements
    findings.smallTextElements = [];
    document.querySelectorAll('p, li, td, span, div, a').forEach(el => {
        if (el.offsetParent === null) return;
        if (!(el.textContent || '').trim()) return;
        const fs = parseFloat(window.getComputedStyle(el).fontSize);
        if (fs > 0 && fs < 16) {
            findings.smallTextElements.push({
                tag: el.tagName,
                fontSize: fs,
                text: el.textContent.trim().substring(0, 50),
            });
        }
    });
    findings.smallTextElements = findings.smallTextElements.slice(0, 20);

    // 4. Horizontal scroll detection
    findings.horizontalScroll = {
        detected: document.documentElement.scrollWidth > window.innerWidth,
        pageWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        overflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
    };

    // 5. Input types — email/tel/url inputs should use the correct type
    findings.incorrectInputTypes = [];
    document.querySelectorAll('input').forEach(input => {
        const type = (input.getAttribute('type') || 'text').toLowerCase();
        const name = (input.getAttribute('name') || input.getAttribute('id') || input.getAttribute('placeholder') || '').toLowerCase();
        const checks = [
            { keywords: ['email', 'e-mail', 'mail'], expected: 'email' },
            { keywords: ['phone', 'tel', 'mobile', 'cell'], expected: 'tel' },
            { keywords: ['url', 'website', 'http'], expected: 'url' },
            { keywords: ['number', 'quantity', 'amount', 'count', 'qty'], expected: 'number' },
        ];
        for (const { keywords, expected } of checks) {
            if (keywords.some(k => name.includes(k)) && type !== expected && type === 'text') {
                findings.incorrectInputTypes.push({
                    name: input.getAttribute('name') || input.getAttribute('id'),
                    currentType: type,
                    suggestedType: expected,
                    placeholder: (input.getAttribute('placeholder') || '').substring(0, 40),
                });
                break;
            }
        }
    });

    // 6. Fixed/sticky elements covering too much screen (> 20% of viewport height)
    findings.intrusiveFixedElements = [];
    const vpHeight = window.innerHeight;
    document.querySelectorAll('*').forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.position === 'fixed' || style.position === 'sticky') {
            const rect = el.getBoundingClientRect();
            if (rect.height > 0 && rect.width > 0) {
                const coveragePct = Math.round(rect.height / vpHeight * 100);
                if (coveragePct > 20) {
                    findings.intrusiveFixedElements.push({
                        tag: el.tagName,
                        id: el.id || null,
                        class: (el.className || '').toString().substring(0, 60),
                        position: style.position,
                        heightPx: Math.round(rect.height),
                        coveragePct,
                    });
                }
            }
        }
    });

    // 7. Pinch-zoom disabled check (user-scalable=no)
    const vpRaw = viewportContent.replace(/\\s/g, '').toLowerCase();
    findings.pinchZoom = {
        disabled: vpRaw.includes('user-scalable=no') || vpRaw.includes('user-scalable=0'),
        maximumScaleOne: vpRaw.includes('maximum-scale=1'),
    };

    // Summary
    findings.summary = {
        smallTouchTargetCount: findings.smallTouchTargets.length,
        viewportOk: findings.viewport.exists && findings.viewport.hasWidthDeviceWidth,
        smallTextCount: findings.smallTextElements.length,
        horizontalScroll: findings.horizontalScroll.detected,
        incorrectInputTypeCount: findings.incorrectInputTypes.length,
        intrusiveFixedCount: findings.intrusiveFixedElements.length,
        pinchZoomDisabled: findings.pinchZoom.disabled || findings.pinchZoom.maximumScaleOne,
    };
    findings.summary.totalIssues = Object.values(findings.summary).reduce((acc, v) => {
        if (typeof v === 'boolean') return acc + (v ? 1 : 0);
        if (typeof v === 'number') return acc + v;
        return acc;
    }, 0);

    return findings;
}
"""


async def audit_mobile(config: Any) -> list[dict[str, Any]]:
    """Run mobile-specific audit on mobile viewports only, across all pages.

    Skips desktop viewports (width >= 1024px).

    Returns list of:
        {"page": str, "viewport": str, "url": str, "findings": {...}}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("SCORCH requires playwright. Install with: pip install graqle[scorch]")

    results: list[dict[str, Any]] = []

    # Filter to mobile viewports only
    mobile_viewports = [vp for vp in config.viewports if vp.width < 1024]
    if not mobile_viewports:
        logger.warning("Mobile audit: no mobile viewports configured (all widths >= 1024). Skipping.")
        return results

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for vp in mobile_viewports:
            context = await browser.new_context(
                viewport={"width": vp.width, "height": vp.height},
                device_scale_factor=vp.device_scale_factor,
                storage_state=config.auth_state if config.auth_state else None,
                is_mobile=True,
                has_touch=True,
            )
            page = await context.new_page()

            for page_path in config.pages:
                url = f"{config.base_url.rstrip('/')}{page_path}"
                logger.info("Mobile audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)
                    findings = await page.evaluate(_MOBILE_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("Mobile audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Mobile audit complete: %d test sets", len(results))
    return results
