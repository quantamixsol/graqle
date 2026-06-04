"""Tests for graqle.server.stripe_webhook — Stripe integration."""

# ── graqle:intelligence ──
# module: tests.test_server.test_stripe_webhook
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, hashlib, hmac, json, time +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest


@pytest.fixture(autouse=True)
def _issuing_key(monkeypatch):
    """Inject a fresh in-memory ed25519 licence-issuing key for every test.

    The cutover (ADR-215 §5) issues ed25519 v2 licences signed with a Secrets-
    Manager key; tests substitute a generated key by patching _get_issuing_manifest
    so no AWS is touched. The one test that asserts "issuance fails without a key"
    overrides this by clearing the module globals + env itself.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from graqle.governance.custody.ed25519_key_manifest import Ed25519KeyManifest
    import graqle.server.stripe_webhook as sw

    priv = Ed25519PrivateKey.generate()
    kid = "graqle-license-test"
    manifest = Ed25519KeyManifest()
    manifest.register(
        kid=kid,
        public_key=priv.public_key(),
        valid_from=sw._WIDE_FROM,
        valid_until=sw._WIDE_UNTIL,
        private_key=priv,
    )
    monkeypatch.setattr(sw, "_get_issuing_manifest", lambda: (manifest, kid))
    # Expose for tests that want to verify the issued token.
    return manifest, kid


class TestStripeSignatureVerification:
    """Tests for Stripe webhook signature verification."""

    def _make_signature(self, payload: bytes, secret: str) -> str:
        """Create a valid Stripe signature for testing."""
        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.".encode() + payload
        sig = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={sig}"

    def test_valid_signature(self) -> None:
        from graqle.server.stripe_webhook import verify_stripe_signature
        secret = "whsec_test123"
        payload = b'{"type": "checkout.session.completed"}'
        sig = self._make_signature(payload, secret)

        assert verify_stripe_signature(payload, sig, secret) is True

    def test_invalid_signature(self) -> None:
        from graqle.server.stripe_webhook import verify_stripe_signature
        payload = b'{"type": "test"}'
        assert verify_stripe_signature(payload, "t=123,v1=invalid", "secret") is False

    def test_empty_signature(self) -> None:
        from graqle.server.stripe_webhook import verify_stripe_signature
        assert verify_stripe_signature(b"payload", "", "secret") is False

    def test_old_timestamp_rejected(self) -> None:
        from graqle.server.stripe_webhook import verify_stripe_signature
        secret = "whsec_test"
        payload = b"test"

        # Timestamp from 10 minutes ago
        old_ts = str(int(time.time()) - 600)
        signed_payload = f"{old_ts}.".encode() + payload
        sig = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        header = f"t={old_ts},v1={sig}"

        assert verify_stripe_signature(payload, header, secret) is False


class TestLicenseGeneration:
    """Tests for license key generation from Stripe checkout."""

    def test_generate_from_checkout_issues_ed25519_v2(self, _issuing_key) -> None:
        manifest, kid = _issuing_key
        from graqle.server.stripe_webhook import generate_license_from_checkout
        from graqle.licensing.ed25519_license import verify_ed25519_license

        session = {
            "id": "cs_test_123",
            "customer_email": "buyer@company.com",
            "customer_details": {"name": "Jane Buyer"},
            "customer": "cus_abc123",
            "metadata": {"graqle_tier": "team"},
            "payment_status": "paid",
        }

        result = generate_license_from_checkout(session)

        assert result["tier"] == "team"
        assert result["email"] == "buyer@company.com"
        assert result["holder"] == "Jane Buyer"
        assert result["license_format"] == "graqle-license-v2"
        # license_id is derived from the Stripe session (stable + idempotent).
        assert result["license_id"] == "lic_cs_test_123"
        # v2 token shape: payload.kid.sig (3 dot-parts).
        assert result["license_key"].count(".") == 2

        # The issued token verifies against the SAME issuing key (the public half).
        payload = verify_ed25519_license(result["license_key"], manifest)
        assert payload is not None
        assert payload["tier"] == "team"
        assert payload["email"] == "buyer@company.com"
        assert payload["license_id"] == "lic_cs_test_123"
        assert payload["format"] == "graqle-license-v2"
        assert payload["nonce"]  # a fresh replay nonce is present

    def test_issuance_idempotent_license_id_on_retry(self) -> None:
        """A Stripe webhook retry re-issues the SAME license_id (derived from session)."""
        from graqle.server.stripe_webhook import generate_license_from_checkout

        session = {"id": "cs_retry_1", "customer_email": "a@b.com",
                   "customer_details": {"name": "A"}, "metadata": {"graqle_tier": "pro"},
                   "payment_status": "paid"}
        r1 = generate_license_from_checkout(session)
        r2 = generate_license_from_checkout(session)
        assert r1["license_id"] == r2["license_id"] == "lic_cs_retry_1"

    def test_enterprise_tier_mapping(self, monkeypatch) -> None:
        from graqle.server.stripe_webhook import generate_license_from_checkout

        session = {
            "id": "cs_ent_456",
            "customer_email": "admin@bigcorp.com",
            "customer_details": {"name": "Big Corp Admin"},
            "customer": "cus_def456",
            "metadata": {"graqle_tier": "enterprise"},
            "payment_status": "paid",
        }

        result = generate_license_from_checkout(session)
        assert result["tier"] == "enterprise"

    def test_default_tier_is_team(self, monkeypatch) -> None:
        from graqle.server.stripe_webhook import generate_license_from_checkout

        session = {
            "id": "cs_no_meta",
            "customer_email": "user@test.com",
            "customer_details": {"name": "User"},
            "customer": "cus_xyz",
            "metadata": {},
            "payment_status": "paid",
        }

        result = generate_license_from_checkout(session)
        assert result["tier"] == "team"

    def test_issuance_requires_configured_key(self, monkeypatch) -> None:
        """Issuance fails loudly (no silent fallback) when the issuing key is unset."""
        import importlib

        import graqle.server.stripe_webhook as sw

        # Reload the module so the autouse fixture's patch of _get_issuing_manifest
        # is gone — we want the REAL builder, which must fail without config.
        sw = importlib.reload(sw)
        monkeypatch.setattr(sw, "_ISSUING_MANIFEST", None)
        monkeypatch.setattr(sw, "_ISSUING_KID", None)
        monkeypatch.delenv("GRAQLE_LICENSE_ISSUING_SECRET_ID", raising=False)
        monkeypatch.delenv("GRAQLE_LICENSE_ISSUING_KID", raising=False)
        with pytest.raises(sw.IssuanceError):
            sw.generate_license_from_checkout({"id": "cs_x", "metadata": {}, "payment_status": "paid"})


class TestWebhookEventHandler:
    """Tests for the main event handler."""

    def test_checkout_completed_generates_license(self) -> None:
        from graqle.server.stripe_webhook import handle_webhook_event

        data = {
            "object": {
                "id": "cs_test",
                "customer_email": "dev@test.com",
                "customer_details": {"name": "Dev"},
                "customer": "cus_test",
                "metadata": {"graqle_tier": "team"},
                "payment_status": "paid",
            }
        }

        result = handle_webhook_event("checkout.session.completed", data)
        assert result["status"] == "ok"
        assert result["license_generated"] is True
        assert result["license_key"]

    def test_unpaid_session_skipped(self) -> None:
        from graqle.server.stripe_webhook import handle_webhook_event

        data = {
            "object": {
                "id": "cs_unpaid",
                "payment_status": "unpaid",
            }
        }

        result = handle_webhook_event("checkout.session.completed", data)
        assert result["status"] == "skipped"

    def test_unknown_event_ignored(self) -> None:
        from graqle.server.stripe_webhook import handle_webhook_event
        result = handle_webhook_event("some.random.event", {})
        assert result["status"] == "ignored"

    def test_subscription_deleted_logged(self) -> None:
        from graqle.server.stripe_webhook import handle_webhook_event
        result = handle_webhook_event("customer.subscription.deleted", {
            "object": {"id": "sub_test"}
        })
        assert result["status"] == "ok"
        assert result["action"] == "subscription_cancelled"


class TestLambdaHandler:
    """Tests for the AWS Lambda handler wrapper."""

    def test_lambda_handler_invalid_json(self) -> None:
        from graqle.server.stripe_webhook import lambda_handler

        event = {
            "body": "not json",
            "headers": {},
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_lambda_handler_valid_event(self) -> None:
        from graqle.server.stripe_webhook import lambda_handler

        stripe_event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_lambda",
                    "customer_email": "lambda@test.com",
                    "customer_details": {"name": "Lambda"},
                    "customer": "cus_lambda",
                    "metadata": {"graqle_tier": "team"},
                    "payment_status": "paid",
                }
            }
        }

        event = {
            "body": json.dumps(stripe_event),
            "headers": {},
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["license_generated"] is True
