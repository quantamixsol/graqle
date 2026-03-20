"""SCORCH Phase: Frontend security audit.

Checks for exposed API keys, inline scripts, missing CSRF tokens,
mixed content, insecure form actions, sensitive localStorage/sessionStorage
keys, untrusted external scripts, and sensitive data in JS globals.
Also inspects response headers: CSP, X-Frame-Options, X-Content-Type-Options,
and Strict-Transport-Security.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.security")

_SECURITY_JS = """
() => {
    const findings = {};

    // 1. Exposed API keys in inline scripts and page source
    //    Patterns: OpenAI sk-*, AWS AKIA*, GitHub ghp_/ghs_/gho_, Stripe sk_live_*, generic secrets
    findings.exposedKeys = [];
    const KEY_PATTERNS = [
        { name: 'openai', rx: /sk-[A-Za-z0-9]{32,}/ },
        { name: 'openai_proj', rx: /sk-proj-[A-Za-z0-9_\-]{32,}/ },
        { name: 'aws_access_key', rx: /AKIA[0-9A-Z]{16}/ },
        { name: 'aws_secret', rx: /(?:aws[_\-]?secret|AWS_SECRET)[^'"\\s]*['"]?\\s*[:=]\\s*['"]?[A-Za-z0-9/+]{40}/ },
        { name: 'github_pat', rx: /ghp_[A-Za-z0-9]{36}/ },
        { name: 'github_server', rx: /ghs_[A-Za-z0-9]{36}/ },
        { name: 'github_oauth', rx: /gho_[A-Za-z0-9]{36}/ },
        { name: 'stripe_live', rx: /sk_live_[A-Za-z0-9]{24,}/ },
        { name: 'stripe_test', rx: /sk_test_[A-Za-z0-9]{24,}/ },
        { name: 'sendgrid', rx: /SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}/ },
        { name: 'twilio', rx: /SK[0-9a-fA-F]{32}/ },
        { name: 'google_api', rx: /AIza[0-9A-Za-z\-_]{35}/ },
        { name: 'firebase', rx: /AAAA[A-Za-z0-9_\-]{7}:[A-Za-z0-9_\-]{140}/ },
    ];
    document.querySelectorAll('script:not([src])').forEach(script => {
        const code = script.textContent || '';
        for (const { name, rx } of KEY_PATTERNS) {
            const match = code.match(rx);
            if (match) {
                findings.exposedKeys.push({
                    type: name,
                    snippet: match[0].substring(0, 20) + '...',
                    location: 'inline_script',
                });
            }
        }
    });
    // Check window globals (Next.js __NEXT_DATA__, Nuxt __NUXT_DATA__, etc.)
    const globalKeys = ['__NEXT_DATA__', '__NUXT_DATA__', '__INITIAL_STATE__', '__APP_STATE__', 'window.__config'];
    for (const key of globalKeys) {
        try {
            const val = window[key];
            if (val) {
                const str = typeof val === 'string' ? val : JSON.stringify(val);
                for (const { name, rx } of KEY_PATTERNS) {
                    const match = str.match(rx);
                    if (match) {
                        findings.exposedKeys.push({
                            type: name,
                            snippet: match[0].substring(0, 20) + '...',
                            location: key,
                        });
                    }
                }
            }
        } catch (e) { /* skip inaccessible globals */ }
    }

    // 2. Inline scripts without nonce/hash (potential CSP violation)
    findings.inlineScripts = [];
    document.querySelectorAll('script:not([src])').forEach(script => {
        const nonce = script.getAttribute('nonce');
        const content = (script.textContent || '').trim();
        if (content.length > 0 && !nonce) {
            findings.inlineScripts.push({
                hasNonce: false,
                contentLength: content.length,
                preview: content.substring(0, 60),
            });
        }
    });

    // 3. Forms without CSRF tokens (heuristic: forms with method POST lacking hidden token fields)
    findings.formsWithoutCsrf = [];
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(form => {
        const hasToken = !!form.querySelector(
            'input[name*="csrf"], input[name*="token"], input[name*="_token"], input[name*="authenticity"]'
        );
        if (!hasToken) {
            findings.formsWithoutCsrf.push({
                action: (form.getAttribute('action') || '').substring(0, 100),
                id: form.id || null,
                fieldCount: form.querySelectorAll('input, select, textarea').length,
            });
        }
    });

    // 4. Mixed content (http:// resources on an https:// page)
    findings.mixedContent = [];
    if (window.location.protocol === 'https:') {
        const selectors = [
            { sel: 'img[src]', attr: 'src' },
            { sel: 'script[src]', attr: 'src' },
            { sel: 'link[href]', attr: 'href' },
            { sel: 'iframe[src]', attr: 'src' },
            { sel: 'video[src]', attr: 'src' },
            { sel: 'audio[src]', attr: 'src' },
        ];
        for (const { sel, attr } of selectors) {
            document.querySelectorAll(sel).forEach(el => {
                const val = el.getAttribute(attr) || '';
                if (val.startsWith('http://')) {
                    findings.mixedContent.push({
                        tag: el.tagName,
                        attr,
                        url: val.substring(0, 120),
                    });
                }
            });
        }
    }

    // 5. Insecure form actions (http:// on an https:// page)
    findings.insecureFormActions = [];
    if (window.location.protocol === 'https:') {
        document.querySelectorAll('form[action]').forEach(form => {
            const action = form.getAttribute('action') || '';
            if (action.startsWith('http://')) {
                findings.insecureFormActions.push({
                    action: action.substring(0, 120),
                    method: form.getAttribute('method') || 'GET',
                });
            }
        });
    }

    // 6. localStorage / sessionStorage with sensitive key names
    findings.sensitiveStorage = [];
    const SENSITIVE_KEYS = ['token', 'password', 'secret', 'key', 'apikey', 'api_key',
                            'auth', 'credential', 'private', 'jwt', 'bearer', 'passwd'];
    const checkStorage = (store, storeName) => {
        try {
            for (let i = 0; i < store.length; i++) {
                const k = store.key(i) || '';
                const lk = k.toLowerCase();
                if (SENSITIVE_KEYS.some(sk => lk.includes(sk))) {
                    findings.sensitiveStorage.push({
                        storage: storeName,
                        key: k,
                        valuePreview: (store.getItem(k) || '').substring(0, 20) + '...',
                    });
                }
            }
        } catch (e) { /* storage not accessible */ }
    };
    checkStorage(localStorage, 'localStorage');
    checkStorage(sessionStorage, 'sessionStorage');

    // 7. External scripts from untrusted domains
    findings.externalScripts = [];
    const ownOrigin = window.location.origin;
    const TRUSTED_CDNS = ['googleapis.com', 'cloudflare.com', 'jsdelivr.net', 'unpkg.com',
                          'cdnjs.cloudflare.com', 'bootstrapcdn.com', 'jquery.com'];
    document.querySelectorAll('script[src]').forEach(script => {
        const src = script.getAttribute('src') || '';
        if (src.startsWith('http') && !src.startsWith(ownOrigin)) {
            const isTrusted = TRUSTED_CDNS.some(cdn => src.includes(cdn));
            findings.externalScripts.push({
                src: src.substring(0, 120),
                hasIntegrity: script.hasAttribute('integrity'),
                hasCrossorigin: script.hasAttribute('crossorigin'),
                trusted: isTrusted,
            });
        }
    });
    // Flag external scripts without SRI integrity hash
    findings.externalScriptsWithoutIntegrity = findings.externalScripts.filter(s => !s.hasIntegrity);

    // 8. Sensitive data in __NEXT_DATA__ / similar globals
    findings.sensitiveGlobals = [];
    const SENSITIVE_FIELD_NAMES = ['password', 'secret', 'token', 'apiKey', 'api_key',
                                   'privateKey', 'private_key', 'credential'];
    const scanObject = (obj, path = '', depth = 0) => {
        if (depth > 5 || !obj || typeof obj !== 'object') return;
        for (const [k, v] of Object.entries(obj)) {
            if (SENSITIVE_FIELD_NAMES.some(sk => k.toLowerCase().includes(sk.toLowerCase()))) {
                findings.sensitiveGlobals.push({ path: `${path}.${k}`, key: k });
            }
            if (v && typeof v === 'object') scanObject(v, `${path}.${k}`, depth + 1);
        }
    };
    try {
        if (window.__NEXT_DATA__) scanObject(window.__NEXT_DATA__, '__NEXT_DATA__');
    } catch (e) { /* ignore */ }

    // Summary
    findings.summary = {
        exposedKeyCount: findings.exposedKeys.length,
        inlineScriptCount: findings.inlineScripts.length,
        formsWithoutCsrfCount: findings.formsWithoutCsrf.length,
        mixedContentCount: findings.mixedContent.length,
        insecureFormActionCount: findings.insecureFormActions.length,
        sensitiveStorageCount: findings.sensitiveStorage.length,
        externalScriptsWithoutIntegrityCount: findings.externalScriptsWithoutIntegrity.length,
        sensitiveGlobalsCount: findings.sensitiveGlobals.length,
    };
    findings.summary.totalIssues = Object.values(findings.summary).reduce((a, b) => a + b, 0);
    findings.summary.severity = findings.exposedKeys.length > 0 ? 'critical'
        : findings.mixedContent.length > 0 || findings.insecureFormActions.length > 0 ? 'high'
        : findings.sensitiveStorage.length > 0 || findings.formsWithoutCsrf.length > 0 ? 'medium'
        : findings.inlineScripts.length > 0 ? 'low'
        : 'info';

    return findings;
}
"""

# Security headers are checked via Playwright's response object, not JS,
# because JS cannot read response headers directly.
_HEADER_CHECKS = [
    ("content-security-policy", "csp"),
    ("x-frame-options", "x_frame_options"),
    ("x-content-type-options", "x_content_type_options"),
    ("strict-transport-security", "hsts"),
    ("permissions-policy", "permissions_policy"),
    ("referrer-policy", "referrer_policy"),
]


async def audit_security(config: Any) -> list[dict[str, Any]]:
    """Run frontend security audit across all pages x viewports.

    In addition to JS-based checks, captures HTTP security response headers
    via Playwright's response interception.

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
                logger.info("Security audit: %s @ %s", url, vp.name)

                try:
                    # Intercept the main document response to capture headers
                    captured_headers: dict[str, str] = {}

                    async def on_response(response: Any) -> None:
                        if response.url == url or response.url == url + "/":
                            try:
                                headers = await response.all_headers()
                                captured_headers.update(headers)
                            except Exception:
                                pass

                    page.on("response", on_response)

                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    page.remove_listener("response", on_response)

                    # Run JS checks
                    js_findings = await page.evaluate(_SECURITY_JS)

                    # Analyse security headers
                    header_findings: dict[str, Any] = {}
                    missing_headers: list[str] = []
                    for header_name, key in _HEADER_CHECKS:
                        value = captured_headers.get(header_name)
                        header_findings[key] = value
                        if not value:
                            missing_headers.append(header_name)

                    js_findings["responseHeaders"] = header_findings
                    js_findings["missingSecurityHeaders"] = missing_headers
                    js_findings["summary"]["missingSecurityHeaderCount"] = len(missing_headers)
                    js_findings["summary"]["totalIssues"] = (
                        js_findings["summary"].get("totalIssues", 0) + len(missing_headers)
                    )
                    # Re-evaluate severity considering missing headers
                    if js_findings["summary"]["severity"] == "info" and missing_headers:
                        js_findings["summary"]["severity"] = "low"

                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "findings": js_findings,
                    })
                except Exception as exc:
                    logger.error("Security audit failed for %s @ %s: %s", url, vp.name, exc)
                    results.append({
                        "page": page_path, "viewport": vp.name,
                        "url": url, "error": str(exc),
                    })

            await context.close()
        await browser.close()

    logger.info("Security audit complete: %d test sets", len(results))
    return results
