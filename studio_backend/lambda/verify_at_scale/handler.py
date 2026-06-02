"""Hosted verifier-at-scale Lambda (BizQ S2, Studio backend) — moat M2.

The free, no-auth, no-meter HTTP surface over the Community offline verifier
(``graqle.governance.tamper_evidence.verifier.verify_bundle``). Auditors,
regulators, and customers can verify GraQle proof bundles at scale over HTTP
without installing the SDK — and it is **FREE FOREVER**: never metered, never
gated (ADR-BIZ-001 §3.3, Q3 sign-off).

WHY THIS IS A SEPARATE, STANDALONE LAMBDA (do not move it into graqle/server)
----------------------------------------------------------------------------
The Community verifier carries a *runtime isolation guard*
(``verifier._assert_isolated``): importing it raises ``ImportError`` if any
``graqle.server.*`` or ``graqle.studio.*`` module is already loaded in the
process. That guard is moat M2 (WS-A3) — it guarantees the canonical verifier
never co-resides with proprietary/networked code, so "if GraQle vanished, your
proofs still verify" stays an engineered invariant, not a promise.

Therefore the hosted verify endpoint CANNOT live inside the ``graqle.server``
FastAPI app (that process loads ``graqle.server.*``). It is deployed as its own
dedicated Lambda whose handler imports ONLY ``graqle.verify`` /
``graqle.governance.tamper_evidence.verifier`` (both Community, both clean of
server/studio). The isolation is enforced by the **deployment/process
boundary**. (Confirmed by graq_reason, 96% — Option B over an in-process or
subprocess design.)

This module also lives OUTSIDE the importable ``graqle`` package (under
``studio_backend/``), so it never ships in the public Community wheel — it is
proprietary Studio-backend code, exactly like the other ``infra/lambda/*``
handlers.

It re-uses the shipped Community verification primitives unchanged (it does NOT
re-implement any crypto), so the canonical verifier stays the single free/open
implementation.

Request body (POST, Lambda Function URL)
----------------------------------------
::

    {
      "proof_bundle": { ... },          # REQUIRED — a GraQle proof bundle (dict)
      "public_key": "-----BEGIN ...",   # ONE of public_key | keyring (not both)
      "keyring": { "keys": [ ... ] },   #   explicit per-kid windows/states
      "rekor_sth": { ... }              # OPTIONAL — offline Rekor STH (DATA only,
                                        #   never fetched)
    }

Response
--------
* ``200 {"verified": bool, "ok": bool, "failure": str, "checks": {...},
  "rekor_checked": bool}`` for a *well-formed request* (``verified`` reflects the
  proof result — a failed proof is a valid 200 answer, not an error).
* ``400 {"error": "..."}`` for a *malformed request* (missing ``proof_bundle``,
  both/neither key form, bad PEM, malformed keyring, bad JSON, oversize body).

No metering, ever
-----------------
This handler imports nothing from ``graqle.metering`` and emits no
``MeterEvent``. The only billable unit is ``proof_anchored`` (hosted anchoring),
which lives in the anchoring worker — not here.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from graqle.governance.tamper_evidence.verifier import verify_bundle
from graqle.verify import (
    VerifyUsageError,
    manifest_from_keyring,
    manifest_from_single_key,
    result_to_dict,
)

logger = logging.getLogger("studio_backend.verify_at_scale")

# HTTP status codes — the request-validity contract (NOT the proof result).
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_PAYLOAD_TOO_LARGE = 413

# Defence-in-depth: a hosted endpoint takes untrusted input, so cap the body
# size to refuse absurd payloads before they reach the verifier. A real proof
# bundle is a few KB (one record + a Merkle path of sibling hashes); 1 MiB is
# orders of magnitude of headroom while still rejecting a memory-exhaustion
# attempt.
MAX_BODY_BYTES = 1_048_576


def verify_request(body: Any) -> tuple[int, dict[str, Any]]:
    """Verify a proof bundle supplied in a request body.

    Pure function (no network, no I/O, no global state) so it is trivially
    testable and reusable from any HTTP framework. Returns
    ``(http_status, response_dict)``. NEVER raises for a bad proof or bad input
    — every input problem maps to a 400 (fail-closed: an un-verifiable request
    is reported, never crashes the endpoint). Never emits a metering event.
    """
    # 1. Request shape — must be a JSON object carrying a dict proof_bundle.
    if not isinstance(body, dict):
        return HTTP_BAD_REQUEST, {"error": "request body must be a JSON object"}

    proof_bundle = body.get("proof_bundle")
    if not isinstance(proof_bundle, dict):
        return HTTP_BAD_REQUEST, {
            "error": "missing or invalid 'proof_bundle' (expected a JSON object)"
        }

    # 2. Trust material — exactly one of public_key (PEM) | keyring (dict).
    public_key = body.get("public_key")
    keyring = body.get("keyring")
    if (public_key is None) == (keyring is None):
        return HTTP_BAD_REQUEST, {
            "error": "provide exactly one of 'public_key' (PEM string) or "
            "'keyring' (object with a 'keys' array)"
        }

    # 3. Optional Rekor STH — injected as DATA into the bundle's rekor block,
    #    never fetched. An explicit rekor_sth overrides any rekor block already
    #    present (lets an auditor supply their own STH).
    rekor_sth = body.get("rekor_sth")
    if rekor_sth is not None:
        if not isinstance(rekor_sth, dict):
            return HTTP_BAD_REQUEST, {
                "error": "'rekor_sth' must be a JSON object when provided"
            }
        proof_bundle = {**proof_bundle, "rekor": rekor_sth}

    # 4. Build the trusted-key manifest from the request (reusing the Community
    #    loaders). VerifyUsageError = a usage problem (bad PEM, malformed
    #    keyring, missing kid) → 400, distinct from a failed proof.
    try:
        manifest = _manifest_from_request(
            proof_bundle=proof_bundle, public_key=public_key, keyring=keyring
        )
    except VerifyUsageError as exc:
        logger.info("verify-at-scale usage error: %s", exc)
        return HTTP_BAD_REQUEST, {"error": str(exc)}

    # 5. Verify (the Community core; never raises on a bad proof — returns a
    #    typed VerifyResult). Map ok→verified.
    result = verify_bundle(proof_bundle, manifest)
    payload = result_to_dict(result)
    response = {"verified": payload["ok"], **payload}
    return HTTP_OK, response


def _manifest_from_request(
    *,
    proof_bundle: dict[str, Any],
    public_key: Any,
    keyring: Any,
):
    """Build an Ed25519KeyManifest from request fields (public_key XOR keyring).

    Mirrors :func:`graqle.verify.load_manifest` but sources the trust material
    from request data (a PEM *string* / a keyring *dict*) instead of file paths.
    Raises :class:`VerifyUsageError` on any bad input (caller maps to HTTP 400).
    """
    if public_key is not None:
        if not isinstance(public_key, str) or not public_key.strip():
            raise VerifyUsageError("'public_key' must be a non-empty PEM string")
        # With a bare key, register it under the bundle's own signature.kid so
        # verify_bundle can find it (same convention as the --key CLI path).
        sig = proof_bundle.get("signature")
        kid = sig.get("kid") if isinstance(sig, dict) else None
        if not isinstance(kid, str) or not kid:
            raise VerifyUsageError(
                "bundle has no signature.kid to register the public_key under; "
                "use 'keyring' with an explicit kid instead"
            )
        return manifest_from_single_key(public_key.encode("utf-8"), kid)

    # keyring path
    if not isinstance(keyring, dict):
        raise VerifyUsageError("'keyring' must be a JSON object with a 'keys' array")
    return manifest_from_keyring(keyring)


def _json_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build an AWS Lambda Function URL / API Gateway proxy response.

    CORS is handled by the Function URL config (single source of truth, per
    ADR-056) — this handler does NOT set Access-Control-* headers, to avoid the
    duplicate-CORS-header bug that makes browsers reject the response.
    """
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entrypoint (Function URL / API Gateway proxy integration).

    Parses the request body, enforces the size cap, and delegates to
    :func:`verify_request`. Never raises out of the handler — any unexpected
    error degrades to a 400/500 JSON response (fail-closed, never a stack trace
    to the caller).
    """
    try:
        raw = event.get("body") if isinstance(event, dict) else None

        # Function URL may base64-encode the body (binary content types).
        if raw is not None and event.get("isBase64Encoded"):
            try:
                raw = base64.b64decode(raw, validate=True).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                # Narrow: a bad base64/utf-8 body is a client error, not an
                # internal fault — don't let it fall to the 500 guard.
                return _json_response(
                    HTTP_BAD_REQUEST, {"error": "could not decode request body"}
                )

        if raw is None:
            return _json_response(
                HTTP_BAD_REQUEST, {"error": "missing request body"}
            )

        if isinstance(raw, str) and len(raw.encode("utf-8")) > MAX_BODY_BYTES:
            return _json_response(
                HTTP_PAYLOAD_TOO_LARGE, {"error": "request body too large"}
            )

        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json_response(
                HTTP_BAD_REQUEST, {"error": "request body must be valid JSON"}
            )

        status, payload = verify_request(body)
        return _json_response(status, payload)

    except Exception:  # pragma: no cover - last-resort guard
        # Never leak internals; never crash the endpoint. Fail-closed to 500
        # WITHOUT a stack trace in the response (logged server-side only).
        logger.exception("verify-at-scale handler unexpected error")
        return _json_response(500, {"error": "internal verifier error"})


# Some deployment tooling looks for `handler`; expose both names.
handler = lambda_handler


__all__ = [
    "HTTP_OK",
    "HTTP_BAD_REQUEST",
    "HTTP_PAYLOAD_TOO_LARGE",
    "MAX_BODY_BYTES",
    "verify_request",
    "lambda_handler",
    "handler",
]
