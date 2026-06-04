"""Tests for the authenticated dashboard read Lambda (BizQ S2 Phase 5).

The security focus: identity is taken ONLY from the verified authorizer claims,
never from the body/query/headers. A request with no authenticated tenant is a
401; a cross-tenant read is denied; RBAC denial is a 403 with no leaked reason.

The read-API's stores are stubbed by monkeypatching the three read-API functions
the handler imports, so no AWS is touched. (The read-API's own tenant-scoping is
covered by its own test suite; here we prove the HTTP/auth/routing binding.)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_LAMBDA_DIR = Path(__file__).resolve().parents[1]


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the read-API first (the handler imports it by package path).
_read_api = _load(
    "studio_backend.dashboard.read_api",
    _LAMBDA_DIR.parents[1] / "dashboard" / "read_api.py",
)
handler = _load("studio_backend.lambda.dashboard_read.handler", _LAMBDA_DIR / "handler.py")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USAGE_TABLE", "usage-tbl")
    monkeypatch.setenv("DASHBOARD_S3_BUCKET", "bkt")
    monkeypatch.setenv("DASHBOARD_REGION", "eu-central-1")
    # Use the Cognito-style custom claims (the defaults).
    yield


def _jwt_event(method, path, *, tenant="acme", role="viewer", query=None, claims=None):
    """An HTTP-API (payload v2) event with a JWT authorizer."""
    c = {"custom:tenant_id": tenant, "custom:role": role}
    if claims is not None:
        c = claims
    return {
        "rawPath": path,
        "queryStringParameters": query,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": c}},
        },
    }


# ── identity is the security boundary ────────────────────────────────────────
def test_no_authorizer_is_401():
    resp = handler.lambda_handler({"rawPath": "/usage", "requestContext": {}})
    assert resp["statusCode"] == 401
    assert "error" in json.loads(resp["body"])


def test_blank_tenant_claim_is_401():
    ev = _jwt_event("GET", "/usage", tenant="   ")
    assert handler.lambda_handler(ev)["statusCode"] == 401


def test_identity_ignores_body_and_query(monkeypatch):
    """A tenant_id in the query/body must NOT override the claim — the read-API
    is called with the CLAIM's tenant, not the attacker-supplied one."""
    seen = {}

    def fake_usage(*, tenant_id, role, period, usage_table, free_allowance, region_name):
        seen["tenant_id"] = tenant_id
        return _read_api.UsageView(tenant_id, "studio", period, 1, free_allowance, free_allowance - 1, False)

    monkeypatch.setattr(handler, "get_usage", fake_usage)
    ev = _jwt_event("GET", "/usage", tenant="acme", query={"period": "2026-06", "tenant_id": "globex"})
    ev["body"] = json.dumps({"tenant_id": "globex"})
    resp = handler.lambda_handler(ev)
    assert resp["statusCode"] == 200
    assert seen["tenant_id"] == "acme"  # the claim won, not the query/body


def test_rest_api_cognito_claims_shape(monkeypatch):
    """REST-API/Cognito authorizer puts claims at authorizer.claims (no .jwt)."""
    captured = {}

    def fake_usage(*, tenant_id, role, **kw):
        captured["tenant_id"] = tenant_id
        return _read_api.UsageView(tenant_id, "studio", kw["period"], 0, 1000, 1000, False)

    monkeypatch.setattr(handler, "get_usage", fake_usage)
    ev = {
        "path": "/usage",
        "httpMethod": "GET",
        "queryStringParameters": {"period": "2026-06"},
        "requestContext": {"authorizer": {"claims": {"custom:tenant_id": "acme", "custom:role": "viewer"}}},
    }
    assert handler.lambda_handler(ev)["statusCode"] == 200
    assert captured["tenant_id"] == "acme"


