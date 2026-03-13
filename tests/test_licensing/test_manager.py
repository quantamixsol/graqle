"""Tests for graqle.licensing.manager — tiers, features, decorators, LicenseManager."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.licensing.manager import (
    TIER_FEATURES,
    License,
    LicenseError,
    LicenseManager,
    LicenseTier,
    _TIER_ORDER,
    _get_manager,
    check_license,
    has_feature,
    require_license,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(
    tier: str = "pro",
    holder: str = "Test Co",
    email: str = "test@example.com",
    expires_at: str | None = None,
    features: list[str] | None = None,
) -> dict:
    return {
        "tier": tier,
        "holder": holder,
        "email": email,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "features": features or [],
    }


def _sign_payload(payload: dict) -> str:
    """Create a valid signed key from a payload dict."""
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    signature = hmac.new(
        LicenseManager._VERIFICATION_KEY,
        payload_bytes,
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{payload_b64}.{sig_b64}"


def _generate_key(tier: str = "pro", **kwargs) -> str:
    return _sign_payload(_make_payload(tier=tier, **kwargs))


# ---------------------------------------------------------------------------
# LicenseTier
# ---------------------------------------------------------------------------

class TestLicenseTier:
    def test_tier_values(self):
        assert LicenseTier.FREE.value == "free"
        assert LicenseTier.PRO.value == "pro"
        assert LicenseTier.TEAM.value == "team"
        assert LicenseTier.ENTERPRISE.value == "enterprise"

    def test_tier_is_str_enum(self):
        assert isinstance(LicenseTier.FREE, str)
        assert LicenseTier.PRO == "pro"

    def test_tier_order(self):
        assert _TIER_ORDER == [
            LicenseTier.FREE,
            LicenseTier.PRO,
            LicenseTier.TEAM,
            LicenseTier.ENTERPRISE,
        ]


# ---------------------------------------------------------------------------
# TIER_FEATURES
# ---------------------------------------------------------------------------

class TestTierFeatures:
    def test_free_tier_has_core_features(self):
        free = TIER_FEATURES[LicenseTier.FREE]
        assert "pcst_activation" in free
        assert "master_observer" in free
        assert "mcp_context" in free
        assert "workflow_engine" in free

    def test_free_tier_has_advanced_features_since_075(self):
        """All solo developer features were ungated in v0.7.5."""
        free = TIER_FEATURES[LicenseTier.FREE]
        assert "semantic_shacl_gate" in free
        assert "mcp_preflight" in free
        assert "tamr_connector" in free
        assert "session_analytics" in free
        assert "debate_protocol" in free
        assert "ontology_generator" in free
        assert "mcp_learn" in free

    def test_pro_tier_is_empty(self):
        """PRO tier reserved for future team-adjacent features (v0.7.5)."""
        pro = TIER_FEATURES[LicenseTier.PRO]
        assert len(pro) == 0

    def test_team_tier_features(self):
        team = TIER_FEATURES[LicenseTier.TEAM]
        assert "shared_kg_sync" in team
        assert "team_analytics" in team

    def test_enterprise_tier_features(self):
        ent = TIER_FEATURES[LicenseTier.ENTERPRISE]
        assert "private_deployment" in ent
        assert "audit_trail" in ent

    def test_tiers_have_no_overlap(self):
        """Features introduced at each tier should be unique to that tier."""
        all_sets = list(TIER_FEATURES.values())
        for i, s1 in enumerate(all_sets):
            for j, s2 in enumerate(all_sets):
                if i != j:
                    assert s1.isdisjoint(s2), (
                        f"Overlap between tier {list(TIER_FEATURES.keys())[i]} "
                        f"and {list(TIER_FEATURES.keys())[j]}: {s1 & s2}"
                    )


# ---------------------------------------------------------------------------
# License dataclass
# ---------------------------------------------------------------------------

class TestLicense:
    def test_valid_perpetual(self):
        lic = License(
            tier=LicenseTier.PRO,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
            expires_at=None,
        )
        assert lic.is_valid is True

    def test_valid_not_expired(self):
        lic = License(
            tier=LicenseTier.PRO,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert lic.is_valid is True

    def test_expired(self):
        lic = License(
            tier=LicenseTier.PRO,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc) - timedelta(days=60),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert lic.is_valid is False

    def test_all_features_free(self):
        lic = License(
            tier=LicenseTier.FREE,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
        )
        features = lic.all_features
        assert features == TIER_FEATURES[LicenseTier.FREE]

    def test_all_features_pro_is_cumulative(self):
        lic = License(
            tier=LicenseTier.PRO,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
        )
        features = lic.all_features
        # PRO should include all FREE + PRO features
        assert TIER_FEATURES[LicenseTier.FREE].issubset(features)
        assert TIER_FEATURES[LicenseTier.PRO].issubset(features)
        # But not TEAM or ENTERPRISE
        assert not TIER_FEATURES[LicenseTier.TEAM].issubset(features)

    def test_all_features_enterprise_includes_all(self):
        lic = License(
            tier=LicenseTier.ENTERPRISE,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
        )
        features = lic.all_features
        for tier in LicenseTier:
            assert TIER_FEATURES[tier].issubset(features)

    def test_all_features_with_extras(self):
        lic = License(
            tier=LicenseTier.FREE,
            holder="Test",
            email="test@example.com",
            issued_at=datetime.now(timezone.utc),
            features={"custom_addon"},
        )
        features = lic.all_features
        assert "custom_addon" in features
        assert "pcst_activation" in features


# ---------------------------------------------------------------------------
# LicenseManager._verify_key
# ---------------------------------------------------------------------------

def _make_clean_manager() -> LicenseManager:
    """Create a LicenseManager with no loaded license (bypasses file/env loading)."""
    mgr = LicenseManager.__new__(LicenseManager)
    mgr._license = None
    return mgr


def _make_manager_safe(**env_overrides) -> LicenseManager:
    """Create a LicenseManager safely (patches Path.home to avoid RuntimeError on CI)."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    with patch.dict(os.environ, env_overrides, clear=True):
        with patch.object(Path, "home", return_value=tmp):
            return LicenseManager()


