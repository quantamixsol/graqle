"""Feedback loop — before/after comparison for iterative improvement."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.phantom.feedback.loop")


class FeedbackLoop:
    """Compares audit results across runs to track improvement.

    Supports comparing current findings against a previous audit
    to show resolved issues, new issues, and persistent issues.
    """

    def compare(
        self,
        current: dict[str, Any],
        previous_path: str | None = None,
    ) -> dict[str, Any]:
        """Compare current audit with previous results."""
        if not previous_path:
            return {"comparison": "no_previous", "message": "No previous audit to compare against"}

        path = Path(previous_path)
        if not path.exists():
            return {"comparison": "file_not_found", "path": previous_path}

        with open(path, "r", encoding="utf-8") as f:
            previous = json.load(f)

        prev_summary = previous.get("summary", {})
        curr_summary = current.get("summary", {})

        prev_total = prev_summary.get("total_issues", 0)
        curr_total = curr_summary.get("total_issues", 0)

        delta = curr_total - prev_total
        improvement_pct = (
            round((prev_total - curr_total) / prev_total * 100, 1)
            if prev_total > 0 else 0
        )

        return {
            "comparison": "complete",
            "previous_grade": prev_summary.get("grade", "N/A"),
            "current_grade": curr_summary.get("grade", "N/A"),
            "previous_total": prev_total,
            "current_total": curr_total,
            "delta": delta,
            "improvement_pct": improvement_pct,
            "improved": delta < 0,
            "severity_changes": {
                "critical": curr_summary.get("critical", 0) - prev_summary.get("critical", 0),
                "high": curr_summary.get("high", 0) - prev_summary.get("high", 0),
                "medium": curr_summary.get("medium", 0) - prev_summary.get("medium", 0),
                "low": curr_summary.get("low", 0) - prev_summary.get("low", 0),
            },
        }
