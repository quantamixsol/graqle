"""Tests for the ed25519-signed CRL (WS-D D1d) — all failure points.

100% statement + branch coverage of graqle/licensing/crl.py.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest, KeyState
from graqle.licensing.crl import CRL_FORMAT_V1, CRLError, issue_crl, verify_crl

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_VF, _VU = _NOW - timedelta(days=1), _NOW + timedelta(days=365)


@pytest.fixture
def keys():
    priv = Ed25519PrivateKey.generate()
    server = Ed25519KeyManifest()
    server.register("crl-kid", priv.public_key(), _VF, _VU, KeyState.ACTIVE, private_key=priv)
    client = Ed25519KeyManifest()
    client.register("crl-kid", priv.public_key(), _VF, _VU, KeyState.ACTIVE)
    return server, client


def _crl(server, **over):
    kw = dict(issued_at=_NOW.isoformat(), sequence=5, revoked_license_ids=["L-1", "L-2"], at=_NOW)
    kw.update(over)
    return issue_crl(server, "crl-kid", **kw)


def test_issue_verify_roundtrip(keys):
    server, client = keys
    rl = verify_crl(_crl(server), client, min_sequence=-1, at=_NOW)
    assert rl is not None
    assert rl.is_revoked("L-1") and rl.is_revoked("L-2")
    assert not rl.is_revoked("L-9")
    assert not rl.is_revoked(None)
    assert rl.sequence == 5 and rl.count == 2
    assert rl.issued_at == _NOW.isoformat()


def test_dedup_revoked_ids(keys):
    server, client = keys
    rl = verify_crl(_crl(server, revoked_license_ids=["L-1", "L-1", "L-2"]), client, at=_NOW)
    assert rl.count == 2


def test_rollback_defence(keys):
    server, client = keys
    tok = _crl(server, sequence=5)
    assert verify_crl(tok, client, min_sequence=5, at=_NOW) is None  # equal => rejected
    assert verify_crl(tok, client, min_sequence=6, at=_NOW) is None  # older => rejected
    assert verify_crl(tok, client, min_sequence=4, at=_NOW) is not None


def test_tampered_rejected(keys):
    server, client = keys
    tok = _crl(server)
    bad = ("Z" + tok[1:]) if tok[0] != "Z" else ("Y" + tok[1:])
    assert verify_crl(bad, client, at=_NOW) is None


def test_revoked_kid_kills_crl_trust(keys):
    server, client = keys
    tok = _crl(server)
    client.revoke("crl-kid")
    assert verify_crl(tok, client, at=_NOW) is None


def test_unknown_kid_fails_closed(keys):
    server, _ = keys
    assert verify_crl(_crl(server), Ed25519KeyManifest(), at=_NOW) is None


@pytest.mark.parametrize("bad", ["", "one.two", "a.b.c.d", 123, None])
def test_malformed_shape_returns_none(bad):
    assert verify_crl(bad, Ed25519KeyManifest()) is None  # type: ignore[arg-type]


def test_empty_kid_returns_none():
    assert verify_crl("msg..sig", Ed25519KeyManifest()) is None


def test_undecodable_returns_none():
    assert verify_crl("!!!.kid.!!!", Ed25519KeyManifest()) is None


def test_wrong_format_returns_none(keys):
    _, client = keys
    body = base64.urlsafe_b64encode(json.dumps({"format": "x", "kid": "crl-kid"}).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"x").rstrip(b"=").decode()
    assert verify_crl(f"{body}.crl-kid.{sig}", client, at=_NOW) is None


def test_kid_mismatch_returns_none(keys):
    server, client = keys
    msg, kid, sig = _crl(server).split(".")
    assert verify_crl(f"{msg}.crl-OTHER.{sig}", client, at=_NOW) is None


def test_non_int_sequence_returns_none(keys):
    _, client = keys
    body = base64.urlsafe_b64encode(
        json.dumps({"format": CRL_FORMAT_V1, "kid": "crl-kid", "sequence": "nope",
                    "revoked_license_ids": []}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"x").rstrip(b"=").decode()
    assert verify_crl(f"{body}.crl-kid.{sig}", client, at=_NOW) is None


def test_non_list_revoked_ids_returns_none(keys):
    _, client = keys
    body = base64.urlsafe_b64encode(
        json.dumps({"format": CRL_FORMAT_V1, "kid": "crl-kid", "sequence": 1,
                    "revoked_license_ids": "not-a-list"}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"x").rstrip(b"=").decode()
    assert verify_crl(f"{body}.crl-kid.{sig}", client, at=_NOW) is None


def test_non_str_revoked_id_returns_none(keys):
    _, client = keys
    body = base64.urlsafe_b64encode(
        json.dumps({"format": CRL_FORMAT_V1, "kid": "crl-kid", "sequence": 1,
                    "revoked_license_ids": [1, 2]}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"x").rstrip(b"=").decode()
    assert verify_crl(f"{body}.crl-kid.{sig}", client, at=_NOW) is None


# ---- issue failure points -----------------------------------------------------


def test_canonical_body_handles_non_list_rids():
    # Direct unit of the helper: when revoked_license_ids is absent/non-list, the
    # sort branch is skipped (defensive — verify_crl rejects non-list before this,
    # but the helper must be total).
    from graqle.licensing.crl import _canonical_body
    out = _canonical_body({"format": CRL_FORMAT_V1, "kid": "k", "sequence": 1,
                           "issued_at": "t", "revoked_license_ids": None})
    assert b"revoked_license_ids" in out


def test_issue_negative_sequence_rejected(keys):
    server, _ = keys
    with pytest.raises(CRLError, match="sequence"):
        _crl(server, sequence=-1)


def test_issue_requires_private_key(keys):
    _, client = keys
    with pytest.raises(Exception):  # KeyNotSignableError (public-only)
        _crl(client)
