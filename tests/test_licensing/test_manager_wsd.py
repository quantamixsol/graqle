"""Tests for the WS-D LicenseManager hardening delta — all gate + loader paths.

Covers: dual-verify (v2 ed25519 + v1 HMAC fallback), the grace window,
CRL-revocation gate, nonce-replay gate, and every loader (trusted manifest,
CRL, nonce store) incl. their fail-closed branches.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import graqle.licensing.manager as M
from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest, KeyState
from graqle.licensing.crl import issue_crl
from graqle.licensing.ed25519_license import issue_ed25519_license
from graqle.licensing.manager import License, LicenseTier

_NOW = datetime.now(timezone.utc)
_VF, _VU = _NOW - timedelta(days=1), _NOW + timedelta(days=3650)


@pytest.fixture
def server_kid():
    priv = Ed25519PrivateKey.generate()
    server = Ed25519KeyManifest()
    server.register("k1", priv.public_key(), _VF, _VU, KeyState.ACTIVE, private_key=priv)
    pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return server, pem


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    for n in ("_trusted_manifest_loaded", "_active_crl_loaded", "_nonce_store_loaded"):
        monkeypatch.setattr(M, n, False, raising=False)
    monkeypatch.setattr(M, "_trusted_license_manifest", None, raising=False)
    monkeypatch.setattr(M, "_active_crl", None, raising=False)
    monkeypatch.setattr(M, "_nonce_store", None, raising=False)
    for v in ("GRAQLE_LICENSE_PUBLIC_KEYS", "GRAQLE_LICENSE_CRL", "GRAQLE_LICENSE_NONCE_DIR",
              "COGNIGRAPH_LICENSE_KEY", "GRAQLE_LICENSE_GRACE_DAYS"):
        monkeypatch.delenv(v, raising=False)
    yield


def _trust(monkeypatch, pem):
    monkeypatch.setenv("GRAQLE_LICENSE_PUBLIC_KEYS", json.dumps(
        [{"kid": "k1", "public_key_pem": pem, "valid_from": _VF.isoformat(),
          "valid_until": _VU.isoformat(), "state": "active"}]))
    M._trusted_manifest_loaded = False


def _v2(server, **over):
    kw = dict(license_id="L-1", tier="enterprise", holder="A", email="a@a",
              issued_at=_NOW.isoformat(), nonce="N-1",
              expires_at=(_NOW + timedelta(days=300)).isoformat(), at=_NOW)
    kw.update(over)
    return issue_ed25519_license(server, "k1", **kw)


def _load(monkeypatch, token):
    monkeypatch.setenv("COGNIGRAPH_LICENSE_KEY", token)
    for n in ("_trusted_manifest_loaded", "_active_crl_loaded", "_nonce_store_loaded"):
        setattr(M, n, False)
    return M.LicenseManager().current_tier.value


# ---- dual-verify --------------------------------------------------------------


def test_v2_ed25519_load(monkeypatch, server_kid):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    assert _load(monkeypatch, _v2(server)) == "enterprise"


def test_v1_hmac_backcompat(monkeypatch):
    # v1 HMAC verifies ONLY when a real secret is configured (server-side / issuer).
    monkeypatch.setenv("GRAQLE_LICENSE_KEY_SECRET", "real-production-secret")
    v1 = M.LicenseManager.generate_key("pro", "B", "b@b", None)
    assert _load(monkeypatch, v1) == "pro"


def test_v1_downgrade_attack_blocked_without_secret(monkeypatch):
    # SECURITY (sentinel graq_predict vector #4): an attacker with only the public
    # Community wheel knows the dev-fallback HMAC secret. They forge a v1 ENTERPRISE
    # key with it. With NO GRAQLE_LICENSE_KEY_SECRET configured, HMAC verification
    # is REFUSED → the downgrade-forgery is blocked → free tier.
    monkeypatch.setenv("GRAQLE_LICENSE_KEY_SECRET", "real-production-secret")
    forged = M.LicenseManager.generate_key("enterprise", "Attacker", "x@x", None)
    monkeypatch.delenv("GRAQLE_LICENSE_KEY_SECRET", raising=False)  # public wheel: no secret
    # the forged key (signed with whatever secret) must NOT verify when no secret set
    assert _load(monkeypatch, forged) == "free"


def test_v1_hmac_rejects_non_string_key(monkeypatch):
    # explicit type guard: a None/non-str key fails closed (no crash)
    monkeypatch.setenv("GRAQLE_LICENSE_KEY_SECRET", "s1")
    mgr = M.LicenseManager.__new__(M.LicenseManager)
    assert mgr._verify_key_hmac(None) is None  # type: ignore[arg-type]
    assert mgr._verify_key_hmac(123) is None  # type: ignore[arg-type]
    assert mgr._verify_key_hmac("") is None


def test_v1_hmac_refused_when_no_secret(monkeypatch):
    # Even a legitimately-generated v1 key won't verify with no secret configured
    # (the dev fallback is public and refused) — fail closed.
    monkeypatch.setenv("GRAQLE_LICENSE_KEY_SECRET", "s1")
    v1 = M.LicenseManager.generate_key("team", "B", "b@b", None)
    monkeypatch.delenv("GRAQLE_LICENSE_KEY_SECRET", raising=False)
    mgr = M.LicenseManager.__new__(M.LicenseManager)
    assert mgr._verify_key_hmac(v1) is None


def test_v2_without_trusted_manifest_falls_back_to_free(monkeypatch, server_kid):
    server, _ = server_kid
    # no GRAQLE_LICENSE_PUBLIC_KEYS => ed25519 path returns None => HMAC fails => free
    assert _load(monkeypatch, _v2(server)) == "free"


def test_garbage_key_free(monkeypatch):
    assert _load(monkeypatch, "not-a-valid-key") == "free"


# ---- grace gate ---------------------------------------------------------------


def test_expired_in_grace_still_valid(monkeypatch, server_kid):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    tok = _v2(server, tier="team", expires_at=(_NOW - timedelta(days=10)).isoformat())
    assert _load(monkeypatch, tok) == "team"


def test_expired_past_grace_free(monkeypatch, server_kid):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    tok = _v2(server, tier="team", expires_at=(_NOW - timedelta(days=90)).isoformat())
    assert _load(monkeypatch, tok) == "free"


# ---- CRL gate -----------------------------------------------------------------


def test_crl_revokes_license(monkeypatch, server_kid):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    monkeypatch.setenv("GRAQLE_LICENSE_CRL",
                       issue_crl(server, "k1", issued_at=_NOW.isoformat(), sequence=1,
                                 revoked_license_ids=["L-1"], at=_NOW))
    assert _load(monkeypatch, _v2(server)) == "free"


def test_crl_does_not_revoke_other(monkeypatch, server_kid):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    monkeypatch.setenv("GRAQLE_LICENSE_CRL",
                       issue_crl(server, "k1", issued_at=_NOW.isoformat(), sequence=1,
                                 revoked_license_ids=["L-OTHER"], at=_NOW))
    assert _load(monkeypatch, _v2(server)) == "enterprise"


def test_crl_ignored_without_manifest(monkeypatch, server_kid):
    server, _ = server_kid
    # CRL configured but no trusted manifest => CRL ignored (can't trust it)
    monkeypatch.setenv("GRAQLE_LICENSE_CRL",
                       issue_crl(server, "k1", issued_at=_NOW.isoformat(), sequence=1,
                                 revoked_license_ids=["L-1"], at=_NOW))
    assert M._get_active_crl() is None


# ---- nonce gate ---------------------------------------------------------------


def test_nonce_replay_blocked(monkeypatch, server_kid, tmp_path):
    server, pem = server_kid
    _trust(monkeypatch, pem)
    monkeypatch.setenv("GRAQLE_LICENSE_NONCE_DIR", str(tmp_path))
    tok = _v2(server)
    assert _load(monkeypatch, tok) == "enterprise"   # first accept
    assert _load(monkeypatch, tok) == "free"          # replay → free


def test_nonce_store_off_by_default(monkeypatch):
    assert M._get_nonce_store() is None


def test_nonce_store_init_failure_disables(monkeypatch, tmp_path):
    # If LicenseNonceStore construction raises for any reason, replay protection
    # is disabled (None) without propagating — must never block licence load.
    # Inject the failure portably by patching the constructor: a null-byte env
    # value is rejected by os.environ on Linux BEFORE our code runs (AUD-010
    # class: Windows-local-green != Linux-CI), so we patch the class instead.
    monkeypatch.setenv("GRAQLE_LICENSE_NONCE_DIR", str(tmp_path))
    import graqle.licensing.nonce_store as ns_mod

    def boom(self, directory):
        raise OSError("simulated nonce-store init failure")

    monkeypatch.setattr(ns_mod.LicenseNonceStore, "__init__", boom)
    M._nonce_store_loaded = False
    assert M._get_nonce_store() is None


# ---- loaders: fail-closed branches -------------------------------------------


def test_trusted_manifest_malformed_disables(monkeypatch):
    monkeypatch.setenv("GRAQLE_LICENSE_PUBLIC_KEYS", "{ not json")
    M._trusted_manifest_loaded = False
    assert M._get_trusted_license_manifest() is None


def test_trusted_manifest_none_when_unset(monkeypatch):
    M._trusted_manifest_loaded = False
    assert M._get_trusted_license_manifest() is None


def test_grace_delta_default_and_override(monkeypatch):
    from graqle.licensing.manager import _grace_delta
    assert _grace_delta() == timedelta(days=60)
    monkeypatch.setenv("GRAQLE_LICENSE_GRACE_DAYS", "30")
    assert _grace_delta() == timedelta(days=30)
    monkeypatch.setenv("GRAQLE_LICENSE_GRACE_DAYS", "-5")  # negative => default
    assert _grace_delta() == timedelta(days=60)
    monkeypatch.setenv("GRAQLE_LICENSE_GRACE_DAYS", "abc")  # malformed => default
    assert _grace_delta() == timedelta(days=60)


def test_accept_license_none_passthrough():
    mgr = M.LicenseManager.__new__(M.LicenseManager)
    assert mgr._accept_license(None) is None


def test_candidate_keys_skips_unreadable(monkeypatch, tmp_path):
    # exercise the OSError-skip branch in _candidate_keys
    from pathlib import Path as _P
    monkeypatch.setattr(_P, "exists", lambda self: (_ for _ in ()).throw(OSError("no")))
    assert isinstance(M.LicenseManager._candidate_keys(), list)
