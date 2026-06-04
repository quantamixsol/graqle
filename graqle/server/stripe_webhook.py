"""Stripe webhook handler for GraQle license key generation.

Handles Stripe checkout.session.completed events:
1. Validates the webhook signature using STRIPE_WEBHOOK_SECRET
2. Extracts customer email + tier from the session metadata
3. Generates an HMAC-signed license key via LicenseManager
4. Stores the lead in the leads table (if configured)
5. Returns the license key (Stripe sends it via email receipt)

Deployment options:
- AWS Lambda (recommended): Deploy as a Lambda behind API Gateway or Function URL
- FastAPI route: Mount in the GraQle server via `graq serve`
- Standalone: Run as any ASGI/WSGI handler

Environment variables:
- STRIPE_WEBHOOK_SECRET: Webhook signing secret from Stripe dashboard
- STRIPE_SECRET_KEY: Stripe API key (for customer lookup if needed)

Usage with FastAPI (integrated into graq serve):
    from graqle.server.stripe_webhook import router as stripe_router
    app.include_router(stripe_router, prefix="/webhooks")

Usage as standalone Lambda:
    from graqle.server.stripe_webhook import lambda_handler
    # Deploy lambda_handler as your Lambda function
"""

# ── graqle:intelligence ──
# module: graqle.server.stripe_webhook
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, hashlib, hmac, json, logging +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("graqle.server.stripe_webhook")

# Tier mapping from Stripe Price/Product metadata
STRIPE_TIER_MAP = {
    "pro": "pro",
    "pro_monthly": "pro",
    "pro_annual": "pro",
    "team": "team",
    "team_monthly": "team",
    "team_annual": "team",
    "enterprise": "enterprise",
    "enterprise_annual": "enterprise",
}

# Default license duration by tier
TIER_DURATION_DAYS = {
    "team": 365,
    "enterprise": 365,
}


