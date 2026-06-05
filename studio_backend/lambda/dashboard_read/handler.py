"""Authenticated dashboard read Lambda (BizQ S2, Studio backend) — Phase 5.

The HTTP surface over the Phase-5 read-API
(:mod:`studio_backend.dashboard.read_api`): a tenant's usage widget and proof
browser. Unlike the *free, no-auth* verify-at-scale Lambda, this endpoint is
**authenticated and tenant-scoped** — it serves a logged-in Studio user their
OWN tenant's data and nothing else.

THE SECURITY BOUNDARY: identity comes from the authorizer, never the request
-----------------------------------------------------------------------------
``tenant_id`` and ``role`` are read EXCLUSIVELY from the API-Gateway / Function-URL
authorizer's verified JWT claims (``event.requestContext.authorizer.jwt.claims``
for an HTTP-API JWT authorizer, or ``...authorizer.claims`` for a REST-API /
Cognito authorizer). They are NEVER read from the request body, query string, or
headers — otherwise any caller could set ``tenant_id`` and read another tenant's
proofs. The upstream authorizer is the trust root; this handler trusts only it.

Fail-closed: a request with no resolvable authenticated tenant is a 401, before
any store is touched. An unknown role is denied by the read-API's fail-closed
RBAC (``require_role``). The read-API itself re-checks tenant ownership on every
proof read (defence-in-depth — even a forged claim can't cross tenants because
``get_proof`` compares the bundle's own ``record.tenant_id``).

Deployment shape: a STANDALONE Lambda outside the importable ``graqle`` package
(``studio_backend/``), so it never ships in the public Community wheel — exactly
like the other ``studio_backend/lambda/*`` handlers. It imports ONLY the
read-API (which imports no verifier, no server, no studio — moat M2 preserved).

Routing (HTTP API / Function URL, GET)
--------------------------------------
* ``GET /usage?period=YYYY-MM``                  → :func:`read_api.get_usage`
* ``GET /proofs?limit=N``                        → :func:`read_api.list_proofs`
* ``GET /proofs/{batch_id}/{leaf_hash}``         → :func:`read_api.get_proof`

Config via env:
* ``DASHBOARD_USAGE_TABLE``    — DynamoDB usage table (per-tenant monthly count).
* ``DASHBOARD_S3_BUCKET``      — proof-bundle bucket (default ``graqle-graphs-eu``).
* ``DASHBOARD_S3_PREFIX``      — key prefix (default ``proofs``).
* ``DASHBOARD_FREE_ALLOWANCE`` — free anchors/tenant/month (default 1000).
* ``DASHBOARD_REGION``         — AWS region (default ``eu-central-1``).
* ``DASHBOARD_TENANT_CLAIM``   — claim name carrying the tenant id (default
                                 ``custom:tenant_id``).
* ``DASHBOARD_ROLE_CLAIM``     — claim name carrying the role (default
                                 ``custom:role``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from studio_backend.dashboard.read_api import (
    DashboardError,
    ForbiddenError,
    get_proof,
    get_usage,
    list_proofs,
)

logger = logging.getLogger("studio_backend.dashboard_read")
logging.getLogger().setLevel(logging.INFO)

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404

_DEFAULT_BUCKET = "graqle-graphs-eu"
_DEFAULT_PREFIX = "proofs"
_DEFAULT_REGION = "eu-central-1"
_DEFAULT_FREE_ALLOWANCE = 1000
_DEFAULT_TENANT_CLAIM = "custom:tenant_id"
_DEFAULT_ROLE_CLAIM = "custom:role"
# A list call defaults small; cap what a single request can ask the read-API to
# scan (the read-API also bounds its own page count).
_MAX_LIST_LIMIT = 200


class AuthError(Exception):
    """No authenticated tenant could be resolved from the request (→ 401)."""


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _claims(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the verified authorizer claims (the ONLY trusted identity source).

    Supports both shapes:
      * HTTP API (payload v2) JWT authorizer → requestContext.authorizer.jwt.claims
      * REST API / Cognito authorizer        → requestContext.authorizer.claims
    Returns ``{}`` when no authorizer context is present (caller maps to 401);
    NEVER falls back to body/query/header identity.
    """
    if not isinstance(event, dict):
        return {}
    rc = event.get("requestContext")
    authorizer = rc.get("authorizer") if isinstance(rc, dict) else None
    if not isinstance(authorizer, dict):
        return {}
    jwt = authorizer.get("jwt")
    if isinstance(jwt, dict) and isinstance(jwt.get("claims"), dict):
        return jwt["claims"]
    if isinstance(authorizer.get("claims"), dict):
        return authorizer["claims"]
    return {}


