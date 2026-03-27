"""Phase 10 Layer 4 — Policy-as-Code, Audit Log, Outcome Feedback Tests.

Tests for graqle/core/governance_policy.py and governance.py Layer 4 wiring.

Coverage:
  - GovernancePolicyConfig.load() — explicit path, env var, CWD, missing file fallback
  - PolicyRule glob matching (fnmatch, Windows path normalization)
  - override_tier() — elevation, no downgrade, TS-BLOCK preservation
  - is_actor_approved() — whitelist matching
  - dry_run mode — blocked=True becomes blocked=False with DRY_RUN warning
  - GovernanceAuditLog — append writes JSONL, fields correct, thread-safe
  - Audit log path from env var
  - GovernanceMiddleware wires audit log on every tier (T1, T2, T3, TS-BLOCK)
  - learn_callback fires for T3 only
  - learn_callback exception does not propagate
  - Policy min_tier elevation via middleware.check()
  - Policy approved_actors bypass T3 block
  - Inline actors from policy (structure test)
  - Backward compat: GovernancePolicyConfig importable from graqle.core.governance

Compliance:
  SOC2 CC7.2 — Audit trail: every gate decision logged
  SOC2 CC6.2 — Policy-enforced access control
  ISO27001 A.12.4.1 — Event logging
  ISO27001 A.12.4.2 — Protection of log information (append-only)
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _env_ctx(key: str, value: str):
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _write_policy(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "governance_policy.yaml"
    p.write_text(content, encoding="utf-8")
    return p


_MINIMAL_POLICY = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors:
      - "alice"
    justification: "Core modules"
  - glob: "tests/**"
    min_tier: "T1"
    approved_actors: []
    justification: "Test files"
actors:
  - actor_id: "alice"
    role: "lead"
    email: "alice@example.com"
  - actor_id: "ci-bot"
    role: "ci_pipeline"
"""


# ---------------------------------------------------------------------------
# 1. PolicyRule glob matching
# ---------------------------------------------------------------------------

