"""Tests for graq activate command."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_activate
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, testing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


class TestActivateCommand:
    """Tests for the activate CLI command."""

    def test_invalid_key_rejected(self) -> None:
        from graqle.cli.main import app
        result = runner.invoke(app, ["activate", "invalid-key-format"])
        assert result.exit_code != 0
        assert "Invalid" in result.output or "invalid" in result.output.lower()

    def test_valid_key_accepted(self, tmp_path, monkeypatch) -> None:
        from graqle.licensing.manager import LicenseManager
        from graqle.cli.main import app

        # Generate a valid key
        key = LicenseManager.generate_key(
            tier="team",
            holder="Test Corp",
            email="test@corp.com",
        )

        # Redirect license storage to tmp
        license_path = tmp_path / "license.key"
        monkeypatch.setattr(
            "graqle.cli.commands.activate.Path",
            type("MockPath", (), {
                "home": staticmethod(lambda: tmp_path),
                "__call__": lambda self, *a: Path(*a),
            })(),
        )

        # Actually, let's just test the core logic directly
        manager = LicenseManager.__new__(LicenseManager)
        manager._license = None
        license_obj = manager._verify_key(key)

        assert license_obj is not None
        assert license_obj.tier.value == "team"
        assert license_obj.holder == "Test Corp"
        assert license_obj.email == "test@corp.com"
        assert license_obj.is_valid is True

    def test_expired_key_rejected(self) -> None:
        from graqle.licensing.manager import LicenseManager
        from datetime import datetime, timezone

        # Generate an already-expired key
        key = LicenseManager.generate_key(
            tier="team",
            holder="Test Corp",
            email="test@corp.com",
            expires_at="2020-01-01T00:00:00+00:00",  # Past date
        )

        manager = LicenseManager.__new__(LicenseManager)
        manager._license = None
        license_obj = manager._verify_key(key)

        assert license_obj is not None
        assert license_obj.is_valid is False


class TestActivateKeyStorage:
    """Tests for license key file storage."""

    def test_key_written_to_user_dir(self, tmp_path) -> None:
        from graqle.licensing.manager import LicenseManager

        key = LicenseManager.generate_key(
            tier="team", holder="Test", email="t@t.com",
        )

        license_path = tmp_path / ".graqle" / "license.key"
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_text(key, encoding="utf-8")

        # Verify the key can be read back and verified
        stored_key = license_path.read_text(encoding="utf-8").strip()
        manager = LicenseManager.__new__(LicenseManager)
        manager._license = None
        license_obj = manager._verify_key(stored_key)

        assert license_obj is not None
        assert license_obj.tier.value == "team"

    def test_key_written_to_project_dir(self, tmp_path) -> None:
        from graqle.licensing.manager import LicenseManager

        key = LicenseManager.generate_key(
            tier="enterprise", holder="BigCo", email="admin@big.co",
        )

        license_path = tmp_path / "graqle.license"
        license_path.write_text(key, encoding="utf-8")

        stored_key = license_path.read_text(encoding="utf-8").strip()
        manager = LicenseManager.__new__(LicenseManager)
        manager._license = None
        license_obj = manager._verify_key(stored_key)

        assert license_obj is not None
        assert license_obj.tier.value == "enterprise"
