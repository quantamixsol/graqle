"""Tests for graqle.guardian.badge — SVG badge generator."""

from __future__ import annotations

from graqle.guardian.badge import render_badge


class TestRenderBadge:
    def test_returns_valid_svg(self):
        svg = render_badge("PASS", 42)
        assert svg.startswith("<svg")
        assert svg.strip().endswith("</svg>")

    def test_pass_is_green(self):
        svg = render_badge("PASS", 0)
        assert "#4c1" in svg

    def test_warn_is_yellow(self):
        svg = render_badge("WARN", 5)
        assert "#dfb317" in svg

    def test_fail_is_red(self):
        svg = render_badge("FAIL", 10)
        assert "#e05d44" in svg

    def test_contains_verdict_text(self):
        svg = render_badge("PASS", 42)
        assert "PASS" in svg
        assert "r:42" in svg

    def test_contains_pr_guardian_label(self):
        svg = render_badge("WARN", 0)
        assert "PR Guardian" in svg

    def test_aria_label(self):
        svg = render_badge("FAIL", 7)
        assert 'aria-label="PR Guardian: FAIL"' in svg

    def test_title_includes_radius(self):
        svg = render_badge("PASS", 99)
        assert "radius: 99" in svg

    def test_unknown_verdict_uses_gray(self):
        svg = render_badge("UNKNOWN", 0)
        assert "#9f9f9f" in svg

    def test_zero_radius(self):
        svg = render_badge("PASS", 0)
        assert "r:0" in svg
