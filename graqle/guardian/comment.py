"""PR comment renderer — generates markdown from GuardianReport.

Uses Jinja2 templates for the full PR comment with blast radius table,
governance verdict, SHACL violations, and approval requirements.
Falls back to inline rendering if Jinja2 is not available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.guardian.engine import GuardianReport


# Sentinel for the HTML comment used to find/upsert existing comments
COMMENT_MARKER = "<!-- graqle-pr-guardian -->"


def render_comment(report: GuardianReport, *, badge_url: str = "") -> str:
    """Render a PR comment markdown string from a GuardianReport."""
    lines: list[str] = [COMMENT_MARKER]
    lines.append("## 🛡️ GraQle PR Guardian\n")

    if badge_url:
        lines.append(f"![PR Guardian]({badge_url})\n")

    # -- Blast Radius Table --
    lines.append(f"### 💥 Blast Radius: {report.total_impact_radius} module{'s' if report.total_impact_radius != 1 else ''} affected\n")
    lines.append("| Module | Files Changed | Risk Level | Impact Radius |")
    lines.append("|--------|:------------:|:----------:|:-------------:|")
    for entry in report.blast_radius:
        risk_icon = _risk_icon(entry.risk_level)
        lines.append(
            f"| `{entry.module}` | {entry.files_changed} "
            f"| {risk_icon} **{entry.risk_level}** | {entry.impact_radius} |"
        )

    lines.append(f"\n**Total blast radius: {report.total_impact_radius}**\n")

    # -- Governance Verdict --
    lines.append("---\n")
    lines.append("### 🏛️ Governance Verdict\n")
    verdict_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "🚫"}.get(report.verdict.value, "❓")
    lines.append(f"#### {verdict_icon} {report.verdict.value}\n")
    for reason in report.verdict_reasons:
        lines.append(f"- {reason}")
    lines.append("")

    if report.ts_block_triggered:
        lines.append(
            "> **TS-BLOCK is unconditional and cannot be overridden by `approved_by`.**\n"
            "> This PR modifies a hard-blocked path. Contact a governance administrator.\n"
        )

    # -- SHACL Violations --
    lines.append("---\n")
    lines.append("### 🔍 SHACL Violations\n")
    if report.shacl_violations:
        lines.append("| # | Severity | Message |")
        lines.append("|---|----------|---------|")
        for i, v in enumerate(report.shacl_violations, 1):
            sev_icon = {"Violation": "🔴", "Warning": "🟡"}.get(v.severity, "ℹ️")
            safe_msg = v.message.replace("|", "\\|").replace("`", "\\`")
            lines.append(
                f"| {i} | {sev_icon} {v.severity} | {safe_msg} |"
            )
    else:
        lines.append("_No SHACL violations detected._ ✅")
    lines.append("")

    # -- Approval Requirements --
    lines.append("---\n")
    lines.append("### 🔐 Approval Requirements\n")
    if report.required_rbac_level:
        lines.append(f"**This PR requires approval from: `{report.required_rbac_level}`**\n")
        if report.required_rbac_level == "T3":
            lines.append(
                "- A registered **Tech Lead** or **Governance Admin** must approve."
            )
        elif report.required_rbac_level == "T2":
            lines.append("- A **Senior Engineer** or above must approve.")
        lines.append("")

        if report.current_approvals:
            approvals = ", ".join(f"`{a}`" for a in report.current_approvals)
            lines.append(f"Current approvals: {approvals}")

        if report.approval_satisfied:
            lines.append("\n✅ Approval requirement satisfied.")
        else:
            lines.append("\n❌ **Approval requirement NOT yet satisfied.**")
    else:
        lines.append("_No elevated approval required._ ✅")
    lines.append("")

    # -- Summary Stats --
    lines.append("---\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Blast Radius | **{report.total_impact_radius}** |")
    lines.append(f"| Files Analyzed | **{len(report.gate_results)}** |")
    lines.append(f"| Blocked | **{report.breaking_count}** |")
    lines.append(f"| SHACL Violations | **{len(report.shacl_violations)}** |")
    lines.append(f"| Verdict | **{report.verdict.value}** |")
    lines.append("")

    # -- Footer --
    lines.append("---\n")
    lines.append(
        f"<sub>🔬 Powered by <a href=\"https://github.com/quantamixsol/graqle\">GraQle</a> "
        f"PR Guardian v{report.version} · "
        f"Scan completed {report.timestamp}</sub>"
    )

    return "\n".join(lines)


def _risk_icon(risk_level: str) -> str:
    """Map risk level to emoji."""
    return {
        "TS-BLOCK": "🔴",
        "T3": "🟠",
        "T2": "🟡",
        "T1": "🟢",
    }.get(risk_level, "⚪")
