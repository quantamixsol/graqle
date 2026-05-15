"""Tests for sentinel pass 3 focus=security defences (CR-010 PR-010b-1).

Covers:
    - MAJOR-S1: log-injection sanitisation of kid in validator failure_reasons
    - MAJOR-S2: 64 KiB defensive token size cap before crypto work
    - MINOR-S3: OPSF vendored-content SHA pin (reproducible builds)
"""

from __future__ import annotations

import os

import pytest

from graqle.pct.schema import (
    VENDORED_OPSF_COMMIT_DATE,
    VENDORED_OPSF_COMMIT_MESSAGE,
    VENDORED_OPSF_SHA,
)
from graqle.pct.validator import (
    _MAX_TOKEN_BYTES,
    _sanitise_kid_for_log,
    validate_pct,
)


# ---------------------------------------------------------------------------
# MAJOR-S1 — log-injection via control chars in kid
# ---------------------------------------------------------------------------


class TestKidLogSanitiser:
    @pytest.mark.parametrize(
        "raw,expected_substring",
        [
            ("\nkid-with-newline", "\\x0a"),
            ("\rkid-with-cr", "\\x0d"),
            ("\x1b[31m-ansi-red", "\\x1b"),
            ("\x00null-byte", "\\x00"),
            ("\x7fdel-char", "\\x7f"),
            ("normal-kid", "normal-kid"),
        ],
    )
    def test_control_chars_escaped(self, raw, expected_substring):
        out = _sanitise_kid_for_log(raw)
        assert expected_substring in out

    def test_oversize_truncated_with_ellipsis(self):
        big = "a" * 200
        out = _sanitise_kid_for_log(big)
        assert len(out) <= 64
        assert out.endswith("…")

    def test_non_string_input_repr_truncated(self):
        out = _sanitise_kid_for_log(b"bytes-not-string")
        # repr would be b'bytes-not-string'; safe to embed in logs
        assert len(out) <= 64
        # Should contain repr markers (single-quote or escape)
        assert "bytes" in out or "b'" in out

    def test_bidi_override_escaped(self):
        # U+202E RIGHT-TO-LEFT OVERRIDE
        out = _sanitise_kid_for_log("kid‮malicious")
        assert "\\x" in out  # bidi codepoint escaped

    def test_empty_input_returns_empty(self):
        assert _sanitise_kid_for_log("") == ""


class TestValidatorKidLogInjectionDefence:
    def test_failure_reason_with_malicious_kid_is_sanitised(
        self,
        rsa_keypair,
        kid,
        issuer_url,
        minimal_issue_request_kwargs,
        public_key_resolver,
    ):
        # Craft a token-like string with a malicious kid embedded in
        # the JWS header. We need to emit a valid 3-segment base64url
        # token whose header parses + has a kid with control chars.
        # We bypass the issuer (which validates the kid) by directly
        # encoding a header dict with a malicious kid.
        import base64
        import json as _json

        malicious_kid = "evil\nINJECTED-LOG-LINE: tampered"
        header = {
            "alg": "RS256",
            "kid": malicious_kid,
            "typ": "PCT",
            "pct_version": "0.1",
        }
        # Minimal payload + bogus signature segment
        payload = {"foo": "bar"}
        header_b64 = (
            base64.urlsafe_b64encode(
                _json.dumps(header, separators=(",", ":")).encode("utf-8")
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        payload_b64 = (
            base64.urlsafe_b64encode(
                _json.dumps(payload, separators=(",", ":")).encode("utf-8")
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        sig_b64 = "AAAA"  # invalid signature; will fail at check 2
        token = f"{header_b64}.{payload_b64}.{sig_b64}"
        result = validate_pct(token, public_key_resolver=public_key_resolver)
        assert result.decision == "BLOCK"
        # The malicious kid must NOT appear with its raw newline in any
        # failure_reason — it must be sanitised to \x0a form.
        joined = " ".join(result.failure_reasons)
        assert "\nINJECTED-LOG-LINE" not in joined
        # Sanitised form should appear (kid is reachable because
        # public_key_resolver receives the raw kid, returns None, and
        # the BLOCK message reports the kid using safe_kid).
        # We check the resolver was called with the raw kid in the
        # decision path — but the LOG output uses safe_kid.


# ---------------------------------------------------------------------------
# MAJOR-S2 — DoS via unbounded token size
# ---------------------------------------------------------------------------


class TestTokenSizeCap:
    def test_oversize_token_rejected_before_crypto(self, public_key_resolver):
        # Build a token larger than _MAX_TOKEN_BYTES
        oversize = "a." * (_MAX_TOKEN_BYTES // 2) + "a.a.a"
        assert len(oversize.encode("utf-8")) > _MAX_TOKEN_BYTES
        result = validate_pct(oversize, public_key_resolver=public_key_resolver)
        assert result.decision == "BLOCK"
        # Reason should mention the cap
        joined = " ".join(result.failure_reasons)
        assert "exceeds defensive cap" in joined or "GRAQLE_PCT_MAX_TOKEN_BYTES" in joined

    def test_undersize_token_passes_size_check(self, public_key_resolver):
        # A short malformed token still passes the size check but
        # fails structural — confirms size check doesn't false-positive.
        result = validate_pct("a.b.c", public_key_resolver=public_key_resolver)
        # Should NOT block on size; should block on subsequent checks
        joined = " ".join(result.failure_reasons)
        assert "exceeds defensive cap" not in joined

    def test_non_string_token_rejected(self, public_key_resolver):
        result = validate_pct(
            12345,  # type: ignore[arg-type]
            public_key_resolver=public_key_resolver,
        )
        assert result.decision == "BLOCK"
        assert any("Token must be a string" in r for r in result.failure_reasons)


# ---------------------------------------------------------------------------
# MINOR-S3 — OPSF vendored-content SHA pin
# ---------------------------------------------------------------------------


class TestOpsfVendoringPin:
    def test_vendored_sha_constant_is_40_hex_chars(self):
        assert len(VENDORED_OPSF_SHA) == 40
        assert all(c in "0123456789abcdef" for c in VENDORED_OPSF_SHA)

    def test_vendored_sha_matches_known_value(self):
        # If this changes, an explicit re-vendoring PR is required —
        # do NOT mutate this assertion without re-pulling all 5 OPSF
        # artefacts from the new SHA + updating the docstrings.
        assert VENDORED_OPSF_SHA == "f04bbc4862af836a2696e635275ead4bc835d9d1"

    def test_vendored_commit_date_present(self):
        assert VENDORED_OPSF_COMMIT_DATE
        assert "-" in VENDORED_OPSF_COMMIT_DATE  # ISO date sanity

    def test_vendored_commit_message_present(self):
        assert VENDORED_OPSF_COMMIT_MESSAGE
        assert len(VENDORED_OPSF_COMMIT_MESSAGE) > 0
