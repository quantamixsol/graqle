"""Performance auditor — DOM size, resources, timing."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.performance")

_PERF_JS = """
() => {
    const r = {};

    r.dom_nodes = document.querySelectorAll('*').length;
    r.resources = performance.getEntriesByType('resource').length;

    // Transfer size
    let totalTransfer = 0;
    performance.getEntriesByType('resource').forEach(entry => {
        totalTransfer += entry.transferSize || 0;
    });
    r.transfer_kb = Math.round(totalTransfer / 1024);

    // Navigation timing
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) {
        r.dom_interactive_ms = Math.round(nav.domInteractive - nav.startTime);
        r.dom_complete_ms = Math.round(nav.domComplete - nav.startTime);
    } else {
        r.dom_interactive_ms = 0;
        r.dom_complete_ms = 0;
    }

    return r;
}
"""


class PerformanceAuditor:
    """Performance audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_PERF_JS)
        except Exception as exc:
            logger.error("Performance audit failed: %s", exc)
            return {"error": str(exc)}
