"""Content auditor — readability, empty states, error indicators."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.auditor.content")

_CONTENT_JS = """
() => {
    const r = {};

    const bodyText = document.body ? document.body.innerText : '';
    const words = bodyText.split(/\\s+/).filter(w => w.length > 0);
    r.word_count = words.length;

    // Empty state detection
    r.has_empty_state = !!(
        document.querySelector('[class*="empty"], [class*="no-data"], [class*="placeholder"]') ||
        bodyText.toLowerCase().includes('no results') ||
        bodyText.toLowerCase().includes('nothing here')
    );

    // Loading indicators
    r.loading_indicators = document.querySelectorAll(
        '[class*="spinner"], [class*="loading"], [class*="skeleton"], [role="progressbar"]'
    ).length;

    // Error indicators
    r.error_indicators = document.querySelectorAll(
        '[class*="error"], [role="alert"], .alert-danger, .error-message'
    ).length;

    // Abbreviation count (uppercase sequences)
    const jargonPattern = /\\b[A-Z]{2,6}\\b/g;
    const matches = bodyText.match(jargonPattern);
    r.abbreviation_count = matches ? matches.length : 0;

    // Readability estimate (average words per sentence)
    const sentences = bodyText.split(/[.!?]+/).filter(s => s.trim().length > 10);
    const avgWordsPerSentence = sentences.length > 0
        ? Math.round(words.length / sentences.length)
        : 0;
    // Rough grade level: 5 + avg_words/3
    const grade = Math.min(16, Math.max(1, Math.round(5 + avgWordsPerSentence / 3)));
    const gradeLabels = {
        1: '1st grade', 2: '2nd grade', 3: '3rd grade', 4: '4th grade',
        5: '5th grade', 6: '6th grade', 7: '7th grade', 8: '8th grade',
        9: '9th grade', 10: '10th grade', 11: '11th grade', 12: '12th grade',
        13: 'College', 14: 'College', 15: 'Graduate', 16: 'Graduate',
    };
    r.readability_grade = gradeLabels[grade] || grade + 'th grade';

    return r;
}
"""


class ContentAuditor:
    """Content quality audit for any web page."""

    async def audit(self, page: Any, config: Any = None) -> dict[str, Any]:
        try:
            return await page.evaluate(_CONTENT_JS)
        except Exception as exc:
            logger.error("Content audit failed: %s", exc)
            return {"error": str(exc)}
