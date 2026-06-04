"""Tests for the dashboard read-API (BizQ S2 Phase 5).

No AWS: fake S3 + DynamoDB clients injected. Covers the thin RBAC, the
tenant-scoping security boundary (a tenant cannot read another's proofs), usage
reads, proof list/get, and the malformed/oversize/not-found guards.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_DASH = Path(__file__).resolve().parents[1]


def _load(modname: str, relpath: str):
    spec = importlib.util.spec_from_file_location(modname, _DASH / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


api = _load("studio_backend.dashboard.read_api", "read_api.py")
get_usage = api.get_usage
list_proofs = api.list_proofs
get_proof = api.get_proof
require_role = api.require_role
DashboardError = api.DashboardError
ForbiddenError = api.ForbiddenError
ROLE_ADMIN, ROLE_VIEWER, ROLE_BILLING = api.ROLE_ADMIN, api.ROLE_VIEWER, api.ROLE_BILLING

LEAF = "a" * 64
BATCH = "b" * 32


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeUsageDdb:
    def __init__(self, counts=None):
        self.counts = counts or {}

    def get_item(self, *, TableName, Key):
        k = Key["usage_key"]["S"]
        if k in self.counts:
            return {"Item": {"usage_key": {"S": k}, "count": {"N": str(self.counts[k])}}}
        return {}


class _Body:
    def __init__(self, data: bytes):
        self._b = io.BytesIO(data)

    def read(self, n=-1):
        return self._b.read(n)


class _FakeS3:
    def __init__(self, objects=None):
        # objects: {key: bundle_dict}
        self.objects = objects or {}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        contents = [
            {"Key": k, "Size": 100, "LastModified": datetime(2026, 6, 4, 12, i % 60, tzinfo=timezone.utc)}
            for i, k in enumerate(self.objects)
            if k.startswith(Prefix)
        ]
        return {"Contents": contents}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"Body": _Body(json.dumps(self.objects[Key]).encode("utf-8"))}


def _bundle(tenant_id, leaf=LEAF, batch=BATCH, log_index=7):
    return {
        "proof_format_version": "1",
        "record": {"proof_format_version": "1", "record_id": "r1", "tenant_id": tenant_id},
        "leaf": {"leaf_index": 0, "tree_size": 1, "leaf_hash": leaf},
        "merkle": {"merkle_root": "c" * 64, "merkle_path": [], "merkle_path_directions": []},
        "signature": {"alg": "ed25519", "kid": "k", "sig": "x", "signed_at": "2026-06-04T12:00:00Z"},
        "rekor": {"log_index": log_index, "signed_tree_head": "c" * 64},
    }


def _key(batch=BATCH, leaf=LEAF):
    return f"proofs/{batch}/{leaf}.json"


# ── RBAC ──────────────────────────────────────────────────────────────────────
def test_require_role_matrix():
    require_role(ROLE_ADMIN, "read_usage")
    require_role(ROLE_VIEWER, "read_proofs")
    require_role(ROLE_BILLING, "read_usage")
    with pytest.raises(ForbiddenError):
        require_role(ROLE_BILLING, "read_proofs")  # billing can't read proofs
    with pytest.raises(ForbiddenError):
        require_role("nobody", "read_usage")  # unknown role denied
    with pytest.raises(ForbiddenError):
        require_role(ROLE_ADMIN, "delete_everything")  # unknown action denied


# ── usage ─────────────────────────────────────────────────────────────────────
def test_get_usage_with_count():
    ddb = _FakeUsageDdb({"acme#studio#2026-06": 42})
    v = get_usage(tenant_id="acme", role=ROLE_VIEWER, period="2026-06",
                  usage_table="usage", free_allowance=1000, client=ddb)
    assert v.used == 42 and v.allowance == 1000 and v.remaining == 958
    assert v.over_allowance is False


def test_get_usage_zero_when_absent():
    v = get_usage(tenant_id="new", role=ROLE_VIEWER, period="2026-06",
                  usage_table="usage", client=_FakeUsageDdb())
    assert v.used == 0 and v.remaining == 1000


def test_get_usage_over_allowance():
    ddb = _FakeUsageDdb({"acme#studio#2026-06": 1500})
    v = get_usage(tenant_id="acme", role=ROLE_VIEWER, period="2026-06",
                  usage_table="usage", free_allowance=1000, client=ddb)
    assert v.over_allowance is True and v.remaining == 0


def test_get_usage_requires_tenant():
    with pytest.raises(DashboardError):
        get_usage(tenant_id="", role=ROLE_VIEWER, period="2026-06", usage_table="u",
                  client=_FakeUsageDdb())


def test_get_usage_requires_role():
    with pytest.raises(ForbiddenError):
        get_usage(tenant_id="acme", role="nobody", period="2026-06", usage_table="u",
                  client=_FakeUsageDdb())


def test_get_usage_bad_period():
    with pytest.raises(DashboardError):
        get_usage(tenant_id="acme", role=ROLE_VIEWER, period="2026", usage_table="u",
                  client=_FakeUsageDdb())


def test_get_usage_tenant_delimiter_stripped():
    ddb = _FakeUsageDdb({"evilstudio#studio#2026-06": 5})  # '#' stripped from tenant
    v = get_usage(tenant_id="evil#studio", role=ROLE_VIEWER, period="2026-06",
                  usage_table="u", client=ddb)
    assert v.used == 5  # read the stripped-key bucket, can't alias another tenant


# ── proof browser: tenant scoping is the security boundary ───────────────────
def test_get_proof_owned():
    s3 = _FakeS3({_key(): _bundle("acme")})
    b = get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash=LEAF, client=s3)
    assert b["record"]["tenant_id"] == "acme"


def test_get_proof_cross_tenant_forbidden():
    """A tenant CANNOT read another tenant's proof even with the right key."""
    s3 = _FakeS3({_key(): _bundle("globex")})
    with pytest.raises(ForbiddenError):
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash=LEAF, client=s3)


