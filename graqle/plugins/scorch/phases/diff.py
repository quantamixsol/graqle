"""Phase: Before/after diff — compare two SCORCH reports to surface regressions and improvements."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scorch.diff")


def _load_report(path: str | Path) -> dict[str, Any] | None:
    """Load a SCORCH report JSON from disk. Returns None if file not found."""
    p = Path(path)
    if not p.exists():
        logger.warning("Report not found: %s", p)
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load report %s: %s", p, exc)
        return None


def _issue_key(issue: dict[str, Any]) -> str:
    """Stable identity key for a single issue — used for resolved/new/persistent diffing."""
    return "|".join([
        str(issue.get("severity", "")),
        str(issue.get("page", "")),
        str(issue.get("viewport", "")),
        str(issue.get("description", ""))[:120],
    ])


def _compare_severity_counts(
    old: dict[str, int], new: dict[str, int]
) -> dict[str, Any]:
    """Compare two severity count dicts, returning deltas."""
    all_keys = set(old) | set(new)
    deltas = {}
    for k in sorted(all_keys):
        old_val = old.get(k, 0)
        new_val = new.get(k, 0)
        deltas[k] = {
            "old": old_val,
            "new": new_val,
            "delta": new_val - old_val,
            "trend": "improved" if new_val < old_val else ("regressed" if new_val > old_val else "unchanged"),
        }
    return deltas


def _compare_behavioral(
    old: dict[str, int], new: dict[str, int]
) -> dict[str, Any]:
    """Compare two behavioral summary dicts."""
    all_keys = set(old) | set(new)
    result = {}
    for k in sorted(all_keys):
        old_val = old.get(k, 0)
        new_val = new.get(k, 0)
        result[k] = {
            "old": old_val,
            "new": new_val,
            "delta": new_val - old_val,
            "trend": "improved" if new_val < old_val else ("regressed" if new_val > old_val else "unchanged"),
        }
    return result


async def audit_diff(
    config: Any,
    previous_report_path: str | None = None,
) -> dict[str, Any]:
    """Compare a previous SCORCH report against the latest report in config.output_dir.

    Does NOT use Playwright. Loads two report.json files and produces a structured
    diff covering issue resolution, new regressions, score changes, and overall trend.

    Args:
        config: ScorchConfig instance (used for output_dir).
        previous_report_path: Path to the older report.json. If None, looks for
            a report.json in the default output dir and a previous one named
            report.previous.json in the same directory.

    Returns:
        A structured diff report dict.
    """
    output_dir = Path(config.output_dir)

    # --- Locate current report ---
    current_path = output_dir / "report.json"
    current = _load_report(current_path)
    if current is None:
        logger.error("Current report not found at %s — run a full SCORCH audit first.", current_path)
        return {
            "error": f"Current report not found at {current_path}",
            "diff": None,
        }

    # --- Locate previous report ---
    resolved_previous_path: str | Path
    if previous_report_path:
        resolved_previous_path = previous_report_path
    else:
        # Fall back to report.previous.json in same directory
        resolved_previous_path = output_dir / "report.previous.json"

    previous = _load_report(resolved_previous_path)
    if previous is None:
        logger.warning(
            "No previous report found at %s — returning current report as baseline.",
            resolved_previous_path,
        )
        return {
            "error": f"Previous report not found at {resolved_previous_path}",
            "currentTimestamp": current.get("timestamp"),
            "diff": None,
        }

    logger.info(
        "Diffing reports: %s (old) vs %s (new)",
        previous.get("timestamp", "unknown"),
        current.get("timestamp", "unknown"),
    )

    # --- Issue-level diff ---
    old_issues: list[dict] = previous.get("issues", [])
    new_issues: list[dict] = current.get("issues", [])

    old_keys = {_issue_key(i): i for i in old_issues}
    new_keys = {_issue_key(i): i for i in new_issues}

    resolved_issues = [old_keys[k] for k in old_keys if k not in new_keys]
    new_regressions = [new_keys[k] for k in new_keys if k not in old_keys]
    persistent_issues = [new_keys[k] for k in new_keys if k in old_keys]

    # --- Severity count diff ---
    old_severity = previous.get("severityCounts", {})
    new_severity = current.get("severityCounts", {})
    severity_diff = _compare_severity_counts(old_severity, new_severity)

    # --- Behavioral summary diff ---
    old_behavioral = previous.get("behavioralSummary", {})
    new_behavioral = current.get("behavioralSummary", {})
    behavioral_diff = _compare_behavioral(old_behavioral, new_behavioral)

    # --- Journey score diff ---
    old_journey = previous.get("journeyAnalysis", {})
    new_journey = current.get("journeyAnalysis", {})
    old_score = old_journey.get("journeyScore", None)
    new_score = new_journey.get("journeyScore", None)
    journey_score_delta: float | None = None
    if old_score is not None and new_score is not None:
        journey_score_delta = round(float(new_score) - float(old_score), 2)

    # --- Overall improvement/regression percentages ---
    old_total = len(old_issues)
    new_total = len(new_issues)
    improvement_pct: float | None = None
    regression_pct: float | None = None

    if old_total > 0:
        improvement_pct = round((len(resolved_issues) / old_total) * 100, 1)
    if old_total > 0:
        regression_pct = round((len(new_regressions) / old_total) * 100, 1)

    # --- Overall trend ---
    old_critical = old_severity.get("critical", 0)
    new_critical = new_severity.get("critical", 0)
    if new_critical < old_critical or (len(resolved_issues) > len(new_regressions)):
        overall_trend = "improved"
    elif new_critical > old_critical or (len(new_regressions) > len(resolved_issues)):
        overall_trend = "regressed"
    else:
        overall_trend = "unchanged"

    # --- Pass/fail comparison ---
    old_pass = previous.get("pass", False)
    new_pass = current.get("pass", False)

    diff_report: dict[str, Any] = {
        "version": "SCORCH diff v1",
        "previousTimestamp": previous.get("timestamp"),
        "currentTimestamp": current.get("timestamp"),
        "previousPath": str(resolved_previous_path),
        "currentPath": str(current_path),
        "overallTrend": overall_trend,
        "passChanged": old_pass != new_pass,
        "previousPass": old_pass,
        "currentPass": new_pass,
        "issueCounts": {
            "previous": old_total,
            "current": new_total,
            "delta": new_total - old_total,
            "resolved": len(resolved_issues),
            "newRegressions": len(new_regressions),
            "persistent": len(persistent_issues),
        },
        "improvementPct": improvement_pct,
        "regressionPct": regression_pct,
        "severityDiff": severity_diff,
        "behavioralDiff": behavioral_diff,
        "journeyScoreDiff": {
            "previous": old_score,
            "current": new_score,
            "delta": journey_score_delta,
            "trend": (
                "improved" if journey_score_delta and journey_score_delta > 0
                else "regressed" if journey_score_delta and journey_score_delta < 0
                else "unchanged"
            ),
        },
        "resolvedIssues": resolved_issues,
        "newRegressions": new_regressions,
        "persistentIssues": persistent_issues,
    }

    logger.info(
        "Diff complete: %d resolved, %d new regressions, %d persistent | trend=%s",
        len(resolved_issues),
        len(new_regressions),
        len(persistent_issues),
        overall_trend,
    )
    return diff_report
