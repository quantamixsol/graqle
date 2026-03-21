"""SEO auditor — meta tags, structured data, Open Graph."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.seo")

_SEO_JS = """
() => {
    const r = {};

    // Title
    r.title_ok = !!document.title && document.title.length > 10 && document.title.length < 70;

    // Meta description
    const desc = document.querySelector('meta[name="description"]');
    r.meta_description_ok = !!desc && desc.content.length > 50 && desc.content.length < 160;

    // Canonical
    r.canonical_present = !!document.querySelector('link[rel="canonical"]');

    // Open Graph
    const ogTitle = document.querySelector('meta[property="og:title"]');
    const ogDesc = document.querySelector('meta[property="og:description"]');
    const ogImage = document.querySelector('meta[property="og:image"]');
    const ogUrl = document.querySelector('meta[property="og:url"]');
    r.og_complete = !!(ogTitle && ogDesc && ogImage && ogUrl);

    // Twitter Card
    const twCard = document.querySelector('meta[name="twitter:card"]');
    const twTitle = document.querySelector('meta[name="twitter:title"]');
    const twDesc = document.querySelector('meta[name="twitter:description"]');
    r.twitter_card_complete = !!(twCard && twTitle && twDesc);

    // Structured data (JSON-LD)
    r.structured_data_count = document.querySelectorAll('script[type="application/ld+json"]').length;

    // Heading issues (multiple H1s)
    r.heading_issues = Math.max(0, document.querySelectorAll('h1').length - 1);

    return r;
}
"""


class SEOAuditor:
    """SEO audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_SEO_JS)
        except Exception as exc:
            logger.error("SEO audit failed: %s", exc)
            return {"error": str(exc)}
