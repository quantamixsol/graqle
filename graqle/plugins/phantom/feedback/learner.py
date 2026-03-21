"""KG Learner — auto-teach audit findings to GraQle knowledge graph."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.feedback.learner")


class KGLearner:
    """Records Phantom audit findings into the GraQle knowledge graph.

    Uses graq_learn internally to persist critical/high findings as
    LESSON nodes so they surface in future preflight checks.
    """

    async def record_audit(
        self,
        page_url: str,
        findings: dict[str, Any],
        summary: dict[str, Any],
    ) -> int:
        """Record critical/high findings as KG lessons. Returns count of nodes created."""
        nodes_created = 0

        # Only teach critical and high findings
        if summary.get("critical", 0) == 0 and summary.get("high", 0) == 0:
            return 0

        try:
            from graqle import Graqle
            graph = Graqle.from_json("graqle.json")
        except Exception:
            logger.debug("No graph available for KG learning")
            return 0

        try:
            lessons = self._extract_lessons(page_url, findings, summary)
            for lesson in lessons:
                graph.add_node(
                    node_id=lesson["id"],
                    node_type="LESSON",
                    label=lesson["label"],
                    description=lesson["description"],
                    metadata={"source": "phantom_audit", "url": page_url},
                )
                nodes_created += 1

            if nodes_created > 0:
                graph.save("graqle.json")
                logger.info("Recorded %d lessons from Phantom audit", nodes_created)

        except Exception as exc:
            logger.warning("Failed to record audit findings to KG: %s", exc)

        return nodes_created

    def _extract_lessons(
        self,
        page_url: str,
        findings: dict[str, Any],
        summary: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Extract teachable lessons from audit findings."""
        lessons = []
        domain = page_url.split("//")[-1].split("/")[0] if "//" in page_url else page_url

        # Security issues
        missing_headers = findings.get("security", {}).get("missing_headers", [])
        if len(missing_headers) >= 4:
            lessons.append({
                "id": f"phantom_security_{domain}",
                "label": f"Missing {len(missing_headers)} security headers on {domain}",
                "description": (
                    f"Phantom audit found missing security headers: {', '.join(missing_headers[:6])}. "
                    f"This is a critical security issue."
                ),
            })

        # Accessibility issues
        a11y = findings.get("accessibility", {})
        if a11y.get("wcag_level") == "BELOW_AA":
            lessons.append({
                "id": f"phantom_a11y_{domain}",
                "label": f"WCAG AA compliance failure on {domain}",
                "description": (
                    f"Phantom audit: {a11y.get('contrast_violations', 0)} contrast violations, "
                    f"{a11y.get('missing_aria_labels', 0)} missing ARIA labels, "
                    f"{a11y.get('unlabeled_inputs', 0)} unlabeled inputs."
                ),
            })

        # Mobile issues
        mobile = findings.get("mobile", {})
        if mobile.get("small_touch_targets", 0) > 20:
            lessons.append({
                "id": f"phantom_mobile_{domain}",
                "label": f"{mobile['small_touch_targets']} small touch targets on {domain}",
                "description": (
                    f"Phantom audit: {mobile['small_touch_targets']} touch targets below 44x44px. "
                    f"This causes tap accuracy issues on mobile devices."
                ),
            })

        return lessons