def test_missing_role_claim_defaults_to_viewer(monkeypatch):
    captured = {}

    def fake_usage(*, tenant_id, role, **kw):
        captured["role"] = role
        return _read_api.UsageView(tenant_id, "studio", kw["period"], 0, 1000, 1000, False)

    monkeypatch.setattr(handler, "get_usage", fake_usage)
    ev = _jwt_event("GET", "/usage", query={"period": "2026-06"},
                    claims={"custom:tenant_id": "acme"})  # no role claim
    handler.lambda_handler(ev)
    assert captured["role"] == "viewer"  # least privilege


# ── routing ──────────────────────────────────────────────────────────────────
def test_usage_route(monkeypatch):
    monkeypatch.setattr(handler, "get_usage",
                        lambda **kw: _read_api.UsageView("acme", "studio", "2026-06", 42, 1000, 958, False))
    resp = handler.lambda_handler(_jwt_event("GET", "/usage", query={"period": "2026-06"}))
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["used"] == 42 and body["remaining"] == 958


def test_list_proofs_route(monkeypatch):
    monkeypatch.setattr(handler, "list_proofs",
                        lambda **kw: [{"batch_id": "b", "leaf_hash": "a"}])
    resp = handler.lambda_handler(_jwt_event("GET", "/proofs", query={"limit": "10"}))
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["count"] == 1 and body["proofs"][0]["leaf_hash"] == "a"


def test_get_proof_route(monkeypatch):
    captured = {}

    def fake_get(*, tenant_id, role, batch_id, leaf_hash, **kw):
        captured.update(batch_id=batch_id, leaf_hash=leaf_hash, tenant_id=tenant_id)
        return {"record": {"tenant_id": tenant_id}}

    monkeypatch.setattr(handler, "get_proof", fake_get)
    b, l = "1" * 32, "a" * 64
    resp = handler.lambda_handler(_jwt_event("GET", f"/proofs/{b}/{l}"))
    assert resp["statusCode"] == 200
    assert captured["batch_id"] == b and captured["leaf_hash"] == l and captured["tenant_id"] == "acme"


def test_stage_prefix_is_tolerated(monkeypatch):
    """A stage/base-path prefix before the resource tail still routes."""
    monkeypatch.setattr(handler, "list_proofs", lambda **kw: [])
    resp = handler.lambda_handler(_jwt_event("GET", "/prod/api/proofs"))
    assert resp["statusCode"] == 200


def test_unknown_route_is_404():
    assert handler.lambda_handler(_jwt_event("GET", "/widgets"))["statusCode"] == 404


def test_empty_path_is_404():
    assert handler.lambda_handler(_jwt_event("GET", "/"))["statusCode"] == 404


def test_non_get_rejected():
    assert handler.lambda_handler(_jwt_event("POST", "/usage"))["statusCode"] == 400


# ── error mapping (no internal leakage) ──────────────────────────────────────
def test_forbidden_maps_to_403_without_reason(monkeypatch):
    def raise_forbidden(**kw):
        raise _read_api.ForbiddenError("proof bundle is not owned by this tenant")

    monkeypatch.setattr(handler, "get_proof", raise_forbidden)
    resp = handler.lambda_handler(_jwt_event("GET", f"/proofs/{'1'*32}/{'a'*64}"))
    assert resp["statusCode"] == 403
    # The reason (which could confirm a foreign proof exists) is NOT echoed.
    assert json.loads(resp["body"])["error"] == "forbidden"


def test_rbac_denied_billing_cannot_read_proofs():
    """billing role → read-API's require_role raises ForbiddenError → 403."""
    resp = handler.lambda_handler(_jwt_event("GET", "/proofs", role="billing"))
    assert resp["statusCode"] == 403


def test_dashboard_error_maps_to_400(monkeypatch):
    def raise_bad(**kw):
        raise _read_api.DashboardError("period must be 'YYYY-MM'")

    monkeypatch.setattr(handler, "get_usage", raise_bad)
    resp = handler.lambda_handler(_jwt_event("GET", "/usage", query={"period": "bad"}))
    assert resp["statusCode"] == 400


def test_bad_limit_is_400():
    resp = handler.lambda_handler(_jwt_event("GET", "/proofs", query={"limit": "notint"}))
    assert resp["statusCode"] == 400


