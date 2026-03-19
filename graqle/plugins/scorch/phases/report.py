"""Phase 4: Generate combined SCORCH audit report."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scorch.report")


def generate_report(
    screenshots: list[dict],
    metrics: list[dict],
    behavioral: list[dict],
    vision_analysis: dict,
    config: Any,
) -> dict[str, Any]:
    """Generate the final SCORCH audit report.

    Returns the complete report dict AND writes report.json + report.md to output_dir.
    """
    now = datetime.now(timezone.utc).isoformat()

    issues = vision_analysis.get("issues", [])
    severity_counts = {"critical": 0, "major": 0, "minor": 0, "cosmetic": 0}
    for issue in issues:
        sev = issue.get("severity", "minor")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    behavioral_summary: dict[str, int] = {}
    for entry in behavioral:
        if "findings" in entry:
            for test_name, findings in entry["findings"].items():
                if isinstance(findings, list):
                    behavioral_summary[test_name] = behavioral_summary.get(test_name, 0) + len(findings)
                elif isinstance(findings, bool) and findings:
                    behavioral_summary[test_name] = behavioral_summary.get(test_name, 0) + 1

    passed = (
        severity_counts["critical"] == 0
        and behavioral_summary.get("deadClicks", 0) == 0
        and behavioral_summary.get("ghostElements", 0) == 0
        and behavioral_summary.get("silentSubmissions", 0) == 0
    )

    journey = vision_analysis.get("journeyAnalysis", {})
    journey_passed = (
        journey.get("journeyScore", 0) >= 6
        and len(journey.get("strandedPoints", [])) == 0
        and len(journey.get("flowBreaks", [])) == 0
    )

    report: dict[str, Any] = {
        "version": "SCORCH v3",
        "timestamp": now,
        "config": {
            "baseUrl": config.base_url,
            "pages": config.pages,
            "viewports": [v.model_dump() for v in config.viewports],
        },
        "screenshots": len([s for s in screenshots if s.get("path")]),
        "pass": passed,
        "journeyPass": journey_passed,
        "severityCounts": severity_counts,
        "behavioralSummary": behavioral_summary,
        "journeyAnalysis": journey,
        "issues": issues,
        "summary": vision_analysis.get("summary", ""),
    }

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    md_path = output_dir / "report.md"
    md = _render_markdown(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    logger.info("Phase 4 complete: report written to %s", output_dir)
    return report


def _render_markdown(report: dict) -> str:
    """Render the report as Markdown."""
    lines = [
        "# SCORCH v3 Audit Report",
        f"**Generated:** {report['timestamp']}",
        f"**Target:** {report['config']['baseUrl']}",
        f"**Pages:** {len(report['config']['pages'])} | **Screenshots:** {report['screenshots']}",
        f"**Result:** {'PASS' if report['pass'] else 'FAIL'} (Visual+Behavioral) | "
        f"{'PASS' if report['journeyPass'] else 'ADVISORY'} (Journey)",
        "",
        "## Issue Summary",
        "| Severity | Count |",
        "|----------|-------|",
    ]

    for sev, count in report["severityCounts"].items():
        lines.append(f"| {sev} | {count} |")

    lines.extend(["", "## Behavioral UX Summary", "| Test | Findings |", "|------|----------|"])
    for test, count in report.get("behavioralSummary", {}).items():
        lines.append(f"| {test} | {count} |")

    journey = report.get("journeyAnalysis", {})
    if journey:
        lines.extend([
            "", "## Journey Psychology",
            f"**Journey Score:** {journey.get('journeyScore', 'N/A')}/10",
            f"**Stranded Points:** {len(journey.get('strandedPoints', []))}",
            f"**Flow Breaks:** {len(journey.get('flowBreaks', []))}",
        ])

    if report.get("issues"):
        lines.extend(["", "## Issues"])
        for i, issue in enumerate(report["issues"], 1):
            archetype = f" (Archetype {issue['archetype']})" if issue.get("archetype") else ""
            lines.append(
                f"{i}. **[{issue['severity'].upper()}]** [{issue.get('viewport', '')}] "
                f"{issue.get('page', '')}: {issue.get('description', '')}{archetype}"
            )
            if issue.get("recommendation"):
                lines.append(f"   - Fix: {issue['recommendation']}")

    lines.extend(["", "## Summary", report.get("summary", "")])
    return "\n".join(lines)
