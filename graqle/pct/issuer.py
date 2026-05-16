"""PCT issuer — mint a Proof Claims Token (JWS, RS256) for a downstream data flow.

Implements ADR-205 §2.3. The issuer:
    1. Validates the request payload against the vendored OPSF
       ``pct_v0_1.json`` schema before signing.
    2. Refuses MD5 / SHA-1 hash algorithms (per OPSF spec).
    3. Embeds ``kid`` in the JWS header so downstream verifiers can
       resolve the operator's signing key via
       ``.well-known/pct-keys.json`` (CR-011 / R25-EU05 ships the full
       custody surface; here the caller supplies the key directly).
    4. Returns a compact-form JWS string.

The issuer NEVER imports a GraQle-internal module that touches
trade-secret patterns (Q-function weights, AGREEMENT_THRESHOLD, etc.).
This is enforced by ``tests/test_pct/test_no_internal_trade_secret_import.py``.

References:
    - ADR-205 §2.3 (issuer API contract)
    - OPSF PCT spec README: "A PCT is a structured, cryptographically
      signed object — inspired by the JSON Web Token (JWT) model — that
      travels with data through systems and pipelines."
    - opsf-org/pct-spec@develop/schema/pct-schema-0.1.json (vendored at
      :mod:`graqle.pct.schema.pct_v0_1`)
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# ---------------------------------------------------------------------------
# Vendored OPSF schema (loaded once at module import)
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).parent / "schema" / "pct_v0_1.json"


def _load_schema() -> dict[str, Any]:
    """Load vendored OPSF pct_v0_1.json once per process."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


_PCT_SCHEMA = _load_schema()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hash algorithms MD5 and SHA-1 are PROHIBITED by the OPSF spec.
_PROHIBITED_HASH_ALGORITHMS: frozenset[str] = frozenset({"md5", "sha-1", "sha1"})

#: Algorithms accepted in the JWS header (RS256 baseline per OPSF spec).
_ACCEPTED_JWS_ALGORITHMS: frozenset[str] = frozenset({"RS256"})

#: Default validity window when ``valid_for_seconds`` not supplied (30 days).
_DEFAULT_VALIDITY_SECONDS: int = 30 * 24 * 3600


# ---------------------------------------------------------------------------
# Request dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PctIssueRequest:
    """Inputs to mint a PCT for a downstream data flow.

    Mirrors the mandatory fields of OPSF ``pct-schema-0.1.json``. The
    ``extensions`` field accepts arbitrary ``x-{framework}:{field}``
    keys per OPSF extension-namespace convention; for the EU AI Act
    extension see :mod:`graqle.pct.extensions.x_ai_eu`.

    The dataclass is frozen so a request, once constructed, cannot be
    mutated between schema validation and signing.

    Attributes:
        subject_id: Identifier for the dataset, data flow, or
            processing subject. Free-form string.
        subject_type: Category of the subject. Common values:
            ``"ai_interaction"``, ``"dataset"``, ``"data_flow"``.
        data_origin: ISO 3166-1 alpha-2 country code of the jurisdiction
            where the data originated.
        data_categories: Categories of data present in the payload.
        lawful_basis: ``{"bases": [...], "framework": "..."}`` per OPSF
            schema.
        allowed_purposes: Purposes for which the data may be used.
        jurisdiction_rules: ``{"permitted_regions": [...],
            "residency_required": bool, ...}``.
        data_hash: Cryptographic hash of the canonicalised data payload
            at the time of PCT issuance.
        hash_algorithm: Hashing algorithm used. MD5 and SHA-1 are
            prohibited; the issuer rejects requests using them.
        hash_scope: ``"full_payload"`` (entire payload) or
            ``"merkle_root"`` (Merkle root of a structured set).
        retention_limit: Optional ISO 8601 duration (e.g. ``"P3Y"``).
        automated_decision_flag: Set ``True`` if the data may be used
            in automated decision-making subject to Article 22.
        ai_context: Optional ``{"model_id": ..., "model_region": ...,
            "risk_tier": ..., ...}``.
        consent_status: Required when lawful basis is consent. ``True``
            indicates valid, informed, current consent.
        consent_scope: Required when ``consent_status`` is ``True``.
        consent_record_ref: Optional URI to external consent record.
        transfer_restrictions: Optional schema-defined object.
        data_format: Optional MIME type or format descriptor.
        extensions: ``{"x-{ns}:{field}": ...}`` — arbitrary extension
            namespace claims.
        valid_for_seconds: How long after ``issued_at`` the token is
            valid. Defaults to 30 days.
        valid_from_offset_seconds: Offset from ``issued_at`` for the
            ``valid_from`` field. Defaults to 0 (immediate).
    """

    # Required (per OPSF schema)
    subject_id: str
    subject_type: str
    data_origin: str
    data_categories: list[str]
    lawful_basis: dict[str, Any]
    allowed_purposes: list[str]
    jurisdiction_rules: dict[str, Any]
    data_hash: str
    hash_algorithm: Literal["sha-256", "sha-384", "sha-512"]
    hash_scope: Literal["full_payload", "merkle_root"]

    # Optional (per OPSF schema)
    retention_limit: str | None = None
    automated_decision_flag: bool = False
    ai_context: dict[str, Any] | None = None
    consent_status: bool | None = None
    consent_scope: list[str] | None = None
    consent_record_ref: str | None = None
    transfer_restrictions: dict[str, Any] | None = None
    data_format: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    # Timing controls
    valid_for_seconds: int = _DEFAULT_VALIDITY_SECONDS
    valid_from_offset_seconds: int = 0


