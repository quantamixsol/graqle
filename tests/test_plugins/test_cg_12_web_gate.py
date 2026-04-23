"""CG-12 Web Gate tests (Wave 2 Phase 6)."""
from __future__ import annotations

import pytest

from graqle.config.settings import GraqleConfig
from graqle.governance.web_gate import (
    RedirectBlocked,
    TRUNCATION_SENTINEL,
    _is_blocked_ip,
    _sanitize_record,
    _secure_parse,
    check_web_url,
    sanitize_response_content,
)


# Scheme enforcement (4)


@pytest.mark.parametrize("url,expected_error", [
    ("file:///etc/passwd", "CG-12_SCHEME_BLOCKED"),
    ("javascript:alert(1)", "CG-12_SCHEME_BLOCKED"),
    ("data:text/html,foo", "CG-12_SCHEME_BLOCKED"),
    ("ftp://example.com/", "CG-12_SCHEME_BLOCKED"),
])
def test_blocked_schemes(url, expected_error):
    allowed, env = check_web_url(url, config=None)
    assert allowed is False
    assert env["error"] == expected_error


# Malformed URL (4)


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "not-a-url",
    "http://",
])
def test_malformed_urls(url):
    allowed, env = check_web_url(url, config=None)
    assert allowed is False
    assert env["error"] == "CG-12_MALFORMED_URL"