def verify_stripe_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify a Stripe webhook signature (v1 scheme).

    Parameters
    ----------
    payload:
        Raw request body bytes.
    signature:
        Value of the Stripe-Signature header.
    secret:
        Webhook signing secret from Stripe dashboard.

    Returns
    -------
    bool
        True if the signature is valid.
    """
    try:
        elements = dict(
            item.split("=", 1) for item in signature.split(",")
        )
        timestamp = elements.get("t", "")
        v1_sig = elements.get("v1", "")

        if not timestamp or not v1_sig:
            return False

        # Stripe tolerance: reject if older than 5 minutes
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("Stripe webhook timestamp too old")
            return False

        # Compute expected signature
        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(v1_sig, expected)

    except Exception as e:
        logger.error(f"Stripe signature verification failed: {e}")
        return False


# ── ed25519 issuance (ADR-215 §5 cutover) ──────────────────────────────────
# The licence-issuing key is a DEDICATED ed25519 key (separate from the
# proof-bundle / Rekor keys), held server-side in AWS Secrets Manager. The
# Community wheel verifies with the PUBLIC key only and cannot forge (asymmetric);
# this issuer is in graqle/server/* which is excluded from the public wheel.
#
# Env:
#   GRAQLE_LICENSE_ISSUING_SECRET_ID — Secrets Manager id of the ed25519 seed
#     (64-char hex SecretString, or 32 raw SecretBinary bytes).
#   GRAQLE_LICENSE_ISSUING_KID — the signing kid (published to the trust source).
#   AWS_REGION / GRAQLE_LICENSE_ISSUING_REGION — region (default eu-central-1).
# The issuing key is fetched from Secrets Manager once and cached for the life of
# a warm Lambda container, then reused. This is the standard AWS Lambda pattern
# (the SDK's own anchor signer caches the same way): the private key has to be in
# this process's memory to sign at all, so per-request re-fetch would add latency
# + Secrets Manager API cost without reducing the in-memory exposure (the key is
# in memory during every signing regardless). Rotation is handled by Secrets
# Manager versioning + a new key picked up on the next cold start. The key never
# leaves this process — never logged, never serialised, never in the response.
_ISSUING_MANIFEST: Any = None  # cached across warm Lambda invocations
_ISSUING_KID: str | None = None

# A licence-issuing key is trusted across a wide window at sign time; the licence
# carries its own issued_at/expires_at as the real lifecycle. We register the kid
# ACTIVE over a wide window so signing never trips the manifest's own window
# guard; revocation lives in the published trust source + the CRL.
_WIDE_FROM = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIDE_UNTIL = datetime(9999, 12, 31, tzinfo=timezone.utc)


class IssuanceError(Exception):
    """Raised when a licence cannot be issued (config / key / signing failure)."""


def _seed_bytes_from_secret(resp: dict[str, Any]) -> bytes:
    """Extract a 32-byte ed25519 seed from a Secrets Manager response.

    Accepts ``SecretBinary`` (raw 32 bytes) or ``SecretString`` (64-char hex).
    """
    binary = resp.get("SecretBinary")
    if binary:
        return bytes(binary)
    text = resp.get("SecretString")
    if isinstance(text, str) and text.strip():
        try:
            return bytes.fromhex(text.strip())
        except ValueError as exc:
            raise IssuanceError("SecretString must be a 64-char hex ed25519 seed") from exc
    raise IssuanceError("issuing secret has neither SecretBinary nor SecretString")


def _get_issuing_manifest() -> tuple[Any, str]:
    """Build (and cache) the Ed25519KeyManifest holding the licence private key.

    Returns ``(manifest, kid)``. Raises :class:`IssuanceError` if the issuing
    env/secret is not configured (issuance fails loudly rather than silently
    falling back to an unforgeable-but-wrong key).
    """
    global _ISSUING_MANIFEST, _ISSUING_KID
    if _ISSUING_MANIFEST is not None and _ISSUING_KID is not None:
        return _ISSUING_MANIFEST, _ISSUING_KID

    secret_id = os.environ.get("GRAQLE_LICENSE_ISSUING_SECRET_ID")
    kid = os.environ.get("GRAQLE_LICENSE_ISSUING_KID")
    if not secret_id or not kid:
        raise IssuanceError(
            "ed25519 licence issuance requires GRAQLE_LICENSE_ISSUING_SECRET_ID "
            "and GRAQLE_LICENSE_ISSUING_KID"
        )
    region = (
        os.environ.get("GRAQLE_LICENSE_ISSUING_REGION")
        or os.environ.get("AWS_REGION")
        or "eu-central-1"
    )

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest

    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    try:
        resp = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        # Log the detail server-side (CloudWatch) but raise a GENERIC message —
        # the underlying boto3 error can embed the secret ARN / AWS internals,
        # which must not leak into a caller-visible exception (A09).
        logger.error("licence issuing key fetch failed: %s", exc)
        raise IssuanceError("could not fetch the licence issuing key") from None
    seed = _seed_bytes_from_secret(resp)
    if len(seed) != 32:
        raise IssuanceError("licence issuing seed must be 32 ed25519 bytes")
    try:
        priv = Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:
        raise IssuanceError(f"invalid ed25519 issuing seed: {exc}") from exc

    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=kid,
        public_key=priv.public_key(),
        valid_from=_WIDE_FROM,
        valid_until=_WIDE_UNTIL,
        private_key=priv,
    )
    _ISSUING_MANIFEST, _ISSUING_KID = manifest, kid
    return manifest, kid


def generate_license_from_checkout(session: dict[str, Any]) -> dict[str, Any]:
    """Generate a GraQle ed25519 (v2) license key from a Stripe checkout session.

    Cutover (ADR-215 §5): issues an ed25519-signed v2 licence (forgery-resistant —
    the public wheel verifies with the public key and cannot mint) instead of the
    legacy HMAC v1. Existing v1 customers keep working via the manager's dual-verify
    until their licence renews as v2.

    Parameters
    ----------
    session:
        The Stripe checkout.session.completed event data object.

    Returns
    -------
    dict
        Contains: license_key, license_id, tier, email, holder, expires_at, ...
    """
    import secrets

    from graqle.licensing.ed25519_license import issue_ed25519_license

    # Extract customer info
    email = session.get("customer_email") or session.get("customer_details", {}).get("email", "")
    name = session.get("customer_details", {}).get("name", "")

    # Extract tier from metadata (set on Stripe Product/Price or checkout session)
    metadata = session.get("metadata", {})
    tier_key = metadata.get("graqle_tier", "team")
    tier = STRIPE_TIER_MAP.get(tier_key, "team")

    # Duration
    duration_days = TIER_DURATION_DAYS.get(tier, 365)
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat()
    expires_at = (now + timedelta(days=duration_days)).isoformat()

    # license_id is derived from the Stripe session so it is stable + idempotent
    # on webhook retries (a retry re-issues the SAME license_id, not a second
    # licence) and traceable to the purchase; the CRL revokes against it.
    session_id = session.get("id", "")
    license_id = f"lic_{session_id}" if session_id else f"lic_{secrets.token_hex(12)}"
    nonce = secrets.token_hex(16)  # fresh per issue — replay protection

    manifest, kid = _get_issuing_manifest()
    license_key = issue_ed25519_license(
        manifest,
        kid,
        license_id=license_id,
        tier=tier,
        holder=name or email,
        email=email,
        issued_at=issued_at,
        nonce=nonce,
        expires_at=expires_at,
        features=[],  # parity with v1: tier drives entitlement (cutover v1)
        at=now,
    )

    result = {
        "license_key": license_key,
        "license_id": license_id,
        "tier": tier,
        "email": email,
        "holder": name or email,
        "expires_at": expires_at,
        "stripe_session_id": session_id,
        "stripe_customer_id": session.get("customer", ""),
        "license_format": "graqle-license-v2",
    }

    logger.info(
        "ed25519 licence issued: license_id=%s tier=%s email=%s expires=%s session=%s kid=%s",
        license_id, tier, email, expires_at, session_id, kid,
    )

    return result


def handle_webhook_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Handle a Stripe webhook event.

    Parameters
    ----------
    event_type:
        Stripe event type (e.g., 'checkout.session.completed').
    data:
        The event data object.

    Returns
    -------
    dict
        Response payload with status and any generated license info.
    """
    if event_type == "checkout.session.completed":
        session = data.get("object", data)

        # Only process paid sessions
        payment_status = session.get("payment_status", "")
        if payment_status != "paid":
            logger.info(f"Skipping unpaid session: {session.get('id')}")
            return {"status": "skipped", "reason": "payment_status != paid"}

        license_info = generate_license_from_checkout(session)

        # Store lead (best-effort)
        try:
            _store_lead(license_info)
        except Exception as e:
            logger.warning(f"Lead storage failed (non-fatal): {e}")

        return {
            "status": "ok",
            "license_generated": True,
            **license_info,
        }

    elif event_type == "customer.subscription.deleted":
        # Subscription cancelled — store a downgrade lead entry
        sub = data.get("object", {})
        sub_id = sub.get("id", "unknown")
        customer_id = sub.get("customer", "")
        logger.info(f"Subscription cancelled: {sub_id}, customer: {customer_id}")
        try:
            _store_lead({
                "email": sub.get("customer_email", ""),
                "tier": "cancelled",
                "holder": "",
                "stripe_session_id": sub_id,
                "stripe_customer_id": customer_id,
            })
        except Exception as e:
            logger.warning(f"Lead storage on cancel failed (non-fatal): {e}")
        return {"status": "ok", "action": "subscription_cancelled", "subscription_id": sub_id}

    else:
        return {"status": "ignored", "event_type": event_type}


