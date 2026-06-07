# V-A1B-NATIVE-004: new test file via native Write (S-010: graq_write rejects
# absolute source-tree path; graq_generate mode=test infers wrong location).
"""Tests for graqle.studio.auth — the A1b cross-tenant trust root.

The security contract under test:
  * A VALID Cognito ID token's email is accepted.
  * A FORGED identity is rejected and FAILS CLOSED (returns None), specifically:
      - a raw x-user-email header (no token) → None  (the original hole)
      - an ``alg:none`` self-minted token → None
      - an HS256 token signed with a guessed secret → None
      - a token signed by a DIFFERENT key (wrong signature) → None
      - an expired token → None
      - a token whose ``token_use`` != "id" (e.g. an access token) → None
  * The raw x-user-email header is honoured ONLY when GRAQLE_TRUST_PROXY_EMAIL
    is set (behind-a-real-authorizer shape), and even then only if well-formed.
  * Nothing ever raises, even on hostile/binary input.

Verification is tested fully OFFLINE: we generate an RSA keypair in-process,
build a fake JWKS-style signing key, and monkeypatch the module's JWKS client so
``get_signing_key_from_jwt`` returns our public key. No network, deterministic.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from graqle.studio import auth


# ---------------------------------------------------------------- fixtures ----

@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_rsa_key():
    """A DIFFERENT key — tokens signed with this must fail (wrong signature)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Req:
    """Minimal request stand-in with a case-insensitive .headers.get()."""

    def __init__(self, headers: dict[str, str] | None = None):
        self._h = {k.lower(): v for k, v in (headers or {}).items()}

    @property
    def headers(self):
        store = self._h

        class _H:
            def get(self, k, default=None):
                return store.get(k.lower(), default)

        return _H()


def _bearer(token: str) -> _Req:
    return _Req({"authorization": f"Bearer {token}"})


def _mint(key, *, claims: dict[str, Any], alg: str = "RS256") -> str:
    return jwt.encode(claims, key, algorithm=alg)


def _good_claims(email: str = "user@example.com", **over) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "email": email,
        "token_use": "id",
        "iss": auth._COGNITO_ISS,
        "aud": "some-client-id",
        "exp": now + 3600,
        "iat": now,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _patch_jwks(monkeypatch, rsa_key):
    """Make the module's JWKS client return OUR public key for any token."""
    pub = rsa_key.public_key()

    class _SigningKey:
        key = pub

    class _FakeJWKSClient:
        def get_signing_key_from_jwt(self, token):  # noqa: ARG002
            return _SigningKey()

    monkeypatch.setattr(auth, "_jwks_client", _FakeJWKSClient())
    # default: proxy-trust OFF (the secure default)
    monkeypatch.delenv("GRAQLE_TRUST_PROXY_EMAIL", raising=False)
    yield


# ------------------------------------------------------- the happy path -------

def test_valid_id_token_email_accepted(rsa_key):
    req = _bearer(_mint(rsa_key, claims=_good_claims("Alice@Example.com")))
    assert auth.verified_email_from_request(req) == "alice@example.com"  # normalised


def test_bare_token_without_bearer_scheme_accepted(rsa_key):
    tok = _mint(rsa_key, claims=_good_claims("bob@example.com"))
    req = _Req({"authorization": tok})  # no "Bearer " prefix
    assert auth.verified_email_from_request(req) == "bob@example.com"


# ------------------------------------------------- the forged / closed paths --

def test_raw_x_user_email_header_is_ignored_by_default():
    # THE ORIGINAL HOLE: a forged header with no token must NOT grant identity.
    req = _Req({"x-user-email": "victim@example.com"})
    assert auth.verified_email_from_request(req) is None


