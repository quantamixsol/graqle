"""Tests for graqle.core.governance — 3-tier GovernanceMiddleware.

# ── graqle:intelligence ──
# module: tests.test_generation.test_governance
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, graqle.core.governance
# constraints: TS-BLOCK must NEVER be threshold-based, NEVER bypassable
# ── /graqle:intelligence ──
"""
from __future__ import annotations

import pytest

from graqle.core.governance import (
    GateResult,
    GovernanceBypassNode,
    GovernanceConfig,
    GovernanceMiddleware,
    _check_secret_exposure,
    _check_ts_leakage,
)


# ---------------------------------------------------------------------------
# GovernanceConfig Tests
# ---------------------------------------------------------------------------

class TestGovernanceConfig:
    def test_defaults(self) -> None:
        cfg = GovernanceConfig()
        assert cfg.ts_hard_block is True
        assert cfg.auto_pass_max_radius == 2
        assert cfg.auto_pass_max_risk == "LOW"
        assert cfg.review_threshold == 0.70
        assert cfg.block_threshold == 0.90
        assert cfg.cumulative_radius_cap == 10
        assert cfg.cumulative_window_hours == 24

    def test_risk_to_int_ordering(self) -> None:
        cfg = GovernanceConfig()
        assert cfg.risk_to_int("LOW") < cfg.risk_to_int("MEDIUM")
        assert cfg.risk_to_int("MEDIUM") < cfg.risk_to_int("HIGH")
        assert cfg.risk_to_int("HIGH") < cfg.risk_to_int("CRITICAL")

    def test_risk_to_int_case_insensitive(self) -> None:
        cfg = GovernanceConfig()
        assert cfg.risk_to_int("low") == cfg.risk_to_int("LOW")
        assert cfg.risk_to_int("High") == cfg.risk_to_int("HIGH")

    def test_risk_to_int_unknown_defaults_medium(self) -> None:
        cfg = GovernanceConfig()
        assert cfg.risk_to_int("UNKNOWN") == 1  # defaults to MEDIUM


# ---------------------------------------------------------------------------
# TS-BLOCK Pattern Tests (unconditional hard-block)
# ---------------------------------------------------------------------------

class TestTSBlockPatterns:
    def test_ts1_weight_blocked(self) -> None:
        # TS-1: Q-function weight names
        blocked, reason = _check_ts_leakage("w_J = 0.5")
        assert blocked is True
        assert "w_J" in reason

    def test_ts1_w_a_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("config.w_A = 0.3")
        assert blocked is True

    def test_ts2_jaccard_formula_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("jaccard formula implementation")
        assert blocked is True

    def test_ts3_production_rule_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("production_rule: TYPE -> NODE_TYPE")
        assert blocked is True

    def test_ts3_stg_rule_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("stg rule for class IV")
        assert blocked is True

    def test_ts4_theta_fold_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("theta_fold = 0.82")
        assert blocked is True

    def test_ts4_unicode_theta_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("θ_fold derivation")
        assert blocked is True

    def test_agreement_threshold_value_blocked(self) -> None:
        blocked, reason = _check_ts_leakage("AGREEMENT_THRESHOLD = REDACTED")
        assert blocked is True

    def test_safe_content_passes(self) -> None:
        blocked, reason = _check_ts_leakage("def compute_confidence(score: float) -> float:")
        assert blocked is False
        assert reason == ""

    def test_empty_content_passes(self) -> None:
        blocked, reason = _check_ts_leakage("")
        assert blocked is False

    def test_unrelated_content_passes(self) -> None:
        blocked, reason = _check_ts_leakage("import json\nresult = {'confidence': 0.85}")
        assert blocked is False


# ---------------------------------------------------------------------------
# Secret Pattern Tests
# ---------------------------------------------------------------------------

class TestSecretPatterns:
    def test_password_assignment_detected(self) -> None:
        found, matches = _check_secret_exposure("password = 'super_secret_pw'")
        assert found is True

    def test_api_key_detected(self) -> None:
        found, matches = _check_secret_exposure("api_key = 'sk-12345678901234567890'")
        assert found is True

    def test_openai_key_detected(self) -> None:
        found, matches = _check_secret_exposure("key = sk-abcdefghijklmnopqrstuvwxyz12345678")
        assert found is True

    def test_anthropic_key_detected(self) -> None:
        found, matches = _check_secret_exposure("ANTHROPIC_API_KEY = 'ant-12345678901234567'")
        assert found is True

    def test_aws_secret_key_detected(self) -> None:
        found, matches = _check_secret_exposure(
            "aws_secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
        )
        assert found is True

    def test_clean_content_passes(self) -> None:
        found, matches = _check_secret_exposure("x = 1\nprint(x)")
        assert found is False
        assert matches == []


