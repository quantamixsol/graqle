"""Tests for graqle.cloud.team — team config management."""

# ── graqle:intelligence ──
# module: tests.test_cloud.test_team
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pytest, pathlib, team
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.cloud.team import (
    TeamConfig,
    TeamMember,
    add_repo,
    create_team,
    invite_member,
    load_team_config,
    remove_member,
    remove_repo,
    save_team_config,
)


class TestTeamMember:
    def test_default_member(self):
        m = TeamMember(email="alice@company.com")
        assert m.role == "member"
        assert m.can_teach
        assert not m.can_admin

    def test_owner_permissions(self):
        m = TeamMember(email="owner@company.com", role="owner")
        assert m.can_teach
        assert m.can_admin

    def test_viewer_permissions(self):
        m = TeamMember(email="viewer@company.com", role="viewer")
        assert not m.can_teach
        assert not m.can_admin

    def test_admin_permissions(self):
        m = TeamMember(email="admin@company.com", role="admin")
        assert m.can_teach
        assert m.can_admin

    def test_roundtrip(self):
        m = TeamMember(email="test@test.com", role="admin", status="active")
        d = m.to_dict()
        restored = TeamMember.from_dict(d)
        assert restored.email == "test@test.com"
        assert restored.role == "admin"


class TestTeamConfig:
    def test_default_not_configured(self):
        config = TeamConfig()
        assert not config.is_configured
        assert config.member_count == 0

    def test_configured(self):
        config = TeamConfig(
            team_id="team-test",
            owner_email="owner@test.com",
            members=[TeamMember(email="owner@test.com", role="owner", status="active")],
        )
        assert config.is_configured
        assert config.member_count == 1

    def test_get_member(self):
        config = TeamConfig(
            team_id="team-test",
            owner_email="owner@test.com",
            members=[
                TeamMember(email="owner@test.com", role="owner", status="active"),
                TeamMember(email="alice@test.com", role="member", status="active"),
            ],
        )
        assert config.get_member("alice@test.com").role == "member"
        assert config.get_member("nobody@test.com") is None

    def test_persistence(self, tmp_path):
        config = TeamConfig(
            team_id="team-persist",
            team_name="Persist Team",
            owner_email="owner@test.com",
            members=[TeamMember(email="owner@test.com", role="owner", status="active")],
        )
        save_team_config(config, tmp_path)
        loaded = load_team_config(tmp_path)
        assert loaded.team_id == "team-persist"
        assert loaded.team_name == "Persist Team"
        assert loaded.member_count == 1

    def test_load_missing(self, tmp_path):
        config = load_team_config(tmp_path)
        assert not config.is_configured

    def test_load_corrupt(self, tmp_path):
        config_path = tmp_path / ".graqle" / "team.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("not json", encoding="utf-8")
        config = load_team_config(tmp_path)
        assert not config.is_configured


class TestCreateTeam:
    def test_create_team(self, tmp_path):
        config = create_team("Test Team", "owner@test.com", tmp_path)
        assert config.team_id == "team-test-team"
        assert config.team_name == "Test Team"
        assert config.owner_email == "owner@test.com"
        assert config.member_count == 1
        assert config.members[0].role == "owner"

    def test_create_team_persists(self, tmp_path):
        create_team("Persist", "owner@test.com", tmp_path)
        loaded = load_team_config(tmp_path)
        assert loaded.is_configured
        assert loaded.team_name == "Persist"


class TestInviteMember:
    def test_invite_member(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        member = invite_member("alice@test.com", "member", tmp_path)
        assert member.email == "alice@test.com"
        assert member.status == "invited"

        config = load_team_config(tmp_path)
        assert config.member_count == 1  # only owner is "active"
        assert len(config.members) == 2

    def test_invite_duplicate_fails(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        with pytest.raises(ValueError, match="already a team member"):
            invite_member("owner@test.com", "member", tmp_path)

    def test_invite_no_team_fails(self, tmp_path):
        with pytest.raises(RuntimeError, match="No team configured"):
            invite_member("alice@test.com", "member", tmp_path)


class TestRemoveMember:
    def test_remove_member(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        invite_member("alice@test.com", "member", tmp_path)
        remove_member("alice@test.com", tmp_path)
        config = load_team_config(tmp_path)
        assert len(config.members) == 1

    def test_cannot_remove_owner(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        with pytest.raises(ValueError, match="Cannot remove the team owner"):
            remove_member("owner@test.com", tmp_path)

    def test_remove_nonexistent_fails(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        with pytest.raises(ValueError, match="not a team member"):
            remove_member("nobody@test.com", tmp_path)


class TestRepos:
    def test_add_repo(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        add_repo("https://github.com/org/repo1", tmp_path)
        config = load_team_config(tmp_path)
        assert "https://github.com/org/repo1" in config.repos

    def test_add_duplicate_repo(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        add_repo("https://github.com/org/repo1", tmp_path)
        add_repo("https://github.com/org/repo1", tmp_path)  # no error
        config = load_team_config(tmp_path)
        assert len(config.repos) == 1

    def test_remove_repo(self, tmp_path):
        create_team("Test", "owner@test.com", tmp_path)
        add_repo("https://github.com/org/repo1", tmp_path)
        remove_repo("https://github.com/org/repo1", tmp_path)
        config = load_team_config(tmp_path)
        assert len(config.repos) == 0
