"""Tests for cognigraph.leads.collector — lead capture and telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path, monkeypatch):
    """Redirect profile storage to a temp directory for test isolation."""
    monkeypatch.setattr(
        "cognigraph.leads.collector.PROFILE_DIR", tmp_path
    )
    monkeypatch.setattr(
        "cognigraph.leads.collector.PROFILE_PATH", tmp_path / "profile.json"
    )
    monkeypatch.setattr(
        "cognigraph.leads.collector.EVENTS_PATH", tmp_path / "events.jsonl"
    )


class TestProfile:
    """Tests for profile load/save and install ID."""

    def test_load_empty_profile(self) -> None:
        from cognigraph.leads.collector import load_profile
        profile = load_profile()
        assert profile == {}

    def test_save_and_load_profile(self, tmp_path) -> None:
        from cognigraph.leads.collector import load_profile, save_profile
        save_profile({"email": "test@example.com", "name": "Test"})
        profile = load_profile()
        assert profile["email"] == "test@example.com"
        assert profile["name"] == "Test"

    def test_get_install_id_stable(self) -> None:
        from cognigraph.leads.collector import get_install_id
        id1 = get_install_id()
        id2 = get_install_id()
        assert id1 == id2
        assert len(id1) == 36  # UUID format

    def test_is_registered_false_by_default(self) -> None:
        from cognigraph.leads.collector import is_registered
        assert is_registered() is False

    def test_is_telemetry_enabled_false_by_default(self) -> None:
        from cognigraph.leads.collector import is_telemetry_enabled
        assert is_telemetry_enabled() is False


class TestRegistration:
    """Tests for the register() function."""

    def test_register_saves_email(self) -> None:
        from cognigraph.leads.collector import is_registered, register
        assert is_registered() is False

        profile = register(
            email="dev@company.com",
            name="Developer",
            company="Acme",
            telemetry_opt_in=True,
            source="test",
        )

        assert is_registered() is True
        assert profile["email"] == "dev@company.com"
        assert profile["name"] == "Developer"
        assert profile["company"] == "Acme"
        assert profile["telemetry_opt_in"] is True

    def test_register_creates_install_id(self) -> None:
        from cognigraph.leads.collector import register
        profile = register(email="dev@test.com")
        assert "install_id" in profile
        assert len(profile["install_id"]) == 36

    def test_register_queues_event(self, tmp_path) -> None:
        from cognigraph.leads.collector import register
        register(email="dev@test.com", source="cli")

        events_path = tmp_path / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        event = json.loads(lines[0])
        assert event["type"] == "registration"
        assert event["data"]["email"] == "dev@test.com"


class TestProjectTracking:
    """Tests for track_project_init()."""

    def test_track_project_init(self, tmp_path) -> None:
        from cognigraph.leads.collector import load_profile, save_profile, track_project_init

        # Enable telemetry first
        save_profile({"email": "dev@test.com", "telemetry_opt_in": True})

        track_project_init(
            project_path="/home/user/my-project",
            node_count=42,
            edge_count=18,
            backend="anthropic",
            ide="cursor",
        )

        profile = load_profile()
        assert len(profile["projects"]) == 1
        project = profile["projects"][0]
        assert project["node_count"] == 42
        assert project["edge_count"] == 18
        assert project["backend"] == "anthropic"
        assert project["ide"] == "cursor"
        # Path should be hashed, not stored
        assert "/home/user/my-project" not in json.dumps(profile)

    def test_track_project_init_updates_existing(self, tmp_path) -> None:
        from cognigraph.leads.collector import load_profile, track_project_init

        track_project_init("/p", 10, 5, "ollama", "claude")
        track_project_init("/p", 20, 10, "anthropic", "cursor")

        profile = load_profile()
        assert len(profile["projects"]) == 1
        assert profile["projects"][0]["node_count"] == 20


class TestUsageTracking:
    """Tests for track_usage() and milestone detection."""

    def test_track_usage_increments_counters(self) -> None:
        from cognigraph.leads.collector import load_profile, track_usage
        track_usage("reason_query")
        track_usage("reason_query")
        track_usage("context_lookup")

        profile = load_profile()
        assert profile["usage_counters"]["reason_query"] == 2
        assert profile["usage_counters"]["context_lookup"] == 1

    def test_check_milestone_at_50(self) -> None:
        from cognigraph.leads.collector import check_milestone, save_profile

        # Simulate 50 queries
        save_profile({"usage_counters": {"reason_query": 50}})

        milestone = check_milestone()
        assert milestone == 50

        # Should not trigger again
        milestone2 = check_milestone()
        assert milestone2 is None

    def test_check_milestone_returns_none_below_threshold(self) -> None:
        from cognigraph.leads.collector import check_milestone, save_profile
        save_profile({"usage_counters": {"reason_query": 10}})
        assert check_milestone() is None


class TestNudges:
    """Tests for nudge message generation."""

    def test_registration_nudge_when_unregistered(self) -> None:
        from cognigraph.leads.collector import get_registration_nudge
        nudge = get_registration_nudge()
        assert nudge is not None
        assert "kogni register" in nudge

    def test_registration_nudge_none_when_registered(self) -> None:
        from cognigraph.leads.collector import get_registration_nudge, register
        register(email="dev@test.com")
        nudge = get_registration_nudge()
        assert nudge is None

    def test_milestone_nudge_messages(self) -> None:
        from cognigraph.leads.collector import get_milestone_nudge
        msg_50 = get_milestone_nudge(50)
        assert "50" in msg_50

        msg_100 = get_milestone_nudge(100)
        assert "100" in msg_100

        msg_500 = get_milestone_nudge(500)
        assert "500" in msg_500
        assert "Team" in msg_500 or "billing" in msg_500


class TestEventQueue:
    """Tests for the offline event queue."""

    def test_queue_event_creates_file(self, tmp_path) -> None:
        from cognigraph.leads.collector import _queue_event
        _queue_event("test_event", {"key": "value"})

        events_path = tmp_path / "events.jsonl"
        assert events_path.exists()
        event = json.loads(events_path.read_text().strip())
        assert event["type"] == "test_event"
        assert event["data"]["key"] == "value"

    def test_sync_graceful_failure(self, tmp_path) -> None:
        from cognigraph.leads.collector import _queue_event, _try_sync_leads
        _queue_event("test", {"x": 1})

        # Sync should fail gracefully (no server running)
        result = _try_sync_leads()
        assert result is False  # Failed but didn't raise

        # Events file should still exist (not deleted on failure)
        assert (tmp_path / "events.jsonl").exists()