def _identity(event: dict[str, Any]) -> tuple[str, str]:
    """Resolve (tenant_id, role) from authorizer claims. Raise AuthError if absent.

    Identity is taken ONLY from the verified claims — this is the security
    boundary. A missing/blank tenant claim is a 401 (fail-closed: no anonymous
    tenant). A missing role claim defaults to the least-privileged ``viewer``
    (it can still only ever read its OWN tenant's data, never escalate).
    """
    claims = _claims(event)
    tenant_claim = _env("DASHBOARD_TENANT_CLAIM", _DEFAULT_TENANT_CLAIM)
    role_claim = _env("DASHBOARD_ROLE_CLAIM", _DEFAULT_ROLE_CLAIM)

    tenant_id = claims.get(tenant_claim)
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise AuthError("no authenticated tenant in request")

    role = claims.get(role_claim)
    if not isinstance(role, str) or not role.strip():
        role = "viewer"  # least privilege; RBAC + tenant scoping still apply
    return tenant_id.strip(), role.strip()


def _route(event: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (method, path_segments) for both HTTP-API v2 and REST/Function-URL.

    Path segments are the non-empty parts after an optional leading ``/api`` or
    stage prefix is dropped down to the dashboard path. We only key off the tail
    (``usage`` / ``proofs`` / ``proofs/{b}/{l}``), so stage/base-path prefixes are
    harmless.
    """
    method = "GET"
    rc = event.get("requestContext") if isinstance(event, dict) else None
    if isinstance(rc, dict):
        http = rc.get("http")
        if isinstance(http, dict) and isinstance(http.get("method"), str):
            method = http["method"]
        elif isinstance(rc.get("httpMethod"), str):
            method = rc["httpMethod"]
    elif isinstance(event, dict) and isinstance(event.get("httpMethod"), str):
        method = event["httpMethod"]

    raw = ""
    if isinstance(event, dict):
        raw = event.get("rawPath") or event.get("path") or ""
    segments = [s for s in str(raw).split("/") if s]
    return method.upper(), segments


def _query(event: dict[str, Any]) -> dict[str, str]:
    if not isinstance(event, dict):
        return {}
    q = event.get("queryStringParameters")
    return q if isinstance(q, dict) else {}


def handle(event: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Resolve identity, route, and call the read-API. Returns (status, payload).

    Pure-ish (delegates I/O to the read-API's injectable clients via env), and
    maps every error to a status WITHOUT leaking internals:
      * AuthError      → 401  (no authenticated tenant)
      * ForbiddenError → 403  (RBAC denied / cross-tenant)
      * DashboardError → 400/404 (bad input / not found)
    """
    try:
        tenant_id, role = _identity(event)
    except AuthError as exc:
        logger.info("dashboard read unauthenticated: %s", exc)
        return HTTP_UNAUTHORIZED, {"error": "authentication required"}

    method, segments = _route(event)
    if method != "GET":
        return HTTP_BAD_REQUEST, {"error": "only GET is supported"}

    # Find the dashboard resource at the tail of the path.
    if not segments:
        return HTTP_NOT_FOUND, {"error": "unknown route"}
    region = _env("DASHBOARD_REGION", _DEFAULT_REGION)

    try:
        if segments[-1] == "usage" or (len(segments) >= 1 and "usage" in segments):
            return _handle_usage(tenant_id, role, _query(event), region)
        if "proofs" in segments:
            idx = segments.index("proofs")
            tail = segments[idx + 1 :]
            if len(tail) >= 2:
                # GET /proofs/{batch_id}/{leaf_hash}
                return _handle_get_proof(tenant_id, role, tail[0], tail[1], region)
            if not tail:
                # GET /proofs
                return _handle_list_proofs(tenant_id, role, _query(event), region)
            return HTTP_NOT_FOUND, {"error": "unknown proofs route"}
    except ForbiddenError:
        # Do NOT echo the reason (could confirm another tenant's proof exists).
        return HTTP_FORBIDDEN, {"error": "forbidden"}
    except DashboardError as exc:
        # Log the precise read-API reason server-side; return a SAFE, stable
        # message to the caller (never echo the raw exception — defence in depth
        # so a future read-API change can't leak internals through this surface).
        logger.info("dashboard read bad request: %s", exc)
        return HTTP_BAD_REQUEST, {"error": "invalid request"}

    return HTTP_NOT_FOUND, {"error": "unknown route"}


def _handle_usage(
    tenant_id: str, role: str, q: dict[str, str], region: str | None
) -> tuple[int, dict[str, Any]]:
    usage_table = _env("DASHBOARD_USAGE_TABLE")
    if not usage_table:
        logger.error("DASHBOARD_USAGE_TABLE not configured")
        return HTTP_BAD_REQUEST, {"error": "usage not available"}
    period = q.get("period") or ""
    allowance = _free_allowance()
    view = get_usage(
        tenant_id=tenant_id,
        role=role,
        period=period,
        usage_table=usage_table,
        free_allowance=allowance,
        region_name=region or _DEFAULT_REGION,
    )
    return HTTP_OK, {
        "tenant_id": view.tenant_id,
        "edition": view.edition,
        "period": view.period,
        "used": view.used,
        "allowance": view.allowance,
        "remaining": view.remaining,
        "over_allowance": view.over_allowance,
    }


def _handle_list_proofs(
    tenant_id: str, role: str, q: dict[str, str], region: str | None
) -> tuple[int, dict[str, Any]]:
    limit = 50
    raw_limit = q.get("limit")
    if raw_limit is not None:
        try:
            limit = max(1, min(_MAX_LIST_LIMIT, int(raw_limit)))
        except (TypeError, ValueError):
            return HTTP_BAD_REQUEST, {"error": "limit must be an integer"}
    proofs = list_proofs(
        tenant_id=tenant_id,
        role=role,
        bucket=_env("DASHBOARD_S3_BUCKET", _DEFAULT_BUCKET),
        prefix=_env("DASHBOARD_S3_PREFIX", _DEFAULT_PREFIX),
        limit=limit,
        region_name=region or _DEFAULT_REGION,
    )
    return HTTP_OK, {"proofs": proofs, "count": len(proofs)}


def _handle_get_proof(
    tenant_id: str, role: str, batch_id: str, leaf_hash: str, region: str | None
) -> tuple[int, dict[str, Any]]:
    bundle = get_proof(
        tenant_id=tenant_id,
        role=role,
        batch_id=batch_id,
        leaf_hash=leaf_hash,
        bucket=_env("DASHBOARD_S3_BUCKET", _DEFAULT_BUCKET),
        prefix=_env("DASHBOARD_S3_PREFIX", _DEFAULT_PREFIX),
        region_name=region or _DEFAULT_REGION,
    )
    return HTTP_OK, {"proof": bundle}


def _free_allowance() -> int:
    try:
        return int(_env("DASHBOARD_FREE_ALLOWANCE", str(_DEFAULT_FREE_ALLOWANCE)))
    except (TypeError, ValueError):
        return _DEFAULT_FREE_ALLOWANCE


def _json_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Lambda Function URL / API Gateway proxy response.

    CORS is the Function URL config's job (ADR-056, single source of truth) — no
    Access-Control-* headers here (duplicate CORS headers make browsers reject
    the response).
    """
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entrypoint. Never raises out of the handler (fail-closed)."""
    try:
        status, payload = handle(event)
        return _json_response(status, payload)
    except Exception:  # pragma: no cover - last-resort guard
        logger.exception("dashboard read handler unexpected error")
        return _json_response(500, {"error": "internal error"})


handler = lambda_handler


__all__ = [
    "HTTP_OK",
    "HTTP_BAD_REQUEST",
    "HTTP_UNAUTHORIZED",
    "HTTP_FORBIDDEN",
    "HTTP_NOT_FOUND",
    "AuthError",
    "handle",
    "lambda_handler",
    "handler",
]
