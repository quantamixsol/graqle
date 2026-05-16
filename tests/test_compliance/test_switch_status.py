"""Tests for graqle.compliance.switch_status (v0.57.0 consolidated visibility)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.compliance.switch_status import (
    SWITCH_STATUS_SCHEMA_VERSION,
    _probe_article_14_gate,
    _probe_ai_disclosure,
    _probe_baseline_document,
    _probe_claim_limits,
    _probe_eur_lex_drift_guard,
    _probe_feedback_trend,
    _probe_master_switch,
    _probe_periodic_assessment,
    build_switch_status,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Start every test with the master switch OFF."""
    monkeypatch.delenv("GRAQLE_EU_AI_ACT_MODE", raising=False)
    monkeypatch.delenv("GRAQLE_AI_DISCLOSURE", raising=False)


class TestSchema:
    def test_schema_version_is_one_zero(self):
        assert SWITCH_STATUS_SCHEMA_VERSION == "1.0"

    def test_envelope_has_required_top_level_keys(self):
        status = build_switch_status()
        assert "schema_version" in status
        assert "master_switch" in status
        assert "subsystems" in status
        assert "summary" in status

    def test_envelope_serialises_to_json(self):
        status = build_switch_status()
        # Round-trip must not raise — exercise every nested value
        round_trip = json.loads(json.dumps(status))
        assert round_trip["schema_version"] == "1.0"


