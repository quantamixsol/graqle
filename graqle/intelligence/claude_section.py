"""CLAUDE.md / .cursorrules Auto-Section Generator — Layer B intelligence.

Generates a bounded markdown section with module risk map, recent incidents,
and quality gate status. Auto-detects which AI tool config files exist.

Markers: <!-- graqle:intelligence --> ... <!-- /graqle:intelligence -->

See ADR-105 §CLAUDE.md Auto-Section.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.claude_section
# risk: LOW (impact radius: 3 modules)
# consumers: compile, __init__, test_claude_section
# dependencies: __future__, logging, re, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from pathlib import Path

from graqle.intelligence.models import ModulePacket
from graqle.intelligence.scorecard import RunningScorecard

logger = logging.getLogger("graqle.intelligence.claude_section")

OPEN_MARKER = "<!-- graqle:intelligence -->"
CLOSE_MARKER = "<!-- /graqle:intelligence -->"

# AI tool config file detection
AI_TOOL_FILES = {
    "claude": ["CLAUDE.md"],
    "cursor": [".cursorrules"],
    "copilot": [".github/copilot-instructions.md"],
    "windsurf": [".windsurfrules"],
}


def generate_section(
    packets: list[ModulePacket],
    scorecard: RunningScorecard,
) -> str:
    """Generate the intelligence section content."""
    lines = [OPEN_MARKER]
    lines.append("## Graqle Quality Gate (auto-generated)")
    lines.append("")
    lines.append("### Module Risk Map")
    lines.append("| Module | Risk | Impact | Functions | Consumers |")
    lines.append("|--------|------|--------|-----------|-----------|")

    # Sort by risk score descending, show top 15
    sorted_pkts = sorted(packets, key=lambda p: p.risk_score, reverse=True)
    for pkt in sorted_pkts[:15]:
        short_mod = pkt.module.rsplit(".", 1)[-1] if "." in pkt.module else pkt.module
        lines.append(
            f"| {short_mod} | {pkt.risk_level} | {pkt.impact_radius} | "
            f"{pkt.function_count} | {pkt.consumer_count} |"
        )

    # Recent incidents
    all_incidents: list[tuple[str, str]] = []
    for pkt in packets:
        for inc in pkt.incidents:
            all_incidents.append((pkt.module, inc))

    if all_incidents:
        lines.append("")
        lines.append("### Recent Incidents")
        for mod, inc in all_incidents[:5]:
            short_mod = mod.rsplit(".", 1)[-1]
            lines.append(f"- **{short_mod}**: {inc[:100]}")

    # Active constraints
    all_constraints: list[tuple[str, str]] = []
    for pkt in packets:
        for con in pkt.constraints:
            all_constraints.append((pkt.module, con))

    if all_constraints:
        lines.append("")
        lines.append("### Active Constraints")
        for mod, con in all_constraints[:5]:
            short_mod = mod.rsplit(".", 1)[-1]
            lines.append(f"- **{short_mod}**: {con}")

    # Quality gate status
    cov = scorecard.coverage
    lines.append("")
    lines.append("### Quality Gate Status")
    lines.append(
        f"Coverage: {cov.chunk_coverage}% chunks | "
        f"{cov.description_coverage}% descriptions | "
        f"Health: {cov.health}"
    )
    lines.append(f"Modules: {len(packets)} | Auto-repairs: {scorecard.auto_repairs}")

    # Top insights
    if scorecard.insights:
        lines.append("")
        lines.append("### Key Insights")
        for insight in scorecard.insights[:5]:
            lines.append(f"- **{insight.module}**: {insight.message[:100]}")

    lines.append(CLOSE_MARKER)
    return "\n".join(lines)


def detect_ai_tools(root: Path) -> dict[str, Path]:
    """Auto-detect which AI tool config files exist.

    Returns {tool_name: file_path} for each detected tool.
    """
    found: dict[str, Path] = {}
    for tool, filenames in AI_TOOL_FILES.items():
        for fname in filenames:
            fpath = root / fname
            if fpath.exists():
                found[tool] = fpath
                break
    return found


def inject_section(file_path: Path, section: str) -> bool:
    """Inject intelligence section into a markdown/text file.

    If markers exist, replaces content between them.
    If not, appends at end of file.
    Returns True if file was modified.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        content = ""

    if OPEN_MARKER in content:
        # Replace between markers
        pattern = re.escape(OPEN_MARKER) + r".*?" + re.escape(CLOSE_MARKER)
        new_content = re.sub(pattern, section, content, count=1, flags=re.DOTALL)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            return True
        return False
    else:
        # Append at end
        separator = "\n\n" if content and not content.endswith("\n\n") else "\n" if content and not content.endswith("\n") else ""
        new_content = content + separator + section + "\n"
        file_path.write_text(new_content, encoding="utf-8")
        return True


def eject_section(file_path: Path) -> bool:
    """Remove intelligence section from a file.

    Returns True if file was modified.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return False

    if OPEN_MARKER not in content:
        return False

    pattern = r"\n?" + re.escape(OPEN_MARKER) + r".*?" + re.escape(CLOSE_MARKER) + r"\n?"
    new_content = re.sub(pattern, "", content, count=1, flags=re.DOTALL)

    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False