# ---------------------------------------------------------------------------
# JWS helpers (RFC 7515 §3.1 compact serialisation)
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    """Base64URL encoding without padding (per RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _canonical_json(obj: Any) -> bytes:
    """Canonical JSON encoding for signing input.

    ``sort_keys=True`` + compact separators give a stable byte
    representation so re-signing the same logical payload yields the
    same JWS body.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _validate_against_schema(payload: dict[str, Any]) -> None:
    """Validate the PCT payload against the vendored OPSF schema.

    ``jsonschema`` is a hard dependency declared in ``pyproject.toml``
    (``jsonschema>=4.0``) — there is no fallback. A missing
    ``jsonschema`` import indicates a broken install and is a hard
    failure: we refuse to mint tokens we cannot fully validate.

    Required-fields-only validation (per the OPSF schema's ``required``
    array) is insufficient because it skips type and enum checks on
    fields like ``data_categories`` (enum of 12 OPSF-defined values),
    ``hash_algorithm`` (rejection of MD5/SHA-1), and
    ``jurisdiction_rules.permitted_regions`` (string array of ISO
    country codes). A producer that emitted invalid values would mint
    tokens that every conformant verifier later rejects — worst
    possible UX.
    """
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PctIssueError(
            "jsonschema is required for PCT issuance but is not "
            "importable. Install via `pip install jsonschema>=4.0` "
            "(declared in pyproject.toml). Refusing to mint a token "
            "without full schema validation."
        ) from exc
    try:
        jsonschema.validate(instance=payload, schema=_PCT_SCHEMA)
    except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
        raise PctIssueError(
            f"Payload fails OPSF schema validation: {exc.message}"
        ) from exc


def _validate_kid(kid: str) -> None:
    """Validate the JWS ``kid`` (key identifier) header value.

    Defensive rules:
    - Must be a non-empty string.
    - Must be ≤ 256 characters (RFC 7515 §4.1.4 does not impose a
      limit but downstream key-ring loaders typically bound it).
    - Must use only characters safe in a URL path / HTTP header
      context: alphanumeric, dash, underscore, dot, colon.
      (Excludes spaces, slashes, control characters.)

    Raises:
        PctIssueError: If any rule fails.
    """
    if not isinstance(kid, str) or not kid:
        raise PctIssueError(
            f"kid must be a non-empty string, got {type(kid).__name__} "
            f"{kid!r}."
        )
    if len(kid) > 256:
        raise PctIssueError(
            f"kid must be ≤ 256 characters, got {len(kid)}."
        )
    # Safe charset for header / .well-known URL embedding.
    _kid_safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" \
                "0123456789-_.:"
    bad = [c for c in kid if c not in _kid_safe]
    if bad:
        raise PctIssueError(
            f"kid contains characters outside the safe set "
            f"[A-Za-z0-9-_.:]; bad characters: {sorted(set(bad))!r}."
        )


