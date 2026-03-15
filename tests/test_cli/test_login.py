"""Tests for graq login / logout commands."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_login
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, mock, pytest, credentials
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from graqle.cloud.credentials import CloudCredentials


class TestLoginCommand:
    def test_status_when_not_connected(self, tmp_path, monkeypatch):
        """graq login --status when not connected."""
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "nonexistent.json",
        )
        from graqle.cli.commands.login import login_command
        # Should not raise
        login_command(api_key="", email="", status=True)

    def test_status_when_connected(self, tmp_path, monkeypatch):
        """graq login --status when connected."""
        import json
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({
            "api_key": "grq_test123",
            "email": "user@test.com",
            "plan": "pro",
            "cloud_url": "https://api.graqle.com",
            "connected": True,
        }))
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE", creds_file
        )
        from graqle.cli.commands.login import login_command
        login_command(api_key="", email="", status=True)

    def test_login_with_valid_key(self, tmp_path, monkeypatch):
        """graq login --api-key grq_xxx saves credentials."""
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "credentials.json",
        )
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_DIR", tmp_path
        )
        from graqle.cli.commands.login import login_command
        login_command(api_key="grq_testkey123", email="me@test.com", status=False)

        from graqle.cloud.credentials import load_credentials
        creds = load_credentials()
        assert creds.api_key == "grq_testkey123"
        assert creds.email == "me@test.com"
        assert creds.connected

    def test_login_rejects_invalid_key(self, tmp_path, monkeypatch):
        """graq login rejects keys that don't start with grq_."""
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "credentials.json",
        )
        from graqle.cli.commands.login import login_command
        with pytest.raises((SystemExit, Exception)):
            login_command(api_key="invalid_key", email="", status=False)

    def test_logout_clears_credentials(self, tmp_path, monkeypatch):
        """graq logout removes stored credentials."""
        import json
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({
            "api_key": "grq_test", "connected": True,
            "email": "", "plan": "free",
            "cloud_url": "https://api.graqle.com",
        }))
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE", creds_file
        )
        from graqle.cli.commands.login import logout_command
        logout_command()
        assert not creds_file.exists()

    def test_logout_when_not_connected(self, tmp_path, monkeypatch):
        """graq logout when already disconnected."""
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "nonexistent.json",
        )
        from graqle.cli.commands.login import logout_command
        # Should not raise
        logout_command()
