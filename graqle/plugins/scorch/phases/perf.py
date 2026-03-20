"""SCORCH Phase: Performance (Core Web Vitals) audit.

Measures LCP, CLS, FID approximation (long tasks), resource counts and sizes,
render-blocking resources, DOM size, and image optimisation issues.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.perf")

_PERF_JS = """
async () => {
    const findings = {};

    // 1. LCP — Largest Contentful Paint (via PerformanceObserver, best-effort)
    findings.lcp = null;
    try {
        findings.lcp = await new Promise((resolve) => {
            let value = null;
            const obs = new PerformanceObserver((list) => {
                const entries = list.getEntries();
                if (entries.length) {
                    value = entries[entries.length - 1].startTime;
                }
            });
            obs.observe({ type: 'largest-contentful-paint', buffered: true });
            // Give the observer a moment to collect buffered entries
            setTimeout(() => {
                obs.disconnect();
                resolve(value);
            }, 200);
        });
    } catch (e) {
        findings.lcp = null; // API not supported in this context
    }

    // 2. CLS — Cumulative Layout Shift
    findings.cls = null;
    try {
        findings.cls = await new Promise((resolve) => {
            let score = 0;
            const obs = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (!entry.hadRecentInput) {
                        score += entry.value;
                    }
                }
            });
            obs.observe({ type: 'layout-shift', buffered: true });
            setTimeout(() => {
                obs.disconnect();
                resolve(Math.round(score * 1000) / 1000);
            }, 200);
        });
    } catch (e) {
        findings.cls = null;
    }

    // 3. Long Tasks (FID proxy — tasks > 50ms block the main thread)
    findings.longTasks = [];
    try {
        findings.longTasks = await new Promise((resolve) => {
            const tasks = [];
            const obs = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    tasks.push({
                        duration: Math.round(entry.duration),
                        startTime: Math.round(entry.startTime),
                    });
                }
            });
            obs.observe({ type: 'longtask', buffered: true });
            setTimeout(() => {
                obs.disconnect();
                resolve(tasks);
            }, 200);
        });
    } catch (e) {
        findings.longTasks = [];
    }

    // 4. Resources — count and total transfer size
    findings.resources = { total: 0, totalSizeKB: 0, byType: {} };
    performance.getEntriesByType('resource').forEach(r => {
        findings.resources.total++;
        const sizeKB = Math.round((r.transferSize || 0) / 1024 * 10) / 10;
        findings.resources.totalSizeKB += sizeKB;
        const type = r.initiatorType || 'other';
        if (!findings.resources.byType[type]) {
            findings.resources.byType[type] = { count: 0, sizeKB: 0 };
        }
        findings.resources.byType[type].count++;
        findings.resources.byType[type].sizeKB += sizeKB;
    });
    findings.resources.totalSizeKB = Math.round(findings.resources.totalSizeKB * 10) / 10;

    // 5. Render-blocking resources
    findings.renderBlockingResources = [];
    // Stylesheets in <head> without media query or print-only (no async equivalent for CSS)
    document.querySelectorAll('head link[rel="stylesheet"]').forEach(el => {
        const media = el.getAttribute('media');
        const isBlocking = !media || media === 'all' || media === 'screen';
        if (isBlocking) {
            findings.renderBlockingResources.push({
                type: 'stylesheet',
                href: (el.href || '').substring(0, 100),
            });
        }
    });
    // Scripts in <head> without defer or async
    document.querySelectorAll('head script[src]').forEach(el => {
        if (!el.defer && !el.async) {
            findings.renderBlockingResources.push({
                type: 'script',
                src: (el.src || '').substring(0, 100),
            });
        }
    });

    // 6. DOM size
    findings.domSize = document.querySelectorAll('*').length;

    // 7. Image optimisation issues
    findings.imageIssues = [];
    document.querySelectorAll('img').forEach(img => {
        const issues = [];
        if (!img.hasAttribute('width') || !img.hasAttribute('height')) {
            issues.push('missing_dimensions');
        }
        // Rendered size significantly smaller than natural size (oversized image)
        if (img.naturalWidth > 0 && img.offsetWidth > 0) {
            const ratio = img.naturalWidth / img.offsetWidth;
            if (ratio > 2) {
                issues.push(`oversized_${Math.round(ratio)}x`);
            }
        }
        if (issues.length) {
            findings.imageIssues.push({
                src: (img.src || img.dataset.src || '').substring(0, 100),
                naturalSize: `${img.naturalWidth}x${img.naturalHeight}`,
                renderedWidth: img.offsetWidth,
                issues,
            });
        }
    });

    // Summary scores
    const lcpMs = findings.lcp || 0;
    findings.summary = {
        lcpMs: Math.round(lcpMs),
        lcpRating: lcpMs === 0 ? 'unknown' : lcpMs <= 2500 ? 'good' : lcpMs <= 4000 ? 'needs_improvement' : 'poor',
        cls: findings.cls,
        clsRating: findings.cls === null ? 'unknown' : findings.cls <= 0.1 ? 'good' : findings.cls <= 0.25 ? 'needs_improvement' : 'poor',
        longTaskCount: findings.longTasks.length,
        totalResources: findings.resources.total,
        totalSizeKB: findings.resources.totalSizeKB,
        renderBlockingCount: findings.renderBlockingResources.length,
        domSize: findings.domSize,
        domSizeRating: findings.domSize <= 800 ? 'good' : findings.domSize <= 1500 ? 'needs_improvement' : 'poor',
        imageIssueCount: findings.imageIssues.length,
    };

    return findings;
}
"""


async def audit_performance(config: Any) -> list[dict[str, Any]]:
    """Run Core Web Vitals and performance audit across all pages x viewports.

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
                logger.info("Perf audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)
                    findings = await page.evaluate(_PERF_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("Perf audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Perf audit complete: %d test sets", len(results))
    return results
