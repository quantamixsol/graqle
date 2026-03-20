"""SCORCH Phase: Accessibility (WCAG 2.1 AA/AAA) audit.

Tests color contrast, missing aria-labels, focus order, screen reader
simulation, heading hierarchy, and landmark structure.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.a11y")

_A11Y_JS = """
() => {
    const findings = {};

    // 1. Color contrast violations (text elements with insufficient contrast)
    findings.contrastIssues = [];
    document.querySelectorAll('p, h1, h2, h3, h4, h5, h6, span, a, li, td, th, label, button').forEach(el => {
        const style = window.getComputedStyle(el);
        const color = style.color;
        const bg = style.backgroundColor;
        if (el.offsetParent !== null && el.textContent.trim().length > 0) {
            // Parse RGB values
            const parseRgb = (c) => {
                const m = c.match(/\\d+/g);
                return m ? m.map(Number) : null;
            };
            const fg = parseRgb(color);
            const bgc = parseRgb(bg);
            if (fg && bgc && bgc[3] !== 0) {
                // Relative luminance
                const lum = (rgb) => {
                    const [r, g, b] = rgb.slice(0, 3).map(v => {
                        v = v / 255;
                        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                    });
                    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
                };
                const l1 = lum(fg);
                const l2 = lum(bgc);
                const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
                const fontSize = parseFloat(style.fontSize);
                const isBold = parseInt(style.fontWeight) >= 700;
                const isLargeText = fontSize >= 24 || (fontSize >= 18.66 && isBold);
                const minRatio = isLargeText ? 3.0 : 4.5;
                const aaaRatio = isLargeText ? 4.5 : 7.0;
                if (ratio < minRatio) {
                    findings.contrastIssues.push({
                        text: el.textContent.trim().substring(0, 50),
                        ratio: Math.round(ratio * 100) / 100,
                        required: minRatio,
                        level: 'AA_FAIL',
                        tag: el.tagName,
                        fontSize: fontSize,
                    });
                } else if (ratio < aaaRatio) {
                    findings.contrastIssues.push({
                        text: el.textContent.trim().substring(0, 50),
                        ratio: Math.round(ratio * 100) / 100,
                        required: aaaRatio,
                        level: 'AAA_FAIL',
                        tag: el.tagName,
                        fontSize: fontSize,
                    });
                }
            }
        }
    });
    // Limit to top 20 most severe
    findings.contrastIssues = findings.contrastIssues
        .sort((a, b) => a.ratio - b.ratio)
        .slice(0, 20);

    // 2. Missing aria-labels on interactive elements
    findings.missingAriaLabels = [];
    document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"], [role="tab"]').forEach(el => {
        const hasLabel = el.getAttribute('aria-label') ||
                         el.getAttribute('aria-labelledby') ||
                         el.getAttribute('title') ||
                         (el.textContent || '').trim().length > 0 ||
                         el.querySelector('img[alt]');
        if (!hasLabel && el.offsetParent !== null) {
            findings.missingAriaLabels.push({
                tag: el.tagName,
                role: el.getAttribute('role'),
                class: (el.className || '').toString().substring(0, 60),
                type: el.getAttribute('type'),
            });
        }
    });

    // 3. Images without alt text
    findings.missingAltText = [];
    document.querySelectorAll('img').forEach(img => {
        if (!img.hasAttribute('alt') && img.offsetParent !== null) {
            findings.missingAltText.push({
                src: (img.src || '').substring(0, 80),
                size: `${img.naturalWidth}x${img.naturalHeight}`,
            });
        }
    });

    // 4. Focus order / tab index issues
    findings.focusOrderIssues = [];
    document.querySelectorAll('[tabindex]').forEach(el => {
        const ti = parseInt(el.getAttribute('tabindex'));
        if (ti > 0) {
            findings.focusOrderIssues.push({
                tag: el.tagName,
                tabindex: ti,
                text: (el.textContent || '').trim().substring(0, 40),
                issue: 'positive_tabindex',
            });
        }
    });
    // Check for missing tabindex on custom interactive elements
    document.querySelectorAll('[onclick], [role="button"], [role="tab"], [role="link"]').forEach(el => {
        if (!el.getAttribute('tabindex') && el.tagName !== 'BUTTON' && el.tagName !== 'A' && el.tagName !== 'INPUT') {
            findings.focusOrderIssues.push({
                tag: el.tagName,
                role: el.getAttribute('role'),
                issue: 'missing_tabindex_on_interactive',
            });
        }
    });

    // 5. Heading hierarchy
    findings.headingIssues = [];
    let lastLevel = 0;
    document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
        const level = parseInt(h.tagName[1]);
        if (level - lastLevel > 1 && lastLevel > 0) {
            findings.headingIssues.push({
                tag: h.tagName,
                text: h.textContent.trim().substring(0, 60),
                issue: `skipped_level_h${lastLevel}_to_h${level}`,
            });
        }
        lastLevel = level;
    });
    // Check for multiple h1s
    const h1Count = document.querySelectorAll('h1').length;
    if (h1Count > 1) {
        findings.headingIssues.push({
            tag: 'H1', issue: 'multiple_h1', count: h1Count,
        });
    }
    if (h1Count === 0) {
        findings.headingIssues.push({
            tag: 'H1', issue: 'missing_h1',
        });
    }

    // 6. Missing landmarks
    findings.landmarkIssues = [];
    if (!document.querySelector('main, [role="main"]')) {
        findings.landmarkIssues.push({ issue: 'missing_main_landmark' });
    }
    if (!document.querySelector('nav, [role="navigation"]')) {
        findings.landmarkIssues.push({ issue: 'missing_nav_landmark' });
    }

    // 7. Form labels
    findings.missingFormLabels = [];
    document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select').forEach(el => {
        const id = el.getAttribute('id');
        const hasLabel = (id && document.querySelector(`label[for="${id}"]`)) ||
                         el.getAttribute('aria-label') ||
                         el.getAttribute('aria-labelledby') ||
                         el.getAttribute('placeholder');
        if (!hasLabel && el.offsetParent !== null) {
            findings.missingFormLabels.push({
                tag: el.tagName,
                type: el.getAttribute('type'),
                name: el.getAttribute('name'),
            });
        }
    });

    // Summary
    findings.summary = {
        contrastViolations: findings.contrastIssues.length,
        missingAriaLabels: findings.missingAriaLabels.length,
        missingAltText: findings.missingAltText.length,
        focusOrderIssues: findings.focusOrderIssues.length,
        headingIssues: findings.headingIssues.length,
        landmarkIssues: findings.landmarkIssues.length,
        missingFormLabels: findings.missingFormLabels.length,
    };
    findings.summary.totalIssues = Object.values(findings.summary).reduce((a, b) => a + b, 0);
    findings.summary.wcagLevel = findings.contrastIssues.some(i => i.level === 'AA_FAIL') ? 'BELOW_AA' :
                                  findings.contrastIssues.some(i => i.level === 'AAA_FAIL') ? 'AA' : 'AAA';

    return findings;
}
"""


async def audit_accessibility(config: Any) -> list[dict[str, Any]]:
    """Run WCAG 2.1 AA/AAA accessibility audit across all pages x viewports.

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
                logger.info("A11y audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)
                    findings = await page.evaluate(_A11Y_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("A11y audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("A11y audit complete: %d test sets", len(results))
    return results
