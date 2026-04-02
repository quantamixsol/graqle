"""Tests for graqle.guardian.comment — PR comment renderer."""

from __future__ import annotations

from graqle.guardian.comment import COMMENT_MARKER, render_comment
from graqle.guardian.engine import (
    BlastRadiusEntry,
    GuardianReport,
    SHACLViolation,
    Verdict,
)


class TestRenderComment:
    def test_contains_marker(self):
        report = GuardianReport()
        result = render_comment(report)
        assert COMMENT_MARKER in result

    def test_pass_verdict(self):
        report = GuardianReport(
            verdict=Verdict.PASS,
            verdict_reasons=["All checks passed."],
        )
        result = render_comment(report)
        assert "✅ PASS" in result
        assert "All checks passed." in result

    def test_fail_verdict(self):
        report = GuardianReport(
            verdict=Verdict.FAIL,
            verdict_reasons=["TS-BLOCK triggered."],
            ts_block_triggered=True,
        )
        result = render_comment(report)
        assert "🚫 FAIL" in result
        assert "TS-BLOCK is unconditional" in result

    def test_warn_verdict(self):
        report = GuardianReport(
            verdict=Verdict.WARN,
            verdict_reasons=["Advisory warnings."],
        )
        result = render_comment(report)
        assert "⚠️ WARN" in result

    def test_blast_radius_table(self):
        report = GuardianReport(
            blast_radius=[
                BlastRadiusEntry(
                    module="graqle",
                    files_changed=3,
                    risk_level="T2",
                    impact_radius=5,
                ),
            ],
            total_impact_radius=5,
        )
        result = render_comment(report)
        assert "`graqle`" in result
        assert "T2" in result
        assert "5" in result

    def test_shacl_violations_rendered(self):
        report = GuardianReport(
            shacl_violations=[
                SHACLViolation(
                    shape="AuthShape",
                    focus_node="auth.py",
                    severity="Violation",
                    message="Missing auth middleware.",
                ),
            ],
        )
        result = render_comment(report)
        assert "`AuthShape`" in result
        assert "Missing auth middleware" in result

    def test_no_shacl_violations(self):
        report = GuardianReport()
        result = render_comment(report)
        assert "No SHACL violations detected" in result

    def test_approval_required(self):
        report = GuardianReport(
            required_rbac_level="T3",
            approval_satisfied=False,
        )
        result = render_comment(report)
        assert "T3" in result
        assert "NOT yet satisfied" in result

    def test_approval_satisfied(self):
        report = GuardianReport(
            required_rbac_level="T3",
            approval_satisfied=True,
            current_approvals=["alice"],
        )
        result = render_comment(report)
        assert "satisfied" in result.lower()
        assert "`alice`" in result

    def test_no_approval_required(self):
        report = GuardianReport()
        result = render_comment(report)
        assert "No elevated approval required" in result

    def test_badge_url_included(self):
        report = GuardianReport()
        result = render_comment(report, badge_url="https://example.com/badge.svg")
        assert "https://example.com/badge.svg" in result

    def test_footer_contains_graqle_link(self):
        report = GuardianReport()
        result = render_comment(report)
        assert "quantamixsol/graqle" in result
        assert "PR Guardian" in result

    def test_summary_stats_table(self):
        report = GuardianReport(
            total_impact_radius=10,
            breaking_count=2,
        )
        result = render_comment(report)
        assert "Blast Radius" in result
        assert "Files Analyzed" in result
        assert "Blocked" in result
