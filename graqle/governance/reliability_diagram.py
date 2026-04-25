# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26166054.2 (Divisional, Claims F-J), owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Reliability Diagram SVG Generator (R20 ADR-203).

Generates an audit-grade reliability diagram as an SVG string.
No external plotting libraries — pure string generation.

The diagram shows:
- Perfect calibration diagonal (y=x)
- Per-bin points with confidence interval whiskers
- ECE metric and sample count labels
- Status indicator (calibrated / uncalibrated)
"""

from __future__ import annotations

from graqle.governance.calibration import CalibrationModel


# SVG canvas dimensions
_WIDTH = 500
_HEIGHT = 500
_MARGIN = 60
_PLOT_WIDTH = _WIDTH - 2 * _MARGIN
_PLOT_HEIGHT = _HEIGHT - 2 * _MARGIN


def _x_to_px(x: float) -> float:
    """Map [0, 1] data x to SVG px."""
    return _MARGIN + x * _PLOT_WIDTH


def _y_to_px(y: float) -> float:
    """Map [0, 1] data y to SVG px (inverted)."""
    return _MARGIN + (1.0 - y) * _PLOT_HEIGHT


def generate_svg(model: CalibrationModel) -> str:
    """Generate reliability diagram SVG for a calibration model.

    Parameters
    ----------
    model:
        Fitted CalibrationModel (must be "calibrated" status to show bins).

    Returns
    -------
    SVG string suitable for display or export.
    """
    parts: list[str] = []

    # Header
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_WIDTH}" height="{_HEIGHT}" '
        f'viewBox="0 0 {_WIDTH} {_HEIGHT}" '
        f'font-family="sans-serif" font-size="12">'
    )

    # Background
    parts.append(f'<rect width="{_WIDTH}" height="{_HEIGHT}" fill="white"/>')

    # Plot area border
    parts.append(
        f'<rect x="{_MARGIN}" y="{_MARGIN}" '
        f'width="{_PLOT_WIDTH}" height="{_PLOT_HEIGHT}" '
        f'fill="#fafafa" stroke="#333" stroke-width="1"/>'
    )

    # Grid lines (every 0.2)
    for i in range(1, 5):
        v = i / 5.0
        x_px = _x_to_px(v)
        y_px = _y_to_px(v)
        parts.append(
            f'<line x1="{x_px}" y1="{_MARGIN}" x2="{x_px}" '
            f'y2="{_MARGIN + _PLOT_HEIGHT}" stroke="#e5e5e5" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{_MARGIN}" y1="{y_px}" '
            f'x2="{_MARGIN + _PLOT_WIDTH}" y2="{y_px}" stroke="#e5e5e5" stroke-width="1"/>'
        )

    # Perfect calibration diagonal (y = x)
    parts.append(
        f'<line x1="{_x_to_px(0)}" y1="{_y_to_px(0)}" '
        f'x2="{_x_to_px(1)}" y2="{_y_to_px(1)}" '
        f'stroke="#888" stroke-width="1.5" stroke-dasharray="4,4"/>'
    )

    # Axis labels
    parts.append(
        f'<text x="{_WIDTH / 2}" y="{_HEIGHT - 20}" '
        f'text-anchor="middle" fill="#333">Predicted probability</text>'
    )
    parts.append(
        f'<text x="20" y="{_HEIGHT / 2}" '
        f'text-anchor="middle" fill="#333" '
        f'transform="rotate(-90, 20, {_HEIGHT / 2})">Observed frequency</text>'
    )

    # Axis tick labels
    for i in range(6):
        v = i / 5.0
        parts.append(
            f'<text x="{_x_to_px(v)}" y="{_MARGIN + _PLOT_HEIGHT + 18}" '
            f'text-anchor="middle" fill="#555">{v:.1f}</text>'
        )
        parts.append(
            f'<text x="{_MARGIN - 8}" y="{_y_to_px(v) + 4}" '
            f'text-anchor="end" fill="#555">{v:.1f}</text>'
        )

    # Plot per-bin points (only if calibrated)
    if model.status == "calibrated" and model.bins:
        # CI whiskers first (underneath points)
        for b in model.bins:
            if b.count == 0:
                continue
            x_px = _x_to_px(b.avg_pred)
            if b.ci_low is not None and b.ci_high is not None:
                y_low = _y_to_px(b.ci_low)
                y_high = _y_to_px(b.ci_high)
                parts.append(
                    f'<line x1="{x_px}" y1="{y_low}" x2="{x_px}" y2="{y_high}" '
                    f'stroke="#1e40af" stroke-width="2"/>'
                )
                # Whisker caps
                cap = 4
                parts.append(
                    f'<line x1="{x_px - cap}" y1="{y_low}" '
                    f'x2="{x_px + cap}" y2="{y_low}" stroke="#1e40af" stroke-width="2"/>'
                )
                parts.append(
                    f'<line x1="{x_px - cap}" y1="{y_high}" '
                    f'x2="{x_px + cap}" y2="{y_high}" stroke="#1e40af" stroke-width="2"/>'
                )

        # Bin points
        for b in model.bins:
            if b.count == 0:
                continue
            x_px = _x_to_px(b.avg_pred)
            y_px = _y_to_px(b.avg_actual)
            # Size scales with count
            max_count = max(bb.count for bb in model.bins if bb.count > 0)
            radius = 4 + 6 * (b.count / max_count)
            parts.append(
                f'<circle cx="{x_px}" cy="{y_px}" r="{radius:.1f}" '
                f'fill="#2563eb" fill-opacity="0.7" stroke="#1e40af" stroke-width="1.5"/>'
            )

    # Title
    title = f"Reliability Diagram - {model.method.title()}"
    parts.append(
        f'<text x="{_WIDTH / 2}" y="25" text-anchor="middle" '
        f'font-size="16" font-weight="bold" fill="#111">{title}</text>'
    )

    # Metadata block (top-left of plot area)
    meta_x = _MARGIN + 10
    meta_y = _MARGIN + 18
    ece_str = f"{model.ece:.4f}" if model.ece is not None else "N/A"
    status_color = "#16a34a" if model.status == "calibrated" else "#dc2626"
    parts.append(
        f'<text x="{meta_x}" y="{meta_y}" fill="{status_color}" font-weight="bold">'
        f'Status: {model.status}</text>'
    )
    parts.append(
        f'<text x="{meta_x}" y="{meta_y + 16}" fill="#333">N = {model.n_samples}</text>'
    )
    parts.append(
        f'<text x="{meta_x}" y="{meta_y + 32}" fill="#333">ECE = {ece_str}</text>'
    )
    ece_passed = "PASS" if model.ece_passed else "FAIL"
    ece_color = "#16a34a" if model.ece_passed else "#dc2626"
    parts.append(
        f'<text x="{meta_x}" y="{meta_y + 48}" fill="{ece_color}">'
        f'Target ECE &lt; {model.target_ece}: {ece_passed}</text>'
    )

    # Version footer
    parts.append(
        f'<text x="{_WIDTH - 10}" y="{_HEIGHT - 8}" '
        f'text-anchor="end" fill="#888" font-size="10">{model.version}</text>'
    )

    parts.append('</svg>')
    return "\n".join(parts)
