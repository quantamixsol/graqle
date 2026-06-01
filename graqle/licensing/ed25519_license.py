"""Ed25519-signed licence keys (WS-D D1a) — the asymmetric replacement for HMAC.

Why this exists (grounded in the WS-C C1 carve-out):
The legacy licence format (``manager.py``) is HMAC-SHA256 — symmetric. The same
secret verifies AND signs, so any verifier must hold the signing secret. Since
the Community wheel is now public (Apache-2.0) and ``graqle/licensing/`` ships in
it, an HMAC verifier embeds the forging secret — anyone could mint an ENTERPRISE
licence. (``keygen.py`` even warns: "embeds the HMAC signing secret … never
distribute to end users".)

Ed25519 closes that: the **private** signing key stays server-side (issuer only —
Stripe webhook / admin keygen, excluded from the Community wheel); the Community
wheel carries only the **public** verification key, which cannot forge anything.

This module composes the SHIPPED ``Ed25519KeyManifest``
(``graqle/governance/custody/ed25519_key_manifest.py``) — its windowed 3-state
``kid`` lifecycle (ACTIVE→RETIRED→REVOKED) gives us **kid-revocation for free**:
a REVOKED ``kid`` makes :meth:`Ed25519KeyManifest.verify` return ``False``, so
every licence that ``kid`` signed is invalidated at once.

Wire format (``v2`` licence)::

    base64url(canonical_json_payload) "." kid "." base64url(ed25519_signature)

The signature covers the canonical JSON of the payload. The ``kid`` travels in
the token (so the verifier knows which public key to check) and is itself part of
the signed payload (so it cannot be swapped). Payload fields::

    {format, license_id, tier, holder, email, issued_at, expires_at,
     features, nonce, kid}

* ``license_id`` — stable unique id (CRL revocation targets this).
* ``nonce`` — random per-issue value for replay protection (see
  :mod:`graqle.licensing.nonce_store`).
* ``format`` — ``"graqle-license-v2"`` (distinguishes from the legacy HMAC v1).

Pure stdlib + ``cryptography`` (already a hard dependency). Ships in Community —
it holds verification logic + the public key, never a private key.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Security observability (OWASP A09): verification REJECTIONS are logged at
# WARNING so a flood of failed/forged/revoked attempts is visible to incident
# response — WITHOUT changing the fail-closed return-None behaviour, and without
# logging the token itself (no secret/PII in logs).
logger = logging.getLogger("graqle.licensing.ed25519_license")

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    UnknownKidError,
)

__all__ = [
    "LICENSE_FORMAT_V2",
    "Ed25519LicenseError",
    "issue_ed25519_license",
    "parse_ed25519_license",
    "verify_ed25519_license",
]

LICENSE_FORMAT_V2 = "graqle-license-v2"

# Fields, in a fixed order, that constitute the signed payload. Canonicalised via
# json.dumps(sort_keys=True) so signer and verifier agree byte-for-byte.
_PAYLOAD_FIELDS = (
    "format",
    "license_id",
    "tier",
    "holder",
    "email",
    "issued_at",
    "expires_at",
    "features",
    "nonce",
    "kid",
)


class Ed25519LicenseError(Exception):
    """Raised when an ed25519 licence cannot be parsed or is structurally invalid."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic bytes for signing/verification — only the allowlisted fields.

    Projecting to ``_PAYLOAD_FIELDS`` (rather than signing the raw dict) means a
    verifier recomputes the signed message from exactly the fields it trusts, so
    an attacker cannot smuggle an unsigned extra field past the signature.
    """
    projected = {k: payload.get(k) for k in _PAYLOAD_FIELDS}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class _ParsedLicense:
    """The decoded (not-yet-trusted) parts of an ed25519 licence token."""

    payload: dict[str, Any]
    kid: str
    signature: bytes
    signed_message: bytes


def issue_ed25519_license(
    manifest: Ed25519KeyManifest,
    kid: str,
    *,
    license_id: str,
    tier: str,
    holder: str,
    email: str,
    issued_at: str,
    nonce: str,
    expires_at: str | None = None,
    features: list[str] | None = None,
    at: datetime | None = None,
) -> str:
    """Issue an ed25519-signed licence token (SERVER-SIDE only — needs a private key).

    ``manifest`` must hold the private key for ``kid`` (it won't in a Community
    install — issuance happens server-side). Timestamps are passed in (not read
    from the clock) so issuance is deterministic and testable.
    """
    payload: dict[str, Any] = {
        "format": LICENSE_FORMAT_V2,
        "license_id": license_id,
        "tier": tier,
        "holder": holder,
        "email": email,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "features": sorted(features or []),
        "nonce": nonce,
        "kid": kid,
    }
    message = _canonical_payload_bytes(payload)
    signature = manifest.sign(kid, message, at=at)  # raises if kid can't sign
    return ".".join(
        (_b64url_encode(message), kid, _b64url_encode(signature))
    )


def parse_ed25519_license(token: str) -> _ParsedLicense:
    """Decode a licence token into its parts WITHOUT verifying the signature.

    Raises :class:`Ed25519LicenseError` on any structural problem (wrong shape,
    bad base64, non-JSON payload, format mismatch, or a kid/payload-kid
    disagreement — which would be a tamper attempt).
    """
    if not isinstance(token, str) or token.count(".") != 2:
        raise Ed25519LicenseError("malformed ed25519 licence token (expected 3 dot-parts)")
    msg_b64, kid, sig_b64 = token.split(".")
    if not kid:
        raise Ed25519LicenseError("ed25519 licence token has empty kid")
    try:
        signed_message = _b64url_decode(msg_b64)
        signature = _b64url_decode(sig_b64)
        payload = json.loads(signed_message.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Ed25519LicenseError(f"undecodable ed25519 licence token: {exc}") from exc
    if not isinstance(payload, dict):
        raise Ed25519LicenseError("ed25519 licence payload is not a JSON object")
    if payload.get("format") != LICENSE_FORMAT_V2:
        raise Ed25519LicenseError(
            f"not a {LICENSE_FORMAT_V2} licence (format={payload.get('format')!r})"
        )
    # The kid in the token must equal the kid inside the signed payload — else an
    # attacker could route verification to a different key than the one signed.
    if payload.get("kid") != kid:
        raise Ed25519LicenseError("ed25519 licence kid mismatch (token vs signed payload)")
    # Recompute the signed message from the trusted field projection (defends
    # against smuggled unsigned fields).
    return _ParsedLicense(
        payload=payload,
        kid=kid,
        signature=signature,
        signed_message=_canonical_payload_bytes(payload),
    )


def verify_ed25519_license(
    token: str,
    manifest: Ed25519KeyManifest,
    *,
    at: datetime | None = None,
) -> dict[str, Any] | None:
    """Verify an ed25519 licence token. Return the trusted payload, or ``None``.

    Returns the payload dict ONLY if: the token parses, its ``kid`` is registered
    in ``manifest``, and ``manifest.verify`` trusts the signature at ``at`` (which
    enforces kid-revocation — a REVOKED kid always fails — and the kid's validity
    window). Returns ``None`` for any untrusted/forged/malformed token. Never
    raises on a bad token (a caller treats ``None`` as "no valid licence"); this
    is the security boundary, so it fails closed.

    NOTE: expiry, grace, nonce-replay, and CRL checks are layered on TOP of this
    by the manager — this function answers only "is the signature cryptographically
    trusted under a non-revoked kid".
    """
    when = at if at is not None else datetime.now(timezone.utc)
    try:
        parsed = parse_ed25519_license(token)
    except Ed25519LicenseError as exc:
        logger.warning("ed25519 licence rejected: malformed/invalid token (%s)", exc)
        return None
    try:
        trusted = manifest.verify(parsed.kid, parsed.signed_message, parsed.signature, at=when)
    except UnknownKidError:
        logger.warning("ed25519 licence rejected: unknown signing kid %r", parsed.kid)
        return None  # unknown signer => not trusted (fail closed)
    if not trusted:
        logger.warning(
            "ed25519 licence rejected: signature not trusted for kid %r "
            "(revoked kid, bad signature, or out-of-window)", parsed.kid
        )
        return None
    return parsed.payload
