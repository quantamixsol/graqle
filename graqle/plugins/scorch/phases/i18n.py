"""SCORCH Phase: Internationalisation (i18n) audit.

Checks html lang attribute, RTL support, hardcoded date/currency patterns,
Unicode/encoding declarations, font fallbacks, and mixed-language content.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.i18n")

_I18N_JS = """
() => {
    const findings = {};

    // 1. html lang attribute
    const htmlEl = document.documentElement;
    findings.langAttribute = {
        exists: htmlEl.hasAttribute('lang'),
        value: htmlEl.getAttribute('lang'),
        valid: /^[a-z]{2,3}(-[A-Z]{2,4})?$/.test(htmlEl.getAttribute('lang') || ''),
    };

    // 2. Charset / encoding declaration
    const charsetEl = document.querySelector('meta[charset]') ||
                      document.querySelector('meta[http-equiv="Content-Type"]');
    findings.encoding = {
        declared: !!charsetEl,
        charset: charsetEl
            ? (charsetEl.getAttribute('charset') || charsetEl.getAttribute('content') || '').toLowerCase()
            : null,
        isUtf8: charsetEl
            ? (charsetEl.getAttribute('charset') || charsetEl.getAttribute('content') || '').toLowerCase().includes('utf-8')
            : false,
    };

    // 3. RTL support
    findings.rtl = {
        htmlDir: htmlEl.getAttribute('dir'),
        hasDirAttribute: htmlEl.hasAttribute('dir'),
        hasRtlElements: !!document.querySelector('[dir="rtl"]'),
        hasCssDirection: false,
    };
    // Check inline styles for direction: rtl
    document.querySelectorAll('[style]').forEach(el => {
        if ((el.getAttribute('style') || '').includes('direction: rtl') ||
            (el.getAttribute('style') || '').includes('direction:rtl')) {
            findings.rtl.hasCssDirection = true;
        }
    });

    // 4. Hardcoded date patterns (MM/DD/YYYY or DD/MM/YYYY or YYYY-MM-DD literal in text)
    findings.hardcodedDates = [];
    const dateRegexes = [
        /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/g,   // MM/DD/YYYY or DD/MM/YYYY
        /\b\d{4}-\d{2}-\d{2}\b/g,            // ISO YYYY-MM-DD
        /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b/gi,
    ];
    const walkText = (node, handler) => {
        if (node.nodeType === 3) { handler(node); return; }
        if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.tagName)) return;
        node.childNodes.forEach(child => walkText(child, handler));
    };
    walkText(document.body, (node) => {
        const text = node.nodeValue || '';
        for (const rx of dateRegexes) {
            const matches = text.match(rx);
            if (matches) {
                findings.hardcodedDates.push(...matches.map(m => ({
                    pattern: m,
                    context: text.trim().substring(0, 80),
                })));
            }
        }
    });
    findings.hardcodedDates = findings.hardcodedDates.slice(0, 20);

    // 5. Hardcoded currency symbols without locale context
    findings.hardcodedCurrency = [];
    const currencyRx = /(?<![\\w\\d])[$€£¥₹₩₺]\\s?\\d+(?:[.,]\\d+)*(?![\\d])/g;
    walkText(document.body, (node) => {
        const text = node.nodeValue || '';
        const matches = text.match(currencyRx);
        if (matches) {
            findings.hardcodedCurrency.push(...matches.map(m => ({
                pattern: m,
                context: text.trim().substring(0, 80),
            })));
        }
    });
    findings.hardcodedCurrency = findings.hardcodedCurrency.slice(0, 20);

    // 6. Font fallback check — generic families in font stacks
    findings.fontFallback = { hasGenericFamily: false, fontFamilies: [] };
    const genericFamilies = ['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui'];
    ['body', 'p', 'h1', 'span'].forEach(sel => {
        const el = document.querySelector(sel);
        if (el) {
            const ff = window.getComputedStyle(el).fontFamily;
            if (ff && !findings.fontFallback.fontFamilies.includes(ff)) {
                findings.fontFallback.fontFamilies.push(ff.substring(0, 120));
                if (genericFamilies.some(g => ff.toLowerCase().includes(g))) {
                    findings.fontFallback.hasGenericFamily = true;
                }
            }
        }
    });

    // 7. Mixed language detection (heuristic: Unicode script ranges)
    // Detect if page mixes Latin + CJK + Arabic/Hebrew scripts in text nodes
    findings.mixedLanguage = { detected: false, scripts: [] };
    const scriptChecks = [
        { name: 'CJK', rx: /[\u4E00-\u9FFF\u3040-\u30FF]/ },
        { name: 'Arabic', rx: /[\u0600-\u06FF]/ },
        { name: 'Hebrew', rx: /[\u0590-\u05FF]/ },
        { name: 'Cyrillic', rx: /[\u0400-\u04FF]/ },
        { name: 'Latin', rx: /[A-Za-z]{3,}/ },
        { name: 'Devanagari', rx: /[\u0900-\u097F]/ },
    ];
    const bodyText = document.body.innerText || '';
    const detectedScripts = scriptChecks.filter(s => s.rx.test(bodyText)).map(s => s.name);
    findings.mixedLanguage.scripts = detectedScripts;
    // Mixed = more than one non-Latin script, or Latin + any non-Latin without dir/lang differentiation
    if (detectedScripts.length > 1 && !findings.rtl.hasRtlElements && !htmlEl.getAttribute('lang')) {
        findings.mixedLanguage.detected = true;
    }

    // 8. i18n meta tags (Content-Language, hreflang alternates)
    const contentLang = document.querySelector('meta[http-equiv="Content-Language"]');
    findings.hreflang = {
        contentLanguageMeta: contentLang ? contentLang.getAttribute('content') : null,
        alternates: [],
    };
    document.querySelectorAll('link[rel="alternate"][hreflang]').forEach(el => {
        findings.hreflang.alternates.push({
            hreflang: el.getAttribute('hreflang'),
            href: (el.getAttribute('href') || '').substring(0, 100),
        });
    });

    // Summary
    findings.summary = {
        langAttributeOk: findings.langAttribute.exists && findings.langAttribute.valid,
        encodingOk: findings.encoding.isUtf8,
        rtlSupport: findings.rtl.hasDirAttribute || findings.rtl.hasRtlElements,
        hardcodedDateCount: findings.hardcodedDates.length,
        hardcodedCurrencyCount: findings.hardcodedCurrency.length,
        hasFontFallback: findings.fontFallback.hasGenericFamily,
        mixedLanguageDetected: findings.mixedLanguage.detected,
        hreflangCount: findings.hreflang.alternates.length,
    };
    findings.summary.totalIssues =
        (findings.langAttribute.exists ? 0 : 1) +
        (!findings.langAttribute.valid && findings.langAttribute.exists ? 1 : 0) +
        (findings.encoding.isUtf8 ? 0 : 1) +
        findings.hardcodedDates.length +
        findings.hardcodedCurrency.length +
        (findings.fontFallback.hasGenericFamily ? 0 : 1) +
        (findings.mixedLanguage.detected ? 1 : 0);

    return findings;
}
"""


async def audit_i18n(config: Any) -> list[dict[str, Any]]:
    """Run internationalisation (i18n) audit across all pages x viewports.

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
                logger.info("i18n audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)
                    findings = await page.evaluate(_I18N_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("i18n audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("i18n audit complete: %d test sets", len(results))
    return results
