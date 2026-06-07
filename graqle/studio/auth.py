# V-A1B-NATIVE-001: new-file creation via native Write — graq_write rejected
# absolute source-tree path ("path escapes project root", S-010 capability gap:
# MCP resolves paths against site-packages, not graqle-sdk/). Logged per CG-G4/S-010.
"""Studio request identity — the cross-tenant trust root (A1b).

THE SECURITY BOUNDARY: identity comes from a cryptographically verified token,
never from a raw request header.
---------------------------------------------------------------------------
The cloud Studio backend loads a caller's graph from
``graphs/{sha256(lower(email))}/{project}/graqle.json`` in S3. The *email* is
therefore the tenant key — whoever controls it reads that tenant's graph. So it
MUST come from a verified source.

Historically three sites trusted the raw ``x-user-email`` header (or base64-
decoded a JWT *without* checking its signature) and fed it straight into the S3
key. On a public Lambda Function URL the caller controls every header, so a
forged ``x-user-email`` (or a self-minted ``alg:none`` token) read ANY tenant's
graph — OWASP A01 broken access control. This module closes that hole.

:func:`verified_email_from_request` is the single trust root. It verifies the
caller's Cognito ID token (RS256, against the pool's JWKS) and returns the email
from the *verified* claim — or ``None``. It NEVER raises and ALWAYS fails CLOSED:
every failure path returns ``None`` (→ no graph, treated as unauthenticated), so
a masked error can only DENY access, never grant it.

``tenant_id = sha256(lower(email))`` is the product-wide tenant convention
(matches ``graqle._email_hash`` and the dashboard_read handler). See ADR-PHASE5-001
and lesson PUBLIC-FUNCTION-URL-CLAIMS-BYPASS (lesson_20260607T063254).

Trusting the raw header is opt-in only
--------------------------------------
``GRAQLE_TRUST_PROXY_EMAIL=true`` re-enables the legacy "trust ``x-user-email``"
behaviour, for the deployment shape where a REAL upstream authorizer (API
Gateway / Cognito / a trusted reverse proxy) has already verified the user and
overwrites/strips client-supplied values. It is OFF by default, so a bare public
Function URL is JWT-only and fails closed. NEVER set it on a public Function URL.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# A pragmatic email shape check (defence in depth — the value is also hashed, but
# we never want a path/control-char value reaching the S3 key). Mirrors the
# proxy-layer ``safeHeaderValue`` intent on the Studio side.
_EMAIL_RE = re.compile(r"\A[^\s@\x00-\x1f]{1,64}@[^\s@\x00-\x1f]{1,255}\.[^\s@\x00-\x1f]{2,}\Z")

# ── Cognito ID-token verification (the real security boundary on a public URL) ──
# A Cognito user-pool id is NOT a secret — it is public metadata (it appears in
# every token's ``iss`` and in the JWKS URL the client fetches). It is provided
# env-overridable so non-prod stacks can point at a different pool.
_DEFAULT_REGION = "eu-central-1"
_COGNITO_REGION = os.environ.get("COGNITO_REGION") or _DEFAULT_REGION
_COGNITO_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID") or "eu-central-1_RwEo6O1ow"
_COGNITO_ISS = f"https://cognito-idp.{_COGNITO_REGION}.amazonaws.com/{_COGNITO_POOL_ID}"
_COGNITO_JWKS_URL = f"{_COGNITO_ISS}/.well-known/jwks.json"

# Module-level cached JWKS client (PyJWKClient caches keys across calls, so a warm
# Lambda reuses them — no JWKS fetch per request). Built lazily on first use.
_jwks_client: Any = None


def _get_jwks_client() -> Any:
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient

        _jwks_client = PyJWKClient(_COGNITO_JWKS_URL)
    return _jwks_client


def _trust_proxy_email() -> bool:
    """Whether to trust the raw ``x-user-email`` header for identity.

    MUST be False (the default) for a public Function URL: there the caller
    controls every header, so a raw ``x-user-email`` is forgeable. Set
    ``GRAQLE_TRUST_PROXY_EMAIL=true`` ONLY when a real upstream authorizer /
    trusted reverse proxy fronts the backend and has already verified the user.
    """
    return (os.environ.get("GRAQLE_TRUST_PROXY_EMAIL", "false") or "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _bearer_token(request: Any) -> str | None:
    """Extract a Bearer token from the request's Authorization header.

    Header names are case-insensitive per RFC 7230; Starlette/FastAPI headers
    already fold case, but we are defensive in case a plain dict is passed.
    """
    try:
        headers = request.headers
    except Exception:  # noqa: BLE001 - hostile/odd request object → no token
        return None
    auth = None
    try:
        auth = headers.get("authorization")
    except Exception:  # noqa: BLE001
        auth = None
    if not isinstance(auth, str):
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    # Some clients send the bare token with no scheme.
    if len(parts) == 1 and parts[0].count(".") == 2 and parts[0].strip():
        return parts[0].strip()
    return None


def _verify_bearer(request: Any) -> dict[str, Any] | None:
    """Cryptographically verify a Cognito ID token; return its claims or None.

    Never raises and ALWAYS fails CLOSED: every failure path returns None. This
    is the trust root when the backend is on a public Function URL.
    """
    token = _bearer_token(request)
    if not token:
        return None

    try:
        import jwt  # PyJWT
        from jwt import PyJWKClientError
    except Exception as exc:  # noqa: BLE001 - PyJWT not installed → cannot verify → deny
        logger.error("studio auth: PyJWT unavailable, cannot verify token (%s)", type(exc).__name__)
        return None

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_COGNITO_ISS,
            # Cognito ID tokens carry ``aud`` = the app client id; multiple Studio
            # clients exist, so we do not pin one here — we verify everything else
            # and check ``token_use`` explicitly below.
            options={"verify_aud": False, "require": ["exp", "iss"]},
        )
    except jwt.InvalidTokenError as exc:
        # Normal reject: bad signature, expired, wrong issuer, malformed, missing
        # required claim, OR ``alg:none``/HS256 (algorithms=["RS256"] forbids them).
        logger.info("studio auth: bearer token rejected (%s)", type(exc).__name__)
        return None
    except PyJWKClientError as exc:
        # Could not obtain the signing key (unknown kid / JWKS unreachable). We
        # cannot assert validity, so fail closed — never open.
        logger.warning("studio auth: could not resolve signing key (%s)", type(exc).__name__)
        return None
    except Exception as exc:  # noqa: BLE001 - unexpected: still fail closed, but loudly
        logger.error("studio auth: unexpected token-verification error (%s)", type(exc).__name__)
        return None

    if claims.get("token_use") != "id":
        logger.info("studio auth: bearer token is not an ID token")
        return None
    return claims


def _valid_email(value: Any) -> str | None:
    """Return a normalised email if ``value`` is a well-formed email, else None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _EMAIL_RE.match(candidate):
        return None
    return candidate.lower()