class TestVerifyKey:
    def setup_method(self):
        self.mgr = _make_clean_manager()

    def test_valid_key(self):
        key = _generate_key("pro")
        lic = self.mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.PRO
        assert lic.holder == "Test Co"
        assert lic.email == "test@example.com"

    def test_invalid_signature(self):
        key = _generate_key("pro")
        # Tamper with the signature
        parts = key.split(".")
        tampered = parts[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        lic = self.mgr._verify_key(tampered)
        assert lic is None

    def test_malformed_key_no_dot(self):
        lic = self.mgr._verify_key("no-dot-here")
        assert lic is None

    def test_malformed_key_too_many_dots(self):
        lic = self.mgr._verify_key("a.b.c")
        assert lic is None

    def test_garbage_input(self):
        lic = self.mgr._verify_key("!!!not_base64!!!")
        assert lic is None

    def test_empty_string(self):
        lic = self.mgr._verify_key("")
        assert lic is None

    def test_expired_key(self):
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        key = _generate_key("pro", expires_at=expired)
        lic = self.mgr._verify_key(key)
        # Key is successfully verified (parsing succeeds), but is_valid is False
        assert lic is not None
        assert lic.is_valid is False

    def test_perpetual_key(self):
        key = _generate_key("pro", expires_at=None)
        lic = self.mgr._verify_key(key)
        assert lic is not None
        assert lic.expires_at is None
        assert lic.is_valid is True

    def test_extra_features_in_key(self):
        key = _generate_key("free", features=["beta_feature"])
        lic = self.mgr._verify_key(key)
        assert lic is not None
        assert "beta_feature" in lic.features


# ---------------------------------------------------------------------------
# LicenseManager loading
# ---------------------------------------------------------------------------

class TestLicenseManagerLoading:
    def test_no_license_defaults_to_free(self):
        mgr = _make_manager_safe()
        assert mgr.current_tier == LicenseTier.FREE
        assert mgr.license is None

    def test_load_from_env_var(self):
        key = _generate_key("team")
        mgr = _make_manager_safe(COGNIGRAPH_LICENSE_KEY=key)
        assert mgr.current_tier == LicenseTier.TEAM
        assert mgr.license is not None
        assert mgr.license.tier == LicenseTier.TEAM

    def test_load_from_user_file(self, tmp_path):
        key = _generate_key("enterprise")
        license_dir = tmp_path / ".graqle"
        license_dir.mkdir()
        license_file = license_dir / "license.key"
        license_file.write_text(key, encoding="utf-8")

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(Path, "home", return_value=tmp_path):
                mgr = LicenseManager()
        assert mgr.current_tier == LicenseTier.ENTERPRISE

    def test_invalid_env_key_falls_to_free(self):
        mgr = _make_manager_safe(COGNIGRAPH_LICENSE_KEY="invalid.key")
        assert mgr.current_tier == LicenseTier.FREE

    def test_expired_key_falls_to_free(self):
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        key = _generate_key("pro", expires_at=expired)
        mgr = _make_manager_safe(COGNIGRAPH_LICENSE_KEY=key)
        # Key verified but expired => current_tier returns FREE
        assert mgr.current_tier == LicenseTier.FREE


# ---------------------------------------------------------------------------
# LicenseManager.has_feature / check_feature
# ---------------------------------------------------------------------------

class TestHasFeature:
    def test_free_features_always_available(self):
        mgr = _make_manager_safe()
        assert mgr.has_feature("pcst_activation") is True
        assert mgr.has_feature("mcp_context") is True
        assert mgr.has_feature("workflow_engine") is True

    def test_advanced_features_free_since_075(self):
        """All solo developer features are free since v0.7.5 — no license needed."""
        mgr = _make_manager_safe()
        assert mgr.has_feature("semantic_shacl_gate") is True
        assert mgr.has_feature("mcp_preflight") is True
        assert mgr.has_feature("debate_protocol") is True
        assert mgr.has_feature("ontology_generator") is True

    def test_pro_license_still_works(self):
        key = _generate_key("pro")
        mgr = _make_manager_safe(COGNIGRAPH_LICENSE_KEY=key)
        assert mgr.has_feature("semantic_shacl_gate") is True
        assert mgr.has_feature("mcp_preflight") is True
        # Free features still work
        assert mgr.has_feature("pcst_activation") is True

    def test_team_feature_with_pro_license(self):
        key = _generate_key("pro")
        mgr = _make_manager_safe(COGNIGRAPH_LICENSE_KEY=key)
        assert mgr.has_feature("shared_kg_sync") is False

    def test_nonexistent_feature(self):
        mgr = _make_manager_safe()
        assert mgr.has_feature("totally_fake_feature") is False

    def test_check_feature_raises_on_missing(self):
        mgr = _make_manager_safe()
        with pytest.raises(LicenseError, match="requires Graqle Team"):
            mgr.check_feature("shared_kg_sync")

    def test_check_feature_ok_for_free(self):
        mgr = _make_manager_safe()
        mgr.check_feature("pcst_activation")

    def test_check_feature_error_includes_tier_name(self):
        mgr = _make_manager_safe()
        with pytest.raises(LicenseError, match="Team"):
            mgr.check_feature("shared_kg_sync")

    def test_check_feature_error_includes_upgrade_url(self):
        mgr = _make_manager_safe()
        with pytest.raises(LicenseError, match="graqle.dev/pricing"):
            mgr.check_feature("private_deployment")


# ---------------------------------------------------------------------------
# LicenseManager.generate_key (static method)
# ---------------------------------------------------------------------------

class TestGenerateKey:
    def test_roundtrip(self):
        key = LicenseManager.generate_key(
            tier="pro",
            holder="Roundtrip Corp",
            email="rt@example.com",
        )
        mgr = _make_clean_manager()
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.PRO
        assert lic.holder == "Roundtrip Corp"
        assert lic.email == "rt@example.com"

    def test_with_expiry(self):
        expires = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        key = LicenseManager.generate_key(
            tier="team",
            holder="Test",
            email="test@test.com",
            expires_at=expires,
        )
        mgr = _make_clean_manager()
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.expires_at is not None
        assert lic.is_valid is True

    def test_with_extra_features(self):
        key = LicenseManager.generate_key(
            tier="free",
            holder="Test",
            email="test@test.com",
            extra_features=["beta_x", "beta_y"],
        )
        mgr = _make_clean_manager()
        lic = mgr._verify_key(key)
        assert lic is not None
        assert "beta_x" in lic.features
        assert "beta_y" in lic.features


# ---------------------------------------------------------------------------
# require_license decorator
# ---------------------------------------------------------------------------

class TestRequireLicenseDecorator:
    def _swap_manager(self, mgr):
        """Context manager to temporarily swap the module-level LicenseManager."""
        import graqle.licensing.manager as mod
        old = mod._manager
        mod._manager = mgr
        return old

    def test_sync_function_passes_with_free_feature(self):
        @require_license("pcst_activation")
        def my_func():
            return "ok"

        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            assert my_func() == "ok"
        finally:
            mod._manager = old

    def test_sync_function_blocked_without_license(self):
        @require_license("shared_kg_sync")
        def my_func():
            return "ok"

        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            with pytest.raises(LicenseError):
                my_func()
        finally:
            mod._manager = old

    @pytest.mark.asyncio
    async def test_async_function_passes_with_free_feature(self):
        @require_license("mcp_context")
        async def my_async():
            return "async_ok"

        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            result = await my_async()
            assert result == "async_ok"
        finally:
            mod._manager = old

    @pytest.mark.asyncio
    async def test_async_function_blocked_without_license(self):
        @require_license("shared_kg_sync")
        async def my_async():
            return "should_not_reach"

        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            with pytest.raises(LicenseError):
                await my_async()
        finally:
            mod._manager = old

    def test_decorator_preserves_function_name(self):
        @require_license("pcst_activation")
        def my_named_func():
            """My docstring."""
            pass

        assert my_named_func.__name__ == "my_named_func"
        assert my_named_func.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestModuleLevelAPI:
    def test_has_feature_free(self):
        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            assert has_feature("pcst_activation") is True
            assert has_feature("mcp_preflight") is True  # ungated in v0.7.5
            assert has_feature("shared_kg_sync") is False  # TEAM tier still gated
        finally:
            mod._manager = old

    def test_check_license_raises(self):
        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = _make_manager_safe()
            with pytest.raises(LicenseError):
                check_license("private_deployment")
        finally:
            mod._manager = old

    def test_get_manager_singleton(self):
        import graqle.licensing.manager as mod
        old = mod._manager
        try:
            mod._manager = None
            import tempfile
            tmp = Path(tempfile.mkdtemp())
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(Path, "home", return_value=tmp):
                    m1 = _get_manager()
                    m2 = _get_manager()
            assert m1 is m2
        finally:
            mod._manager = old


# ---------------------------------------------------------------------------
# LicenseError
# ---------------------------------------------------------------------------

class TestLicenseError:
    def test_is_exception(self):
        assert issubclass(LicenseError, Exception)

    def test_message(self):
        err = LicenseError("requires Pro")
        assert str(err) == "requires Pro"