class TestMasterSwitchProbe:
    def test_off_by_default(self):
        probe = _probe_master_switch()
        assert probe["is_on"] is False
        assert probe["raw_value"] == ""

    def test_on_when_truthy(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        probe = _probe_master_switch()
        assert probe["is_on"] is True
        assert probe["raw_value"] == "on"

    @pytest.mark.parametrize("val", ["on", "true", "1", "yes", "ON", "True"])
    def test_truthy_values_all_recognised(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
        probe = _probe_master_switch()
        assert probe["is_on"] is True

    @pytest.mark.parametrize("val", ["off", "false", "0", "no", "", "maybe"])
    def test_falsy_values_all_treated_as_off(self, monkeypatch, val):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", val)
        probe = _probe_master_switch()
        assert probe["is_on"] is False

    def test_env_var_name_is_advertised(self):
        probe = _probe_master_switch()
        assert probe["env_var"] == "GRAQLE_EU_AI_ACT_MODE"

    def test_truthy_values_are_advertised(self):
        probe = _probe_master_switch()
        assert "on" in probe["truthy_values_accepted"]
        assert "true" in probe["truthy_values_accepted"]


class TestArticle14GateProbe:
    def test_threshold_is_placeholder_default(self):
        probe = _probe_article_14_gate()
        assert probe["default_threshold"] == 0.75
        assert probe["threshold_status"] == "placeholder"

    def test_clauses_are_14_4_c_and_d(self):
        probe = _probe_article_14_gate()
        assert probe["clauses"] == ["14(4)(c)", "14(4)(d)"]

    def test_affected_tools_listed(self):
        probe = _probe_article_14_gate()
        assert "graq_edit" in probe["affected_tools"]
        assert "graq_apply" in probe["affected_tools"]
        assert "graq_auto" in probe["affected_tools"]


class TestClaimLimitsProbe:
    def test_taxonomy_v1(self):
        probe = _probe_claim_limits()
        assert probe["taxonomy_version"] == "1.0"

    def test_seventeen_canonical_values(self):
        probe = _probe_claim_limits()
        assert probe["canonical_value_count"] == 17

    def test_extension_namespace_is_x(self):
        probe = _probe_claim_limits()
        assert probe["extension_namespace"] == "x-"

    def test_attribution_in_anchor(self):
        probe = _probe_claim_limits()
        assert "Ricky Jones" in probe["anchor"]


class TestBaselineDocumentProbe:
    def test_proof_format(self):
        probe = _probe_baseline_document()
        assert probe["proof_format_version"] == "R25-EU08-v1.0"

    def test_default_articles_covered(self):
        probe = _probe_baseline_document()
        assert "11" in probe["default_articles_covered"]
        assert "14" in probe["default_articles_covered"]

    def test_cli_command_advertised(self):
        probe = _probe_baseline_document()
        assert probe["cli_command"] == "graq compliance baseline-doc generate"


class TestPeriodicAssessmentProbe:
    def test_thresholds(self):
        probe = _probe_periodic_assessment()
        t = probe["thresholds"]
        assert t["outcome_not_ok_rate_high_severity"] == 0.02
        assert t["degraded_rate_warn_severity"] == 0.05
        assert t["mean_confidence_warn_severity_below"] == 0.6

    def test_cadence_options(self):
        probe = _probe_periodic_assessment()
        assert "monthly" in probe["cadence_options"]
        assert "quarterly" in probe["cadence_options"]
        assert "annual" in probe["cadence_options"]


class TestFeedbackTrendProbe:
    def test_observation_only_mode(self):
        probe = _probe_feedback_trend()
        assert probe["mode"] == "OBSERVATION_ONLY"

    def test_drift_alarm_sigma(self):
        probe = _probe_feedback_trend()
        assert probe["drift_alarm_sigma"] == 2.0

    def test_patent_novelty_boundary_advertised(self):
        probe = _probe_feedback_trend()
        assert "Q-PATENT" in probe["patent_novelty_boundary"]
        assert "observation" in probe["patent_novelty_boundary"].lower()
        assert "trigger" in probe["patent_novelty_boundary"].lower()

    def test_audit_test_path_advertised(self):
        probe = _probe_feedback_trend()
        # The audit test path is the regulatory anchor — must be exact
        assert probe["audit_test"] == (
            "tests/test_compliance/test_q165_no_active_recalibration_path.py"
        )


class TestEurLexDriftGuardProbe:
    def test_baseline_path_default(self):
        probe = _probe_eur_lex_drift_guard()
        assert ".graqle" in probe["baseline_path"]

    def test_max_response_bytes_10mib(self):
        probe = _probe_eur_lex_drift_guard()
        assert probe["max_response_bytes"] == 10 * 1024 * 1024

    def test_workflow_cron_monday(self):
        probe = _probe_eur_lex_drift_guard()
        assert "0 6 * * 1" in probe["workflow_cron"]

    def test_user_agent_identifies_graqle(self):
        probe = _probe_eur_lex_drift_guard()
        assert "GraQle" in probe["user_agent"]


class TestSummary:
    def test_summary_counts_subsystems(self):
        status = build_switch_status()
        s = status["summary"]
        assert s["subsystems_total"] == 7
        assert s["subsystems_available"] >= 6  # at minimum the core ones
        assert s["master_switch_on"] is False

    def test_summary_reflects_master_switch_on(self, monkeypatch):
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "on")
        status = build_switch_status()
        assert status["summary"]["master_switch_on"] is True


class TestNeverRaises:
    """The status surface is regulator-readable — must never raise."""

    def test_build_status_never_raises_with_clean_env(self):
        # Even with no env vars, no .graqle dir, no baseline file — must
        # not raise.
        build_switch_status()  # no assert: success == not raising

    def test_build_status_never_raises_with_garbage_env(self, monkeypatch):
        # Linux disallows NUL in env-var values at the OS level
        # (os.environ raises ValueError: embedded null byte). Use
        # control chars + high-bytes that ARE valid in env vars on all
        # OSes but unusual enough to exercise the probe's
        # "tolerates surprising input" contract.
        monkeypatch.setenv("GRAQLE_EU_AI_ACT_MODE", "\x01\x02garbage\x7f")
        monkeypatch.setenv("GRAQLE_AI_DISCLOSURE", "weird")
        build_switch_status()


class TestCorruptBaselineHandling:
    """Sentinel pass 4 MAJOR fix — degrade gracefully on corrupt files."""

    def test_corrupt_eur_lex_baseline_does_not_crash(self, tmp_path, monkeypatch):
        # Plant a corrupt baseline file at the default location and verify
        # the probe degrades to baseline_entry_count=-1 rather than raising.
        baseline_path = tmp_path / ".graqle" / "eur-lex-baseline.json"
        baseline_path.parent.mkdir(parents=True)
        baseline_path.write_text("not json at all", encoding="utf-8")
        monkeypatch.chdir(tmp_path)  # so the relative DEFAULT_BASELINE_PATH resolves here
        status = build_switch_status()
        eur_lex = status["subsystems"]["eur_lex_drift_guard"]
        # The probe must still return a populated dict — degradation, not crash
        assert "subsystem" in eur_lex
        # Corrupt baseline → -1 sentinel per the probe's documented contract
        assert eur_lex.get("baseline_entry_count") in (-1, 0)
