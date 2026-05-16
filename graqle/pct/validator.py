"""PCT validator — verify an incoming Proof Claims Token (JWS, RS256).

Security defences (per sentinel pass 3 focus=security 2026-05-23):

    - **MAJOR-S2 — DoS via unbounded token**: validator caps token size
      at :data:`_MAX_TOKEN_BYTES` (64 KiB) before any cryptographic work.
      Tokens above the cap are BLOCKed with structured reason.
    - **MAJOR-S1 — Log injection via unvalidated kid**: validator
      sanitises the JWS header ``kid`` value via
      :func:`_sanitise_kid_for_log` before embedding it in
      ``failure_reasons``. Control characters are replaced with ``\\x?`` /
      hex; oversized ``kid`` values are truncated with an ellipsis.


Implements ADR-205 §2.4. Per OPSF PCT v0.1 README:

    "Before any action — an AI model call, a cross-border transfer,
     a processing operation — the PCT is verified. If the claimed
     obligations permit the action, it proceeds. If not, it is blocked."

The validator runs SIX structural + cryptographic + semantic checks:

    1. JWS structural validity (header + payload + signature; three
       dot-separated base64url segments).
    2. RS256 signature against the public key resolved by ``kid``.
    3. JSON-Schema validation of the payload against the vendored OPSF
       ``pct_v0_1.json`` schema.
    4. Temporal validity: ``valid_from <= now <= expires_at``.
    5. (Optional) action permitted by ``allowed_purposes``.
    6. (Optional) jurisdiction permitted by ``jurisdiction_rules.permitted_regions``.

Returns :class:`PctValidationResult` with ``decision = "ALLOW"`` iff all
applicable checks pass; otherwise ``"BLOCK"`` with structured
``failure_reasons`` so callers can route on specific failure modes.

The validator NEVER imports a GraQle-internal module that touches
trade-secret patterns. Enforced by
``tests/test_pct/test_no_internal_trade_secret_import.py``.

References:
    - ADR-205 §2.4 (validator API contract)
    - OPSF PCT spec README enforcement-point pattern (quoted above)
    - opsf-org/pct-spec@develop/schema/pct-schema-0.1.json
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# ---------------------------------------------------------------------------
# Vendored schema (loaded once at module import — shared with issuer)
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).parent / "schema" / "pct_v0_1.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


_PCT_SCHEMA = _load_schema()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

DecisionLiteral = Literal["ALLOW", "BLOCK"]


@dataclass(frozen=True)
class PctValidationResult:
    """Outcome of a :func:`validate_pct` call.

    Attributes:
        decision: ``"ALLOW"`` iff all applicable checks pass; else
            ``"BLOCK"``. Callers route on ``decision`` first then
            inspect ``failure_reasons`` for diagnostics.
        pct_id: ``payload.pct_id`` if the JWS parsed; else ``None``.
        issuer: ``payload.issuer`` if parsed; else ``None``.
        failure_reasons: Empty when ``decision == "ALLOW"``. When
            ``BLOCK``, each string is a single-line human-readable
            reason. Multiple reasons may accumulate across the six
            checks if more than one fails.
        payload: Parsed JSON payload if the JWS parsed and the
            signature verified; ``None`` if structural/cryptographic
            checks failed before payload could be trusted.
    """

    decision: DecisionLiteral
    pct_id: str | None
    issuer: str | None
    failure_reasons: list[str] = field(default_factory=list)
    payload: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: Defensive cap on incoming JWS size before any cryptographic work.
#: Realistic PCT tokens are <10 KiB. Closes the
#: signature-input-buffer DoS surface flagged in sentinel pass 3
#: focus=security (MAJOR-S2). Configurable via env var
#: ``GRAQLE_PCT_MAX_TOKEN_BYTES`` for high-volume operators with
#: legitimately larger payloads.
import os as _os

_MAX_TOKEN_BYTES: int = int(_os.environ.get("GRAQLE_PCT_MAX_TOKEN_BYTES", 65536))

#: Cap on a kid value as embedded in log/failure messages. Sentinel
#: pass 3 MAJOR-S1 — log-injection via control chars.
_KID_LOG_TRUNCATE: int = 64


def _b64url_decode(s: str) -> bytes:
    """Base64URL decode with padding fix-up (per RFC 7515 §2)."""
    padding_chars = 4 - (len(s) % 4)
    if padding_chars != 4:
        s = s + ("=" * padding_chars)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _sanitise_kid_for_log(kid: Any) -> str:
    """Return a log-safe representation of an incoming JWS kid.

    The kid is caller-controlled (lives in the JWS header) and an
    attacker can embed control characters, ANSI escapes, or oversize
    strings to disrupt downstream log readers. Sanitisation:

    - Non-string types → stringified via ``repr`` (bounded).
    - Length capped at :data:`_KID_LOG_TRUNCATE` chars; overage replaced
      with ``…``.
    - Control characters (codepoint < 32 except those that ``repr``
      escapes), DEL (127), and unicode bidi-override range are
      replaced with their hex escape form.

    Returns:
        A string safe to embed inside a log line. Empty string for empty
        input (so log readers don't see ``''`` repeatedly).
    """
    if not isinstance(kid, str):
        return repr(kid)[:_KID_LOG_TRUNCATE]
    truncated = (
        kid
        if len(kid) <= _KID_LOG_TRUNCATE
        else (kid[: _KID_LOG_TRUNCATE - 1] + "…")
    )
    out_chars: list[str] = []
    for ch in truncated:
        cp = ord(ch)
        # Strip control chars + DEL + bidi-override range
        if cp < 0x20 or cp == 0x7F or 0x202A <= cp <= 0x202E:
            out_chars.append(f"\\x{cp:02x}")
        else:
            out_chars.append(ch)
    return "".join(out_chars)


def _parse_jws_segments(token: str) -> tuple[str, str, str] | None:
    """Split a compact-form JWS into its three segments.

    Returns ``None`` if the input does not have exactly three
    dot-separated segments.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def _try_load_jsonschema():
    """Return the ``jsonschema`` module if installed; else ``None``."""
    try:
        import jsonschema  # type: ignore[import-untyped]

        return jsonschema
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_pct(
    token: str,
    *,
    public_key_resolver: Callable[[str], rsa.RSAPublicKey | None],
    expected_action: str | None = None,
    expected_jurisdiction: str | None = None,
    expected_purpose: str | None = None,
    now: int | None = None,
) -> PctValidationResult:
    """Validate an incoming PCT JWS per OPSF spec v0.1.

    Args:
        token: Compact-form JWS string
            ``<header>.<payload>.<signature>``.
        public_key_resolver: Callable from ``kid`` (string) to an RSA
            public key (or ``None`` if unknown). Decouples validation
            from key-custody; CR-011 / R25-EU05 ships
            ``.well-known/pct-keys.json`` resolvers.
        expected_action: Optional. If supplied, BLOCK unless this string
            is in ``allowed_purposes``.
        expected_jurisdiction: Optional ISO 3166-1 alpha-2. If supplied,
            BLOCK unless it is in
            ``jurisdiction_rules.permitted_regions``.
        expected_purpose: Synonym for ``expected_action`` — accepted for
            naming flexibility at call sites.
        now: Override for the current time (Unix seconds). For
            deterministic tests.

    Returns:
        :class:`PctValidationResult` — never raises on validation
        failure; returns ``BLOCK`` with structured reasons instead.
    """
    failure_reasons: list[str] = []
    pct_id: str | None = None
    issuer: str | None = None
    payload: dict[str, Any] | None = None

    # Check 0: defensive size cap — refuse oversized tokens before any
    # cryptographic work. Closes MAJOR-S2 sentinel pass 3 finding
    # (memory-exhaustion DoS via signature-input buffering).
    if not isinstance(token, str):
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                f"Token must be a string, got {type(token).__name__}."
            ],
            payload=None,
        )
    token_byte_len = len(token.encode("utf-8", errors="replace"))
    if token_byte_len > _MAX_TOKEN_BYTES:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                f"Token size {token_byte_len} bytes exceeds defensive "
                f"cap {_MAX_TOKEN_BYTES} bytes (configurable via "
                f"GRAQLE_PCT_MAX_TOKEN_BYTES)."
            ],
            payload=None,
        )

    # Check 1: JWS structural validity
    segments = _parse_jws_segments(token)
    if segments is None:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                "JWS structural validity failed: token does not have "
                "exactly three dot-separated segments."
            ],
            payload=None,
        )

    header_b64, payload_b64, signature_b64 = segments

    try:
        header_bytes = _b64url_decode(header_b64)
        payload_bytes = _b64url_decode(payload_b64)
        signature_bytes = _b64url_decode(signature_b64)
    except Exception as exc:  # base64 decode error
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                f"JWS segment base64url decode failed: {exc}"
            ],
            payload=None,
        )

    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[f"JWS header is not valid JSON: {exc}"],
            payload=None,
        )

    alg = header.get("alg")
    kid = header.get("kid")
    # Sanitise kid + alg for log-safety per MAJOR-S1 sentinel pass 3.
    safe_kid = _sanitise_kid_for_log(kid)
    safe_alg = _sanitise_kid_for_log(alg)
    if alg != "RS256":
        failure_reasons.append(
            f"JWS alg {safe_alg!r} not supported (RS256 baseline per OPSF v0.1)."
        )
    if not kid or not isinstance(kid, str):
        failure_reasons.append("JWS header missing or non-string 'kid' field.")

    # Early exit if header is unusable
    if failure_reasons:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=failure_reasons,
            payload=None,
        )

    # Check 2: RS256 signature against resolved public key
    public_key = public_key_resolver(kid)
    if public_key is None:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                f"public_key_resolver returned None for kid={safe_kid!r}; key "
                f"either unknown, expired, or revoked."
            ],
            payload=None,
        )

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        public_key.verify(
            signature_bytes,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[
                f"RS256 signature did not verify against public key for "
                f"kid={safe_kid!r}."
            ],
            payload=None,
        )

    # Signature verified — payload is now trusted enough to parse.
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return PctValidationResult(
            decision="BLOCK",
            pct_id=None,
            issuer=None,
            failure_reasons=[f"Payload is not valid JSON: {exc}"],
            payload=None,
        )

    pct_id = payload.get("pct_id") if isinstance(payload, dict) else None
    issuer = payload.get("issuer") if isinstance(payload, dict) else None

    # Check 3: JSON-Schema validation against vendored OPSF schema
    jsonschema = _try_load_jsonschema()
    if jsonschema is not None and isinstance(payload, dict):
        try:
            jsonschema.validate(instance=payload, schema=_PCT_SCHEMA)
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            failure_reasons.append(
                f"Payload fails OPSF schema validation: {exc.message}"
            )
    else:
        # Minimal-viable fallback: required-fields check only
        if isinstance(payload, dict):
            missing = [
                f
                for f in _PCT_SCHEMA.get("required", [])
                if f not in payload
            ]
            if missing:
                failure_reasons.append(
                    f"Payload missing required fields: {sorted(missing)}"
                )
        else:
            failure_reasons.append("Payload is not a JSON object.")

    # Check 4: temporal validity
    current_time = int(now) if now is not None else int(time.time())
    if isinstance(payload, dict):
        valid_from = payload.get("valid_from")
        expires_at = payload.get("expires_at")
        if isinstance(valid_from, int) and current_time < valid_from:
            failure_reasons.append(
                f"Token not yet valid: now={current_time} < "
                f"valid_from={valid_from}."
            )
        if isinstance(expires_at, int) and current_time > expires_at:
            failure_reasons.append(
                f"Token expired: now={current_time} > "
                f"expires_at={expires_at}."
            )

    # Check 5: action permitted by allowed_purposes
    action_to_check = expected_action or expected_purpose
    if action_to_check is not None and isinstance(payload, dict):
        allowed = payload.get("allowed_purposes", [])
        if not isinstance(allowed, list) or action_to_check not in allowed:
            failure_reasons.append(
                f"Action {action_to_check!r} not in allowed_purposes "
                f"{allowed!r}."
            )

    # Check 6: jurisdiction permitted by jurisdiction_rules
    if expected_jurisdiction is not None and isinstance(payload, dict):
        rules = payload.get("jurisdiction_rules", {})
        if isinstance(rules, dict):
            permitted = rules.get("permitted_regions", [])
            if (
                not isinstance(permitted, list)
                or expected_jurisdiction not in permitted
            ):
                failure_reasons.append(
                    f"Jurisdiction {expected_jurisdiction!r} not in "
                    f"jurisdiction_rules.permitted_regions {permitted!r}."
                )

    decision: DecisionLiteral = "ALLOW" if not failure_reasons else "BLOCK"
    return PctValidationResult(
        decision=decision,
        pct_id=pct_id,
        issuer=issuer,
        failure_reasons=failure_reasons,
        payload=payload,
    )
