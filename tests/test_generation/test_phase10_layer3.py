"""Phase 10 Layer 3 — RBAC Actor Identity Model Tests.

Tests for graqle/core/rbac.py and governance.py RBAC integration.

Coverage:
  - Role permission matrix (who can approve what tier)
  - ActorRegistry register/get/disable
  - ActorToken sign/verify (HMAC-SHA256)
  - Token expiry rejection
  - Token spoofing rejected (wrong signature)
  - RBACValidator.can_approve per role
  - Unknown actor defaults to developer (T1 only)
  - Disabled actor rejected
  - Governance T3 with unregistered actor blocked
  - Governance T3 with registered lead approved
  - CI pipeline actor blocked from T2/T3
  - SOC2 CC6.2: approval authority enforced

Compliance:
  SOC2  CC6.2 — Access control enforced at approval time
  ISO27001 A.9.1.1 — Access control policy: roles define tier authority
  ISO27001 A.9.2.1 — Registration enforced: unknown actors default to developer
"""
from __future__ import annotations

import time
import pytest


# ---------------------------------------------------------------------------
# 1. Role permission matrix
# ---------------------------------------------------------------------------

class TestRolePermissionMatrix:
    """Verify ROLE_PERMISSIONS table is correct."""

    def test_readonly_cannot_approve_anything(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert len(ROLE_PERMISSIONS["readonly"]) == 0

    def test_developer_can_only_approve_t1(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert ROLE_PERMISSIONS["developer"] == frozenset({"T1"})

    def test_ci_pipeline_can_only_approve_t1(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert ROLE_PERMISSIONS["ci_pipeline"] == frozenset({"T1"})

    def test_senior_can_approve_t1_and_t2(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert "T1" in ROLE_PERMISSIONS["senior"]
        assert "T2" in ROLE_PERMISSIONS["senior"]
        assert "T3" not in ROLE_PERMISSIONS["senior"]

    def test_lead_can_approve_all_tiers(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert "T1" in ROLE_PERMISSIONS["lead"]
        assert "T2" in ROLE_PERMISSIONS["lead"]
        assert "T3" in ROLE_PERMISSIONS["lead"]

    def test_admin_can_approve_all_tiers(self) -> None:
        from graqle.core.rbac import ROLE_PERMISSIONS
        assert "T3" in ROLE_PERMISSIONS["admin"]

    def test_ts_block_cannot_be_approved_by_any_role(self) -> None:
        """TS-BLOCK is unconditional — no role can approve it."""
        from graqle.core.rbac import ROLE_PERMISSIONS
        for role, perms in ROLE_PERMISSIONS.items():
            assert "TS-BLOCK" not in perms, f"Role '{role}' cannot approve TS-BLOCK"


# ---------------------------------------------------------------------------
# 2. ActorRegistry
# ---------------------------------------------------------------------------

class TestActorRegistry:
    """ActorRegistry register, get, disable."""

    def test_register_and_retrieve(self) -> None:
        from graqle.core.rbac import ActorRegistry
        reg = ActorRegistry()
        actor = reg.register("alice", "lead")
        assert actor.actor_id == "alice"
        assert actor.role == "lead"
        assert reg.get("alice") is actor

    def test_register_unknown_role_raises(self) -> None:
        from graqle.core.rbac import ActorRegistry
        reg = ActorRegistry()
        with pytest.raises(ValueError, match="Unknown role"):
            reg.register("bob", "superuser")

    def test_get_unknown_actor_returns_none(self) -> None:
        from graqle.core.rbac import ActorRegistry
        reg = ActorRegistry()
        assert reg.get("nonexistent") is None

    def test_disable_actor(self) -> None:
        from graqle.core.rbac import ActorRegistry
        reg = ActorRegistry()
        reg.register("eve", "senior")
        reg.disable("eve")
        actor = reg.get("eve")
        assert actor is not None
        assert actor.disabled is True

    def test_disabled_actor_cannot_approve(self) -> None:
        from graqle.core.rbac import ActorRegistry, Actor
        reg = ActorRegistry()
        reg.register("mallory", "lead")
        reg.disable("mallory")
        actor = reg.get("mallory")
        assert not actor.can_approve("T3")
        assert not actor.can_approve("T2")
        assert not actor.can_approve("T1")

    def test_list_actors(self) -> None:
        from graqle.core.rbac import ActorRegistry
        reg = ActorRegistry()
        reg.register("alice", "lead")
        reg.register("bob", "senior")
        actors = reg.list_actors()
        assert len([a for a in actors if a["actor_id"] in ("alice", "bob")]) == 2


# ---------------------------------------------------------------------------
# 3. ActorToken sign and verify
# ---------------------------------------------------------------------------

class TestActorToken:
    """HMAC-SHA256 token sign/verify."""

    def test_issue_and_verify(self) -> None:
        from graqle.core.rbac import ActorToken
        import secrets
        key = secrets.token_bytes(32)
        token, encoded = ActorToken.issue("alice", "lead", signing_key=key)
        assert encoded
        verified, err = ActorToken.verify(encoded, signing_key=key)
        assert verified is not None
        assert err == ""
        assert verified.actor_id == "alice"
        assert verified.role == "lead"

    def test_wrong_key_rejected(self) -> None:
        from graqle.core.rbac import ActorToken
        import secrets
        key1 = secrets.token_bytes(32)
        key2 = secrets.token_bytes(32)
        _, encoded = ActorToken.issue("alice", "lead", signing_key=key1)
        token, err = ActorToken.verify(encoded, signing_key=key2)
        assert token is None
        assert "signature" in err.lower() or "invalid" in err.lower()

    def test_tampered_payload_rejected(self) -> None:
        from graqle.core.rbac import ActorToken
        import secrets, base64
        key = secrets.token_bytes(32)
        _, encoded = ActorToken.issue("alice", "lead", signing_key=key)
        # Tamper: replace payload with modified version
        parts = encoded.split(".")
        original = base64.b64decode(parts[0]).decode()
        tampered = original.replace('"role":"lead"', '"role":"admin"')
        tampered_encoded = base64.b64encode(tampered.encode()).decode() + "." + parts[1]
        token, err = ActorToken.verify(tampered_encoded, signing_key=key)
        assert token is None
        assert "signature" in err.lower() or "invalid" in err.lower()

    def test_expired_token_rejected(self) -> None:
        from graqle.core.rbac import ActorToken
        import secrets
        key = secrets.token_bytes(32)
        # Issue token with -1 TTL (already expired)
        _, encoded = ActorToken.issue("alice", "lead", signing_key=key, ttl_seconds=-1)
        token, err = ActorToken.verify(encoded, signing_key=key)
        assert token is None
        assert "expired" in err.lower()

    def test_malformed_token_rejected(self) -> None:
        from graqle.core.rbac import ActorToken
        token, err = ActorToken.verify("not-a-valid-token-at-all")
        assert token is None
        assert err != ""

    def test_token_id_unique(self) -> None:
        from graqle.core.rbac import ActorToken
        import secrets
        key = secrets.token_bytes(32)
        t1, _ = ActorToken.issue("alice", "lead", signing_key=key)
        t2, _ = ActorToken.issue("alice", "lead", signing_key=key)
        assert t1.token_id != t2.token_id


# ---------------------------------------------------------------------------
# 4. RBACValidator.can_approve
# ---------------------------------------------------------------------------

class TestRBACValidator:
    """Validator checks role permissions correctly."""

    def _make_validator(self, actors: dict[str, str]):
        """Create validator with given {actor_id: role} mapping."""
        from graqle.core.rbac import ActorRegistry, RBACValidator
        reg = ActorRegistry()
        for actor_id, role in actors.items():
            reg.register(actor_id, role)
        return RBACValidator(registry=reg)

    def test_lead_can_approve_t3(self) -> None:
        v = self._make_validator({"alice": "lead"})
        ok, reason = v.can_approve("alice", "T3")
        assert ok, reason

    def test_senior_cannot_approve_t3(self) -> None:
        v = self._make_validator({"bob": "senior"})
        ok, reason = v.can_approve("bob", "T3")
        assert not ok
        assert "T3" in reason or "authority" in reason.lower()

    def test_ci_pipeline_cannot_approve_t2(self) -> None:
        v = self._make_validator({"ci-bot": "ci_pipeline"})
        ok, reason = v.can_approve("ci-bot", "T2")
        assert not ok

    def test_ci_pipeline_can_approve_t1(self) -> None:
        v = self._make_validator({"ci-bot": "ci_pipeline"})
        ok, _ = v.can_approve("ci-bot", "T1")
        assert ok

    def test_unknown_actor_defaults_to_developer_t1_only(self) -> None:
        v = self._make_validator({})
        ok_t1, _ = v.can_approve("unknown-actor", "T1")
        ok_t2, _ = v.can_approve("unknown-actor", "T2")
        ok_t3, _ = v.can_approve("unknown-actor", "T3")
        assert ok_t1
        assert not ok_t2
        assert not ok_t3

    def test_empty_actor_id_rejected(self) -> None:
        v = self._make_validator({})
        ok, reason = v.can_approve("", "T2")
        assert not ok
        assert "actor_id" in reason.lower() or "no actor" in reason.lower()

    def test_disabled_actor_rejected_for_all_tiers(self) -> None:
        from graqle.core.rbac import ActorRegistry, RBACValidator
        reg = ActorRegistry()
        reg.register("mallory", "admin")
        reg.disable("mallory")
        v = RBACValidator(registry=reg)
        for tier in ("T1", "T2", "T3"):
            ok, _ = v.can_approve("mallory", tier)
            assert not ok, f"Disabled actor should not approve {tier}"

    def test_admin_can_approve_all(self) -> None:
        v = self._make_validator({"admin-user": "admin"})
        for tier in ("T1", "T2", "T3"):
            ok, reason = v.can_approve("admin-user", tier)
            assert ok, f"Admin should approve {tier}: {reason}"

    def test_readonly_cannot_approve_any(self) -> None:
        v = self._make_validator({"viewer": "readonly"})
        for tier in ("T1", "T2", "T3"):
            ok, _ = v.can_approve("viewer", tier)
            assert not ok, f"Readonly should not approve {tier}"


# ---------------------------------------------------------------------------
# 5. Governance T3 RBAC integration
# ---------------------------------------------------------------------------

class TestGovernanceRBACIntegration:
    """Verify governance gate enforces RBAC for T3 approvals."""

    def test_t3_with_unregistered_actor_blocked(self) -> None:
        """Unknown actor providing approved_by for T3 should be blocked."""
        from graqle.core.governance import GovernanceMiddleware
        gm = GovernanceMiddleware()
        result = gm.check(
            file_path="critical.py",
            risk_level="HIGH",
            impact_radius=10,
            approved_by="unknown-person-xyz",
        )
        # T3 requires registered actor with lead/admin role
        # unknown-person-xyz not registered → default developer → T3 rejected
        assert result.blocked is True
        assert result.tier == "T3"
        assert "RBAC" in result.reason

    def test_t3_with_no_approval_blocked(self) -> None:
        """T3 without approved_by is always blocked."""
        from graqle.core.governance import GovernanceMiddleware
        gm = GovernanceMiddleware()
        result = gm.check(
            file_path="core.py",
            risk_level="HIGH",
            impact_radius=10,
        )
        assert result.blocked is True
        assert result.tier == "T3"
        assert result.requires_approval is True

    def test_t1_unaffected_by_rbac(self) -> None:
        """T1 (low risk, low radius) passes without any RBAC check."""
        from graqle.core.governance import GovernanceMiddleware
        gm = GovernanceMiddleware()
        result = gm.check(
            diff="+def greet(): return 'hello'",
            file_path="utils.py",
            risk_level="LOW",
            impact_radius=0,
        )
        assert result.tier == "T1"
        assert not result.blocked

    def test_ci_pipeline_actor_gets_rbac_advisory_for_t2(self) -> None:
        """CI pipeline actor on T2 gets RBAC advisory warning (not blocked)."""
        import os
        import json
        from graqle.core.governance import GovernanceMiddleware

        # Register ci-bot as ci_pipeline role
        actors_json = json.dumps([{"actor_id": "ci-bot", "role": "ci_pipeline"}])
        with _env_ctx("GRAQLE_RBAC_ACTORS_JSON", actors_json):
            # Reload default validator
            import graqle.core.rbac as rbac_mod
            rbac_mod._default_validator = None

            gm = GovernanceMiddleware()
            result = gm.check(
                file_path="module.py",
                risk_level="MEDIUM",
                impact_radius=4,
                actor="ci-bot",
            )
            # T2 is not blocked (advisory only)
            assert not result.blocked
            # Should have RBAC advisory in warnings
            has_rbac_warn = any("RBAC" in w for w in result.warnings)
            assert has_rbac_warn, f"Expected RBAC advisory warning, got: {result.warnings}"

            # Reset
            rbac_mod._default_validator = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from contextlib import contextmanager
import os


@contextmanager
def _env_ctx(key: str, value: str):
    """Temporarily set an environment variable."""
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