def verified_email_from_request(request: Any) -> str | None:
    """Resolve the caller's email from a VERIFIED source, or return None.

    Order:
      1. A cryptographically verified Cognito ID token's ``email`` claim — the
         only trustworthy identity on a public Function URL.
      2. ONLY IF ``GRAQLE_TRUST_PROXY_EMAIL=true`` (behind a real authorizer):
         the raw ``x-user-email`` header.

    Fails CLOSED: any failure / malformed / forged / absent path → None, which
    callers treat as "no tenant graph" (unauthenticated). Never raises.
    """
    # 1. Verified token (the trust root).
    claims = _verify_bearer(request)
    if claims is not None:
        email = _valid_email(claims.get("email"))
        if email:
            return email
        logger.info("studio auth: verified token has no usable email claim")
        # A verified token with no email is still unauthenticated — do NOT fall
        # through to the raw header (that would defeat verification).
        return None

    # 2. Opt-in proxy trust (only behind a real upstream authorizer).
    #
    # This is an INTENTIONAL bypass of JWT verification (graq_review security:
    # OWASP A01). It is gated behind an env flag an operator must explicitly set
    # for the behind-an-authorizer shape, and even then the value is shape-
    # validated as an email. To make a production misconfiguration LOUD (the flag
    # must NEVER be set on a public Function URL), every USE of this path emits a
    # WARNING — a forged identity here would surface immediately in logs.
    if _trust_proxy_email():
        try:
            raw = request.headers.get("x-user-email", "")
        except Exception:  # noqa: BLE001
            raw = ""
        email = _valid_email(raw)
        if email:
            logger.warning(
                "studio auth: identity taken from UNVERIFIED x-user-email header "
                "because GRAQLE_TRUST_PROXY_EMAIL is set — this is SAFE ONLY behind "
                "a real upstream authorizer, NEVER on a public Function URL"
            )
            return email
        if raw:
            logger.info("studio auth: GRAQLE_TRUST_PROXY_EMAIL set but x-user-email malformed")
    return None


