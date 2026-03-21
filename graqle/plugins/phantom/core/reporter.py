"""Reporter — report compilation from audit results."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.phantom.reporter")


class Reporter:
    """Compiles audit results into structured reports (JSON + Markdown)."""

    def generate(
        self,
        url: str,
        dimensions: dict[str, Any],
        summary: dict[str, Any],
        output_dir: str = "./scorch-output/phantom",
    ) -> dict[str, str]:
        """Generate JSON and Markdown reports."""
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)

        report = {
            "version": "Phantom v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "dimensions": dimensions,
            "summary": summary,
        }

        # JSON report
        json_path = output / "report.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        # Markdown report
        md_path = output / "report.md"
        md = self._to_markdown(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        logger.info("Reports saved: %s, %s", json_path, md_path)
        return {"json": str(json_path), "markdown": str(md_path)}

    def _to_markdown(self, report: dict[str, Any]) -> str:
        """Convert report to Markdown format."""
        lines = [
            f"# Phantom Audit Report",
            f"",
            f"**URL:** {report['url']}",
            f"**Timestamp:** {report['timestamp']}",
            f"**Grade:** {report['summary'].get('grade', 'N/A')}",
            f"",
            f"## Summary",
            f"",
            f"| Severity | Count |",
            f"|----------|-------|",
            f"| Critical | {report['summary'].get('critical', 0)} |",
            f"| High | {report['summary'].get('high', 0)} |",
            f"| Medium | {report['summary'].get('medium', 0)} |",
            f"| Low | {report['summary'].get('low', 0)} |",
            f"| **Total** | **{report['summary'].get('total_issues', 0)}** |",
            f"",
        ]

        for dim_name, dim_data in report.get("dimensions", {}).items():
            lines.append(f"## {dim_name.title()}")
            lines.append("")
            if isinstance(dim_data, dict):
                for key, val in dim_data.items():
                    if isinstance(val, list) and len(val) > 5:
                        lines.append(f"- **{key}:** {len(val)} items")
                    else:
                        lines.append(f"- **{key}:** {val}")
            lines.append("")

        return "\n".join(lines)