def test_alg_none_token_rejected(rsa_key):
    # A self-minted unsigned token must never be accepted.
    tok = jwt.encode(_good_claims("attacker@evil.com"), key=None, algorithm="none")
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_hs256_token_with_guessed_secret_rejected():
    tok = jwt.encode(_good_claims("attacker@evil.com"), "guessed-secret", algorithm="HS256")
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_token_signed_by_wrong_key_rejected(other_rsa_key):
    # Signed with a key our JWKS does NOT correspond to → bad signature.
    tok = _mint(other_rsa_key, claims=_good_claims("attacker@evil.com"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_expired_token_rejected(rsa_key):
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com", exp=int(time.time()) - 10))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_wrong_issuer_rejected(rsa_key):
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com", iss="https://evil.example/pool"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_access_token_rejected(rsa_key):
    # token_use must be "id"; an access token must not authenticate a graph read.
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com", token_use="access"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_verified_token_without_email_is_unauthenticated(rsa_key):
    claims = _good_claims()
    claims.pop("email")
    assert auth.verified_email_from_request(_bearer(_mint(rsa_key, claims=claims))) is None


def test_verified_token_with_malformed_email_rejected(rsa_key):
    # A path-like / non-email value must not reach the S3 key.
    tok = _mint(rsa_key, claims=_good_claims("../../admin"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_no_authorization_header_returns_none():
    assert auth.verified_email_from_request(_Req({})) is None


def test_hostile_binary_token_does_not_raise():
    req = _bearer("\x00\x01.\x02.\x03")
    # must fail closed, never raise
    assert auth.verified_email_from_request(req) is None


def test_odd_request_object_does_not_raise():
    class Weird:
        @property
        def headers(self):
            raise RuntimeError("boom")

    assert auth.verified_email_from_request(Weird()) is None


# ------------------------------------------- opt-in proxy-trust behaviour -----

def test_proxy_trust_flag_honours_well_formed_header(monkeypatch):
    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", "true")
    req = _Req({"x-user-email": "Trusted@Example.com"})
    assert auth.verified_email_from_request(req) == "trusted@example.com"


def test_proxy_trust_path_emits_loud_warning(monkeypatch, caplog):
    # The bypass (graq_review A01 finding) must be LOUD: a production
    # misconfiguration on a public Function URL has to surface in logs.
    import logging

    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", "true")
    req = _Req({"x-user-email": "trusted@example.com"})
    with caplog.at_level(logging.WARNING, logger=auth.logger.name):
        auth.verified_email_from_request(req)
    assert any(
        r.levelno == logging.WARNING and "UNVERIFIED x-user-email" in r.getMessage()
        for r in caplog.records
    )


def test_proxy_trust_flag_still_rejects_malformed_header(monkeypatch):
    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", "true")
    req = _Req({"x-user-email": "not-an-email\r\nX-Admin: 1"})
    assert auth.verified_email_from_request(req) is None


def test_proxy_trust_flag_does_not_override_valid_token(monkeypatch, rsa_key):
    # A real token always wins; we never fall back to the header when a token verifies.
    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", "true")
    req = _Req(
        {
            "authorization": f"Bearer {_mint(rsa_key, claims=_good_claims('real@example.com'))}",
            "x-user-email": "spoof@evil.com",
        }
    )
    assert auth.verified_email_from_request(req) == "real@example.com"


@pytest.mark.parametrize("val", ["", "false", "0", "no", "off"])
def test_proxy_trust_flag_off_values_keep_header_ignored(monkeypatch, val):
    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", val)
    req = _Req({"x-user-email": "victim@example.com"})
    assert auth.verified_email_from_request(req) is None


# -------------------------------------------------------------- tenant_hash ---

def test_tenant_hash_is_sha256_lowercase():
    import hashlib

    expected = hashlib.sha256("alice@example.com".encode()).hexdigest()
    assert auth.tenant_hash("Alice@Example.com") == expected
    # stable + case/whitespace-insensitive
    assert auth.tenant_hash("  ALICE@EXAMPLE.COM  ") == expected


# --------------------------------- defensive fail-closed branch coverage ------

def test_authorization_header_non_string_returns_no_token():
    # headers.get returns a non-str → _bearer_token must yield None (not crash).
    class _H:
        def get(self, k, default=None):  # noqa: ARG002
            return 12345  # not a string

    class _Req2:
        headers = _H()

    assert auth._bearer_token(_Req2()) is None


def test_headers_get_raises_is_swallowed():
    class _H:
        def get(self, k, default=None):  # noqa: ARG002
            raise RuntimeError("boom")

    class _Req2:
        headers = _H()

    # _bearer_token swallows the get() error and returns None (fail closed).
    assert auth._bearer_token(_Req2()) is None


def test_malformed_authorization_value_returns_none():
    # "Bearer" with no token, and a one-part non-jwt token → None both ways.
    assert auth._bearer_token(_Req({"authorization": "Bearer    "})) is None
    assert auth._bearer_token(_Req({"authorization": "notajwt"})) is None


def test_pyjwt_unavailable_fails_closed(monkeypatch, rsa_key):
    # If PyJWT cannot be imported, verification must DENY (return None), never open.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "jwt":
            raise ImportError("no pyjwt")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com"))
    assert auth._verify_bearer(_bearer(tok)) is None


def test_unexpected_verification_error_fails_closed(monkeypatch, rsa_key):
    # An unexpected (non-InvalidToken, non-JWKS) error during signing-key lookup
    # must still fail closed.
    class _Boom:
        def get_signing_key_from_jwt(self, token):  # noqa: ARG002
            raise ValueError("totally unexpected")

    monkeypatch.setattr(auth, "_jwks_client", _Boom())
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_jwks_client_resolution_error_fails_closed(monkeypatch, rsa_key):
    from jwt import PyJWKClientError

    class _NoKey:
        def get_signing_key_from_jwt(self, token):  # noqa: ARG002
            raise PyJWKClientError("unknown kid")

    monkeypatch.setattr(auth, "_jwks_client", _NoKey())
    tok = _mint(rsa_key, claims=_good_claims("alice@example.com"))
    assert auth.verified_email_from_request(_bearer(tok)) is None


def test_get_jwks_client_is_lazy_and_cached(monkeypatch):
    # Force the lazy-build path (lines 72-74): clear the cached client and stub
    # PyJWKClient so no network call happens.
    created = {"n": 0}

    class _FakeClient:
        def __init__(self, url):
            created["n"] += 1
            self.url = url

    import jwt as _jwt

    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(_jwt, "PyJWKClient", _FakeClient)
    c1 = auth._get_jwks_client()
    c2 = auth._get_jwks_client()
    assert c1 is c2  # cached
    assert created["n"] == 1  # built once


def test_proxy_trust_header_read_error_is_swallowed(monkeypatch):
    monkeypatch.setenv("GRAQLE_TRUST_PROXY_EMAIL", "true")

    class _H:
        def get(self, k, default=None):  # noqa: ARG002
            # authorization absent (so no token), but x-user-email read raises
            if k.lower() == "authorization":
                return None
            raise RuntimeError("boom")

    class _Req2:
        headers = _H()

    assert auth.verified_email_from_request(_Req2()) is None