# ---------------------------------------------------------------------------
# GovernanceMiddleware.check() — Tier Logic
# ---------------------------------------------------------------------------

class TestGovernanceTierLogic:
    def setup_method(self) -> None:
        import json
        import os
        import graqle.core.rbac as _rbac_mod
        # Register test actors as leads so T3 approval tests pass with RBAC
        actors = [
            {"actor_id": "alice", "role": "lead"},
            {"actor_id": "bob", "role": "lead"},
            {"actor_id": "cto@graqle.com", "role": "lead"},
        ]
        os.environ["GRAQLE_RBAC_ACTORS_JSON"] = json.dumps(actors)
        _rbac_mod._default_validator = None  # reset so env var is picked up
        self.mw = GovernanceMiddleware()

    def teardown_method(self) -> None:
        import os
        import graqle.core.rbac as _rbac_mod
        os.environ.pop("GRAQLE_RBAC_ACTORS_JSON", None)
        _rbac_mod._default_validator = None

    def test_ts_block_takes_precedence(self) -> None:
        # TS-BLOCK must trigger even when risk=LOW and radius=0
        result = self.mw.check(
            diff="w_J = 0.5",
            risk_level="LOW",
            impact_radius=0,
        )
        assert result.tier == "TS-BLOCK"
        assert result.blocked is True
        assert result.requires_approval is False  # no approval can unblock TS

    def test_ts_block_cannot_be_bypassed_with_approval(self) -> None:
        result = self.mw.check(
            diff="theta_fold = 0.82",
            risk_level="LOW",
            impact_radius=0,
            approved_by="alice",
        )
        assert result.tier == "TS-BLOCK"
        assert result.blocked is True

    def test_t1_autopass_low_risk_low_radius(self) -> None:
        result = self.mw.check(
            risk_level="LOW",
            impact_radius=1,
        )
        assert result.tier == "T1"
        assert result.blocked is False
        assert result.requires_approval is False

    def test_t1_autopass_boundary(self) -> None:
        # Exactly at boundary: LOW risk, radius=2 → T1
        result = self.mw.check(risk_level="LOW", impact_radius=2)
        assert result.tier == "T1"
        assert result.blocked is False

    def test_t1_not_autopass_when_radius_above_boundary(self) -> None:
        # radius=3 with LOW risk → T2
        result = self.mw.check(risk_level="LOW", impact_radius=3)
        assert result.tier in ("T2",)
        assert result.blocked is False

    def test_t3_high_risk_blocked_without_approval(self) -> None:
        result = self.mw.check(risk_level="HIGH", impact_radius=1)
        assert result.tier == "T3"
        assert result.blocked is True
        assert result.requires_approval is True

    def test_t3_critical_risk_blocked_without_approval(self) -> None:
        result = self.mw.check(risk_level="CRITICAL", impact_radius=0)
        assert result.tier == "T3"
        assert result.blocked is True

    def test_t3_high_radius_blocked_without_approval(self) -> None:
        result = self.mw.check(risk_level="LOW", impact_radius=9)
        assert result.tier == "T3"
        assert result.blocked is True

    def test_t3_passes_with_explicit_approval(self) -> None:
        result = self.mw.check(
            risk_level="HIGH",
            impact_radius=5,
            approved_by="alice",
        )
        assert result.tier == "T3"
        assert result.blocked is False
        assert result.bypass_allowed is True

    def test_t3_approval_reason_includes_approver(self) -> None:
        result = self.mw.check(
            risk_level="HIGH",
            impact_radius=5,
            approved_by="bob",
        )
        assert "bob" in result.reason

    def test_t2_medium_risk_passes_without_approval(self) -> None:
        result = self.mw.check(risk_level="MEDIUM", impact_radius=3)
        assert result.tier == "T2"
        assert result.blocked is False
        assert result.requires_approval is False

    def test_t2_bypass_allowed(self) -> None:
        result = self.mw.check(risk_level="MEDIUM", impact_radius=5)
        assert result.tier == "T2"
        assert result.bypass_allowed is True

    def test_gate_score_range(self) -> None:
        result = self.mw.check(risk_level="MEDIUM", impact_radius=5)
        assert 0.0 <= result.gate_score <= 1.0

    def test_secret_exposure_escalates_to_t3(self) -> None:
        result = self.mw.check(
            diff="api_key = 'my-long-secret-key'",
            risk_level="LOW",
            impact_radius=0,
        )
        assert result.tier == "T3"
        assert result.blocked is True
        assert any("secret" in w.lower() or "Secret" in w for w in result.warnings)

    def test_gate_result_to_dict(self) -> None:
        result = self.mw.check(risk_level="LOW", impact_radius=1)
        d = result.to_dict()
        assert "tier" in d
        assert "blocked" in d
        assert "requires_approval" in d
        assert "gate_score" in d
        assert "reason" in d
        assert isinstance(d["warnings"], list)


