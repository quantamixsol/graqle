# V-TRACKB-NATIVE-001: new-file creation via native Write (S-010: graq_write
# rejects absolute source-tree paths — MCP resolves against site-packages).
"""GraQle Cloud Team Registry — the DynamoDB source of truth for teams (Track B).

This is the cloud-side registry behind ``graqle.cloud.team`` (which is a LOCAL
``.graqle/team.json`` cache). It answers the one question the team-graph feature
turns on:

    "Given a VERIFIED member identity, which team's shared graph may they read or
     write, and with what role?"

THE SECURITY BOUNDARY (carries A1b forward)
-------------------------------------------
* Identity is ALWAYS a ``member_hash`` = ``sha256(lower(email))`` derived from a
  *verified* token upstream (``graqle.studio.auth.verified_email_from_request``).
  This module never accepts a raw header email — callers pass the already-hashed,
  already-verified identity. The hash IS the tenant/member key (ADR-PHASE5-001).
* ``resolve_team_for_member`` returns a team ONLY if an ACTIVE member row exists.
  No membership → no team → no shared graph (fail closed).
* Writes to a team graph require ``can_teach`` (owner/admin/member). ``viewer`` is
  read-only. Role is re-checked here AND server-side at the write site (defence in
  depth) — a forged role cannot escalate because role comes from the registry row,
  keyed by the verified ``member_hash``, never from the client.
* ``team_id`` used to build the S3 prefix is ALWAYS the value returned by a
  registry lookup, never a client-supplied string — closing the same class of hole
  as the A1b ``x-user-email`` trap.

Table shape (``graqle-teams``, PAY_PER_REQUEST, ~$1-2/mo)
---------------------------------------------------------
* PK ``team_id``  (e.g. ``team-acme``)
* SK ``META``                      → the team record
* SK ``MEMBER#{member_hash}``      → one row per member
* GSI ``member-index`` on ``member_hash`` → list a member's teams in O(1)

The DynamoDB client is injectable (``table_resource``) so the whole module is
unit-testable offline with a fake/moto table — no AWS calls in tests.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("graqle.cloud.team_registry")

_DEFAULT_TABLE = "graqle-teams"
_DEFAULT_REGION = "eu-central-1"
_MEMBER_INDEX = "member-index"

# Roles that may WRITE/teach the team graph (matches TeamMember.can_teach).
_TEACH_ROLES = ("owner", "admin", "member")
_ADMIN_ROLES = ("owner", "admin")
_VALID_ROLES = ("owner", "admin", "member", "viewer")
_ACTIVE = "active"

# team_id is interpolated into an S3 key — restrict it hard (same discipline as
# the studio project-name guard). Lowercase slug only.
_TEAM_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{1,62}\Z")
# Project name is ALSO interpolated into the S3 key (graphs/{owner}/{project}/...).
# Path-traversal guard: allowed charset AND must contain at least one
# alphanumeric, so an all-dots segment ('.', '..') — which would escape the
# tenant prefix as a path component — is rejected. Single source of truth for any
# caller building a graph key (gateway + studio routes).
_PROJECT_NAME_RE = re.compile(r"\A(?=.*[A-Za-z0-9])[A-Za-z0-9._\- ]{1,128}\Z")
_EMAIL_RE = re.compile(r"\A[^\s@\x00-\x1f]{1,64}@[^\s@\x00-\x1f]{1,255}\.[^\s@\x00-\x1f]{2,}\Z")


class TeamRegistryError(Exception):
    """Base error for registry operations."""


class ForbiddenError(TeamRegistryError):
    """The caller's verified identity is not permitted this action (fail closed)."""


class NotFoundError(TeamRegistryError):
    """Team or member does not exist."""


