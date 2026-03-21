"""i18n auditor — language, encoding, RTL, locale formatting."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.i18n")

_I18N_JS = """
() => {
    const r = {};

    // Lang attribute
    const html = document.documentElement;
    r.lang_attribute_ok = !!html.getAttribute('lang');

    // Encoding
    const charset = document.querySelector('meta[charset]');
    const httpEquiv = document.querySelector('meta[http-equiv="Content-Type"]');
    r.encoding_ok = !!charset || !!httpEquiv;

    // RTL support
    r.rtl_support = html.getAttribute('dir') === 'rtl' ||
        !!document.querySelector('[dir="rtl"]');

    // Hardcoded dates (MM/DD/YYYY or DD/MM/YYYY patterns)
    r.hardcoded_dates = 0;
    const datePattern = /\\b\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}\\b/g;
    const bodyText = document.body ? document.body.innerText : '';
    const dateMatches = bodyText.match(datePattern);
    r.hardcoded_dates = dateMatches ? dateMatches.length : 0;

    // Hardcoded currency
    r.hardcoded_currency = 0;
    const currencyPattern = /[$€£¥₹]\\s*[\\d,]+\\.?\\d*/g;
    const currencyMatches = bodyText.match(currencyPattern);
    r.hardcoded_currency = currencyMatches ? currencyMatches.length : 0;

    return r;
}
"""


class I18nAuditor:
    """Internationalization audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_I18N_JS)
        except Exception as exc:
            logger.error("i18n audit failed: %s", exc)
            return {"error": str(exc)}
