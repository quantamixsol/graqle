"""Tests for graqle.pct.validator (CR-010 PR-010b-1)."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from graqle.pct.issuer import PctIssueRequest, issue_pct
from graqle.pct.validator import PctValidationResult, validate_pct


def _mint(rsa_keypair, kid, issuer_url, minimal_kwargs, **overrides):
    priv, _ = rsa_keypair
    kw = dict(minimal_kwargs)
    timing_overrides = {}
    for k in ("now", "pct_id"):
        if k in overrides:
            timing_overrides[k] = overrides.pop(k)
    kw.update(overrides)
    req = PctIssueRequest(**kw)
    return issue_pct(
        req,
        signing_key=priv,
        kid=kid,
        issuer_url=issuer_url,
        **timing_overrides,
    )


class TestAllow:
    def test_allow_valid_token(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        result = validate_pct(token, public_key_resolver=public_key_resolver)
        assert result.decision == "ALLOW", (
            f"expected ALLOW; got {result.decision} with reasons={result.failure_reasons}"
        )
        assert result.pct_id is not None
        assert result.issuer == issuer_url
        assert result.failure_reasons == []
        assert result.payload is not None


class TestBlockExpired:
    def test_block_when_expires_at_past(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        # Mint with issued_at far in the past + 1-second validity
        kw = dict(minimal_issue_request_kwargs)
        kw["valid_for_seconds"] = 1
        token = _mint(
            rsa_keypair,
            kid,
            issuer_url,
            kw,
            now=1700000000,
        )
        # Validate at much later time
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            now=1740000000,
        )
        assert result.decision == "BLOCK"
        assert any("expired" in r.lower() for r in result.failure_reasons)


class TestBlockNotYetValid:
    def test_block_when_valid_from_future(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        kw = dict(minimal_issue_request_kwargs)
        kw["valid_from_offset_seconds"] = 1_000_000  # ~11 days in the future
        token = _mint(rsa_keypair, kid, issuer_url, kw, now=1740000000)
        # Validate at issued_at: not yet valid
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            now=1740000000,
        )
        assert result.decision == "BLOCK"
        assert any("not yet valid" in r.lower() for r in result.failure_reasons)


class TestBlockBadSignature:
    def test_block_when_signature_tampered(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        # Flip one byte in the signature segment
        header_b64, payload_b64, sig_b64 = token.split(".")
        # Swap first two characters of signature
        tampered_sig = sig_b64[1] + sig_b64[0] + sig_b64[2:]
        tampered = f"{header_b64}.{payload_b64}.{tampered_sig}"
        result = validate_pct(tampered, public_key_resolver=public_key_resolver)
        assert result.decision == "BLOCK"
        assert any("signature" in r.lower() for r in result.failure_reasons)


class TestBlockUnknownKid:
    def test_block_when_resolver_returns_none(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        # Resolver that never finds anything
        def empty_resolver(_kid: str):
            return None
        result = validate_pct(token, public_key_resolver=empty_resolver)
        assert result.decision == "BLOCK"
        assert any("public_key_resolver returned None" in r for r in result.failure_reasons)


class TestBlockMalformedJws:
    @pytest.mark.parametrize(
        "bad_token",
        [
            "not-a-jws",
            "only.two",
            "four.parts.are.invalid",
            "",
        ],
    )
    def test_block_on_structural_failure(
        self,
        public_key_resolver,
        bad_token,
    ):
        result = validate_pct(bad_token, public_key_resolver=public_key_resolver)
        assert result.decision == "BLOCK"
        assert result.payload is None


class TestExpectedActionBlock:
    def test_block_when_action_not_in_allowed_purposes(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        # minimal_kwargs has allowed_purposes=["ai_inference"]
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            expected_action="cross_border_transfer",
        )
        assert result.decision == "BLOCK"
        assert any("allowed_purposes" in r for r in result.failure_reasons)

    def test_allow_when_action_in_allowed_purposes(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            expected_action="ai_inference",
        )
        assert result.decision == "ALLOW", (
            f"expected ALLOW; got {result.decision} with reasons={result.failure_reasons}"
        )


class TestExpectedJurisdictionBlock:
    def test_block_when_jurisdiction_not_permitted(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        # minimal_kwargs has permitted_regions=["DE", "FR", "NL"]
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            expected_jurisdiction="US",
        )
        assert result.decision == "BLOCK"
        assert any("Jurisdiction" in r for r in result.failure_reasons)

    def test_allow_when_jurisdiction_permitted(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        token = _mint(rsa_keypair, kid, issuer_url, minimal_issue_request_kwargs)
        result = validate_pct(
            token,
            public_key_resolver=public_key_resolver,
            expected_jurisdiction="DE",
        )
        assert result.decision == "ALLOW", (
            f"expected ALLOW; got {result.decision} with reasons={result.failure_reasons}"
        )
