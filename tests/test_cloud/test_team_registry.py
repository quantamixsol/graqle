# V-TRACKB-NATIVE-002: new test file via native Write (S-010).
"""Tests for graqle.cloud.team_registry — the Track B DDB team registry.

Security contract under test (carries A1b forward):
  * resolve_team_for_member returns a team ONLY for an ACTIVE member; an unknown
    or forged caller_hash -> None (fail closed, no team graph).
  * Writes require can_teach (owner/admin/member); viewer is read-only (403).
  * Admin-only ops (add/remove member) reject non-admin callers.
  * The owner cannot be removed.
  * team_id is validated (slug only) before it could reach an S3 key.

Runs fully OFFLINE against an in-memory fake DynamoDB Table that implements just
the surface the registry uses (get_item/put_item/update_item/delete_item/query +
ConditionExpression attribute_not_exists). No boto3, no AWS.
"""

from __future__ import annotations

import pytest

from graqle.cloud import team_registry as tr
from graqle.cloud.team_registry import (
    ForbiddenError,
    MemberRecord,
    NotFoundError,
    TeamRegistry,
    TeamRegistryError,
    member_hash,
    slug_team_id,
)


# --------------------------------------------------------------- fake table ----

class _Cond:
    """Raised by the fake to mimic a DynamoDB conditional-check failure."""


class FakeConditionalCheckFailed(Exception):
    pass


