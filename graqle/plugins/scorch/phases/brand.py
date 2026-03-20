"""Phase: Brand consistency audit — color palette, typography, logo, spacing, and element uniformity."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.brand")


def _build_brand_js(brand_rules: Any) -> str:
    """Inject brand_rules values into the JS audit string at call time."""
    primary = brand_rules.primary_color
    secondary = brand_rules.secondary_color
    accent = brand_rules.accent_color
    font_family = brand_rules.font_family
    min_body_font_px = brand_rules.min_body_font_px
    min_caption_font_px = brand_rules.min_caption_font_px

    return f"""
() => {{
    const findings = {{}};

    // Brand palette config (injected from ScorchConfig.brand_rules)
    const brandPalette = [
        "{primary}".toLowerCase(),
        "{secondary}".toLowerCase(),
        "{accent}".toLowerCase(),
    ];
    const brandFontFamily = "{font_family}";
    const minBodyFontPx = {min_body_font_px};
    const minCaptionFontPx = {min_caption_font_px};

    // Helper: parse hex to rgb
    const hexToRgb = (hex) => {{
        const clean = hex.replace('#', '');
        const r = parseInt(clean.substring(0, 2), 16);
        const g = parseInt(clean.substring(2, 4), 16);
        const b = parseInt(clean.substring(4, 6), 16);
        return `rgb(${{r}}, ${{g}}, ${{b}})`;
    }};

    // Helper: rgb string to hex
    const rgbToHex = (rgb) => {{
        const m = (rgb || '').match(/\\d+/g);
        if (!m || m.length < 3) return null;
        return '#' + m.slice(0, 3).map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
    }};

    // 1. Color palette compliance — extract all unique colors, flag off-brand ones
    findings.colorPalette = {{
        brandColors: brandPalette,
        usedColors: [],
        offBrandColors: [],
    }};
    const colorSamples = new Map();
    document.querySelectorAll('*').forEach(el => {{
        if (el.offsetParent === null && el.tagName !== 'BODY') return;
        const style = window.getComputedStyle(el);
        ['color', 'backgroundColor', 'borderColor', 'outlineColor'].forEach(prop => {{
            const val = style[prop];
            if (!val || val === 'rgba(0, 0, 0, 0)' || val === 'transparent') return;
            const hex = rgbToHex(val);
            if (hex && hex !== '#000000' && hex !== '#ffffff' && hex !== '#000' && hex !== '#fff') {{
                colorSamples.set(hex, (colorSamples.get(hex) || 0) + 1);
            }}
        }});
    }});
    const brandRgb = brandPalette.map(hexToRgb);
    colorSamples.forEach((count, hex) => {{
        const rgb = hexToRgb(hex);
        const isOnBrand = brandPalette.includes(hex) || brandRgb.includes(rgb);
        if (!isOnBrand && count >= 3) {{
            findings.colorPalette.offBrandColors.push({{ hex, count }});
        }}
        findings.colorPalette.usedColors.push({{ hex, count }});
    }});
    findings.colorPalette.usedColors.sort((a, b) => b.count - a.count);
    findings.colorPalette.usedColors = findings.colorPalette.usedColors.slice(0, 30);
    findings.colorPalette.offBrandColors.sort((a, b) => b.count - a.count);

    // 2. Typography — check all font-family values against brandFontFamily
    findings.typography = {{
        brandFont: brandFontFamily,
        offBrandFonts: [],
        mixedFonts: false,
    }};
    const fontUsage = new Map();
    document.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, span, a, button, label, td, th').forEach(el => {{
        if (el.offsetParent === null) return;
        const style = window.getComputedStyle(el);
        const family = (style.fontFamily || '').split(',')[0].trim().replace(/['"]/g, '');
        fontUsage.set(family, (fontUsage.get(family) || 0) + 1);
    }});
    fontUsage.forEach((count, family) => {{
        const isOnBrand = family.toLowerCase().includes(brandFontFamily.toLowerCase());
        if (!isOnBrand) {{
            findings.typography.offBrandFonts.push({{ family, count }});
        }}
    }});
    findings.typography.mixedFonts = fontUsage.size > 3;
    findings.typography.fontUsage = Array.from(fontUsage.entries())
        .map(([family, count]) => ({{ family, count }}))
        .sort((a, b) => b.count - a.count);

    // 3. Font size compliance — body text >= minBodyFontPx
    findings.fontSizeCompliance = {{
        violations: [],
        minBodyFontPx,
        minCaptionFontPx,
    }};
    document.querySelectorAll('p, li, span, td, th, label').forEach(el => {{
        if (el.offsetParent === null) return;
        const style = window.getComputedStyle(el);
        const size = parseFloat(style.fontSize);
        const isCaption = el.closest('figcaption, caption, [class*="caption"], [class*="footnote"]');
        const minimum = isCaption ? minCaptionFontPx : minBodyFontPx;
        if (size < minimum) {{
            findings.fontSizeCompliance.violations.push({{
                tag: el.tagName,
                size: Math.round(size),
                minimum,
                text: (el.textContent || '').trim().substring(0, 60),
                isCaption: !!isCaption,
            }});
        }}
    }});
    findings.fontSizeCompliance.violations = findings.fontSizeCompliance.violations.slice(0, 20);

    // 4. Logo presence
    findings.logoPresence = {{
        found: false,
        elements: [],
    }};
    document.querySelectorAll('img, svg, a, [class*="logo"]').forEach(el => {{
        const src = el.getAttribute('src') || '';
        const alt = el.getAttribute('alt') || '';
        const cls = (el.className || '').toString();
        const isLogo = /logo|brand/i.test(src) || /logo|brand/i.test(alt) || /logo|brand/i.test(cls);
        if (isLogo && el.offsetParent !== null) {{
            findings.logoPresence.found = true;
            findings.logoPresence.elements.push({{
                tag: el.tagName,
                src: src.substring(0, 80),
                alt: alt.substring(0, 60),
                class: cls.substring(0, 60),
            }});
        }}
    }});

    // 5. Spacing consistency — detect outlier margin/padding values
    findings.spacingConsistency = {{
        spacingValues: {{}},
        outliers: [],
    }};
    const spacingCounts = new Map();
    document.querySelectorAll('div, section, article, p, h1, h2, h3').forEach(el => {{
        if (el.offsetParent === null) return;
        const style = window.getComputedStyle(el);
        ['marginTop', 'marginBottom', 'paddingTop', 'paddingBottom'].forEach(prop => {{
            const val = Math.round(parseFloat(style[prop]));
            if (val > 0) spacingCounts.set(val, (spacingCounts.get(val) || 0) + 1);
        }});
    }});
    // Values used fewer than 2 times are outliers (if there are at least 10 data points)
    if (spacingCounts.size >= 5) {{
        spacingCounts.forEach((count, val) => {{
            if (count <= 1 && val > 0) {{
                findings.spacingConsistency.outliers.push({{ valuePx: val, count }});
            }}
        }});
    }}
    findings.spacingConsistency.spacingValues = Object.fromEntries(
        Array.from(spacingCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 15)
    );

    // 6. Button style consistency
    findings.buttonConsistency = {{
        styles: [],
        inconsistent: false,
    }};
    const btnStyles = [];
    document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(el => {{
        if (el.offsetParent === null) return;
        const style = window.getComputedStyle(el);
        btnStyles.push({{
            borderRadius: style.borderRadius,
            backgroundColor: style.backgroundColor,
            fontWeight: style.fontWeight,
            fontSize: style.fontSize,
            textTransform: style.textTransform,
        }});
    }});
    // Check if border-radius values vary significantly
    const radii = new Set(btnStyles.map(s => s.borderRadius));
    const bgColors = new Set(btnStyles.map(s => s.backgroundColor));
    findings.buttonConsistency.styles = btnStyles.slice(0, 10);
    findings.buttonConsistency.uniqueBorderRadii = Array.from(radii);
    findings.buttonConsistency.uniqueBackgroundColors = Array.from(bgColors);
    findings.buttonConsistency.inconsistent = radii.size > 3 || bgColors.size > 5;

    // 7. Link style consistency
    findings.linkConsistency = {{
        uniqueColors: [],
        uniqueDecorations: [],
        inconsistent: false,
    }};
    const linkColors = new Set();
    const linkDecorations = new Set();
    document.querySelectorAll('a[href]').forEach(el => {{
        if (el.offsetParent === null) return;
        const style = window.getComputedStyle(el);
        linkColors.add(style.color);
        linkDecorations.add(style.textDecoration);
    }});
    findings.linkConsistency.uniqueColors = Array.from(linkColors).slice(0, 10);
    findings.linkConsistency.uniqueDecorations = Array.from(linkDecorations).slice(0, 10);
    findings.linkConsistency.inconsistent = linkColors.size > 3;

    // 8. Heading style consistency across the page
    findings.headingConsistency = {{
        h1Styles: [],
        h2Styles: [],
        inconsistentH2: false,
    }};
    ['H1', 'H2'].forEach(tag => {{
        const key = tag.toLowerCase() + 'Styles';
        document.querySelectorAll(tag.toLowerCase()).forEach(el => {{
            if (el.offsetParent === null) return;
            const style = window.getComputedStyle(el);
            findings.headingConsistency[key].push({{
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                color: style.color,
                lineHeight: style.lineHeight,
            }});
        }});
    }});
    // Flag if h2 font sizes vary
    const h2Sizes = new Set(findings.headingConsistency.h2Styles.map(s => s.fontSize));
    findings.headingConsistency.inconsistentH2 = h2Sizes.size > 2;

    // Summary
    findings.summary = {{
        offBrandColorCount: findings.colorPalette.offBrandColors.length,
        offBrandFontCount: findings.typography.offBrandFonts.length,
        fontSizeViolations: findings.fontSizeCompliance.violations.length,
        hasLogo: findings.logoPresence.found,
        spacingOutliers: findings.spacingConsistency.outliers.length,
        buttonInconsistent: findings.buttonConsistency.inconsistent,
        linkInconsistent: findings.linkConsistency.inconsistent,
        headingInconsistent: findings.headingConsistency.inconsistentH2,
    }};

    return findings;
}}
"""


async def audit_brand(config: Any) -> list[dict[str, Any]]:
    """Run brand consistency audit across all pages x viewports.

    Checks color palette compliance, typography, font size, logo presence,
    spacing outliers, and element style uniformity against config.brand_rules.

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

            # Build JS with brand rules injected once per run
            brand_js = _build_brand_js(config.brand_rules)

            for page_path in config.pages:
                url = f"{config.base_url.rstrip('/')}{page_path}"
                logger.info("Brand audit: %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    findings = await page.evaluate(brand_js)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error("Brand audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Brand audit complete: %d test sets", len(results))
    return results
