"""Security auditor — headers, exposed keys, CSP, mixed content."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.security")

_SECURITY_JS = """
() => {
    const r = {};

    // Inline scripts without nonce
    r.inline_scripts_without_nonce = 0;
    document.querySelectorAll('script:not([src])').forEach(s => {
        if (!s.getAttribute('nonce')) r.inline_scripts_without_nonce++;
    });

    // Exposed keys (basic pattern matching)
    r.exposed_keys = 0;
    const keyPatterns = [
        /['"](sk|pk|api|key|secret|token|password)[-_]?[a-zA-Z0-9]{20,}['"]/gi,
        /AKIA[0-9A-Z]{16}/g,  // AWS access key
    ];
    const pageText = document.documentElement.innerHTML;
    keyPatterns.forEach(pattern => {
        const matches = pageText.match(pattern);
        if (matches) r.exposed_keys += matches.length;
    });

    // Mixed content (http resources on https page)
    r.mixed_content = 0;
    if (location.protocol === 'https:') {
        document.querySelectorAll('[src^="http:"], [href^="http:"]').forEach(el => {
            const tag = el.tagName.toLowerCase();
            if (['img', 'script', 'link', 'iframe', 'video', 'audio'].includes(tag)) {
                r.mixed_content++;
            }
        });
    }

    // Sensitive data in localStorage/sessionStorage
    r.sensitive_storage = 0;
    const sensitiveKeys = ['password', 'secret', 'credit_card', 'ssn', 'token'];
    try {
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i).toLowerCase();
            if (sensitiveKeys.some(sk => key.includes(sk))) r.sensitive_storage++;
        }
    } catch(e) {}

    return r;
}
"""

_EXPECTED_HEADERS = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "permissions-policy",
    "referrer-policy",
]


class SecurityAuditor:
    """Frontend security audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            js_results = await page.evaluate(_SECURITY_JS)

            # Check response headers
            missing_headers = []
            response = await page.reload(wait_until="networkidle")
            if response:
                headers = response.headers
                for h in _EXPECTED_HEADERS:
                    if h not in headers:
                        # Map to display names
                        display = h.upper().replace("-", "-")
                        missing_headers.append(display)

            js_results["missing_headers"] = missing_headers
            js_results["severity"] = (
                "critical" if len(missing_headers) >= 4 else
                "medium" if len(missing_headers) >= 2 else
                "low"
            )

            return js_results
        except Exception as exc:
            logger.error("Security audit failed: %s", exc)
            return {"error": str(exc)}
