"""Graqle Cloud Team management — team config and membership.

Manages team configuration for the Team tier ($29/dev/mo).
Teams share a cloud-hosted graph via Neptune, enabling:
- Cross-developer knowledge sharing
- Cross-repo graphs
- Persistent graph (survives laptop wipes)
- Access control (teach/modify vs read-only)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.cloud.team")

TEAM_CONFIG_FILE = ".graqle/team.json"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TeamMember:
    """A team member with role-based access."""

    email: str
    name: str = ""
    role: str = "member"  # owner, admin, member, viewer
    joined_at: str = ""
    last_sync: str = ""
    status: str = "active"  # active, invited, suspended

    @property
    def can_teach(self) -> bool:
        """Whether this member can teach/modify the graph."""
        return self.role in ("owner", "admin", "member")

    @property
    def can_admin(self) -> bool:
        """Whether this member can manage team settings."""
        return self.role in ("owner", "admin")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamMember:
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class TeamConfig:
    """Team configuration stored in .graqle/team.json."""

    team_id: str = ""
    team_name: str = ""
    owner_email: str = ""
    plan: str = "team"  # team, enterprise
    created_at: str = ""
    cloud_endpoint: str = ""
    neptune_endpoint: str = ""
    members: list[TeamMember] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=lambda: {
        "auto_sync": True,
        "sync_on_scan": True,
        "conflict_resolution": "source_priority",  # source_priority, timestamp, manual
        "max_graph_nodes": 50_000,
    })

    @property
    def is_configured(self) -> bool:
        return bool(self.team_id and self.owner_email)

    @property
    def member_count(self) -> int:
        return len([m for m in self.members if m.status == "active"])

    def get_member(self, email: str) -> TeamMember | None:
        for m in self.members:
            if m.email == email:
                return m
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamConfig:
        members_data = data.pop("members", [])
        members = [TeamMember.from_dict(m) if isinstance(m, dict) else m
                    for m in members_data]
        filtered = {k: v for k, v in data.items()
                    if k in cls.__dataclass_fields__}
        filtered["members"] = members
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_team_config(project_dir: str | Path = ".") -> TeamConfig:
    """Load team config from .graqle/team.json."""
    config_path = Path(project_dir) / TEAM_CONFIG_FILE
    if not config_path.exists():
        return TeamConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return TeamConfig.from_dict(data)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Corrupt team config: %s", exc)
        return TeamConfig()


def save_team_config(config: TeamConfig, project_dir: str | Path = ".") -> None:
    """Save team config to .graqle/team.json."""
    config_path = Path(project_dir) / TEAM_CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.to_dict(), indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Team operations (local stubs — cloud gateway handles the real work)
# ---------------------------------------------------------------------------

def create_team(
    team_name: str,
    owner_email: str,
    project_dir: str | Path = ".",
) -> TeamConfig:
    """Create a new team (local config — cloud registration via gateway).

    In Phase 1 (foundation), this creates the local config.
    Phase 2+ will register with the Graqle Cloud Gateway.
    """
    config = TeamConfig(
        team_id=f"team-{team_name.lower().replace(' ', '-')}",
        team_name=team_name,
        owner_email=owner_email,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        members=[TeamMember(
            email=owner_email,
            role="owner",
            joined_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            status="active",
        )],
    )
    save_team_config(config, project_dir)
    return config


def invite_member(
    email: str,
    role: str = "member",
    project_dir: str | Path = ".",
) -> TeamMember:
    """Invite a member to the team.

    In Phase 1, this adds to local config.
    Phase 2+ will send invitation via cloud gateway.
    """
    config = load_team_config(project_dir)
    if not config.is_configured:
        raise RuntimeError(
            "No team configured. Create one first: graq team create <name>"
        )

    # Check if already a member
    existing = config.get_member(email)
    if existing:
        raise ValueError(f"{email} is already a team member (role: {existing.role})")

    member = TeamMember(
        email=email,
        role=role,
        joined_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        status="invited",
    )
    config.members.append(member)
    save_team_config(config, project_dir)
    return member


def remove_member(
    email: str,
    project_dir: str | Path = ".",
) -> None:
    """Remove a member from the team."""
    config = load_team_config(project_dir)
    if not config.is_configured:
        raise RuntimeError("No team configured.")

    member = config.get_member(email)
    if not member:
        raise ValueError(f"{email} is not a team member")
    if member.role == "owner":
        raise ValueError("Cannot remove the team owner")

    config.members = [m for m in config.members if m.email != email]
    save_team_config(config, project_dir)


def add_repo(
    repo_url: str,
    project_dir: str | Path = ".",
) -> None:
    """Link a repo to the team's cross-repo graph."""
    config = load_team_config(project_dir)
    if not config.is_configured:
        raise RuntimeError("No team configured.")
    if repo_url not in config.repos:
        config.repos.append(repo_url)
        save_team_config(config, project_dir)


def remove_repo(
    repo_url: str,
    project_dir: str | Path = ".",
) -> None:
    """Unlink a repo from the team's cross-repo graph."""
    config = load_team_config(project_dir)
    if not config.is_configured:
        raise RuntimeError("No team configured.")
    if repo_url in config.repos:
        config.repos.remove(repo_url)
        save_team_config(config, project_dir)
