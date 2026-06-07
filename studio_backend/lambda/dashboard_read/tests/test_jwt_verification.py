"""Tests for the Cognito ID-token verification path in the dashboard_read handler.

The security boundary on a public Function URL: identity comes from a
cryptographically VERIFIED Cognito ID token (RS256), and the tenant is derived as
sha256(lowercase email) — NOT from attacker-controllable authorizer claims, body,
or query. A forged / expired / wrong-issuer / non-ID token is a 401 (fail closed).

These tests mint real RS256 tokens with a throwaway key and monkeypatch the
handler's JWKS client to return that key, so no network/AWS is touched.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

# ``lambda`` is a Python keyword, so the handler cannot be imported by dotted path.
# Load it by file path (same approach as test_handler.py).
_LAMBDA_DIR = Path(__file__).resolve().parents[1]


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the read-API first (the handler imports it by package path), then the handler.
_read_api = _load(
    "studio_backend.dashboard.read_api",
    _LAMBDA_DIR.parents[1] / "dashboard" / "read_api.py",
)
h = _load("studio_backend.lambda.dashboard_read.handler", _LAMBDA_DIR / "handler.py")

# A single throwaway RSA key for the whole module (key-gen is the slow part).
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

ISS = h._COGNITO_ISS


class _FakeSigningKey:
    """Mimics PyJWKClient.get_signing_key_from_jwt(...).key."""

    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return _FakeSigningKey(self._key)


@pytest.fixture(autouse=True)
def _patch_jwks(monkeypatch):
    # Every test resolves signatures against our throwaway public key.
    monkeypatch.setattr(h, "_get_jwks_client", lambda: _FakeJWKClient(_PUBLIC_KEY))
    # Reset the module cache so a real client is never reused across tests.
    monkeypatch.setattr(h, "_jwks_client", None, raising=False)


def _token(claims: dict, *, exp_offset: int = 3600, key=None) -> str:
    import time

    now = int(time.time())
    payload = {
        "iss": ISS,
        "token_use": "id",
        "aud": "some-app-client-id",
        "iat": now,
        "exp": now + exp_offset,
        **claims,
    }
    return jwt.encode(payload, key or _PRIVATE_KEY, algorithm="RS256")


def _bearer_event(method: str, path: str, token: str, *, query=None, body=None):
    ev: dict = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    if query is not None:
        ev["queryStringParameters"] = query
    if body is not None:
        ev["body"] = body
    return ev


def _sha256_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def test_valid_token_derives_tenant_from_sha256_email(monkeypatch):
    seen = {}

    def fake_usage(*, tenant_id, role, period, usage_table, free_allowance, region_name):
        seen["tenant_id"] = tenant_id
        seen["role"] = role
        return _usage_view(tenant_id, period, free_allowance)

    monkeypatch.setattr(h, "get_usage", fake_usage)
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")

    tok = _token({"email": "Alice@Example.COM"})
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok, query={"period": "2026-06"}))

    assert resp["statusCode"] == 200
    # tenant is sha256(lowercased email), case-insensitive
    assert seen["tenant_id"] == _sha256_email("alice@example.com")
    assert seen["role"] == "viewer"  # default least-privilege


def test_forged_signature_is_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    # Sign with a DIFFERENT key than the JWKS will verify against.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tok = _token({"email": "alice@example.com"}, key=other)
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok))
    assert resp["statusCode"] == 401


def test_expired_token_is_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    tok = _token({"email": "alice@example.com"}, exp_offset=-10)  # already expired
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok))
    assert resp["statusCode"] == 401


def test_wrong_issuer_is_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    import time

    now = int(time.time())
    payload = {
        "iss": "https://evil.example.com/pool",
        "token_use": "id",
        "email": "alice@example.com",
        "iat": now,
        "exp": now + 3600,
    }
    tok = jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256")
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok))
    assert resp["statusCode"] == 401


def test_access_token_not_id_token_is_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    tok = _token({"email": "alice@example.com", "token_use": "access"})
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok))
    assert resp["statusCode"] == 401


def test_verified_token_without_email_is_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    tok = _token({})  # valid signature, no email claim
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok))
    assert resp["statusCode"] == 401


def test_body_and_query_tenant_are_ignored(monkeypatch):
    seen = {}

    def fake_usage(*, tenant_id, role, period, usage_table, free_allowance, region_name):
        seen["tenant_id"] = tenant_id
        return _usage_view(tenant_id, period, free_allowance)

    monkeypatch.setattr(h, "get_usage", fake_usage)
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")

    tok = _token({"email": "alice@example.com"})
    ev = _bearer_event(
        "GET", "/usage", tok,
        query={"period": "2026-06", "tenant_id": "globex"},
        body=json.dumps({"tenant_id": "globex"}),
    )
    resp = h.lambda_handler(ev)
    assert resp["statusCode"] == 200
    # The verified email won, not the attacker-supplied tenant_id.
    assert seen["tenant_id"] == _sha256_email("alice@example.com")


def test_role_claim_is_honored_when_present(monkeypatch):
    seen = {}

    def fake_usage(*, tenant_id, role, period, usage_table, free_allowance, region_name):
        seen["role"] = role
        return _usage_view(tenant_id, period, free_allowance)

    monkeypatch.setattr(h, "get_usage", fake_usage)
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    monkeypatch.setenv("DASHBOARD_ROLE_CLAIM", "custom:role")

    tok = _token({"email": "alice@example.com", "custom:role": "admin"})
    resp = h.lambda_handler(_bearer_event("GET", "/usage", tok, query={"period": "2026-06"}))
    assert resp["statusCode"] == 200
    assert seen["role"] == "admin"


def test_forged_authorizer_claims_without_bearer_is_401_on_public_url(monkeypatch):
    """THE bypass the predict caught: on a public Function URL the caller controls
    requestContext, so forged authorizer.claims must NOT be trusted. With
    DASHBOARD_TRUST_AUTHORIZER unset (default), an event carrying forged claims and
    NO bearer token is rejected (401) — the authorizer fallback is unreachable."""
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    monkeypatch.delenv("DASHBOARD_TRUST_AUTHORIZER", raising=False)  # default OFF

    forged = {
        "rawPath": "/usage",
        "queryStringParameters": {"period": "2026-06"},
        "requestContext": {
            "http": {"method": "GET"},
            # Attacker-forged authorizer block — would have granted 'globex' before.
            "authorizer": {"jwt": {"claims": {"custom:tenant_id": "globex", "custom:role": "admin"}}},
        },
        # no Authorization header
    }
    resp = h.lambda_handler(forged)
    assert resp["statusCode"] == 401


def test_authorizer_fallback_works_when_explicitly_trusted(monkeypatch):
    """When the operator opts in (behind a real authorizer), the claims path works."""
    seen = {}

    def fake_usage(*, tenant_id, role, period, usage_table, free_allowance, region_name):
        seen["tenant_id"] = tenant_id
        return _usage_view(tenant_id, period, free_allowance)

    monkeypatch.setattr(h, "get_usage", fake_usage)
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "t")
    monkeypatch.setenv("DASHBOARD_TRUST_AUTHORIZER", "true")

    ev = {
        "rawPath": "/usage",
        "queryStringParameters": {"period": "2026-06"},
        "requestContext": {
            "http": {"method": "GET"},
            "authorizer": {"jwt": {"claims": {"custom:tenant_id": "acme", "custom:role": "viewer"}}},
        },
    }
    resp = h.lambda_handler(ev)
    assert resp["statusCode"] == 200
    assert seen["tenant_id"] == "acme"


# ── helper ──────────────────────────────────────────────────────────────────
def _usage_view(tenant_id, period, free_allowance):
    UsageView = _read_api.UsageView

    return UsageView(
        tenant_id=tenant_id,
        edition="studio",
        period=period or "2026-06",
        used=1,
        allowance=free_allowance,
        remaining=free_allowance - 1,
        over_allowance=False,
    )