def test_invalid_port():
    # Port 99999 is out of range
    allowed, env = check_web_url("https://example.com:99999/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_MALFORMED_URL"


def test_valid_port_matches_hostname():
    # Port is ignored in hostname matching
    cfg = GraqleConfig(web_allowlist=["github.com"])
    allowed, env = check_web_url("https://github.com:8443/foo", config=cfg)
    assert allowed is True


# URL credentials rejected (1)


def test_userinfo_blocked():
    allowed, env = check_web_url("http://user:pass@github.com/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_URL_CREDENTIALS_BLOCKED"


# Special-hostname blocks — unconditional (3)


@pytest.mark.parametrize("url", [
    "http://localhost/",
    "https://localhost:8080/",
    "http://broadcasthost/",
])
def test_special_hostnames_blocked(url):
    allowed, env = check_web_url(url, config=None)
    assert allowed is False
    assert env["error"] == "CG-12_LOCAL_ADDRESS_BLOCKED"


# IP literal blocks via ipaddress module (7)


@pytest.mark.parametrize("ip", [
    "127.0.0.1",         # IPv4 loopback
    "10.0.0.1",          # RFC 1918
    "192.168.1.1",       # RFC 1918
    "172.16.0.1",        # RFC 1918
    "169.254.169.254",   # cloud metadata (link-local)
    "0.0.0.0",           # unspecified
])
def test_ipv4_blocked(ip):
    allowed, env = check_web_url(f"http://{ip}/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_PRIVATE_IP_BLOCKED"


def test_ipv6_loopback_blocked():
    allowed, env = check_web_url("http://[::1]/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_PRIVATE_IP_BLOCKED"


def test_ipv6_ula_blocked():
    allowed, env = check_web_url("http://[fd00::1]/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_PRIVATE_IP_BLOCKED"


def test_ipv4_mapped_ipv6_private_blocked():
    # ::ffff:10.0.0.1 is RFC 1918 embedded in IPv6
    allowed, env = check_web_url("http://[::ffff:10.0.0.1]/", config=None)
    assert allowed is False
    assert env["error"] == "CG-12_PRIVATE_IP_BLOCKED"


def test_public_ipv4_allowed_when_empty_allowlist():
    # 8.8.8.8 is Google DNS — public, not blocked
    allowed, env = check_web_url("http://8.8.8.8/", config=None)
    assert allowed is True


# Allowlist behavior (4)


def test_empty_allowlist_allows_all_non_ssrf():
    cfg = GraqleConfig()
    assert cfg.web_allowlist == []
    allowed, env = check_web_url("https://github.com/x", config=cfg)
    assert allowed is True


def test_allowlist_exact_match():
    cfg = GraqleConfig(web_allowlist=["github.com"])
    allowed, env = check_web_url("https://github.com/x", config=cfg)
    assert allowed is True
    allowed, env = check_web_url("https://evil.com/x", config=cfg)
    assert not allowed
    assert env["error"] == "CG-12_DOMAIN_BLOCKED"


def test_allowlist_wildcard_match():
    cfg = GraqleConfig(web_allowlist=["*.github.com"])
    allowed, env = check_web_url("https://api.github.com/x", config=cfg)
    assert allowed is True


def test_allowlist_still_blocks_ssrf():
    # Even if localhost were in allowlist, SSRF block runs first
    cfg = GraqleConfig(web_allowlist=["localhost"])
    allowed, env = check_web_url("http://localhost/", config=cfg)
    assert not allowed
    assert env["error"] == "CG-12_LOCAL_ADDRESS_BLOCKED"


# Normalization (3)


def test_trailing_dot_normalized():
    cfg = GraqleConfig(web_allowlist=["github.com"])
    allowed, env = check_web_url("https://github.com./x", config=cfg)
    assert allowed is True


def test_mixed_case_hostname_normalized():
    cfg = GraqleConfig(web_allowlist=["github.com"])
    allowed, env = check_web_url("https://GITHUB.COM/x", config=cfg)
    assert allowed is True


def test_mixed_case_scheme_normalized():
    cfg = GraqleConfig(web_allowlist=["github.com"])
    allowed, env = check_web_url("HTTPS://github.com/x", config=cfg)
    assert allowed is True


# _is_blocked_ip direct (3)


def test_is_blocked_ip_non_ip_hostname():
    assert _is_blocked_ip("github.com") is False


def test_is_blocked_ip_public_ipv4():
    assert _is_blocked_ip("8.8.8.8") is False


def test_is_blocked_ip_link_local_169_254():
    assert _is_blocked_ip("169.254.169.254") is True


# Response sanitization (5)


def test_sanitize_aws_key():
    out = sanitize_response_content("my key: AKIAIOSFODNN7EXAMPLE is secret")
    assert "AKIA" not in out
    assert "<aws-access-key>" in out


def test_sanitize_github_token():
    out = sanitize_response_content("tok: ghp_" + "A" * 36)
    assert "<github-token>" in out
    assert "ghp_AAAA" not in out


def test_sanitize_api_key():
    out = sanitize_response_content("api: sk-" + "x" * 50)
    assert "<api-key>" in out


def test_sanitize_clean_input_unchanged():
    assert sanitize_response_content("hello world") == "hello world"


def test_sanitize_non_string_unchanged():
    assert sanitize_response_content(123) == 123
    assert sanitize_response_content(None) is None


# _sanitize_record bounded recursion (3)


def test_sanitize_record_dict_leaves():
    inp = {"a": "AKIAIOSFODNN7EXAMPLE", "b": "clean", "c": {"d": "ghp_" + "A" * 36}}
    out = _sanitize_record(inp)
    assert "<aws-access-key>" in out["a"]
    assert out["b"] == "clean"
    assert "<github-token>" in out["c"]["d"]


def test_sanitize_record_depth_limit():
    # Nest 10 levels — exceeds _SANITIZE_MAX_DEPTH=5
    deep = "inner"
    for _ in range(10):
        deep = {"x": deep}
    out = _sanitize_record(deep)
    # Somewhere in the nested structure, truncation sentinel appears
    def has_sentinel(obj):
        if obj == TRUNCATION_SENTINEL:
            return True
        if isinstance(obj, dict):
            return any(has_sentinel(v) for v in obj.values())
        return False
    assert has_sentinel(out)


def test_sanitize_record_non_recursable_preserved():
    # Sets are passed through as-is (not recursed)
    inp = {"tags": {"a", "b"}, "x": 1}
    out = _sanitize_record(inp)
    assert out["tags"] == {"a", "b"}
    assert out["x"] == 1


# _NoRedirectHandler behavior (lifecycle) (1)


def test_redirect_blocked_exception_shape():
    exc = RedirectBlocked(302, "http://internal.example.com/")
    assert exc.code == 302
    assert exc.location == "http://internal.example.com/"
    assert "blocked" in str(exc)


# Schema (1)


def test_graq_web_search_tool_schema_still_registered():
    import graqle.plugins.mcp_dev_server as m

    names = [t["name"] for t in m.TOOL_DEFINITIONS]
    assert "graq_web_search" in names