class FakeTable:
    """Minimal in-memory DynamoDB Table double keyed by (team_id, sk)."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def get_item(self, Key):
        item = self.items.get((Key["team_id"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["team_id"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(team_id)" and key in self.items:
            raise FakeConditionalCheckFailed("exists")
        self.items[key] = dict(Item)
        return {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues):
        key = (Key["team_id"], Key["sk"])
        item = self.items.get(key)
        if item is None:
            return {}
        # Only the status-set update is used.
        item["status"] = ExpressionAttributeValues[":a"]
        return {}

    def delete_item(self, Key):
        self.items.pop((Key["team_id"], Key["sk"]), None)
        return {}

    def query(self, IndexName, KeyConditionExpression, ExpressionAttributeValues):
        mh = ExpressionAttributeValues[":m"]
        items = [
            dict(v) for v in self.items.values()
            if v.get("member_hash") == mh and str(v.get("sk", "")).startswith("MEMBER#")
        ]
        return {"Items": items}


# Preserve the genuine helper before any patching, for the direct unit test.
_REAL_IS_CONDITIONAL = tr._is_conditional_failure


# Make the fake's conditional error look like DynamoDB's to the registry helper.
# Wraps (not replaces) the real helper so genuine DDB shapes still work.
@pytest.fixture(autouse=True)
def _patch_conditional(monkeypatch):
    monkeypatch.setattr(
        tr, "_is_conditional_failure",
        lambda exc: isinstance(exc, FakeConditionalCheckFailed)
        or _REAL_IS_CONDITIONAL(exc),
    )
    yield


@pytest.fixture
def reg():
    return TeamRegistry(table_resource=FakeTable())


OWNER = "owner@acme.com"
MEMBER = "dev@acme.com"
VIEWER = "watch@acme.com"
OUTSIDER = "evil@elsewhere.com"


# --------------------------------------------------------------- helpers -------

def test_member_hash_matches_auth_convention():
    import hashlib
    assert member_hash("Owner@Acme.com") == hashlib.sha256(b"owner@acme.com").hexdigest()


def test_slug_team_id_is_safe():
    assert slug_team_id("ACME  Corp!!") == "team-acme-corp"
    assert slug_team_id("") == "team-team"


# --------------------------------------------------------------- lifecycle -----

def test_register_team_creates_owner_member(reg):
    rec = reg.register_team("Acme", OWNER)
    assert rec.team_id == "team-acme"
    m = reg.get_membership(member_hash(OWNER), "team-acme")
    assert m is not None and m.role == "owner" and m.can_admin and m.can_teach


def test_register_team_rejects_duplicate(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(TeamRegistryError):
        reg.register_team("Acme", OWNER)


def test_register_team_rejects_bad_email(reg):
    with pytest.raises(TeamRegistryError):
        reg.register_team("Acme", "not-an-email")


def test_get_team_and_missing(reg):
    reg.register_team("Acme", OWNER)
    assert reg.get_team("team-acme").team_name == "Acme"
    with pytest.raises(NotFoundError):
        reg.get_team("team-ghost")


# --------------------------------------------------------------- membership ----

def test_owner_can_invite_and_member_can_accept(reg):
    reg.register_team("Acme", OWNER)
    oh = member_hash(OWNER)
    inv = reg.add_member(oh, "team-acme", MEMBER, role="member")
    assert inv.status == "invited"
    mh = member_hash(MEMBER)
    acc = reg.accept_invite(mh, "team-acme")
    assert acc.status == "active" and acc.can_teach


def test_non_admin_cannot_invite(reg):
    reg.register_team("Acme", OWNER)
    reg.add_member(member_hash(OWNER), "team-acme", MEMBER, role="member")
    reg.accept_invite(member_hash(MEMBER), "team-acme")
    # an active 'member' is not an admin
    with pytest.raises(ForbiddenError):
        reg.add_member(member_hash(MEMBER), "team-acme", VIEWER, role="viewer")


def test_outsider_cannot_invite(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(ForbiddenError):
        reg.add_member(member_hash(OUTSIDER), "team-acme", VIEWER)


def test_add_member_rejects_bad_role(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(TeamRegistryError):
        reg.add_member(member_hash(OWNER), "team-acme", MEMBER, role="superuser")


def test_add_member_rejects_duplicate(reg):
    reg.register_team("Acme", OWNER)
    oh = member_hash(OWNER)
    reg.add_member(oh, "team-acme", MEMBER)
    with pytest.raises(TeamRegistryError):
        reg.add_member(oh, "team-acme", MEMBER)


def test_add_member_rejects_bad_email(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(TeamRegistryError):
        reg.add_member(member_hash(OWNER), "team-acme", "nope")


def test_accept_invite_without_invitation(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(NotFoundError):
        reg.accept_invite(member_hash(OUTSIDER), "team-acme")


def test_remove_member(reg):
    reg.register_team("Acme", OWNER)
    oh = member_hash(OWNER)
    reg.add_member(oh, "team-acme", MEMBER)
    reg.remove_member(oh, "team-acme", member_hash(MEMBER))
    assert reg.get_membership(member_hash(MEMBER), "team-acme") is None


def test_cannot_remove_owner(reg):
    reg.register_team("Acme", OWNER)
    oh = member_hash(OWNER)
    with pytest.raises(ForbiddenError):
        reg.remove_member(oh, "team-acme", oh)


def test_non_admin_cannot_remove(reg):
    reg.register_team("Acme", OWNER)
    with pytest.raises(ForbiddenError):
        reg.remove_member(member_hash(OUTSIDER), "team-acme", member_hash(OWNER))


# --------------------------------------------------- resolve + write authz ----

def test_resolve_team_for_active_member(reg):
    reg.register_team("Acme", OWNER)
    reg.add_member(member_hash(OWNER), "team-acme", MEMBER)
    reg.accept_invite(member_hash(MEMBER), "team-acme")
    got = reg.resolve_team_for_member(member_hash(MEMBER))
    assert got is not None and got.team_id == "team-acme"


def test_resolve_returns_none_for_invited_not_active(reg):
    reg.register_team("Acme", OWNER)
    reg.add_member(member_hash(OWNER), "team-acme", MEMBER)  # invited, not accepted
    assert reg.resolve_team_for_member(member_hash(MEMBER)) is None


def test_resolve_returns_none_for_outsider(reg):
    reg.register_team("Acme", OWNER)
    assert reg.resolve_team_for_member(member_hash(OUTSIDER)) is None


def test_resolve_rejects_non_hash_input(reg):
    # A forged/garbage caller (not a sha256 hex) must never resolve a team.
    assert reg.resolve_team_for_member("victim@example.com") is None
    assert reg.resolve_team_for_member("") is None


def test_resolve_fails_closed_on_query_error(monkeypatch, reg):
    def boom(**_):
        raise RuntimeError("ddb down")
    monkeypatch.setattr(reg.table, "query", boom)
    assert reg.resolve_team_for_member(member_hash(OWNER)) is None


def test_assert_can_write_allows_member_blocks_viewer(reg):
    reg.register_team("Acme", OWNER)
    oh = member_hash(OWNER)
    reg.add_member(oh, "team-acme", MEMBER, role="member")
    reg.accept_invite(member_hash(MEMBER), "team-acme")
    reg.add_member(oh, "team-acme", VIEWER, role="viewer")
    reg.accept_invite(member_hash(VIEWER), "team-acme")

    assert reg.assert_can_write(member_hash(MEMBER), "team-acme").can_teach
    assert reg.assert_can_write(oh, "team-acme").can_admin
    with pytest.raises(ForbiddenError):
        reg.assert_can_write(member_hash(VIEWER), "team-acme")
    with pytest.raises(ForbiddenError):
        reg.assert_can_write(member_hash(OUTSIDER), "team-acme")


def test_get_membership_missing_returns_none(reg):
    reg.register_team("Acme", OWNER)
    assert reg.get_membership(member_hash(OUTSIDER), "team-acme") is None


def test_get_item_failure_returns_none(monkeypatch, reg):
    reg.register_team("Acme", OWNER)
    def boom(**_):
        raise RuntimeError("transient")
    monkeypatch.setattr(reg.table, "get_item", boom)
    assert reg.get_membership(member_hash(OWNER), "team-acme") is None


def test_register_team_non_conditional_error_propagates(monkeypatch, reg):
    def boom(**_):
        raise RuntimeError("unexpected ddb error")
    monkeypatch.setattr(reg.table, "put_item", boom)
    with pytest.raises(RuntimeError):
        reg.register_team("Acme", OWNER)


def test_member_record_can_teach_requires_active():
    inactive = MemberRecord("t", "h" * 64, "member", "invited", "")
    assert not inactive.can_teach
    active = MemberRecord("t", "h" * 64, "member", "active", "")
    assert active.can_teach


def test_is_conditional_failure_recognises_ddb_shapes():
    # Direct unit test of the genuine real-DDB helper (captured before patching).
    fn = _REAL_IS_CONDITIONAL

    class ConditionalCheckFailedException(Exception):
        pass

    class Botoish(Exception):
        def __init__(self):
            self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}

    class OtherCoded(Exception):
        def __init__(self):
            self.response = {"Error": {"Code": "ThrottlingException"}}

    assert fn(ConditionalCheckFailedException())
    assert fn(Botoish())
    assert not fn(RuntimeError("other"))
    assert not fn(OtherCoded())


def test_valid_email_rejects_non_string():
    assert tr._valid_email(None) is None
    assert tr._valid_email(123) is None


def test_register_team_rejects_unsluggable_name(monkeypatch, reg):
    # Force slug_team_id to yield something the team_id regex rejects, to cover
    # the defensive guard in register_team.
    monkeypatch.setattr(tr, "slug_team_id", lambda name: "BAD_ID!!")
    with pytest.raises(TeamRegistryError):
        reg.register_team("whatever", OWNER)


def test_lazy_table_build_uses_boto3(monkeypatch):
    # Cover the lazy boto3 path without a real AWS call.
    built = {}

    class _FakeTableObj:
        pass

    class _FakeResource:
        def Table(self, name):
            built["name"] = name
            return _FakeTableObj()

    import sys, types
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.resource = lambda svc, region_name=None: _FakeResource()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    r = TeamRegistry(table_name="graqle-teams", table_resource=None)
    t = r.table
    assert isinstance(t, _FakeTableObj)
    assert built["name"] == "graqle-teams"
