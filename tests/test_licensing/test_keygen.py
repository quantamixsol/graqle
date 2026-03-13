"""Tests for graqle.licensing.keygen — key generation CLI utility."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from graqle.licensing.keygen import generate_license_key, main
from graqle.licensing.manager import LicenseManager, LicenseTier


# ---------------------------------------------------------------------------
# generate_license_key
# ---------------------------------------------------------------------------

class TestGenerateLicenseKey:
    def test_perpetual_pro_key(self):
        key = generate_license_key("pro", "Acme Corp", "admin@acme.com")
        assert isinstance(key, str)
        assert "." in key
        # Verify the key is valid
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.PRO
        assert lic.holder == "Acme Corp"
        assert lic.email == "admin@acme.com"
        assert lic.expires_at is None
        assert lic.is_valid is True

    def test_time_limited_team_key(self):
        key = generate_license_key("team", "Test Org", "org@test.com", duration_days=365)
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.TEAM
        assert lic.expires_at is not None
        assert lic.is_valid is True
        # Should expire roughly 365 days from now
        delta = lic.expires_at - datetime.now(timezone.utc)
        assert 364 <= delta.days <= 366

    def test_enterprise_key(self):
        key = generate_license_key("enterprise", "BigCo", "cto@bigco.com")
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.ENTERPRISE

    def test_free_key(self):
        key = generate_license_key("free", "FreeUser", "free@example.com")
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.FREE

    def test_short_duration(self):
        key = generate_license_key("pro", "Test", "t@t.com", duration_days=1)
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.is_valid is True  # just created, not expired yet

    def test_zero_duration(self):
        """Zero days should produce a key that expires very soon."""
        key = generate_license_key("pro", "Test", "t@t.com", duration_days=0)
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        # It should still parse, even if it's about to expire


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------

class TestKeygenMain:
    def test_usage_on_insufficient_args(self, capsys):
        with patch.object(sys, "argv", ["keygen"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_usage_on_two_args(self, capsys):
        with patch.object(sys, "argv", ["keygen", "pro"]):
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_generates_key_with_three_args(self, capsys):
        with patch.object(sys, "argv", ["keygen", "pro", "Test User", "test@test.com"]):
            main()
        captured = capsys.readouterr()
        assert "License Key" in captured.out
        assert "pro" in captured.out
        # Extract the key from output and verify
        lines = captured.out.strip().split("\n")
        key_line = lines[-1].strip()
        assert "." in key_line

    def test_generates_key_with_duration(self, capsys):
        with patch.object(sys, "argv", ["keygen", "team", "Org", "org@org.com", "90"]):
            main()
        captured = capsys.readouterr()
        assert "License Key" in captured.out
        assert "team" in captured.out

    def test_generated_key_verifies(self, capsys):
        with patch.object(sys, "argv", ["keygen", "enterprise", "Corp", "c@c.com"]):
            main()
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        key = lines[-1].strip()
        mgr = LicenseManager.__new__(LicenseManager)
        mgr._license = None
        lic = mgr._verify_key(key)
        assert lic is not None
        assert lic.tier == LicenseTier.ENTERPRISE
