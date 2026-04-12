"""Markdown dashboard generator for GraQle metrics."""

# ── graqle:intelligence ──
# module: graqle.metrics.dashboard
# risk: LOW (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, datetime, pathlib, typing, engine
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.metrics.engine import MetricsEngine

_COST_PER_1K_TOKENS = 0.015  # $/1K input tokens (mid-tier LLM)


def generate_dashboard(
    metrics: MetricsEngine,
    output: Path | None = None,
) -> str:
    """Generate a markdown dashboard from metrics.

    Parameters
    ----------
    metrics:
        A populated ``MetricsEngine`` instance.
    output:
        Optional path to write the dashboard. Defaults to
        ``.graqle/dashboard.md`` next to the metrics file.

    Returns
    -------
    str
        The rendered markdown string.
    """
    summary = metrics.get_summary()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: list[str] = [
        "# GraQle Metrics Dashboard",
        "",
        f"> Generated: {now}",
        f"> Tracking since: {summary['init_timestamp'][:10]}",
        "",
    ]

    # ------------------------------------------------------------------
    # Graph statistics
    # ------------------------------------------------------------------
    sections.append("## Graph Statistics\n")
    gs_init: dict[str, Any] = summary.get("graph_stats") or {}
    gs_curr: dict[str, Any] = summary.get("graph_stats_current") or {}

    if gs_curr:
        sections.append("| Metric | Initial | Current |")
        sections.append("|--------|---------|---------|")
        sections.append(
            f"| Nodes  | {gs_init.get('nodes', '—')} | {gs_curr.get('nodes', '—')} |"
        )
        sections.append(
            f"| Edges  | {gs_init.get('edges', '—')} | {gs_curr.get('edges', '—')} |"
        )

        # Node-type breakdown
        curr_types: dict[str, int] = gs_curr.get("node_types", {})
        if curr_types:
            sections.append("")
            sections.append("**Node types:**\n")
            for ntype, count in sorted(curr_types.items(), key=lambda x: -x[1]):
                sections.append(f"- `{ntype}`: {count}")

        # Edge-type breakdown
        curr_etypes: dict[str, int] = gs_curr.get("edge_types", {})
        if curr_etypes:
            sections.append("")
            sections.append("**Edge types:**\n")
            for etype, count in sorted(curr_etypes.items(), key=lambda x: -x[1]):
                sections.append(f"- `{etype}`: {count}")
    else:
        sections.append("_No graph statistics recorded yet._")

    sections.append("")

    # ------------------------------------------------------------------
    # Token efficiency
    # ------------------------------------------------------------------
    sections.append("## Token Efficiency\n")

    context_loads = summary["context_loads"]
    tokens_saved = summary["tokens_saved"]
    avg_saved = tokens_saved // context_loads if context_loads else 0
    avg_returned = 25_000 - avg_saved if context_loads else 0
    reduction = round(25_000 / max(avg_returned, 1), 1) if context_loads else 0

    sections.append("| Metric | Value |")
    sections.append("|--------|-------|")
    sections.append(f"| Context loads | {context_loads:,} |")
    sections.append("| Avg tokens without GraQle | 25,000 |")
    sections.append(f"| Avg tokens with GraQle | {avg_returned:,} |")
    sections.append(f"| Avg tokens saved per load | {avg_saved:,} |")
    sections.append(f"| Total tokens saved | {tokens_saved:,} |")
    sections.append(f"| Reduction factor | **{reduction}x** |")
    sections.append("")

    # ------------------------------------------------------------------
    # Cumulative totals
    # ------------------------------------------------------------------
    sections.append("## Cumulative Totals\n")
    sections.append("| Metric | Count |")
    sections.append("|--------|-------|")
    sections.append(f"| Context loads | {context_loads:,} |")
    sections.append(f"| Reasoning queries | {summary['queries']:,} |")
    sections.append(f"| Tokens saved | {tokens_saved:,} |")
    sections.append(f"| Mistakes prevented | {summary['mistakes_prevented']:,} |")
    sections.append(f"| Lessons applied | {summary['lessons_applied']:,} |")
    sections.append(f"| Safety checks | {summary['safety_checks']:,} |")
    sections.append(f"| Safety violations blocked | {summary['safety_blocks']:,} |")
    sections.append(f"| Sessions completed | {summary['sessions_count']:,} |")
    sections.append(f"| Unique nodes accessed | {summary['unique_nodes_accessed']:,} |")
    sections.append("")

    # ------------------------------------------------------------------
    # Session history
    # ------------------------------------------------------------------
    sessions: list[dict[str, Any]] = metrics.sessions
    sections.append("## Session History\n")
    if sessions:
        sections.append(
            "| # | Date | Queries | Tokens Saved | Lessons | Mistakes Prevented |"
        )
        sections.append(
            "|---|------|---------|--------------|---------|-------------------|"
        )
        for idx, sess in enumerate(sessions[-20:], start=max(len(sessions) - 19, 1)):
            date_str = sess.get("date", "—")[:10]
            sections.append(
                f"| {idx} "
                f"| {date_str} "
                f"| {sess.get('queries', 0):,} "
                f"| {sess.get('tokens_saved', 0):,} "
                f"| {sess.get('lessons_applied', 0):,} "
                f"| {sess.get('mistakes_prevented', 0):,} |"
            )
        if len(sessions) > 20:
            sections.append(
                f"\n_Showing last 20 of {len(sessions)} sessions._"
            )
    else:
        sections.append("_No sessions recorded yet._")
    sections.append("")

    # ------------------------------------------------------------------
    # Top queried nodes
    # ------------------------------------------------------------------
    sections.append("## Top Queried Nodes\n")
    node_access: dict[str, dict[str, Any]] = metrics.node_access
    if node_access:
        ranked = sorted(
            node_access.items(), key=lambda kv: kv[1]["count"], reverse=True
        )[:15]
        sections.append("| Node | Accesses | Last Accessed |")
        sections.append("|------|----------|---------------|")
        for node_id, info in ranked:
            last = info.get("last_accessed", "—")[:10]
            sections.append(f"| `{node_id}` | {info['count']:,} | {last} |")
    else:
        sections.append("_No node access recorded yet._")
    sections.append("")

    # ------------------------------------------------------------------
    # Safety boundary effectiveness
    # ------------------------------------------------------------------
    sections.append("## Safety Boundary Effectiveness\n")
    safety_checks = summary["safety_checks"]
    safety_blocks = summary["safety_blocks"]
    if safety_checks:
        block_rate = safety_blocks / safety_checks * 100
        sections.append("| Metric | Value |")
        sections.append("|--------|-------|")
        sections.append(f"| Total checks | {safety_checks:,} |")
        sections.append(f"| Violations blocked | {safety_blocks:,} |")
        sections.append(f"| Block rate | {block_rate:.1f}% |")
        sections.append(f"| Clean passes | {safety_checks - safety_blocks:,} |")
    else:
        sections.append("_No safety checks recorded yet._")
    sections.append("")

    # ------------------------------------------------------------------
    # Cost impact estimate
    # ------------------------------------------------------------------
    sections.append("## Cost Impact Estimate\n")
    estimated_savings = (tokens_saved / 1000) * _COST_PER_1K_TOKENS
    sections.append("| Parameter | Value |")
    sections.append("|-----------|-------|")
    sections.append(f"| Token cost rate | ${_COST_PER_1K_TOKENS}/1K input tokens |")
    sections.append(f"| Total tokens saved | {tokens_saved:,} |")
    sections.append(f"| **Estimated savings** | **${estimated_savings:,.2f}** |")

    # Per-session average
    if sessions:
        avg_session_savings = estimated_savings / len(sessions)
        sections.append(
            f"| Avg savings per session | ${avg_session_savings:,.2f} |"
        )
    sections.append("")

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    sections.append("---")
    sections.append(
        "_Dashboard generated by [GraQle](https://github.com/the regulatory product/graqle) "
        "metrics engine._"
    )

    markdown = "\n".join(sections) + "\n"

    # Write to file
    if output is None:
        output = metrics._metrics_path.parent / "dashboard.md"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")

    return markdown
