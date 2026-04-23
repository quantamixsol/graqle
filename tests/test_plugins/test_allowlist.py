"""Shared allowlist helper tests (Wave 2 Phase 6 CG-12 + CG-13 support)."""
from __future__ import annotations

import pytest

from graqle.governance.allowlist import (
    _extract_hostname,
    _hostname_matches_pattern,
    _validate_allowlist,
)


# _validate_allowlist (4)


def test_validate_allowlist_happy_path():
    valid, reasons = _validate_allowlist(["a", "b", "c"])
    assert valid is True
    assert reasons == []


def test_validate_allowlist_non_list():
    valid, reasons = _validate_allowlist("not a list")
    assert valid is False
    assert "must be list" in reasons[0]


def test_validate_allowlist_non_str_item():
    valid, reasons = _validate_allowlist(["ok", 123, None])
    assert valid is False
    assert len(reasons) == 2


def test_validate_allowlist_empty_string_item():
    valid, reasons = _validate_allowlist(["ok", "   "])
    assert valid is False
    assert "length" in reasons[0]


# _extract_hostname (2)


def test_extract_hostname_basic():
    assert _extract_hostname("https://github.com/foo") == "github.com"


def test_extract_hostname_invalid_returns_none():
    assert _extract_hostname("") is None
    assert _extract_hostname(None) is None


# _hostname_matches_pattern (2)


@pytest.mark.parametrize("hostname,pattern,expected", [
    ("github.com", "github.com", True),          # exact
    ("api.github.com", "*.github.com", True),    # single-label wildcard
    ("a.b.github.com", "*.github.com", True),    # substring (fnmatch)
    ("github.com", "*.github.com", False),       # base does NOT match *.prefix
    ("GITHUB.COM", "github.com", True),          # case-insensitive
    ("github.com.", "github.com", True),         # trailing dot stripped
    ("evil.com", "github.com", False),
])
def test_hostname_matches_pattern(hostname, pattern, expected):
    assert _hostname_matches_pattern(hostname, pattern) == expected


def test_hostname_matches_pattern_empty_inputs():
    assert _hostname_matches_pattern("", "github.com") is False
    assert _hostname_matches_pattern("github.com", "") is False
