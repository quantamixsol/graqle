"""Stripe webhook handler for Graqle license key generation.

Handles Stripe checkout.session.completed events:
1. Validates the webhook signature using STRIPE_WEBHOOK_SECRET
2. Extracts customer email + tier from the session metadata
3. Generates an HMAC-signed license key via LicenseManager
4. Stores the lead in the leads table (if configured)
5. Returns the license key (Stripe sends it via email receipt)

Deployment options:
- AWS Lambda (recommended): Deploy as a Lambda behind API Gateway or Function URL
- FastAPI route: Mount in the Graqle server via `graq serve`
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


def generate_license_from_checkout(session: dict[str, Any]) -> dict[str, Any]:
    """Generate a Graqle license key from a Stripe checkout session.

    Parameters
    ----------
    session:
        The Stripe checkout.session.completed event data object.

    Returns
    -------
    dict
        Contains: license_key, tier, email, holder, expires_at
    """
    from graqle.licensing.manager import LicenseManager

    # Extract customer info
    email = session.get("customer_email") or session.get("customer_details", {}).get("email", "")
    name = session.get("customer_details", {}).get("name", "")

    # Extract tier from metadata (set on Stripe Product/Price or checkout session)
    metadata = session.get("metadata", {})
    tier_key = metadata.get("graqle_tier", "team")
    tier = STRIPE_TIER_MAP.get(tier_key, "team")

    # Duration
    duration_days = TIER_DURATION_DAYS.get(tier, 365)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=duration_days)
    ).isoformat()

    # Generate the signed license key
    license_key = LicenseManager.generate_key(
        tier=tier,
        holder=name or email,
        email=email,
        expires_at=expires_at,
    )

    result = {
        "license_key": license_key,
        "tier": tier,
        "email": email,
        "holder": name or email,
        "expires_at": expires_at,
        "stripe_session_id": session.get("id", ""),
        "stripe_customer_id": session.get("customer", ""),
    }

    logger.info(
        f"License generated: tier={tier}, email={email}, "
        f"expires={expires_at}, session={session.get('id', '')}"
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
        # Subscription cancelled — log for manual review
        logger.info(f"Subscription cancelled: {data.get('object', {}).get('id')}")
        return {"status": "ok", "action": "subscription_cancelled_logged"}

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
