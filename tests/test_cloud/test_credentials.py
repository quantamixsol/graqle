"""Tests for Graqle Cloud credentials manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.cloud.credentials import (
    CloudCredentials,
    clear_credentials,
    get_cloud_status,
    load_credentials,
    save_credentials,
)


class TestCloudCredentials:
    def test_default_credentials_not_authenticated(self):
        creds = CloudCredentials()
        assert not creds.is_authenticated
        assert creds.plan == "free"
        assert creds.email == ""

    def test_authenticated_with_api_key(self):
        creds = CloudCredentials(api_key="grq_test123", connected=True)
        assert creds.is_authenticated

    def test_not_authenticated_without_connected_flag(self):
        creds = CloudCredentials(api_key="grq_test123", connected=False)
        assert not creds.is_authenticated

    def test_roundtrip_dict(self):
        creds = CloudCredentials(
            api_key="grq_abc", email="test@example.com",
            plan="pro", connected=True,
        )
        data = creds.to_dict()
        restored = CloudCredentials.from_dict(data)
        assert restored.api_key == "grq_abc"
        assert restored.email == "test@example.com"
        assert restored.plan == "pro"
        assert restored.is_authenticated

    def test_save_and_load(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE", creds_file
        )
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_DIR", tmp_path
        )

        creds = CloudCredentials(
            api_key="grq_test", email="user@test.com",
            plan="team", connected=True,
        )
        save_credentials(creds)
        assert creds_file.exists()

        loaded = load_credentials()
        assert loaded.api_key == "grq_test"
        assert loaded.email == "user@test.com"
        assert loaded.is_authenticated

    def test_load_missing_file_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "nonexistent.json",
        )
        creds = load_credentials()
        assert not creds.is_authenticated
        assert creds.plan == "free"

    def test_clear_credentials(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text('{"api_key": "test"}')
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE", creds_file
        )
        clear_credentials()
        assert not creds_file.exists()

    def test_get_cloud_status_unauthenticated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE",
            tmp_path / "nonexistent.json",
        )
        status = get_cloud_status()
        assert status["connected"] is False
        assert status["email"] == ""
        assert status["plan"] == "free"

    def test_get_cloud_status_authenticated(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_FILE", creds_file
        )
        monkeypatch.setattr(
            "graqle.cloud.credentials.CREDENTIALS_DIR", tmp_path
        )
        save_credentials(CloudCredentials(
            api_key="grq_xyz", email="pro@test.com",
            plan="pro", connected=True,
        ))
        status = get_cloud_status()
        assert status["connected"] is True
        assert status["email"] == "pro@test.com"
        assert status["plan"] == "pro"