# ---------------------------------------------------------------------------
# GovernanceConfig — disabled TS hard block (for stripped builds)
# ---------------------------------------------------------------------------

class TestTSHardBlockDisabled:
    def test_ts_block_skipped_when_disabled(self) -> None:
        cfg = GovernanceConfig(ts_hard_block=False)
        mw = GovernanceMiddleware(cfg)
        result = mw.check(diff="w_J = 0.5", risk_level="LOW", impact_radius=0)
        # With TS-BLOCK disabled, LOW risk + low radius → T1
        assert result.tier == "T1"
        assert result.blocked is False


# ---------------------------------------------------------------------------
# GovernanceBypassNode Tests
# ---------------------------------------------------------------------------

class TestGovernanceBypassNode:
    def test_build_bypass_node_t2(self) -> None:
        mw = GovernanceMiddleware()
        gate_result = mw.check(risk_level="MEDIUM", impact_radius=5, file_path="foo.py")
        node = mw.build_bypass_node(
            gate_result,
            approved_by="",
            justification="routine update",
            action="edit",
            actor="dev@graqle.com",
        )
        assert node.gate_tier == "T2"
        assert node.bypass_id.startswith("bypass_")
        assert node.risk_level == "MEDIUM"
        assert node.impact_radius == 5
        assert node.file_path == "foo.py"
        assert node.actor == "dev@graqle.com"
        assert node.actual_outcome == "unknown"
        assert node.regret_score == 0.0

    def test_build_bypass_node_t3_with_approval(self) -> None:
        mw = GovernanceMiddleware()
        gate_result = mw.check(
            risk_level="HIGH",
            impact_radius=3,
            approved_by="cto@graqle.com",
            file_path="graqle/core/graph.py",
        )
        node = mw.build_bypass_node(
            gate_result,
            approved_by="cto@graqle.com",
            justification="critical hotfix",
            action="edit",
            actor="dev@graqle.com",
        )
        assert node.gate_tier == "T3"
        assert node.approved_by == "cto@graqle.com"
        assert node.justification == "critical hotfix"

    def test_bypass_node_to_node_metadata(self) -> None:
        mw = GovernanceMiddleware()
        gate_result = mw.check(risk_level="MEDIUM", impact_radius=4, file_path="x.py")
        node = mw.build_bypass_node(gate_result)
        meta = node.to_node_metadata()
        assert meta["entity_type"] == "GOVERNANCE_BYPASS"
        assert "gate_tier" in meta
        assert "timestamp" in meta
        assert "gate_score" in meta
        assert "risk_level" in meta
        assert "impact_radius" in meta

    def test_bypass_node_id_is_unique(self) -> None:
        import time
        mw = GovernanceMiddleware()
        g1 = mw.check(risk_level="MEDIUM", impact_radius=3, file_path="a.py")
        g2 = mw.check(risk_level="MEDIUM", impact_radius=3, file_path="b.py")
        n1 = mw.build_bypass_node(g1)
        time.sleep(0.001)
        n2 = mw.build_bypass_node(g2)
        # IDs are based on timestamp + file_path — different file_paths → different IDs
        assert n1.bypass_id != n2.bypass_id