def test_get_proof_not_found():
    with pytest.raises(DashboardError):
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash=LEAF,
                  client=_FakeS3({}))


def test_get_proof_bad_ids():
    s3 = _FakeS3({})
    with pytest.raises(DashboardError):
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id="short", leaf_hash=LEAF, client=s3)
    with pytest.raises(DashboardError):
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash="nothex", client=s3)


def test_get_proof_billing_role_forbidden():
    s3 = _FakeS3({_key(): _bundle("acme")})
    with pytest.raises(ForbiddenError):
        get_proof(tenant_id="acme", role=ROLE_BILLING, batch_id=BATCH, leaf_hash=LEAF, client=s3)


def test_get_proof_oversize_refused():
    big = {"record": {"tenant_id": "acme"}, "pad": "x" * (1_048_577)}

    class _BigS3(_FakeS3):
        def get_object(self, *, Bucket, Key):
            return {"Body": _Body(json.dumps(big).encode("utf-8"))}

    with pytest.raises(DashboardError):  # oversize → _read_bundle None → not found
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash=LEAF,
                  client=_BigS3({_key(): big}))


def test_get_proof_malformed_json():
    class _BadS3(_FakeS3):
        def get_object(self, *, Bucket, Key):
            return {"Body": _Body(b"{not json")}

    with pytest.raises(DashboardError):
        get_proof(tenant_id="acme", role=ROLE_VIEWER, batch_id=BATCH, leaf_hash=LEAF,
                  client=_BadS3({_key(): {}}))


