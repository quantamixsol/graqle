"""Tenant identity validation for the multi-tenant memory service (ADR-225, G1).

Single source of truth for what a valid ``tenant_id`` is and how a caller-supplied
value is normalised before it is ever used as a memory partition key. Stdlib-only so
it sits at the bottom of the import graph.

Design (ADR-225, sentinel-approved):

* On-prem / single-tenant deployments use the reserved :data:`DEFAULT_TENANT`
  sentinel — exactly one tenant in the process, behaviour unchanged.
* Cloud callers pass a *pre-hashed* id — ``sha256(lower(email))`` (64-char lowercase
  hex) or a ``team-<slug>`` id. Hashing happens at the verified-identity boundary;
  this module never hashes a raw email, so there is no double-hash "ghost bucket".

:func:`validate_tenant_id` applies a FIXED-ORDER normalisation pipeline *before* any
acceptance decision, closing URL-encoding, double-encoding, NUL-byte (raw AND decoded),
unicode-homograph and path-traversal bypass vectors.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

#: Reserved sentinel for the single (on-prem) tenant. Grep-distinctive and unable to
#: collide with a sha256 hex digest or ``team-`` id. Caller ids beginning with ``__``
#: are rejected so this cannot be spoofed.
DEFAULT_TENANT: str = "__local__"

#: Maximum accepted tenant-id length, enforced AFTER url-decoding (a percent-encoded
#: payload can expand past this once decoded). Guards memory-exhaustion / log-injection.
MAX_TENANT_ID_LEN: int = 128

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_TEAM_ID_RE = re.compile(r"team-[0-9a-zA-Z_-]{1,80}")
# Leftover percent triplet after a single decode pass (e.g. ``%252F`` -> ``%2F``).
_RESIDUAL_PERCENT_RE = re.compile(r"%[0-9a-fA-F]{2}")
# Unicode separator / dot homographs that do NOT NFC-normalise to ASCII but may be
# treated as path separators by some OS/filesystem/string layers. Blocked explicitly.
_FORBIDDEN_CODEPOINTS = frozenset(
    [
        "∕",  # DIVISION SLASH
        "／",  # FULLWIDTH SOLIDUS
        "⧵",  # REVERSE SOLIDUS OPERATOR
        "＼",  # FULLWIDTH REVERSE SOLIDUS
        "‥",  # TWO DOT LEADER
        "…",  # HORIZONTAL ELLIPSIS
    ]
)


class TenantIdError(ValueError):
    """Raised when a tenant identifier is missing, malformed, or fails validation.

    The message never echoes the offending raw value (it may be attacker-controlled);
    callers that must log it should record only a redacted hash.
    """


def validate_tenant_id(raw: str) -> str:
    """Normalise and validate a tenant identifier; return the accepted value.

    Pipeline (fixed order — no acceptance check ever sees an un-normalised value):

    1. Reject ``None``/non-``str``; reject a raw NUL byte.
    2. URL-decode **exactly once**; reject residual ``%XX`` (double-encoding); then
       re-reject a NUL byte that the decode may have produced (e.g. ``%00``).
    3. NFC-normalise unicode.
    4. Reject if longer than :data:`MAX_TENANT_ID_LEN` *after* decoding.
    5. Reject ``__``-prefixed values (unless exactly :data:`DEFAULT_TENANT`), ASCII
       ``/`` ``\\`` ``..`` or control chars, AND unicode separator/dot homographs.
    6. Allow-list: :data:`DEFAULT_TENANT`, a 64-char sha256 hex digest, or ``team-<slug>``.

    Note: passing validation does NOT assert the tenant exists — downstream authz must
    verify tenant existence independently.

    Raises:
        TenantIdError: if the value is missing or fails any step above.
    """
    if raw is None or not isinstance(raw, str):
        raise TenantIdError("tenant_id must be a non-empty string")
    if "\x00" in raw:
        raise TenantIdError("tenant_id contains a NUL byte")

    # unquote() is called EXACTLY ONCE. Do not add a second decode pass.
    decoded = unquote(raw)
    if _RESIDUAL_PERCENT_RE.search(decoded):
        raise TenantIdError("tenant_id contains double/residual percent-encoding")
    # NUL re-check MUST follow unquote() (a `%00` decodes to \x00). Do not reorder.
    if "\x00" in decoded:
        raise TenantIdError("tenant_id contains a decoded NUL byte")

    value = unicodedata.normalize("NFC", decoded)

    if len(value) > MAX_TENANT_ID_LEN:
        raise TenantIdError("tenant_id exceeds maximum length")

    if value.startswith("__") and value != DEFAULT_TENANT:
        raise TenantIdError("tenant_id may not use the reserved '__' prefix")
    if "/" in value or "\\" in value or ".." in value:
        raise TenantIdError("tenant_id contains illegal path characters")
    if any(ord(ch) < 32 for ch in value):
        raise TenantIdError("tenant_id contains control characters")
    if any(ch in _FORBIDDEN_CODEPOINTS for ch in value):
        raise TenantIdError("tenant_id contains a forbidden unicode separator")

    if value == DEFAULT_TENANT:
        return value
    if _SHA256_HEX_RE.fullmatch(value):
        return value
    if _TEAM_ID_RE.fullmatch(value):
        return value

    raise TenantIdError("tenant_id is not a recognised identity form")


def is_default_tenant(tenant_id: str) -> bool:
    """Return ``True`` iff *tenant_id* is the reserved on-prem :data:`DEFAULT_TENANT`."""
    return tenant_id == DEFAULT_TENANT
