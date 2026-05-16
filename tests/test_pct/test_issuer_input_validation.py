"""Tests for issuer input-validation additions (sentinel pass 1 MAJOR-2).

Covers:
    - _validate_kid: empty, non-string, oversize, unsafe characters
    - _validate_issuer_url: empty, non-http(s) scheme, missing netloc, oversize
    - jsonschema is a hard dependency (no silent fallback)
"""

from __future__ import annotations

import pytest

from graqle.pct.issuer import (
    PctIssueError,
    PctIssueRequest,
    _validate_issuer_url,
    _validate_kid,
    issue_pct,
)


class TestValidateKid:
    @pytest.mark.parametrize("bad_kid", ["", None, 123, b"bytes-not-str"])
    def test_rejects_empty_or_non_string(self, bad_kid):
        with pytest.raises(PctIssueError, match="kid"):
            _validate_kid(bad_kid)  # type: ignore[arg-type]

    def test_rejects_oversize(self):
        with pytest.raises(PctIssueError, match="256 characters"):
            _validate_kid("a" * 257)

    @pytest.mark.parametrize(
        "bad_kid",
        [
            "kid with space",
            "kid/with/slash",
            "kid\nwith\nnewline",
            "kid<with>brackets",
            "kid?with=query",
        ],
    )
    def test_rejects_unsafe_charset(self, bad_kid):
        with pytest.raises(PctIssueError, match="characters outside"):
            _validate_kid(bad_kid)

    @pytest.mark.parametrize(
        "good_kid",
        [
            "pct-key-2026-03",
            "pct.key.2026.03",
            "pct_key_2026_03",
            "K1",
            "did:web:operator-x.com:keys:K1",
            "ABC123_xyz.test-key",
        ],
    )
    def test_accepts_safe_charsets(self, good_kid):
        # Should not raise
        _validate_kid(good_kid)


class TestValidateIssuerUrl:
    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_rejects_empty_or_non_string(self, bad):
        with pytest.raises(PctIssueError, match="non-empty string"):
            _validate_issuer_url(bad)  # type: ignore[arg-type]

    def test_rejects_oversize(self):
        with pytest.raises(PctIssueError, match="2048"):
            _validate_issuer_url("https://" + "a" * 2050 + ".com")

    @pytest.mark.parametrize(
        "bad_scheme_url",
        [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "urn:uuid:f3a2b1c4-1234-4abc-8def-000000000001",
            "ftp://example.com",
            "ws://example.com",
            "just-a-string-no-scheme",
        ],
    )
    def test_rejects_non_http_schemes(self, bad_scheme_url):
        with pytest.raises(PctIssueError, match="scheme must be"):
            _validate_issuer_url(bad_scheme_url)

    def test_rejects_missing_netloc(self):
        with pytest.raises(PctIssueError, match="network location"):
            _validate_issuer_url("https://")

    @pytest.mark.parametrize(
        "good_url",
        [
            "https://example.com",
            "https://orchestrator.example.com/path",
            "https://operator-x.com:8443/issuer",
            "http://localhost:9000",  # http allowed for local-dev
        ],
    )
    def test_accepts_valid_urls(self, good_url):
        # Should not raise
        _validate_issuer_url(good_url)


class TestIssueRejectsBadInputs:
    def test_issue_rejects_empty_kid(
        self,
        rsa_keypair,
        issuer_url,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        with pytest.raises(PctIssueError, match="kid"):
            issue_pct(req, signing_key=priv, kid="", issuer_url=issuer_url)

    def test_issue_rejects_file_scheme_issuer_url(
        self,
        rsa_keypair,
        kid,
        minimal_issue_request_kwargs,
    ):
        priv, _ = rsa_keypair
        req = PctIssueRequest(**minimal_issue_request_kwargs)
        with pytest.raises(PctIssueError, match="scheme must be"):
            issue_pct(
                req,
                signing_key=priv,
                kid=kid,
                issuer_url="file:///etc/passwd",
            )