def _validate_issuer_url(issuer_url: str) -> None:
    """Validate the ``issuer`` field URL shape.

    Per OPSF schema the field is a URI; the issuer field of a JWT/PCT
    is conventionally an HTTPS URL identifying the issuing entity.
    Rules:
    - Must be a non-empty string.
    - Must be ≤ 2048 characters (RFC 7230 baseline URL bound).
    - Must parse with ``urllib.parse.urlparse`` to a scheme + netloc.
    - Scheme MUST be ``http`` or ``https`` (no ``file://``, no
      ``javascript:``, no ``urn:`` — they break verifier expectations).

    Raises:
        PctIssueError: If any rule fails.
    """
    from urllib.parse import urlparse

    if not isinstance(issuer_url, str) or not issuer_url:
        raise PctIssueError(
            f"issuer_url must be a non-empty string, got "
            f"{type(issuer_url).__name__} {issuer_url!r}."
        )
    if len(issuer_url) > 2048:
        raise PctIssueError(
            f"issuer_url must be ≤ 2048 characters, got {len(issuer_url)}."
        )
    parsed = urlparse(issuer_url)
    if parsed.scheme not in ("http", "https"):
        raise PctIssueError(
            f"issuer_url scheme must be 'http' or 'https', got "
            f"{parsed.scheme!r} (issuer_url={issuer_url!r})."
        )
    if not parsed.netloc:
        raise PctIssueError(
            f"issuer_url must have a non-empty network location, got "
            f"{issuer_url!r}."
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PctIssueError(ValueError):
    """Raised when a PctIssueRequest cannot be signed.

    Reasons include: prohibited hash algorithm, schema validation
    failure, prohibited JWS algorithm, missing required fields.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def issue_pct(
    request: PctIssueRequest,
    *,
    signing_key: rsa.RSAPrivateKey,
    kid: str,
    issuer_url: str,
    now: int | None = None,
    pct_id: str | None = None,
) -> str:
    """Mint a PCT JWS (compact form) for a downstream data flow.

    Args:
        request: The PCT issuance request, frozen + validated.
        signing_key: RSA private key for RS256 signature.
            CR-011 / R25-EU05 ships the full key-custody surface
            (KMS backends, Shamir, ``.well-known/pct-keys.json``
            publisher). Here the caller supplies the key directly.
        kid: Key identifier embedded in the JWS header so downstream
            verifiers can resolve the operator's signing key.
        issuer_url: URI identifying the issuing entity.
        now: Override for the current time (Unix seconds). Used in
            tests for deterministic ``issued_at`` / ``valid_from`` /
            ``expires_at`` triplets.
        pct_id: Override for the UUID v4 in the ``pct_id`` field.
            Used in tests for deterministic token bytes.

    Returns:
        A compact-form JWS string per RFC 7515 §3.1:
        ``<base64url(header)>.<base64url(payload)>.<base64url(signature)>``.

    Raises:
        PctIssueError: If the request fails schema validation, uses a
            prohibited hash algorithm, or supplies a non-RS256 alg.
        TypeError: If ``signing_key`` is not an RSA private key.
    """
    if request.hash_algorithm.lower() in _PROHIBITED_HASH_ALGORITHMS:
        raise PctIssueError(
            f"hash_algorithm {request.hash_algorithm!r} is prohibited "
            f"by OPSF PCT v0.1 spec (MD5 and SHA-1 disallowed). Use "
            f"sha-256, sha-384, or sha-512."
        )

    if not isinstance(signing_key, rsa.RSAPrivateKey):
        raise TypeError(
            f"signing_key must be an RSA private key, got "
            f"{type(signing_key).__name__}"
        )

    # Input validation on header / payload fields the caller supplies
    # directly (not via the dataclass). These checks address sentinel
    # pass 1 MAJOR-2 and harden the issuer against malformed call sites.
    _validate_kid(kid)
    _validate_issuer_url(issuer_url)

    issued_at = int(now) if now is not None else int(time.time())
    valid_from = issued_at + request.valid_from_offset_seconds
    expires_at = issued_at + request.valid_for_seconds

    payload: dict[str, Any] = {
        "pct_id": pct_id or str(uuid.uuid4()),
        "issued_at": issued_at,
        "valid_from": valid_from,
        "expires_at": expires_at,
        "issuer": issuer_url,
        "subject_id": request.subject_id,
        "subject_type": request.subject_type,
        "data_origin": request.data_origin,
        "data_categories": list(request.data_categories),
        "lawful_basis": dict(request.lawful_basis),
        "allowed_purposes": list(request.allowed_purposes),
        "jurisdiction_rules": dict(request.jurisdiction_rules),
        "data_hash": request.data_hash,
        "hash_algorithm": request.hash_algorithm,
        "hash_scope": request.hash_scope,
    }

    # Optional fields (only included when supplied)
    if request.retention_limit is not None:
        payload["retention_limit"] = request.retention_limit
    if request.automated_decision_flag:
        payload["automated_decision_flag"] = True
    if request.ai_context is not None:
        payload["ai_context"] = dict(request.ai_context)
    if request.consent_status is not None:
        payload["consent_status"] = request.consent_status
    if request.consent_scope is not None:
        payload["consent_scope"] = list(request.consent_scope)
    if request.consent_record_ref is not None:
        payload["consent_record_ref"] = request.consent_record_ref
    if request.transfer_restrictions is not None:
        payload["transfer_restrictions"] = dict(request.transfer_restrictions)
    if request.data_format is not None:
        payload["data_format"] = request.data_format
    if request.extensions:
        payload["extensions"] = dict(request.extensions)

    # Schema validation before signing — refuse to mint malformed tokens.
    _validate_against_schema(payload)

    header: dict[str, Any] = {
        "alg": "RS256",
        "kid": kid,
        "typ": "PCT",
        "pct_version": "0.1",
    }

    header_b64 = _b64url(_canonical_json(header))
    payload_b64 = _b64url(_canonical_json(payload))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    signature = signing_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = _b64url(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def export_public_key_pem(public_key: rsa.RSAPublicKey) -> str:
    """Serialise an RSA public key as PEM (SubjectPublicKeyInfo).

    Helper for tests + ``.well-known/pct-keys.json`` publisher in
    CR-011 / R25-EU05.
    """
    pem_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem_bytes.decode("ascii")
