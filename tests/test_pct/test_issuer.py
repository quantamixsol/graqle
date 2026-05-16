"""Tests for graqle.pct.issuer (CR-010 PR-010b-1)."""

from __future__ import annotations

import json

import pytest

from graqle.pct.issuer import (
    PctIssueError,
    PctIssueRequest,
    _b64url,
    _canonical_json,
    export_public_key_pem,
    issue_pct,
)


class TestIssueMinimal:
    def test_minimal_request_produces_three_part_jws(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        token = issue_pct(req, signing_key=priv, kid=kid, issuer_url=issuer_url)
        parts = token.split(".")
        assert len(parts) == 3, "compact-form JWS must have 3 dot-separated segments"
        assert all(len(p) > 0 for p in parts), "no segment may be empty"

    def test_header_contains_alg_rs256_and_kid(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        token = issue_pct(req, signing_key=priv, kid=kid, issuer_url=issuer_url)
        header_b64 = token.split(".")[0]
        # Decode header
        import base64
        padding = "=" * (4 - (len(header_b64) % 4))
        header_bytes = base64.urlsafe_b64decode(header_b64 + padding)
        header = json.loads(header_bytes.decode("utf-8"))
        assert header["alg"] == "RS256"
        assert header["kid"] == kid
        assert header["typ"] == "PCT"
        assert header["pct_version"] == "0.1"

    def test_payload_contains_required_fields(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        token = issue_pct(
            req,
            signing_key=priv,
            kid=kid,
            issuer_url=issuer_url,
            now=1740000000,
            pct_id="00000000-1111-4222-9333-444444444444",
        )
        import base64
        payload_b64 = token.split(".")[1]
        pad = "=" * (4 - (len(payload_b64) % 4))
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad).decode("utf-8"))
        # All 15 OPSF-required fields must be present
        for f in [
            "pct_id",
            "issued_at",
            "valid_from",
            "expires_at",
            "issuer",
            "subject_id",
            "subject_type",
            "data_origin",
            "data_categories",
            "lawful_basis",
            "allowed_purposes",
            "jurisdiction_rules",
            "data_hash",
            "hash_algorithm",
            "hash_scope",
        ]:
            assert f in payload, f"required field {f!r} missing from payload"
        assert payload["issued_at"] == 1740000000
        assert payload["valid_from"] == 1740000000
        assert payload["expires_at"] == 1740000000 + 30 * 24 * 3600


class TestHashAlgorithmGuard:
    @pytest.mark.parametrize("bad_algo", ["md5", "sha-1", "sha1", "MD5", "SHA-1"])
    def test_prohibited_hash_algorithms_rejected(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        bad_algo,
    ):
        priv, _ = rsa_keypair
        bad_kwargs = dict(minimal_issue_request_kwargs)
        bad_kwargs["hash_algorithm"] = bad_algo
        # PctIssueRequest accepts the string via dataclass; issuer rejects it
        req = PctIssueRequest(**bad_kwargs)
        with pytest.raises(PctIssueError, match="prohibited"):
            issue_pct(req, signing_key=priv, kid=kid, issuer_url=issuer_url)


class TestSigningKeyType:
    def test_non_rsa_signing_key_rejected(
        self,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        with pytest.raises(TypeError, match="RSA private key"):
            issue_pct(req, signing_key="not-a-key", kid=kid, issuer_url=issuer_url)  # type: ignore[arg-type]


class TestSchemaValidation:
    def test_extension_payload_emitted(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        kwargs = dict(minimal_issue_request_kwargs)
        kwargs["extensions"] = {"x-ai-eu:articles_covered": ["4", "12", "13"]}
        req = PctIssueRequest(**kwargs)
        token = issue_pct(req, signing_key=priv, kid=kid, issuer_url=issuer_url)
        import base64
        payload_b64 = token.split(".")[1]
        pad = "=" * (4 - (len(payload_b64) % 4))
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad).decode("utf-8"))
        assert payload["extensions"]["x-ai-eu:articles_covered"] == ["4", "12", "13"]


class TestHelpers:
    def test_canonical_json_is_stable(self):
        a = {"a": 1, "b": 2}
        b = {"b": 2, "a": 1}
        assert _canonical_json(a) == _canonical_json(b)

    def test_b64url_no_padding(self):
        # Standard base64 of 'hi' = 'aGk=' — base64url should be 'aGk' (no padding)
        assert _b64url(b"hi") == "aGk"

    def test_export_public_key_pem_round_trips(self, rsa_keypair):
        _, pub = rsa_keypair
        pem = export_public_key_pem(pub)
        assert pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert "-----END PUBLIC KEY-----" in pem
