"""Badge SVG generator — shields.io compatible governance badges.

Generates self-hosted SVG badges with three states:
  PASS (green) · WARN (yellow) · FAIL (red)

Badge includes blast radius count for at-a-glance impact awareness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.guardian.engine import Verdict


# shields.io-compatible SVG template
_BADGE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{total_width}" height="20" role="img"
     aria-label="PR Guardian: {verdict}">
  <title>PR Guardian: {verdict} (radius: {radius})</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle"
     font-family="Verdana,Geneva,DejaVu Sans,sans-serif"
     text-rendering="geometricPrecision" font-size="110">
    <text aria-hidden="true"
          x="{label_center}" y="150"
          fill="#010101" fill-opacity=".3"
          transform="scale(.1)"
          textLength="{label_text_width}">PR Guardian</text>
    <text x="{label_center}" y="140"
          transform="scale(.1)"
          textLength="{label_text_width}">PR Guardian</text>
    <text aria-hidden="true"
          x="{value_center}" y="150"
          fill="#010101" fill-opacity=".3"
          transform="scale(.1)"
          textLength="{value_text_width}">{value_text}</text>
    <text x="{value_center}" y="140"
          transform="scale(.1)"
          textLength="{value_text_width}">{value_text}</text>
  </g>
</svg>"""


_VERDICT_COLORS = {
    "PASS": "#4c1",      # green
    "WARN": "#dfb317",   # yellow
    "FAIL": "#e05d44",   # red
}


def render_badge(verdict: str, blast_radius: int = 0) -> str:
    """Render a shields.io-compatible SVG badge.

    Args:
        verdict: "PASS", "WARN", or "FAIL"
        blast_radius: total number of affected modules

    Returns:
        SVG string ready to write to file or serve via HTTP.
    """
    label_width = 85
    value_text = f"{verdict} · r:{blast_radius}"
    # Approximate text width: ~6.5px per character
    value_text_width = int(len(value_text) * 65)
    value_width = max(int(len(value_text) * 6.5) + 10, 60)
    total_width = label_width + value_width

    return _BADGE_SVG.format(
        total_width=total_width,
        label_width=label_width,
        value_width=value_width,
        color=_VERDICT_COLORS.get(verdict, "#9f9f9f"),
        verdict=verdict,
        radius=blast_radius,
        label_center=int(label_width / 2) * 10,
        label_text_width=int(75 * 10),
        value_center=int(label_width + value_width / 2) * 10,
        value_text_width=value_text_width,
        value_text=value_text,
    )
