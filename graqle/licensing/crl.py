"""Ed25519-signed Certificate/Licence Revocation List (WS-D D1d).

A CRL lets the issuer revoke INDIVIDUAL licences (by ``license_id``) without
waiting for them to expire — the per-licence complement to ``kid``-revocation
(which kills every licence a compromised key signed at once).

The CRL is itself **ed25519-signed** (reusing :class:`Ed25519KeyManifest`), so an
air-gapped / offline install can import a manually-fetched CRL and trust it
**only if the signature verifies** — never a plain, unauthenticated import
(sentinel hardening: integrity-verified, never plain). Wire format mirrors the
licence token::

    base64url(canonical_json_body) "." kid "." base64url(ed25519_signature)

Body::

    {format, issued_at, sequence, revoked_license_ids: [...], kid}

* ``sequence`` — monotonically increasing; a verifier rejects a CRL whose
  sequence is older than the last one it accepted (rollback / replay defence).
* ``revoked_license_ids`` — the set of revoked ``license_id`` values.

Pure stdlib + ``cryptography``. Ships in Community (verification + public key
only — it can check a CRL but cannot forge one).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from graqle.governance.custody.ed25519_key_manifest import (
    Ed25519KeyManifest,
    UnknownKidError,
)

__all__ = [
    "CRL_FORMAT_V1",
    "CRLError",
    "issue_crl",
    "verify_crl",
    "RevocationList",
]

CRL_FORMAT_V1 = "graqle-crl-v1"

_BODY_FIELDS = ("format", "issued_at", "sequence", "revoked_license_ids", "kid")


class CRLError(Exception):
    """Raised when a CRL cannot be parsed or is structurally invalid."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _canonical_body(body: dict[str, Any]) -> bytes:
    projected = {k: body.get(k) for k in _BODY_FIELDS}
    # revoked_license_ids is order-insensitive; sort for a deterministic signature.
    rids = projected.get("revoked_license_ids")
    if isinstance(rids, list):
        projected["revoked_license_ids"] = sorted(rids)
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


class RevocationList:
    """A verified, in-memory revocation set with monotonic-sequence enforcement.

    Holds the trusted CRL body after verification. :meth:`is_revoked` is the
    hot-path check the licence manager calls per verification.
    """

    def __init__(self, revoked_license_ids: set[str], sequence: int, issued_at: str) -> None:
        self._revoked = set(revoked_license_ids)
        self.sequence = sequence
        self.issued_at = issued_at

    def is_revoked(self, license_id: str | None) -> bool:
        """True iff ``license_id`` is on the revocation list. ``None`` is never revoked."""
        return license_id is not None and license_id in self._revoked

    @property
    def count(self) -> int:
        return len(self._revoked)


def issue_crl(
    manifest: Ed25519KeyManifest,
    kid: str,
    *,
    issued_at: str,
    sequence: int,
    revoked_license_ids: list[str],
    at: datetime | None = None,
) -> str:
    """Issue an ed25519-signed CRL token (SERVER-SIDE only — needs a private key)."""
    if not isinstance(sequence, int) or sequence < 0:
        raise CRLError("CRL sequence must be a non-negative int")
    body: dict[str, Any] = {
        "format": CRL_FORMAT_V1,
        "issued_at": issued_at,
        "sequence": sequence,
        "revoked_license_ids": sorted(set(revoked_license_ids)),
        "kid": kid,
    }
    message = _canonical_body(body)
    signature = manifest.sign(kid, message, at=at)
    return ".".join((_b64url_encode(message), kid, _b64url_encode(signature)))


def verify_crl(
    token: str,
    manifest: Ed25519KeyManifest,
    *,
    min_sequence: int = -1,
    at: datetime | None = None,
) -> RevocationList | None:
    """Verify a signed CRL token. Return a :class:`RevocationList`, or ``None``.

    Returns ``None`` (never raises on a bad token — fail closed) if: the token is
    malformed, the ``kid`` is unknown/untrusted/REVOKED, the signature is invalid,
    or ``sequence <= min_sequence`` (rollback/replay defence — pass the last
    accepted sequence as ``min_sequence`` so an older CRL cannot un-revoke a
    licence). A trusted, fresh CRL yields the revocation set.
    """
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    msg_b64, kid, sig_b64 = token.split(".")
    if not kid:
        return None
    try:
        message = _b64url_decode(msg_b64)
        signature = _b64url_decode(sig_b64)
        body = json.loads(message.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or body.get("format") != CRL_FORMAT_V1:
        return None
    if body.get("kid") != kid:
        return None  # token kid vs signed-body kid mismatch => tamper
    seq = body.get("sequence")
    if not isinstance(seq, int) or seq <= min_sequence:
        return None  # stale/rollback CRL rejected
    rids = body.get("revoked_license_ids")
    if not isinstance(rids, list) or not all(isinstance(r, str) for r in rids):
        return None
    # Recompute the signed message from the trusted field projection.
    recomputed = _canonical_body(body)
    try:
        trusted = manifest.verify(kid, recomputed, signature, at=at)
    except UnknownKidError:
        return None
    if not trusted:
        return None
    return RevocationList(set(rids), seq, str(body.get("issued_at", "")))