def member_hash(email: str) -> str:
    """``sha256(lower(email))`` — the member/tenant key (matches auth.tenant_hash)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def slug_team_id(team_name: str) -> str:
    """Derive a safe ``team-<slug>`` id from a display name."""
    base = re.sub(r"[^a-z0-9]+", "-", team_name.strip().lower()).strip("-")
    base = base or "team"
    candidate = f"team-{base}"[:63]
    return candidate


@dataclass(frozen=True)
class TeamRecord:
    team_id: str
    team_name: str
    owner_hash: str
    created_at: str
    plan: str = "team"


@dataclass(frozen=True)
class MemberRecord:
    team_id: str
    member_hash: str
    role: str
    status: str
    joined_at: str

    @property
    def can_teach(self) -> bool:
        return self.status == _ACTIVE and self.role in _TEACH_ROLES

    @property
    def can_admin(self) -> bool:
        return self.status == _ACTIVE and self.role in _ADMIN_ROLES


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _valid_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v.lower() if _EMAIL_RE.match(v) else None


class TeamRegistry:
    """DynamoDB-backed team registry. Inject ``table_resource`` for tests.

    Every method that grants access takes a ``caller_hash`` (the VERIFIED member
    identity) and fails CLOSED: an unknown/inactive caller, a missing team, or a
    role too low for the action raises rather than silently succeeding.
    """

    def __init__(
        self,
        table_name: str = _DEFAULT_TABLE,
        region_name: str = _DEFAULT_REGION,
        table_resource: Any = None,
    ):
        self._table_name = table_name
        self._region = region_name
        self._table = table_resource  # lazily built if None

    # ---- low-level table access (injectable) ----

    @property
    def table(self) -> Any:
        if self._table is None:
            import boto3

            self._table = boto3.resource(
                "dynamodb", region_name=self._region
            ).Table(self._table_name)
        return self._table

    @staticmethod
    def _member_sk(mh: str) -> str:
        return f"MEMBER#{mh}"

    # ---- team lifecycle ----

    def register_team(self, team_name: str, owner_email: str) -> TeamRecord:
        """Create a team; the owner is added as an active ``owner`` member.

        ``owner_email`` must be a verified email (the caller's own). Returns the
        created :class:`TeamRecord`. Idempotent-ish: a colliding team_id raises.
        """
        email = _valid_email(owner_email)
        if not email:
            raise TeamRegistryError("owner_email is not a valid email")
        team_id = slug_team_id(team_name)
        if not _TEAM_ID_RE.match(team_id):
            raise TeamRegistryError(f"derived team_id is invalid: {team_id!r}")

        owner = member_hash(email)
        created = _now()
        meta = {
            "team_id": team_id,
            "sk": "META",
            "team_name": team_name.strip()[:128],
            "owner_hash": owner,
            "created_at": created,
            "plan": "team",
        }
        member = {
            "team_id": team_id,
            "sk": self._member_sk(owner),
            "member_hash": owner,
            "role": "owner",
            "status": _ACTIVE,
            "joined_at": created,
        }
        # Conditional put: do not clobber an existing team.
        try:
            self.table.put_item(
                Item=meta,
                ConditionExpression="attribute_not_exists(team_id)",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_conditional_failure(exc):
                raise TeamRegistryError(f"team already exists: {team_id}") from exc
            raise
        self.table.put_item(Item=member)
        logger.info("registered team %s (owner %s…)", team_id, owner[:8])
        return TeamRecord(team_id, meta["team_name"], owner, created)

    def get_team(self, team_id: str) -> TeamRecord:
        item = self._get(team_id, "META")
        if not item:
            raise NotFoundError(f"no such team: {team_id}")
        return TeamRecord(
            team_id=item["team_id"],
            team_name=item.get("team_name", ""),
            owner_hash=item.get("owner_hash", ""),
            created_at=item.get("created_at", ""),
            plan=item.get("plan", "team"),
        )

    # ---- membership ----

    def add_member(
        self,
        caller_hash: str,
        team_id: str,
        invitee_email: str,
        role: str = "member",
        status: str = "invited",
    ) -> MemberRecord:
        """Invite/add a member. Caller must be an active admin/owner of the team."""
        if role not in _VALID_ROLES:
            raise TeamRegistryError(f"invalid role: {role}")
        self._require_admin(caller_hash, team_id)
        email = _valid_email(invitee_email)
        if not email:
            raise TeamRegistryError("invitee_email is not a valid email")
        mh = member_hash(email)
        existing = self._get(team_id, self._member_sk(mh))
        if existing:
            raise TeamRegistryError("already a member")
        joined = _now()
        self.table.put_item(
            Item={
                "team_id": team_id,
                "sk": self._member_sk(mh),
                "member_hash": mh,
                "role": role,
                "status": status,
                "joined_at": joined,
            }
        )
        return MemberRecord(team_id, mh, role, status, joined)

    def accept_invite(self, caller_hash: str, team_id: str) -> MemberRecord:
        """A pending invitee (identified by their OWN verified hash) goes active."""
        item = self._get(team_id, self._member_sk(caller_hash))
        if not item:
            raise NotFoundError("no invitation for this identity")
        self.table.update_item(
            Key={"team_id": team_id, "sk": self._member_sk(caller_hash)},
            UpdateExpression="SET #s = :a",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":a": _ACTIVE},
        )
        return MemberRecord(
            team_id, caller_hash, item.get("role", "member"), _ACTIVE,
            item.get("joined_at", ""),
        )

    def remove_member(self, caller_hash: str, team_id: str, target_hash: str) -> None:
        """Remove a member. Caller must be admin/owner; the owner cannot be removed."""
        self._require_admin(caller_hash, team_id)
        team = self.get_team(team_id)
        if target_hash == team.owner_hash:
            raise ForbiddenError("cannot remove the team owner")
        self.table.delete_item(
            Key={"team_id": team_id, "sk": self._member_sk(target_hash)}
        )

    def get_membership(self, caller_hash: str, team_id: str) -> MemberRecord | None:
        """Return the caller's member row for a team, or None (no exception)."""
        item = self._get(team_id, self._member_sk(caller_hash))
        if not item:
            return None
        return MemberRecord(
            team_id, caller_hash, item.get("role", "viewer"),
            item.get("status", ""), item.get("joined_at", ""),
        )

    # ---- the resolution the graph path depends on ----

    def resolve_team_for_member(self, caller_hash: str) -> MemberRecord | None:
        """Return the caller's ACTIVE team membership, or None (fail closed).

        Uses the ``member-index`` GSI to find the caller's team(s); returns the
        first ACTIVE one. None means "no team graph for you" — the caller falls
        back to their own per-user graph. NEVER raises on a missing/forged caller.
        """
        if not _is_hash(caller_hash):
            return None
        try:
            resp = self.table.query(
                IndexName=_MEMBER_INDEX,
                KeyConditionExpression="member_hash = :m",
                ExpressionAttributeValues={":m": caller_hash},
            )
        except Exception as exc:  # noqa: BLE001 - registry unreachable → fail closed
            logger.warning("team resolve query failed: %s", type(exc).__name__)
            return None
        for item in resp.get("Items", []):
            if item.get("status") == _ACTIVE and _TEAM_ID_RE.match(
                str(item.get("team_id", ""))
            ):
                return MemberRecord(
                    team_id=item["team_id"],
                    member_hash=caller_hash,
                    role=item.get("role", "viewer"),
                    status=_ACTIVE,
                    joined_at=item.get("joined_at", ""),
                )
        return None

    def assert_can_write(self, caller_hash: str, team_id: str) -> MemberRecord:
        """Authorise a team-graph WRITE. Raises ForbiddenError if not allowed."""
        m = self.get_membership(caller_hash, team_id)
        if m is None or not m.can_teach:
            raise ForbiddenError("not permitted to write this team graph")
        return m

    # ---- internals ----

    def _require_admin(self, caller_hash: str, team_id: str) -> MemberRecord:
        m = self.get_membership(caller_hash, team_id)
        if m is None or not m.can_admin:
            raise ForbiddenError("admin role required")
        return m

    def _get(self, team_id: str, sk: str) -> dict[str, Any] | None:
        try:
            resp = self.table.get_item(Key={"team_id": team_id, "sk": sk})
        except Exception as exc:  # noqa: BLE001
            logger.warning("registry get_item failed: %s", type(exc).__name__)
            return None
        item = resp.get("Item")
        return item if isinstance(item, dict) else None


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _is_conditional_failure(exc: Exception) -> bool:
    name = type(exc).__name__
    if name == "ConditionalCheckFailedException":
        return True
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    return False


__all__ = [
    "TeamRegistry",
    "TeamRecord",
    "MemberRecord",
    "TeamRegistryError",
    "ForbiddenError",
    "NotFoundError",
    "member_hash",
    "slug_team_id",
]
