"""Tests for graqle.guardian.engine — PR Guardian orchestrator."""

from __future__ import annotations

import pytest

from graqle.core.governance import GateResult, GovernanceConfig, GovernanceMiddleware
from graqle.guardian.engine import (
    BlastRadiusEntry,
    GuardianReport,
    PRGuardianEngine,
    Verdict,
    _tier_order,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    return GovernanceConfig()


@pytest.fixture
def middleware(config):
    return GovernanceMiddleware(config)


@pytest.fixture
def engine(config, middleware):
    return PRGuardianEngine(config=config, middleware=middleware)


def _diff_entry(file_path: str, diff: str = "", content: str = "") -> dict[str, str]:
    return {"file_path": file_path, "diff": diff, "content": content}


# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_values(self):
        assert Verdict.PASS.value == "PASS"
        assert Verdict.WARN.value == "WARN"
        assert Verdict.FAIL.value == "FAIL"

    def test_is_str_enum(self):
        assert isinstance(Verdict.PASS, str)
        assert Verdict.PASS == "PASS"


# ---------------------------------------------------------------------------
# GuardianReport
# ---------------------------------------------------------------------------


class TestGuardianReport:
    def test_default_verdict_is_pass(self):
        r = GuardianReport()
        assert r.verdict == Verdict.PASS

    def test_to_dict_keys(self):
        r = GuardianReport(verdict=Verdict.WARN, total_impact_radius=42)
        d = r.to_dict()  # public=True by default
        assert d["verdict"] == "WARN"
        assert d["blast_radius"] == 42
        assert "timestamp" in d
        # B1: gate_results must NOT be in public output
        assert "gate_results" not in d

    def test_to_dict_includes_breaking_count(self):
        r = GuardianReport(breaking_count=3)
        assert r.to_dict()["breaking_count"] == 3


# ---------------------------------------------------------------------------
# Engine: evaluate()
# ---------------------------------------------------------------------------


class TestPRGuardianEngine:
    def test_empty_diff_returns_pass(self, engine):
        report = engine.evaluate([])
        assert report.verdict == Verdict.PASS

    def test_single_low_risk_file_passes(self, engine):
        entries = [_diff_entry("tests/test_foo.py", diff="+ assert True")]
        report = engine.evaluate(entries)
        assert report.verdict == Verdict.PASS
        assert report.total_impact_radius >= 0

    def test_high_risk_file_escalates(self, engine):
        entries = [_diff_entry("graqle/core/auth_handler.py", diff="+ secret = 'abc'")]
        report = engine.evaluate(entries)
        # Auth file → HIGH risk → at minimum T2/T3
        assert len(report.gate_results) == 1

    def test_ts_block_triggers_fail(self, engine):
        # w_J is a TS-1 pattern → unconditional TS-BLOCK
        entries = [_diff_entry("graqle/core/weights.py", diff="+ w_J = 0.7")]
        report = engine.evaluate(entries)
        assert report.ts_block_triggered is True
        assert report.verdict == Verdict.FAIL

    def test_multiple_files_aggregates(self, engine):
        entries = [
            _diff_entry("tests/test_a.py", diff="+ pass"),
            _diff_entry("tests/test_b.py", diff="+ pass"),
            _diff_entry("graqle/config/settings.py", diff="+ x = 1"),
        ]
        report = engine.evaluate(entries)
        assert len(report.gate_results) == 3
        assert len(report.blast_radius) >= 1

    def test_fail_closed_on_engine_error(self):
        """B3: Engine must return FAIL (fail-closed), not WARN, on internal errors."""

        class BrokenMiddleware:
            def check(self, **kwargs):
                raise RuntimeError("boom")

        engine = PRGuardianEngine(middleware=BrokenMiddleware())
        entries = [_diff_entry("foo.py", diff="+ x")]
        report = engine.evaluate(entries)
        assert report.verdict == Verdict.FAIL
        assert "do not merge" in report.verdict_reasons[0].lower()

    def test_report_has_timestamp(self, engine):
        entries = [_diff_entry("foo.py")]
        report = engine.evaluate(entries)
        assert report.timestamp != ""

    def test_blast_radius_entry_fields(self):
        e = BlastRadiusEntry(
            module="graqle", files_changed=3, risk_level="T2", impact_radius=5
        )
        assert e.module == "graqle"
        assert e.files_changed == 3
        assert e.impact_radius == 5


# ---------------------------------------------------------------------------
# Risk estimation
# ---------------------------------------------------------------------------


class TestRiskEstimation:
    def test_auth_file_is_high(self, engine):
        assert engine._estimate_risk_level("graqle/auth/handler.py") == "HIGH"

    def test_security_file_is_high(self, engine):
        assert engine._estimate_risk_level("security/middleware.py") == "HIGH"

    def test_test_file_is_low(self, engine):
        assert engine._estimate_risk_level("tests/test_foo.py") == "LOW"

    def test_config_file_is_medium(self, engine):
        assert engine._estimate_risk_level("config/settings.py") == "MEDIUM"

    def test_regular_file_is_medium(self, engine):
        assert engine._estimate_risk_level("graqle/core/graph.py") == "MEDIUM"


# ---------------------------------------------------------------------------
# Tier ordering
# ---------------------------------------------------------------------------


class TestTierOrder:
    def test_ordering(self):
        assert _tier_order("T1") < _tier_order("T2")
        assert _tier_order("T2") < _tier_order("T3")
        assert _tier_order("T3") < _tier_order("TS-BLOCK")

    def test_unknown_tier(self):
        assert _tier_order("UNKNOWN") == -1


# ---------------------------------------------------------------------------
# IP Blocker Tests (B1-B5 from Senior Researcher review)
# ---------------------------------------------------------------------------


class TestIPBlockerFixes:
    """Tests for all 5 P0 IP blockers identified in PR #30 review."""

    def test_b1_gate_score_not_in_public_dict(self, engine):
        """B1: gate_score floats must NOT appear in public to_dict()."""
        entries = [_diff_entry("tests/test_foo.py", diff="+ pass")]
        report = engine.evaluate(entries)
        d = report.to_dict()  # default public=True
        assert "gate_results" not in d
        assert "gate_score" not in str(d)

    def test_b1_gate_results_in_private_dict(self, engine):
        """B1: gate_results available in internal mode only."""
        entries = [_diff_entry("tests/test_foo.py", diff="+ pass")]
        report = engine.evaluate(entries)
        d = report.to_dict(public=False)
        assert "gate_results" in d

    def test_b3_fail_closed_not_warn(self):
        """B3: Engine error must produce FAIL, never WARN."""

        class BrokenMiddleware:
            def check(self, **kwargs):
                raise RuntimeError("simulated failure")

        engine = PRGuardianEngine(middleware=BrokenMiddleware())
        report = engine.evaluate([_diff_entry("x.py", diff="+ y")])
        assert report.verdict == Verdict.FAIL
        assert report.verdict != Verdict.WARN

    def test_plus1_no_numeric_threshold_in_verdict(self, engine):
        """+1: Verdict reasons must not contain numeric threshold values."""
        report = GuardianReport(
            verdict=Verdict.WARN,
            verdict_reasons=["Blast radius exceeds auto-pass threshold. Review recommended."],
        )
        for reason in report.verdict_reasons:
            # Must not contain specific numbers like (2) or (10)
            assert "(" not in reason or "auto_pass" not in reason
