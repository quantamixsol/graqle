"""Phase: Conversion funnel analysis — CTA inventory, form quality, trust signals, pricing clarity."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.conversion")

_CONVERSION_JS = """
() => {
    const findings = {};
    const vpHeight = window.innerHeight;

    // 1. CTA inventory — all buttons/links with action-oriented text
    findings.ctaInventory = [];
    const actionPattern = /\\b(sign\\s*up|buy|start|try|get\\s*started|subscribe|join|register|purchase|download|book|schedule|request|claim|access|unlock|begin|create|launch|activate|install|add\\s*to\\s*cart|checkout|upgrade|explore|learn\\s*more|see\\s*plans|contact\\s*us|get\\s*demo|watch\\s*demo|free\\s*trial)\\b/i;
    document.querySelectorAll('a[href], button, input[type="submit"], input[type="button"]').forEach(el => {
        const text = (el.textContent || el.value || '').trim();
        if (actionPattern.test(text) && el.offsetParent !== null) {
            const rect = el.getBoundingClientRect();
            const absTop = rect.top + window.scrollY;
            findings.ctaInventory.push({
                tag: el.tagName,
                text: text.substring(0, 80),
                href: el.getAttribute('href') || null,
                aboveFold: absTop < vpHeight,
                top: Math.round(absTop),
            });
        }
    });

    // 2. CTA placement — above vs below fold breakdown
    const aboveFoldCtas = findings.ctaInventory.filter(c => c.aboveFold).length;
    const belowFoldCtas = findings.ctaInventory.length - aboveFoldCtas;
    findings.ctaPlacement = {
        total: findings.ctaInventory.length,
        aboveFold: aboveFoldCtas,
        belowFold: belowFoldCtas,
        hasAboveFoldCta: aboveFoldCtas > 0,
    };

    // 3. CTA visibility — size, whitespace, and color contrast of primary CTAs
    findings.ctaVisibility = [];
    findings.ctaInventory.forEach(cta => {
        const selector = `a[href], button, input[type="submit"]`;
        document.querySelectorAll(selector).forEach(el => {
            const text = (el.textContent || el.value || '').trim();
            if (text.substring(0, 80) !== cta.text) return;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const width = rect.width;
            const height = rect.height;
            const paddingTop = parseFloat(style.paddingTop);
            const paddingBottom = parseFloat(style.paddingBottom);
            const paddingLeft = parseFloat(style.paddingLeft);
            const paddingRight = parseFloat(style.paddingRight);
            const marginTop = parseFloat(style.marginTop);
            const marginBottom = parseFloat(style.marginBottom);

            // Estimate contrast ratio between color and backgroundColor
            const parseRgb = (c) => { const m = c.match(/\\d+/g); return m ? m.map(Number) : null; };
            const lum = (rgb) => {
                const [r, g, b] = rgb.slice(0, 3).map(v => {
                    v = v / 255;
                    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                });
                return 0.2126 * r + 0.7152 * g + 0.0722 * b;
            };
            const fg = parseRgb(style.color);
            const bg = parseRgb(style.backgroundColor);
            let contrastRatio = null;
            if (fg && bg && bg[3] !== 0) {
                const l1 = lum(fg), l2 = lum(bg);
                contrastRatio = Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100;
            }

            findings.ctaVisibility.push({
                text: cta.text,
                width: Math.round(width),
                height: Math.round(height),
                tooSmall: width < 120 || height < 36,
                paddingAdequate: paddingTop >= 10 && paddingLeft >= 16,
                verticalMargin: Math.round(marginTop + marginBottom),
                contrastRatio,
                lowContrast: contrastRatio !== null && contrastRatio < 4.5,
                backgroundColor: style.backgroundColor,
            });
        });
    });
    // Deduplicate by text
    const seen = new Set();
    findings.ctaVisibility = findings.ctaVisibility.filter(c => {
        if (seen.has(c.text)) return false;
        seen.add(c.text);
        return true;
    });

    // 4. Form analysis — field count, required fields, error messages, submit text
    findings.formAnalysis = [];
    document.querySelectorAll('form').forEach(form => {
        const fields = form.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');
        const requiredFields = form.querySelectorAll('[required], [aria-required="true"]');
        const hasErrorMsg = !!form.querySelector('[class*="error"], [role="alert"], [aria-invalid="true"]');
        const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
        const submitText = submitBtn ? (submitBtn.textContent || submitBtn.value || '').trim() : null;
        const hasTooManyFields = fields.length > 7;
        const passwordFields = form.querySelectorAll('input[type="password"]');
        const hasPasswordToggle = passwordFields.length > 0 &&
            !!form.querySelector('[class*="toggle"], [aria-label*="password"], [class*="show-pass"], [class*="eye"]');
        findings.formAnalysis.push({
            action: form.getAttribute('action') || '(inline)',
            totalFields: fields.length,
            requiredFields: requiredFields.length,
            hasTooManyFields,
            hasErrorMessage: hasErrorMsg,
            submitText,
            hasPasswordToggle: passwordFields.length > 0 ? hasPasswordToggle : null,
            hasAutoComplete: !!form.querySelector('[autocomplete]'),
        });
    });

    // 5. Exit intent indicators — outbound links inside CTA regions
    findings.exitIntentIndicators = [];
    const ctaRegions = document.querySelectorAll('[class*="cta"], [class*="hero"], [class*="pricing"], [class*="conversion"], section');
    ctaRegions.forEach(region => {
        region.querySelectorAll('a[href]').forEach(link => {
            const href = link.getAttribute('href') || '';
            const isOutbound = href.startsWith('http') && !href.includes(window.location.hostname);
            if (isOutbound) {
                findings.exitIntentIndicators.push({
                    text: (link.textContent || '').trim().substring(0, 60),
                    href: href.substring(0, 100),
                    region: (region.className || '').toString().substring(0, 60),
                });
            }
        });
    });

    // 6. Trust signals — testimonials, social proof, security badges, guarantees
    findings.trustSignals = {
        hasTestimonials: !!document.querySelector('[class*="testimonial"], [class*="review"], [class*="quote"], blockquote'),
        hasSocialProof: !!document.querySelector('[class*="social-proof"], [class*="customer-count"], [class*="users-count"], [class*="trusted-by"]'),
        hasSecurityBadge: !!document.querySelector('[class*="security"], [class*="ssl"], [class*="secure"], img[alt*="secure"], img[alt*="SSL"], img[alt*="trust"]'),
        hasGuarantee: !!document.querySelector('[class*="guarantee"], [class*="money-back"], [class*="refund"]'),
        hasRatings: !!document.querySelector('[class*="rating"], [class*="stars"], [aria-label*="rating"], [class*="score"]'),
        hasLogoCloud: !!document.querySelector('[class*="logo-cloud"], [class*="client-logo"], [class*="partner-logo"], [class*="featured-in"]'),
        totalSignals: 0,
    };
    findings.trustSignals.totalSignals = Object.values(findings.trustSignals)
        .filter(v => v === true).length;

    // 7. Pricing clarity — pricing tables, comparison grids, hidden fee indicators
    findings.pricingClarity = {
        hasPricingSection: !!document.querySelector('[class*="pricing"], [id*="pricing"], [class*="plan"], [class*="tier"]'),
        hasComparisonTable: !!document.querySelector('table, [class*="comparison"], [class*="feature-grid"]'),
        hasMoneySymbol: /\\.00|\\$|€|£|¥/.test(document.body.textContent || ''),
        hiddenFeeIndicators: [],
    };
    // Flag asterisks or "terms apply" near pricing
    document.querySelectorAll('[class*="pricing"], [class*="plan"]').forEach(el => {
        const text = el.textContent || '';
        if (/\\*|\\†|terms apply|conditions apply|\\+VAT|excl\\. tax/i.test(text)) {
            findings.pricingClarity.hiddenFeeIndicators.push({
                text: text.substring(0, 120).trim(),
            });
        }
    });

    // 8. Micro-copy quality — button text length, action verbs, urgency indicators
    findings.microCopyQuality = {
        weakCtaTexts: [],
        urgencyIndicators: [],
        averageCtaLength: 0,
    };
    const weakPattern = /^(click here|submit|go|ok|yes|no|more|next|continue)$/i;
    const urgencyPattern = /\\b(today|now|limited|hurry|only \\d+ left|expires|last chance|offer ends)\\b/i;
    document.querySelectorAll('button, a[href], input[type="submit"]').forEach(el => {
        if (el.offsetParent === null) return;
        const text = (el.textContent || el.value || '').trim();
        if (text.length === 0) return;
        if (weakPattern.test(text)) {
            findings.microCopyQuality.weakCtaTexts.push({ text: text.substring(0, 60) });
        }
        if (urgencyPattern.test(text)) {
            findings.microCopyQuality.urgencyIndicators.push({ text: text.substring(0, 60) });
        }
    });
    if (findings.ctaInventory.length > 0) {
        const totalLen = findings.ctaInventory.reduce((sum, c) => sum + c.text.length, 0);
        findings.microCopyQuality.averageCtaLength = Math.round(totalLen / findings.ctaInventory.length);
    }

    // Summary
    findings.summary = {
        totalCtas: findings.ctaInventory.length,
        hasAboveFoldCta: findings.ctaPlacement.hasAboveFoldCta,
        totalForms: findings.formAnalysis.length,
        trustSignalCount: findings.trustSignals.totalSignals,
        hasPricing: findings.pricingClarity.hasPricingSection,
        weakCtaCount: findings.microCopyQuality.weakCtaTexts.length,
        exitRisks: findings.exitIntentIndicators.length,
    };

    return findings;
}
"""


async def audit_conversion(config: Any) -> list[dict[str, Any]]:
    """Run conversion funnel analysis across all pages x viewports.

    Checks CTA inventory and placement, form quality, trust signals,
    pricing clarity, exit intent risks, and micro-copy quality.

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
                logger.info("Conversion audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    findings = await page.evaluate(_CONVERSION_JS)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("Conversion audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Conversion audit complete: %d test sets", len(results))
    return results