def test_usage_without_table_configured_is_unavailable(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USAGE_TABLE", raising=False)
    resp = handler.lambda_handler(_jwt_event("GET", "/usage", query={"period": "2026-06"}))
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "usage not available"


def test_handler_never_raises_on_internal_error(monkeypatch):
    def boom(**kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(handler, "get_usage", boom)
    resp = handler.lambda_handler(_jwt_event("GET", "/usage", query={"period": "2026-06"}))
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"])["error"] == "internal error"  # no stack trace leaked


def test_custom_claim_names_via_env(monkeypatch):
    """Tenant/role claim names are configurable (some IdPs use different names)."""
    monkeypatch.setenv("DASHBOARD_TENANT_CLAIM", "org")
    monkeypatch.setenv("DASHBOARD_ROLE_CLAIM", "rol")
    captured = {}

    def fake_usage(*, tenant_id, role, **kw):
        captured.update(tenant_id=tenant_id, role=role)
        return _read_api.UsageView(tenant_id, "studio", kw["period"], 0, 1000, 1000, False)

    monkeypatch.setattr(handler, "get_usage", fake_usage)
    ev = _jwt_event("GET", "/usage", query={"period": "2026-06"},
                    claims={"org": "acme", "rol": "admin"})
    handler.lambda_handler(ev)
    assert captured["tenant_id"] == "acme" and captured["role"] == "admin"


# ── coverage: alternate event shapes + edge routes ───────────────────────────
def test_rest_api_requestcontext_httpmethod(monkeypatch):
    """REST proxy puts the method at requestContext.httpMethod (not http.method)."""
    monkeypatch.setattr(handler, "list_proofs", lambda **kw: [])
    ev = {
        "path": "/proofs",
        "requestContext": {"httpMethod": "GET",
                           "authorizer": {"claims": {"custom:tenant_id": "acme", "custom:role": "viewer"}}},
    }
    assert handler.lambda_handler(ev)["statusCode"] == 200


def test_event_level_httpmethod(monkeypatch):
    """Oldest shape: httpMethod at the top level of the event."""
    monkeypatch.setattr(handler, "list_proofs", lambda **kw: [])
    ev = {
        "path": "/proofs",
        "httpMethod": "GET",
        "requestContext": {"authorizer": {"claims": {"custom:tenant_id": "acme", "custom:role": "viewer"}}},
    }
    assert handler.lambda_handler(ev)["statusCode"] == 200


def test_proofs_single_segment_is_404():
    """/proofs/{batch} without a leaf is not a valid resource."""
    resp = handler.lambda_handler(_jwt_event("GET", f"/proofs/{'1'*32}"))
    assert resp["statusCode"] == 404


def test_free_allowance_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv("DASHBOARD_FREE_ALLOWANCE", "not-a-number")
    captured = {}

    def fake_usage(*, tenant_id, role, free_allowance, **kw):
        captured["allowance"] = free_allowance
        return _read_api.UsageView(tenant_id, "studio", kw["period"], 0, free_allowance, free_allowance, False)

    monkeypatch.setattr(handler, "get_usage", fake_usage)
    handler.lambda_handler(_jwt_event("GET", "/usage", query={"period": "2026-06"}))
    assert captured["allowance"] == 1000  # default, not a crash


def test_authorizer_present_but_no_claims_is_401():
    """Authorizer block present but carrying neither jwt.claims nor claims → 401."""
    ev = {"rawPath": "/usage", "requestContext": {"http": {"method": "GET"}, "authorizer": {"lambda": {}}}}
    assert handler.lambda_handler(ev)["statusCode"] == 401


def test_query_params_null_handled(monkeypatch):
    """API Gateway sends queryStringParameters: null when there are none."""
    monkeypatch.setattr(handler, "get_usage",
                        lambda **kw: _read_api.UsageView("acme", "studio", "", 0, 1000, 1000, False))
    ev = _jwt_event("GET", "/usage", query=None)  # → get_usage with period="" → read-API would 400, but we stub
    # period missing → empty string passed through; stubbed usage returns 200
    assert handler.lambda_handler(ev)["statusCode"] == 200
