"""SCORCH Phase: SEO audit.

Checks title tag, meta description, canonical URL, Open Graph tags,
Twitter Card tags, heading hierarchy, structured data, link counts,
image alt text coverage, robots meta, and viewport meta.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.seo")

_SEO_JS = """
() => {
    const findings = {};

    // Helper: get content of a <meta> tag by name or property
    const getMeta = (attr, value) => {
        const el = document.querySelector(`meta[${attr}="${value}"]`);
        return el ? (el.getAttribute('content') || '').trim() : null;
    };

    // 1. Title tag
    const titleEl = document.querySelector('title');
    const titleText = titleEl ? titleEl.textContent.trim() : null;
    findings.title = {
        exists: !!titleText,
        text: titleText ? titleText.substring(0, 120) : null,
        length: titleText ? titleText.length : 0,
        lengthOk: titleText ? (titleText.length >= 30 && titleText.length <= 60) : false,
        issue: !titleText ? 'missing'
             : titleText.length < 30 ? 'too_short'
             : titleText.length > 60 ? 'too_long'
             : null,
    };

    // 2. Meta description
    const descText = getMeta('name', 'description');
    findings.metaDescription = {
        exists: !!descText,
        text: descText ? descText.substring(0, 200) : null,
        length: descText ? descText.length : 0,
        lengthOk: descText ? (descText.length >= 120 && descText.length <= 160) : false,
        issue: !descText ? 'missing'
             : descText.length < 120 ? 'too_short'
             : descText.length > 160 ? 'too_long'
             : null,
    };

    // 3. Canonical URL
    const canonicalEl = document.querySelector('link[rel="canonical"]');
    findings.canonical = {
        exists: !!canonicalEl,
        href: canonicalEl ? (canonicalEl.getAttribute('href') || '').substring(0, 200) : null,
    };

    // 4. Open Graph tags
    findings.openGraph = {
        title: getMeta('property', 'og:title'),
        description: getMeta('property', 'og:description'),
        image: getMeta('property', 'og:image'),
        url: getMeta('property', 'og:url'),
        type: getMeta('property', 'og:type'),
    };
    findings.openGraph.missing = Object.entries(findings.openGraph)
        .filter(([k, v]) => k !== 'missing' && !v)
        .map(([k]) => `og:${k}`);

    // 5. Twitter Card tags
    findings.twitterCard = {
        card: getMeta('name', 'twitter:card'),
        title: getMeta('name', 'twitter:title'),
        description: getMeta('name', 'twitter:description'),
        image: getMeta('name', 'twitter:image'),
    };
    findings.twitterCard.missing = Object.entries(findings.twitterCard)
        .filter(([k, v]) => k !== 'missing' && !v)
        .map(([k]) => `twitter:${k}`);

    // 6. Heading hierarchy
    findings.headings = { h1Count: 0, hierarchy: [], issues: [] };
    const headingEls = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    let lastLevel = 0;
    headingEls.forEach(h => {
        const level = parseInt(h.tagName[1]);
        findings.headings.hierarchy.push({
            level,
            text: h.textContent.trim().substring(0, 80),
        });
        if (level === 1) findings.headings.h1Count++;
        if (level - lastLevel > 1 && lastLevel > 0) {
            findings.headings.issues.push(`skipped_h${lastLevel}_to_h${level}`);
        }
        lastLevel = level;
    });
    if (findings.headings.h1Count === 0) findings.headings.issues.push('missing_h1');
    if (findings.headings.h1Count > 1) findings.headings.issues.push(`multiple_h1_count_${findings.headings.h1Count}`);
    // Cap hierarchy list
    findings.headings.hierarchy = findings.headings.hierarchy.slice(0, 30);

    // 7. Structured data (JSON-LD)
    findings.structuredData = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(el => {
        try {
            const parsed = JSON.parse(el.textContent);
            findings.structuredData.push({
                type: parsed['@type'] || 'unknown',
                context: parsed['@context'] || null,
            });
        } catch (e) {
            findings.structuredData.push({ type: 'parse_error', raw: el.textContent.substring(0, 100) });
        }
    });

    // 8. Link counts
    findings.links = { internal: 0, external: 0, noText: 0 };
    const origin = window.location.origin;
    document.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        const isExternal = href.startsWith('http') && !href.startsWith(origin);
        if (isExternal) findings.links.external++;
        else findings.links.internal++;
        if (!(a.textContent || '').trim() && !a.querySelector('img[alt]') && !a.getAttribute('aria-label')) {
            findings.links.noText++;
        }
    });

    // 9. Image alt text coverage
    let totalImgs = 0, missingAlt = 0;
    document.querySelectorAll('img').forEach(img => {
        totalImgs++;
        if (!img.hasAttribute('alt') || img.getAttribute('alt') === '') {
            // Empty alt is valid for decorative, but no alt at all is a miss
            if (!img.hasAttribute('alt')) missingAlt++;
        }
    });
    findings.imageAltCoverage = {
        total: totalImgs,
        missingAlt,
        coveragePct: totalImgs ? Math.round((totalImgs - missingAlt) / totalImgs * 100) : 100,
    };

    // 10. Robots meta tag
    const robotsMeta = getMeta('name', 'robots');
    findings.robotsMeta = {
        exists: !!robotsMeta,
        content: robotsMeta,
        isIndexable: !robotsMeta || (!robotsMeta.includes('noindex') && !robotsMeta.includes('none')),
    };

    // 11. Viewport meta tag
    const viewportMeta = getMeta('name', 'viewport');
    findings.viewportMeta = {
        exists: !!viewportMeta,
        content: viewportMeta,
    };

    // Summary
    const totalIssues =
        (findings.title.issue ? 1 : 0) +
        (findings.metaDescription.issue ? 1 : 0) +
        (findings.canonical.exists ? 0 : 1) +
        findings.openGraph.missing.length +
        findings.twitterCard.missing.length +
        findings.headings.issues.length +
        (findings.structuredData.length === 0 ? 1 : 0) +
        (findings.links.noText > 0 ? findings.links.noText : 0) +
        (findings.imageAltCoverage.missingAlt) +
        (!findings.robotsMeta.isIndexable ? 1 : 0) +
        (findings.viewportMeta.exists ? 0 : 1);

    findings.summary = {
        titleOk: !findings.title.issue,
        metaDescriptionOk: !findings.metaDescription.issue,
        canonicalPresent: findings.canonical.exists,
        ogComplete: findings.openGraph.missing.length === 0,
        twitterCardComplete: findings.twitterCard.missing.length === 0,
        headingIssues: findings.headings.issues.length,
        structuredDataCount: findings.structuredData.length,
        imageCoveragePct: findings.imageAltCoverage.coveragePct,
        isIndexable: findings.robotsMeta.isIndexable,
        viewportPresent: findings.viewportMeta.exists,
        totalIssues,
    };

    return findings;
}
"""


async def audit_seo(config: Any) -> list[dict[str, Any]]:
    """Run SEO audit across all pages x viewports.

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
                logger.info("SEO audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)
                    findings = await page.evaluate(_SEO_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("SEO audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("SEO audit complete: %d test sets", len(results))
    return results
