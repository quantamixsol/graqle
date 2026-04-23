"""Shared allowlist helpers for CG-12 Web gate + CG-13 Dependency gate.

Centralizes:
  - _validate_allowlist: generic list+type+min-length validator
  - _extract_hostname: URL -> lowercased hostname
  - _hostname_matches_pattern: fnmatch-based hostname matcher

Used by:
  - graqle.governance.web_gate.check_web_url
  - graqle.governance.deps_gate.check_deps_install
"""

from __future__ import annotations

import fnmatch
from typing import Any
from urllib.parse import urlsplit


def _validate_allowlist(
    items: Any,
    expected_type: type = str,
    min_length: int = 1,
) -> tuple[bool, list[str]]:
    """Validate a list of items all match expected_type and min_length.

    Returns (valid, error_reasons).

    Rules:
      - ``items`` must be ``list``; non-list -> invalid.
      - Each item must be ``isinstance(expected_type)``.
      - For ``str`` items, ``strip()`` must have length >= ``min_length``.
    """
    reasons: list[str] = []
    if not isinstance(items, list):
        return False, [f"items must be list, got {type(items).__name__}"]
    for i, item in enumerate(items):
        if not isinstance(item, expected_type):
            reasons.append(
                f"items[{i}] must be {expected_type.__name__}, "
                f"got {type(item).__name__}"
            )
            continue
        if expected_type is str and len(item.strip()) < min_length:
            reasons.append(
                f"items[{i}] must have stripped length >= {min_length}"
            )
    return (len(reasons) == 0, reasons)


def _extract_hostname(url: str) -> str | None:
    """Return lowercased hostname from a URL, or None on parse failure.

    Normalizes trailing dots. Returns None for:
      - non-string input
      - empty/whitespace-only input
      - URL without a parseable hostname
    """
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    # Try direct urlsplit — works for http://host/path
    try:
        parts = urlsplit(url)
    except Exception:
        return None
    host = parts.hostname
    if host is None:
        return None
    host = host.strip().lower().rstrip(".")
    return host or None


def _hostname_matches_pattern(hostname: str, pattern: str) -> bool:
    """Hostname-only fnmatch. Both normalized: lowercased, trailing dots stripped.

    Wildcard semantics (standard fnmatch):
      - ``github.com`` matches ``github.com`` only (exact).
      - ``*.github.com`` matches ``api.github.com`` AND ``a.b.github.com``
        (``*`` matches any chars including dots — substring semantics).
      - ``**`` is NOT specially supported — it behaves as literal.
      - Users wanting strict single-label matching should use explicit
        patterns per subdomain.

    Port and path are NOT part of the hostname — callers MUST extract
    hostname via ``_extract_hostname`` before calling this.
    """
    if not isinstance(hostname, str) or not isinstance(pattern, str):
        return False
    if not hostname or not pattern:
        return False
    hostname = hostname.lower().rstrip(".")
    pattern = pattern.strip().lower().rstrip(".")
    if not hostname or not pattern:
        return False
    if hostname == pattern:
        return True
    return fnmatch.fnmatchcase(hostname, pattern)
