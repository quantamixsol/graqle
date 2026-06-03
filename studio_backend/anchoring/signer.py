"""Producer-side ed25519 proof-bundle signer (BizQ S2, Studio backend).

The SDK ships the *verifier* (``verify_bundle``) but **no producer-side signer** —
``verify_bundle`` defines the signature contract (SD-001) and the verifier-internal
``_signed_message`` helper recomputes it, but nothing in the public SDK signs a
Merkle root to produce the ``signature`` block. The hosted anchoring worker is
the producer, so signing is the Studio backend's responsibility.

SD-001 (locked 2026-05-31): the ed25519 signature covers ``canon`` (RFC 8785 JCS)
of exactly these four fields::

    {"proof_format_version": <v>, "merkle_root": <root hex>, "kid": <kid>,
     "signed_at": <RFC3339 UTC>}

This module reconstructs that message from the **public** ``canon`` function (NOT
the verifier's private ``_signed_message``), so the producer is built on the
published contract and stays decoupled from verifier internals. A verifier
recomputes the identical bytes from the bundle's own values, so signer and
verifier agree byte-for-byte.

Key custody (ADR-215 §5, Harish-approved 2026-06-02): the ed25519 **private**
signing key lives in AWS Secrets Manager (never the public wheel — the forgery
invariant). This same key/custody is shared with licence issuance. The signer
fetches the raw 32-byte ed25519 seed from Secrets Manager, builds an in-memory
:class:`Ed25519KeyManifest`, and signs. The corresponding **public** key + ``kid``
are published to the Community trust source so anyone can verify offline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest
from graqle.governance.tamper_evidence.canonicalize import canon

logger = logging.getLogger("studio_backend.anchoring.signer")

# A signing key is trusted across a wide window at sign time; the bundle's
# signed_at is the trust instant a verifier checks. We register the key ACTIVE
# over a wide window so signing never trips the manifest's own window guard;
# real lifecycle/revocation is expressed in the PUBLISHED trust source (the
# verifier side), and via the CRL.
_WIDE_FROM = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIDE_UNTIL = datetime(9999, 12, 31, tzinfo=timezone.utc)


class SignerError(Exception):
    """Raised when the signer cannot be built or a root cannot be signed."""


def signed_message(proof_format_version: Any, merkle_root_hex: str, kid: str, signed_at: str) -> bytes:
    """Reconstruct the SD-001 signed message from the PUBLIC canon contract.

    Mirrors the verifier's reconstruction exactly (same four-field set, same
    ``canon``), but is built here from the published primitive so the producer
    does not depend on a verifier-private helper.
    """
    return canon(
        {
            "proof_format_version": proof_format_version,
            "merkle_root": merkle_root_hex,
            "kid": kid,
            "signed_at": signed_at,
        }
    )


@dataclass(frozen=True)
class RootSigner:
    """Signs Merkle roots into SD-001 ``signature`` blocks with an ed25519 key.

    Construct via :meth:`from_private_bytes` (raw 32-byte ed25519 seed, e.g. from
    Secrets Manager) or :meth:`from_private_key`. Immutable + holds the manifest
    so a single signer is reused across a batch.
    """

    kid: str
    _manifest: Ed25519KeyManifest
    _public_key: Ed25519PublicKey

    @classmethod
    def from_private_key(cls, kid: str, private_key: Ed25519PrivateKey) -> "RootSigner":
        if not isinstance(kid, str) or not kid:
            raise SignerError("kid must be a non-empty string")
        if not isinstance(private_key, Ed25519PrivateKey):
            raise SignerError("private_key must be an Ed25519PrivateKey")
        public_key = private_key.public_key()
        manifest = Ed25519KeyManifest()
        manifest.register(
            kid=kid,
            public_key=public_key,
            valid_from=_WIDE_FROM,
            valid_until=_WIDE_UNTIL,
            private_key=private_key,
        )
        return cls(kid=kid, _manifest=manifest, _public_key=public_key)

    @classmethod
    def from_private_bytes(cls, kid: str, raw_seed: bytes) -> "RootSigner":
        """Build a signer from a raw 32-byte ed25519 seed (e.g. Secrets Manager)."""
        if not isinstance(raw_seed, (bytes, bytearray)) or len(raw_seed) != 32:
            raise SignerError(
                f"raw_seed must be 32 ed25519 seed bytes, got "
                f"{len(raw_seed) if isinstance(raw_seed, (bytes, bytearray)) else type(raw_seed).__name__}"
            )
        try:
            priv = Ed25519PrivateKey.from_private_bytes(bytes(raw_seed))
        except Exception as exc:  # cryptography raises a variety of types
            raise SignerError(f"invalid ed25519 private seed: {exc}") from exc
        return cls.from_private_key(kid, priv)

    def sign_root(self, *, proof_format_version: Any, merkle_root_hex: str, signed_at: str) -> dict[str, Any]:
        """Produce the SD-001 ``signature`` block for a Merkle root.

        Returns ``{"alg": "ed25519", "kid": ..., "sig": <hex>, "signed_at": ...}``
        — exactly the shape ``verify_bundle`` expects.
        """
        if not isinstance(merkle_root_hex, str) or not merkle_root_hex:
            raise SignerError("merkle_root_hex must be a non-empty hex string")
        # Validate it is actually hex of SHA-256 length — refuse to sign a
        # malformed "root" (defence: a non-hex value would otherwise be signed as
        # an opaque string, producing a bundle a verifier could never bind to a
        # real Merkle root). A SHA-256 root is 32 bytes = 64 lowercase hex chars.
        if len(merkle_root_hex) != 64:
            raise SignerError("merkle_root_hex must be 64 hex chars (a SHA-256 root)")
        try:
            bytes.fromhex(merkle_root_hex)
        except ValueError as exc:
            raise SignerError("merkle_root_hex is not valid hexadecimal") from exc
        if not isinstance(signed_at, str) or not signed_at:
            raise SignerError("signed_at must be a non-empty RFC 3339 string")
        message = signed_message(proof_format_version, merkle_root_hex, self.kid, signed_at)
        try:
            sig = self._manifest.sign(self.kid, message)
        except Exception as exc:
            raise SignerError(f"failed to sign Merkle root: {exc}") from exc
        return {
            "alg": "ed25519",
            "kid": self.kid,
            "sig": sig.hex(),
            "signed_at": signed_at,
        }


def _sign_raw(signer: "RootSigner", message: bytes) -> bytes:
    """Raw ed25519 signature over ``message`` (used for the Rekor hashedrekord).

    Distinct from :meth:`RootSigner.sign_root` (which signs the SD-001 canonical
    message): Rekor's ``hashedrekord`` records a signature over the *artifact*
    (here the Merkle root bytes), so we sign those bytes directly.
    """
    try:
        return signer._manifest.sign(signer.kid, message)
    except Exception as exc:
        raise SignerError(f"failed to raw-sign for Rekor: {exc}") from exc


def _public_key_pem(signer: "RootSigner") -> bytes:
    """The signer's public key as a PEM (for the Rekor hashedrekord publicKey)."""
    from cryptography.hazmat.primitives import serialization

    return signer._public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_signer_from_secrets_manager(
    *,
    secret_id: str,
    kid: str,
    client: Any = None,
    region_name: str = "eu-central-1",
) -> RootSigner:
    """Build a :class:`RootSigner` from an ed25519 seed in AWS Secrets Manager.

    The secret value is the raw 32-byte ed25519 seed, stored as a hex string
    (``SecretString``) or raw binary (``SecretBinary``). ``client`` is injectable
    (a boto3 ``secretsmanager`` client) so this is testable without AWS — in
    production it is created lazily.

    The PRIVATE key never leaves this process's memory; only the public key + kid
    are published to the Community trust source.
    """
    if client is None:  # pragma: no cover - exercised only in real AWS
        import boto3

        client = boto3.client("secretsmanager", region_name=region_name)

    try:
        resp = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        raise SignerError(f"could not fetch signing key from Secrets Manager: {exc}") from exc

    raw = _seed_bytes_from_secret(resp)
    return RootSigner.from_private_bytes(kid, raw)


def _seed_bytes_from_secret(resp: dict[str, Any]) -> bytes:
    """Extract the 32-byte ed25519 seed from a Secrets Manager response.

    Accepts ``SecretBinary`` (raw 32 bytes) or ``SecretString`` (64-char hex).
    """
    binary = resp.get("SecretBinary")
    if binary:
        return bytes(binary)
    text = resp.get("SecretString")
    if isinstance(text, str) and text:
        stripped = text.strip()
        try:
            return bytes.fromhex(stripped)
        except ValueError as exc:
            raise SignerError(
                "SecretString must be a 64-char hex ed25519 seed"
            ) from exc
    raise SignerError("Secrets Manager response has neither SecretBinary nor SecretString")


__all__ = [
    "SignerError",
    "RootSigner",
    "signed_message",
    "load_signer_from_secrets_manager",
]