class TestPolicyRuleGlobMatching:
    def _config(self, policy_yaml: str):
        from graqle.core.governance_policy import GovernancePolicyConfig
        return GovernancePolicyConfig._parse_yaml(policy_yaml)

    def test_exact_glob_matches(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        rule = cfg.get_rule_for_file("graqle/core/graph.py")
        assert rule is not None
        assert rule.min_tier == "T3"

    def test_wildcard_glob_matches_all_py_in_dir(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        for name in ("governance.py", "rbac.py", "models.py"):
            rule = cfg.get_rule_for_file(f"graqle/core/{name}")
            assert rule is not None, f"Expected match for {name}"

    def test_double_star_glob_matches_nested(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        rule = cfg.get_rule_for_file("tests/test_generation/test_foo.py")
        assert rule is not None
        assert rule.min_tier == "T1"

    def test_no_rule_returns_none(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        rule = cfg.get_rule_for_file("graqle/backends/openai.py")
        assert rule is None

    def test_first_match_wins_not_last(self) -> None:
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors: []
    justification: "First"
  - glob: "graqle/**"
    min_tier: "T1"
    approved_actors: []
    justification: "Second"
"""
        cfg = self._config(yaml)
        rule = cfg.get_rule_for_file("graqle/core/governance.py")
        assert rule is not None
        assert rule.justification == "First"

    def test_windows_backslash_normalized(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        # Simulate Windows path with backslashes
        rule = cfg.get_rule_for_file("graqle\\core\\graph.py")
        assert rule is not None
        assert rule.min_tier == "T3"

    def test_glob_does_not_match_wrong_dir(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        rule = cfg.get_rule_for_file("graqle/plugins/mcp_dev_server.py")
        assert rule is None

    def test_empty_file_path_returns_none(self) -> None:
        cfg = self._config(_MINIMAL_POLICY)
        assert cfg.get_rule_for_file("") is None


# ---------------------------------------------------------------------------
# 2. Tier override
# ---------------------------------------------------------------------------

class TestPolicyTierOverride:
    def _config(self):
        from graqle.core.governance_policy import GovernancePolicyConfig
        return GovernancePolicyConfig._parse_yaml(_MINIMAL_POLICY)

    def test_no_rule_returns_computed_tier(self) -> None:
        cfg = self._config()
        assert cfg.override_tier("graqle/backends/foo.py", "T2") == "T2"

    def test_rule_elevates_t1_to_t3(self) -> None:
        cfg = self._config()
        assert cfg.override_tier("graqle/core/graph.py", "T1") == "T3"

    def test_rule_does_not_downgrade_t3_to_t1(self) -> None:
        cfg = self._config()
        # tests/** has min_tier=T1, but computed=T3 — must NOT downgrade
        assert cfg.override_tier("tests/test_foo.py", "T3") == "T3"

    def test_ts_block_never_overridden_by_policy(self) -> None:
        cfg = self._config()
        # Even if rule says T1, TS-BLOCK is preserved
        assert cfg.override_tier("tests/test_foo.py", "TS-BLOCK") == "TS-BLOCK"
        assert cfg.override_tier("graqle/core/graph.py", "TS-BLOCK") == "TS-BLOCK"

    def test_t2_elevated_to_t3_by_policy(self) -> None:
        cfg = self._config()
        assert cfg.override_tier("graqle/core/governance.py", "T2") == "T3"

    def test_t1_stays_t1_when_rule_says_t1(self) -> None:
        cfg = self._config()
        assert cfg.override_tier("tests/unit/test_foo.py", "T1") == "T1"


# ---------------------------------------------------------------------------
# 3. Approved actors
# ---------------------------------------------------------------------------

class TestPolicyApprovedActors:
    def _config(self):
        from graqle.core.governance_policy import GovernancePolicyConfig
        return GovernancePolicyConfig._parse_yaml(_MINIMAL_POLICY)

    def test_actor_in_whitelist_returns_true(self) -> None:
        cfg = self._config()
        assert cfg.is_actor_approved("graqle/core/graph.py", "alice") is True

    def test_actor_not_in_whitelist_returns_false(self) -> None:
        cfg = self._config()
        assert cfg.is_actor_approved("graqle/core/graph.py", "bob") is False

    def test_empty_whitelist_returns_false(self) -> None:
        cfg = self._config()
        # tests/** rule has empty approved_actors
        assert cfg.is_actor_approved("tests/test_foo.py", "alice") is False

    def test_no_rule_returns_false(self) -> None:
        cfg = self._config()
        assert cfg.is_actor_approved("graqle/backends/foo.py", "alice") is False

    def test_empty_actor_returns_false(self) -> None:
        cfg = self._config()
        assert cfg.is_actor_approved("graqle/core/graph.py", "") is False


# ---------------------------------------------------------------------------
# 4. GovernancePolicyConfig.load()
# ---------------------------------------------------------------------------

class TestGovernancePolicyConfigLoad:
    def test_load_from_explicit_path(self, tmp_path: Path) -> None:
        p = _write_policy(tmp_path, _MINIMAL_POLICY)
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        assert len(cfg.rules) == 2
        assert cfg.version == "1.0"

    def test_load_from_env_var(self, tmp_path: Path, monkeypatch) -> None:
        p = _write_policy(tmp_path, _MINIMAL_POLICY)
        monkeypatch.setenv("GRAQLE_POLICY_PATH", str(p))
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load()
        assert len(cfg.rules) == 2

    def test_load_missing_file_returns_permissive_default(self) -> None:
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path="/nonexistent/path/policy.yaml")
        assert cfg.rules == []
        assert cfg.dry_run is False

    def test_load_malformed_yaml_returns_permissive_default(self, tmp_path: Path) -> None:
        p = tmp_path / "bad_policy.yaml"
        p.write_text("{{{{invalid: yaml: [[[", encoding="utf-8")
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        assert cfg.rules == []

    def test_dry_run_false_by_default(self) -> None:
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path="/nonexistent")
        assert cfg.dry_run is False

    def test_dry_run_true_when_set_in_yaml(self, tmp_path: Path) -> None:
        yaml = "version: '1.0'\ndry_run: true\nrules: []\nactors: []\n"
        p = _write_policy(tmp_path, yaml)
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        assert cfg.dry_run is True

    def test_version_field_stored(self, tmp_path: Path) -> None:
        yaml = "version: '2.5'\ndry_run: false\nrules: []\nactors: []\n"
        p = _write_policy(tmp_path, yaml)
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        assert cfg.version == "2.5"

    def test_inline_actors_parsed(self, tmp_path: Path) -> None:
        p = _write_policy(tmp_path, _MINIMAL_POLICY)
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        actors = cfg.inline_actors()
        assert len(actors) == 2
        ids = {a.actor_id for a in actors}
        assert "alice" in ids
        assert "ci-bot" in ids

    def test_rules_parsed_in_order(self, tmp_path: Path) -> None:
        p = _write_policy(tmp_path, _MINIMAL_POLICY)
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load(path=p)
        assert cfg.rules[0].glob == "graqle/core/*.py"
        assert cfg.rules[1].glob == "tests/**"

    def test_no_policy_file_returns_empty_rules(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("GRAQLE_POLICY_PATH", raising=False)
        monkeypatch.chdir(tmp_path)  # no governance_policy.yaml in tmp_path
        from graqle.core.governance_policy import GovernancePolicyConfig
        cfg = GovernancePolicyConfig.load()
        assert cfg.rules == []


# ---------------------------------------------------------------------------
# 5. GovernanceAuditLog
# ---------------------------------------------------------------------------

class TestGovernanceAuditLog:
    def _make_result(self, tier="T1", blocked=False, score=0.1):
        from graqle.core.governance import GateResult
        return GateResult(
            tier=tier,
            blocked=blocked,
            requires_approval=False,
            gate_score=score,
            reason=f"{tier} test result",
            risk_level="LOW",
            impact_radius=0,
            file_path="test.py",
            threshold_at_time=0.7,
        )

    def test_append_creates_file(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        log.append(self._make_result())
        assert (tmp_path / "audit.log").exists()

    def test_append_writes_valid_jsonl(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        log.append(self._make_result("T2", score=0.5), actor="alice")
        lines = (tmp_path / "audit.log").read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tier"] == "T2"

    def test_append_fields_correct(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        log.append(
            self._make_result("T3", blocked=True, score=0.95),
            actor="mallory",
            approved_by="",
            file_path="graqle/core/graph.py",
        )
        entry = json.loads((tmp_path / "audit.log").read_text())
        required = {"timestamp", "tier", "blocked", "actor", "approved_by", "file_path", "gate_score", "reason"}
        assert required <= set(entry.keys())
        assert entry["tier"] == "T3"
        assert entry["blocked"] is True
        assert entry["actor"] == "mallory"
        assert entry["file_path"] == "graqle/core/graph.py"

    def test_multiple_appends_each_on_own_line(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        for i in range(5):
            log.append(self._make_result("T1", score=0.1 * i))
        lines = (tmp_path / "audit.log").read_text().splitlines()
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # each line must be valid JSON

    def test_file_opened_append_mode_not_truncated(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log_path = tmp_path / "audit.log"
        log = GovernanceAuditLog(path=log_path)
        log.append(self._make_result("T1"))
        first_content = log_path.read_text()

        # Second append must not truncate
        log.append(self._make_result("T2"))
        second_content = log_path.read_text()
        assert second_content.startswith(first_content.rstrip())
        assert len(second_content.splitlines()) == 2

    def test_audit_log_path_from_env_var(self, tmp_path: Path, monkeypatch) -> None:
        log_path = tmp_path / "custom_audit.log"
        monkeypatch.setenv("GRAQLE_AUDIT_LOG_PATH", str(log_path))
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog()
        log.append(self._make_result())
        assert log_path.exists()

    def test_thread_safe_concurrent_writes(self, tmp_path: Path) -> None:
        from graqle.core.governance import GovernanceAuditLog
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        errors = []

        def write_entry():
            try:
                log.append(self._make_result("T1"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_entry) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        lines = (tmp_path / "audit.log").read_text().splitlines()
        assert len(lines) == 20


# ---------------------------------------------------------------------------
# 6. GovernanceMiddleware audit wiring
# ---------------------------------------------------------------------------

class TestGovernanceMiddlewareAuditWiring:
    def _make_middleware(self, tmp_path: Path):
        from graqle.core.governance import GovernanceAuditLog, GovernanceMiddleware
        log = GovernanceAuditLog(path=tmp_path / "audit.log")
        # Use permissive policy (no file) to avoid CWD policy loading
        from graqle.core.governance_policy import GovernancePolicyConfig
        policy = GovernancePolicyConfig()  # empty rules
        return GovernanceMiddleware(audit_log=log, policy=policy), tmp_path / "audit.log"

    def _read_entries(self, log_path: Path) -> list[dict]:
        if not log_path.exists():
            return []
        return [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]

    def test_t1_decision_written_to_audit_log(self, tmp_path: Path) -> None:
        mw, log_path = self._make_middleware(tmp_path)
        mw.check(risk_level="LOW", impact_radius=0, file_path="utils.py")
        entries = self._read_entries(log_path)
        assert len(entries) >= 1
        assert entries[-1]["tier"] == "T1"

    def test_t3_blocked_written_to_audit_log(self, tmp_path: Path) -> None:
        mw, log_path = self._make_middleware(tmp_path)
        mw.check(risk_level="HIGH", impact_radius=5, file_path="core.py")
        entries = self._read_entries(log_path)
        t3_entries = [e for e in entries if e["tier"] == "T3"]
        assert t3_entries
        assert t3_entries[-1]["blocked"] is True

    def test_ts_block_written_to_audit_log(self, tmp_path: Path) -> None:
        mw, log_path = self._make_middleware(tmp_path)
        mw.check(diff="w_J = 0.7", risk_level="LOW", impact_radius=0, file_path="leak.py")
        entries = self._read_entries(log_path)
        ts_entries = [e for e in entries if e["tier"] == "TS-BLOCK"]
        assert ts_entries

    def test_audit_log_tier_field_matches_gate_result(self, tmp_path: Path) -> None:
        mw, log_path = self._make_middleware(tmp_path)
        result = mw.check(risk_level="LOW", impact_radius=0)
        entries = self._read_entries(log_path)
        assert entries[-1]["tier"] == result.tier

    def test_audit_log_actor_field_written(self, tmp_path: Path) -> None:
        mw, log_path = self._make_middleware(tmp_path)
        mw.check(risk_level="LOW", impact_radius=0, actor="ci-bot")
        entries = self._read_entries(log_path)
        assert entries[-1]["actor"] == "ci-bot"

    def test_audit_log_approved_by_field_written(self, tmp_path: Path) -> None:
        import json, os
        import graqle.core.rbac as rbac_mod
        actors = [{"actor_id": "alice", "role": "lead"}]
        with _env_ctx("GRAQLE_RBAC_ACTORS_JSON", json.dumps(actors)):
            rbac_mod._default_validator = None
            mw, log_path = self._make_middleware(tmp_path)
            mw.check(risk_level="HIGH", impact_radius=5, approved_by="alice")
            rbac_mod._default_validator = None
        entries = self._read_entries(log_path)
        t3 = [e for e in entries if e["tier"] == "T3"]
        assert t3
        assert t3[-1]["approved_by"] == "alice"


# ---------------------------------------------------------------------------
# 7. learn_callback
# ---------------------------------------------------------------------------

class TestLearnCallback:
    def _make_mw_with_callback(self):
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig
        received = []
        policy = GovernancePolicyConfig()

        def cb(payload):
            received.append(payload)

        mw = GovernanceMiddleware(
            learn_callback=cb,
            policy=policy,
            audit_log=_null_audit_log(),
        )
        return mw, received

    def test_callback_fires_for_t3_blocked(self) -> None:
        mw, received = self._make_mw_with_callback()
        mw.check(risk_level="HIGH", impact_radius=5)
        assert len(received) == 1
        assert received[0]["tier"] == "T3"
        assert received[0]["blocked"] is True

    def test_callback_fires_for_t3_approved(self) -> None:
        import json
        import graqle.core.rbac as rbac_mod
        actors = [{"actor_id": "lead-dev", "role": "lead"}]
        with _env_ctx("GRAQLE_RBAC_ACTORS_JSON", json.dumps(actors)):
            rbac_mod._default_validator = None
            mw, received = self._make_mw_with_callback()
            mw.check(risk_level="HIGH", impact_radius=5, approved_by="lead-dev")
            rbac_mod._default_validator = None
        assert any(r["tier"] == "T3" and not r["blocked"] for r in received)

    def test_callback_does_not_fire_for_t1(self) -> None:
        mw, received = self._make_mw_with_callback()
        mw.check(risk_level="LOW", impact_radius=0)
        assert not received

    def test_callback_does_not_fire_for_ts_block(self) -> None:
        mw, received = self._make_mw_with_callback()
        mw.check(diff="w_J = 0.5", risk_level="LOW", impact_radius=0)
        assert not received

    def test_callback_exception_does_not_propagate(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig

        def bad_cb(payload):
            raise RuntimeError("KG is down!")

        mw = GovernanceMiddleware(
            learn_callback=bad_cb,
            policy=GovernancePolicyConfig(),
            audit_log=_null_audit_log(),
        )
        # Must not raise
        result = mw.check(risk_level="HIGH", impact_radius=5)
        assert result.tier == "T3"

    def test_callback_receives_correct_payload_keys(self) -> None:
        mw, received = self._make_mw_with_callback()
        mw.check(risk_level="HIGH", impact_radius=5, actor="dev1")
        assert received
        payload = received[0]
        expected_keys = {"actor", "tier", "blocked", "file_path", "reason",
                         "timestamp", "gate_score", "approved_by"}
        assert expected_keys <= set(payload.keys())

    def test_callback_payload_tier_is_t3(self) -> None:
        mw, received = self._make_mw_with_callback()
        mw.check(risk_level="HIGH", impact_radius=5)
        assert received[0]["tier"] == "T3"

    def test_callback_payload_timestamp_iso8601(self) -> None:
        from datetime import datetime
        mw, received = self._make_mw_with_callback()
        mw.check(risk_level="HIGH", impact_radius=5)
        ts = received[0]["timestamp"]
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# 8. Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRunMode:
    def _make_dry_run_mw(self, policy_yaml: str | None = None):
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig
        if policy_yaml is None:
            policy_yaml = "version: '1.0'\ndry_run: true\nrules: []\nactors: []\n"
        policy = GovernancePolicyConfig._parse_yaml(policy_yaml)
        return GovernanceMiddleware(policy=policy, audit_log=_null_audit_log())

    def test_dry_run_false_does_not_affect_t3_block(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig
        policy = GovernancePolicyConfig._parse_yaml(
            "version: '1.0'\ndry_run: false\nrules: []\nactors: []\n"
        )
        mw = GovernanceMiddleware(policy=policy, audit_log=_null_audit_log())
        result = mw.check(risk_level="HIGH", impact_radius=5)
        assert result.blocked is True

    def test_dry_run_true_converts_t3_block_to_pass(self) -> None:
        mw = self._make_dry_run_mw()
        result = mw.check(risk_level="HIGH", impact_radius=5)
        assert result.blocked is False

    def test_dry_run_true_adds_dry_run_warning(self) -> None:
        mw = self._make_dry_run_mw()
        result = mw.check(risk_level="HIGH", impact_radius=5)
        assert any("DRY_RUN" in w for w in result.warnings)

    def test_dry_run_true_ts_block_still_blocked(self) -> None:
        """TS-BLOCK is unconditional — dry_run must NOT override it."""
        mw = self._make_dry_run_mw()
        result = mw.check(diff="w_J = 0.5", risk_level="LOW", impact_radius=0)
        assert result.tier == "TS-BLOCK"
        assert result.blocked is True

    def test_dry_run_true_t1_not_affected(self) -> None:
        mw = self._make_dry_run_mw()
        result = mw.check(risk_level="LOW", impact_radius=0)
        assert result.tier == "T1"
        assert result.blocked is False
        # No DRY_RUN warning for non-blocked results
        assert not any("DRY_RUN" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 9. Policy integration with middleware
# ---------------------------------------------------------------------------

class TestPolicyIntegrationWithMiddleware:
    def _make_mw_with_policy(self, policy_yaml: str):
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig
        policy = GovernancePolicyConfig._parse_yaml(policy_yaml)
        return GovernanceMiddleware(policy=policy, audit_log=_null_audit_log())

    def test_policy_elevates_file_from_t1_to_t3(self) -> None:
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors: []
    justification: "Core modules"
"""
        mw = self._make_mw_with_policy(yaml)
        # LOW risk, low radius — would normally be T1, but policy forces T3
        result = mw.check(
            risk_level="LOW",
            impact_radius=0,
            file_path="graqle/core/graph.py",
        )
        assert result.tier == "T3"
        assert result.blocked is True

    def test_policy_elevation_blocked_without_approved_by(self) -> None:
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors: []
    justification: "Core modules"
"""
        mw = self._make_mw_with_policy(yaml)
        result = mw.check(
            risk_level="LOW",
            impact_radius=0,
            file_path="graqle/core/governance.py",
        )
        assert result.tier == "T3"
        assert result.requires_approval is True

    def test_policy_approved_actor_bypasses_t3_block(self) -> None:
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors:
      - "alice"
    justification: "Core modules"
"""
        mw = self._make_mw_with_policy(yaml)
        # alice is pre-approved — no explicit approved_by needed
        result = mw.check(
            risk_level="LOW",
            impact_radius=0,
            file_path="graqle/core/graph.py",
            actor="alice",
        )
        assert result.tier == "T3"
        assert result.blocked is False

    def test_policy_test_glob_does_not_downgrade_computed_t3(self) -> None:
        """tests/** has min_tier=T1, but computed T3 must not be downgraded."""
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "tests/**"
    min_tier: "T1"
    approved_actors: []
    justification: "Test files"
"""
        mw = self._make_mw_with_policy(yaml)
        # HIGH risk — would be T3 regardless of policy
        result = mw.check(
            risk_level="HIGH",
            impact_radius=5,
            file_path="tests/test_governance.py",
        )
        assert result.tier == "T3"  # policy must NOT downgrade to T1

    def test_no_policy_file_uses_permissive_default(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("GRAQLE_POLICY_PATH", raising=False)
        monkeypatch.chdir(tmp_path)  # no governance_policy.yaml
        from graqle.core.governance import GovernanceMiddleware
        mw = GovernanceMiddleware(audit_log=_null_audit_log())
        result = mw.check(risk_level="LOW", impact_radius=0, file_path="utils.py")
        assert result.tier == "T1"  # permissive default — no elevation

    def test_policy_approved_actor_justification_from_rule(self) -> None:
        yaml = """\
version: "1.0"
dry_run: false
rules:
  - glob: "graqle/core/*.py"
    min_tier: "T3"
    approved_actors:
      - "lead-bot"
    justification: "Pre-approved lead bot"
"""
        mw = self._make_mw_with_policy(yaml)
        result = mw.check(
            risk_level="LOW",
            impact_radius=0,
            file_path="graqle/core/governance.py",
            actor="lead-bot",
        )
        assert "lead-bot" in result.reason or "policy:" in result.reason


# ---------------------------------------------------------------------------
# 10. Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_governance_policy_config_importable_from_governance_module(self) -> None:
        from graqle.core.governance import GovernancePolicyConfig
        assert GovernancePolicyConfig is not None

    def test_policy_rule_importable_from_governance_module(self) -> None:
        from graqle.core.governance import PolicyRule
        assert PolicyRule is not None

    def test_governance_audit_log_importable_from_governance_module(self) -> None:
        from graqle.core.governance import GovernanceAuditLog
        assert GovernanceAuditLog is not None

    def test_inline_actor_importable_from_governance_module(self) -> None:
        from graqle.core.governance import InlineActor
        assert InlineActor is not None

    def test_middleware_init_with_no_args_still_works(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("GRAQLE_POLICY_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        from graqle.core.governance import GovernanceMiddleware
        mw = GovernanceMiddleware()
        assert mw is not None

    def test_middleware_check_signature_unchanged(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        from graqle.core.governance_policy import GovernancePolicyConfig
        mw = GovernanceMiddleware(policy=GovernancePolicyConfig(), audit_log=_null_audit_log())
        # All original args still work
        result = mw.check(
            diff="",
            content="",
            file_path="foo.py",
            risk_level="LOW",
            impact_radius=0,
            approved_by="",
            justification="",
            action="edit",
            actor="",
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _null_audit_log():
    """Audit log that writes to /dev/null equivalent (avoids test file side effects)."""
    import tempfile
    from graqle.core.governance import GovernanceAuditLog
    # Use a unique temp file per call; not deleted — will be cleaned by OS
    return GovernanceAuditLog(path=Path(tempfile.mktemp(suffix=".log")))