def tenant_hash(email: str) -> str:
    """``sha256(lower(email))`` — the product-wide tenant key (S3 path segment)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


# ── team-aware S3 owner resolution (Track B, B2.2) ──
# The S3 graph key is ``graphs/{owner}/{project}/graqle.json``. ``owner`` is
# normally ``sha256(lower(email))`` (the caller's own graph). When the caller is
# an ACTIVE member of a team AND explicitly asks for team scope (header
# ``x-graph-scope: team``), ``owner`` becomes ``team-{team_id}`` so they read the
# SHARED team graph. Membership is resolved from the registry keyed by the
# VERIFIED email's hash — never a client-supplied team id — so a forged scope
# header can only ever resolve to a team the caller actually belongs to.

_TEAM_SCOPE_VALUES = ("team", "shared")


def _wants_team_scope(request: Any) -> bool:
    try:
        scope = request.headers.get("x-graph-scope", "")
    except Exception:  # noqa: BLE001
        return False
    return isinstance(scope, str) and scope.strip().lower() in _TEAM_SCOPE_VALUES


def resolve_graph_owner_prefix(request: Any, registry: Any = None) -> str | None:
    """Return the S3 owner segment for the caller, or None if unauthenticated.

    * No verified email → None (caller gets no per-tenant graph; same as before).
    * ``x-graph-scope: team`` AND the verified caller is an ACTIVE team member →
      ``team-{team_id}`` (the shared graph).
    * Otherwise → ``sha256(lower(email))`` (the caller's own graph — unchanged
      default behaviour; team resolution NEVER changes the self path implicitly).

    Fails CLOSED to the SELF prefix on any registry error — a team lookup failure
    must never deny a user their own graph, and must never grant a team graph
    without an active membership.
    """
    email = verified_email_from_request(request)
    if not email:
        return None

    self_prefix = tenant_hash(email)
    if not _wants_team_scope(request):
        return self_prefix

    try:
        from graqle.cloud.team_registry import TeamRegistry

        reg = registry if registry is not None else TeamRegistry()
        membership = reg.resolve_team_for_member(self_prefix)
    except Exception as exc:  # noqa: BLE001 - registry unavailable → fall back to self
        logger.warning(
            "studio auth: team resolve failed, using self graph (%s)", type(exc).__name__
        )
        return self_prefix

    if membership is not None and getattr(membership, "team_id", None):
        return membership.team_id  # already a validated 'team-<slug>'
    # Asked for team scope but not an active member → their own graph (not denied).
    return self_prefix


__all__ = ["verified_email_from_request", "tenant_hash", "resolve_graph_owner_prefix"]