# ── list_proofs: tenant-filtered, summary-only ───────────────────────────────
def test_list_proofs_filters_by_tenant():
    s3 = _FakeS3({
        f"proofs/{'1'*32}/{'a'*64}.json": _bundle("acme", leaf="a" * 64, batch="1" * 32),
        f"proofs/{'2'*32}/{'b'*64}.json": _bundle("globex", leaf="b" * 64, batch="2" * 32),
        f"proofs/{'3'*32}/{'c'*64}.json": _bundle("acme", leaf="c" * 64, batch="3" * 32),
    })
    out = list_proofs(tenant_id="acme", role=ROLE_VIEWER, client=s3)
    assert len(out) == 2  # only acme's two proofs
    assert all(e["leaf_hash"] in ("a" * 64, "c" * 64) for e in out)
    assert all("batch_id" in e and "last_modified" in e and "rekor_log_index" in e for e in out)


def test_list_proofs_respects_limit():
    objs = {f"proofs/{str(i)*32}/{format(i,'064x')}.json": _bundle("acme", leaf=format(i, "064x"),
            batch=str(i) * 32) for i in range(1, 6)}
    out = list_proofs(tenant_id="acme", role=ROLE_VIEWER, limit=2, client=_FakeS3(objs))
    assert len(out) == 2


def test_list_proofs_bad_limit():
    with pytest.raises(DashboardError):
        list_proofs(tenant_id="acme", role=ROLE_VIEWER, limit=0, client=_FakeS3({}))


def test_list_proofs_billing_forbidden():
    with pytest.raises(ForbiddenError):
        list_proofs(tenant_id="acme", role=ROLE_BILLING, client=_FakeS3({}))


def test_list_proofs_skips_non_json_and_unreadable():
    class _PartlyBadS3(_FakeS3):
        def get_object(self, *, Bucket, Key):
            if "bad" in Key:
                raise RuntimeError("boom")
            return super().get_object(Bucket=Bucket, Key=Key)

    s3 = _PartlyBadS3({
        f"proofs/{'1'*32}/{'a'*64}.json": _bundle("acme", leaf="a" * 64, batch="1" * 32),
        "proofs/x/not-a-bundle.txt": {},          # non-json, skipped by extension
        f"proofs/bad/{'d'*64}.json": _bundle("acme"),  # get_object raises → skipped
    })
    out = list_proofs(tenant_id="acme", role=ROLE_VIEWER, client=s3)
    assert len(out) == 1 and out[0]["leaf_hash"] == "a" * 64


def test_list_proofs_paginates_across_pages():
    """Exercise the continuation-token path: tenant match on page 2."""
    page1_key = f"proofs/{'1'*32}/{'a'*64}.json"
    page2_key = f"proofs/{'2'*32}/{'b'*64}.json"

    class _PagedS3:
        def __init__(self):
            self.bundles = {page1_key: _bundle("globex", leaf="a"*64, batch="1"*32),
                            page2_key: _bundle("acme", leaf="b"*64, batch="2"*32)}

        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, ContinuationToken=None):
            if ContinuationToken is None:
                return {"Contents": [{"Key": page1_key, "Size": 100,
                        "LastModified": datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)}],
                        "NextContinuationToken": "tok2"}
            # page 2 (token present → exercises the `if token` branch)
            return {"Contents": [{"Key": page2_key, "Size": 100,
                    "LastModified": datetime(2026, 6, 4, 12, 1, tzinfo=timezone.utc)}]}

        def get_object(self, *, Bucket, Key):
            return {"Body": _Body(json.dumps(self.bundles[Key]).encode("utf-8"))}

    out = list_proofs(tenant_id="acme", role=ROLE_VIEWER, client=_PagedS3())
    assert len(out) == 1 and out[0]["leaf_hash"] == "b" * 64  # acme's proof found on page 2


def test_get_usage_rejects_freeform_period_injection():
    """A 7-char free-form period (old len-check would pass) is now refused by the regex."""
    with pytest.raises(DashboardError):  # would have built a bad usage_key pre-hardening
        get_usage(tenant_id="acme", role=ROLE_VIEWER, period="x#y#z#w", usage_table="u",
                  client=_FakeUsageDdb())