def _store_lead(license_info: dict[str, Any]) -> None:
    """Store the lead/customer info for CRM purposes.

    Currently writes to a local JSONL file. In production, this would
    write to DynamoDB, a CRM API, or a marketing automation tool.
    """
    leads_dir = os.environ.get("COGNIGRAPH_LEADS_DIR", "/tmp/graqle-leads")
    os.makedirs(leads_dir, exist_ok=True)

    leads_path = os.path.join(leads_dir, "customers.jsonl")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "email": license_info.get("email"),
        "tier": license_info.get("tier"),
        "holder": license_info.get("holder"),
        "stripe_session_id": license_info.get("stripe_session_id"),
        "stripe_customer_id": license_info.get("stripe_customer_id"),
    }

    with open(leads_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# AWS Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda handler for Stripe webhooks.

    Deploy this as a Lambda behind API Gateway or Lambda Function URL.
    Set environment variables:
    - STRIPE_WEBHOOK_SECRET: from Stripe dashboard
    """
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # Extract body and signature
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    signature = headers.get("stripe-signature", "")

    # Verify signature
    if webhook_secret and not verify_stripe_signature(
        body.encode("utf-8"), signature, webhook_secret
    ):
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid signature"}),
        }

    # Parse event
    try:
        stripe_event = json.loads(body)
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON"}),
        }

    event_type = stripe_event.get("type", "")
    data = stripe_event.get("data", {})

    result = handle_webhook_event(event_type, data)

    return {
        "statusCode": 200,
        "body": json.dumps(result, default=str),
        "headers": {"Content-Type": "application/json"},
    }


# ---------------------------------------------------------------------------
# FastAPI router (for graq serve integration)
# ---------------------------------------------------------------------------

try:
    from fastapi import APIRouter, Request, Response

    router = APIRouter(tags=["webhooks"])

    @router.post("/stripe")
    async def stripe_webhook(request: Request) -> Response:
        """Handle Stripe webhook events."""
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        body = await request.body()
        signature = request.headers.get("stripe-signature", "")

        if webhook_secret and not verify_stripe_signature(
            body, signature, webhook_secret
        ):
            return Response(
                content=json.dumps({"error": "Invalid signature"}),
                status_code=400,
                media_type="application/json",
            )

        try:
            stripe_event = json.loads(body)
        except json.JSONDecodeError:
            return Response(
                content=json.dumps({"error": "Invalid JSON"}),
                status_code=400,
                media_type="application/json",
            )

        event_type = stripe_event.get("type", "")
        data = stripe_event.get("data", {})

        result = handle_webhook_event(event_type, data)

        return Response(
            content=json.dumps(result, default=str),
            status_code=200,
            media_type="application/json",
        )

except ImportError:
    # FastAPI not installed — Lambda-only mode
    router = None  # type: ignore[assignment]
