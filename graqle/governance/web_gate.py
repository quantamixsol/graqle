"""CG-12 Web Gate — URL allowlist + SSRF hardening + response sanitization.

## Security model

### What IS protected:
  - Scheme enforcement (only http/https; blocks file://, javascript:, data://, etc.)
  - URL credentials (user:pass@host) rejection
  - IDNA/punycode normalization on hostname
  - IP literal classification via ``ipaddress`` module:
    loopback, private (RFC 1918), link-local (incl. 169.254.169.254
    cloud metadata), multicast, reserved, unspecified — IPv4 AND IPv6
  - Bracketed IPv6 literal handling (urlsplit strips brackets)
  - Hostname allowlist (exact + fnmatch wildcard; empty = legacy allow-all)
  - HTTP redirects disabled via custom HTTPRedirectHandler (3xx -> envelope)
  - Port validation (invalid ports rejected at parse)
  - Response-content secret sanitization (AWS/GitHub/API keys/JWT/DB URIs)
  - Bounded recursive sanitization (depth + item limits with sentinel)

### What is NOT protected (residual risks — see .gcc/OPEN-TRACKER-SECURITY-OPERATIONAL.md):
  - DNS rebinding (W2P6-R1): allowlisted hostnames that resolve to
    blocked IPs at connect time are not re-checked. Mitigation requires
    socket-level pin-then-connect, out of scope for Phase 6.
  - Wildcard substring semantics (W2P6-R2): ``*.example.com`` matches
    both single- and multi-label subdomains. Documented + tested.

### Integration points in mcp_dev_server.py:
  - Top of ``_web_fetch_url`` — ``check_web_url`` before any network I/O.
  - Top of ``_web_search_query`` — ``check_web_url`` on the search
    provider URL only (result URLs are advisory; CG-12 runs again when
    those are fetched via ``_web_fetch_url``).
  - Response pathway — ``sanitize_response_content`` on text body and
    ``_sanitize_record`` on structured results.
  - HTTP client — ``build_opener(_NoRedirectHandler())`` for both
    ``_web_fetch_url`` and ``_web_search_query``.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from graqle.governance.allowlist import _hostname_matches_pattern
from graqle.governance.config_drift import build_error_envelope

logger = logging.getLogger("graqle.governance.web_gate")


# ─────────────────────────────────────────────────────────────────────────
# Scheme + hostname + sanitization constants
# ─────────────────────────────────────────────────────────────────────────

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Explicitly blocked schemes (would otherwise pass loose checks)
_BLOCKED_SCHEMES: frozenset[str] = frozenset({
    "file", "ftp", "gopher", "dict", "javascript", "data", "vbscript",
    "ldap", "ssh", "chrome", "chrome-extension", "about",
})

# Special hostnames that always resolve to local/unroutable
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost", "broadcasthost",
})

# Sanitization bounds (MAJOR 4 resolution — fail-closed with sentinel)
_SANITIZE_MAX_DEPTH: int = 5
_SANITIZE_MAX_ITEMS: int = 500
TRUNCATION_SENTINEL: str = "<sanitize-limit-exceeded>"

# Secret patterns redacted from response content before return to caller.
# Order matters: more-specific patterns first.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "<aws-access-key>"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "<github-token>"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "<github-oauth>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{82}"), "<github-pat>"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "<api-key>"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "<slack-token>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"), "<jwt>"),
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), "<pem-private-key>"),
    (re.compile(r"postgres(?:ql)?://[^:]+:[^@]+@[^\s/]+"), "<db-url-with-creds>"),
    (re.compile(r"mysql://[^:]+:[^@]+@[^\s/]+"), "<db-url-with-creds>"),
    (re.compile(r"mongodb(?:\+srv)?://[^:]+:[^@]+@[^\s/]+"), "<db-url-with-creds>"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer <token>"),
)


# ─────────────────────────────────────────────────────────────────────────
# Redirect-blocking HTTP handler
# ─────────────────────────────────────────────────────────────────────────


class RedirectBlocked(Exception):
    """Raised when an HTTP response is a 3xx — redirects are SSRF bypass vectors."""

    def __init__(self, code: int, location: str | None) -> None:
        self.code = code
        self.location = location or ""
        super().__init__(f"{code} redirect to {location!r} blocked")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses to follow ANY HTTP redirect.

    Implementation note: overriding ``redirect_request`` is the single
    authoritative entry point for ALL 3xx responses in urllib. This
    catches 300/301/302/303/304/305/307/308 uniformly without needing
    per-code overrides. 304 Not Modified is rare for fresh GETs but
    still rejected as part of the "no redirect" policy.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectBlocked(code, headers.get("Location") or newurl)


# ─────────────────────────────────────────────────────────────────────────
# Secure URL parse
# ─────────────────────────────────────────────────────────────────────────


def _secure_parse(
    url: Any,
) -> tuple[tuple[str, str, int | None, str] | None, dict | None]:
    """Canonical parse pipeline. Returns ``(parsed, None)`` on success,
    ``(None, error_envelope)`` on rejection.

    Parse order (STRICT):
      1. Type + non-empty check.
      2. Scheme lowercased; must be in allowed set; blocked schemes
         (file/javascript/data/etc.) rejected explicitly.
      3. ``urlsplit`` — structural parse.
      4. ``parts.port`` accessed (may raise ValueError on invalid port).
      5. Reject userinfo (anything before @ in authority).
      6. Extract hostname, lowercased, trailing dots stripped.
      7. IDNA-encode hostname; decode failures rejected as malformed.

    Returns ``(scheme, hostname_ascii, port, path)``.
    """
    if not isinstance(url, str):
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            f"url must be str, got {type(url).__name__}",
        )
    url = url.strip()
    if not url:
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL", "url must be non-empty",
        )

    # Scheme check (case-insensitive). Detect via first `:` — this
    # catches schemeless URLs AND opaque schemes (javascript:, data:)
    # that don't use `://` authority form.
    colon_idx = url.find(":")
    if colon_idx == -1 or colon_idx == 0:
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            "url must include scheme (http:// or https://)",
        )
    scheme = url[:colon_idx].lower()
    # RFC 3986 scheme charset: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
    if not re.match(r"^[a-z][a-z0-9+\-.]*$", scheme):
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            "url scheme has invalid characters",
        )
    if scheme in _BLOCKED_SCHEMES:
        return None, build_error_envelope(
            "CG-12_SCHEME_BLOCKED",
            f"scheme {scheme!r} is not permitted",
        )
    if scheme not in _ALLOWED_SCHEMES:
        return None, build_error_envelope(
            "CG-12_SCHEME_BLOCKED",
            f"only http/https supported, got {scheme!r}",
        )
    # After scheme validation, http/https MUST use authority form
    if not url[colon_idx:].startswith("://"):
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            "http/https urls must use `scheme://` authority form",
        )

    # Structural parse
    try:
        parts = urlsplit(url)
    except Exception as exc:
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            f"url could not be parsed: {type(exc).__name__}",
        )

    # Port extraction — may raise ValueError on invalid port
    try:
        port = parts.port
    except ValueError as exc:
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            f"url has invalid port: {exc}",
        )

    # Userinfo check — reject user:pass@host
    netloc = parts.netloc or ""
    if "@" in netloc:
        return None, build_error_envelope(
            "CG-12_URL_CREDENTIALS_BLOCKED",
            "urls with userinfo (user:pass@host) are not permitted",
        )

    hostname_raw = parts.hostname or ""
    hostname = hostname_raw.strip().lower().rstrip(".")
    if not hostname:
        return None, build_error_envelope(
            "CG-12_MALFORMED_URL",
            "url has no hostname",
        )

    # IDNA encode — validates unicode hostnames
    try:
        hostname_ascii = hostname.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        # Allow ASCII-only hostnames that may contain chars idna rejects
        # (e.g. single-char or numeric). Fall back to lowercased input.
        if all(ord(c) < 128 for c in hostname):
            hostname_ascii = hostname
        else:
            return None, build_error_envelope(
                "CG-12_MALFORMED_URL",
                "hostname IDNA encoding failed",
            )

    return (scheme, hostname_ascii, port, parts.path or "/"), None


# ─────────────────────────────────────────────────────────────────────────
# IP classification via ipaddress
# ─────────────────────────────────────────────────────────────────────────


def _is_blocked_ip(hostname: str) -> bool:
    """True iff ``hostname`` is a literal IP address in a blocked range.

    Does NOT perform DNS resolution. Blocked ranges:
      - loopback (127.0.0.0/8, ::1)
      - private (RFC 1918, ULA, link-local)
      - link-local (169.254.0.0/16 incl. cloud metadata 169.254.169.254)
      - multicast
      - reserved
      - unspecified (0.0.0.0, ::)

    Non-IP hostnames return False (handled by allowlist).
    IPv4-mapped IPv6 (``::ffff:10.0.0.1``) classified as private since
    the embedded IPv4 is private.
    """
    if not isinstance(hostname, str) or not hostname:
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False  # not an IP literal
    # For IPv4-mapped IPv6, check the embedded IPv4 explicitly
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        embedded = ip.ipv4_mapped
        if (
            embedded.is_loopback or embedded.is_private
            or embedded.is_link_local or embedded.is_multicast
            or embedded.is_reserved or embedded.is_unspecified
        ):
            return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


# ─────────────────────────────────────────────────────────────────────────
# Unified gate — check_web_url
# ─────────────────────────────────────────────────────────────────────────


def check_web_url(
    url: str,
    *,
    config: Any = None,
) -> tuple[bool, dict | None]:
    """CG-12 unified URL gate.

    Enforcement order:
      1. Canonical parse (scheme/userinfo/IDNA/port) — unconditional.
      2. Special-hostname block (localhost, broadcasthost) — unconditional.
      3. IP literal block via ``ipaddress`` — unconditional.
      4. Allowlist (only if ``config.web_allowlist`` is non-empty).

    Empty allowlist preserves legacy allow-all behavior for back-compat,
    but steps 1-3 ALWAYS run regardless.

    Returns ``(allowed, envelope)``. Envelope built via
    ``graqle.governance.config_drift.build_error_envelope`` so
    path-bearing fields are sanitized.
    """
    parsed, env = _secure_parse(url)
    if env is not None:
        return False, env
    scheme, hostname, port, _path = parsed

    # Unconditional: blocked hostnames
    if hostname in _BLOCKED_HOSTNAMES:
        return False, build_error_envelope(
            "CG-12_LOCAL_ADDRESS_BLOCKED",
            f"hostname {hostname!r} is reserved (not routable)",
            hostname=hostname,
        )

    # Unconditional: IP literals in blocked ranges
    if _is_blocked_ip(hostname):
        return False, build_error_envelope(
            "CG-12_PRIVATE_IP_BLOCKED",
            f"ip literal {hostname!r} is in a blocked range "
            "(loopback/private/link-local/reserved/multicast)",
            hostname=hostname,
        )

    # Allowlist (only when configured)
    allowlist_raw = getattr(config, "web_allowlist", None) if config else None
    allowlist = list(allowlist_raw) if isinstance(allowlist_raw, list) else []
    if not allowlist:
        return True, None  # legacy allow-all (SSRF checks above ran)

    for pattern in allowlist:
        if not isinstance(pattern, str):
            continue
        if _hostname_matches_pattern(hostname, pattern):
            return True, None

    return False, build_error_envelope(
        "CG-12_DOMAIN_BLOCKED",
        f"hostname {hostname!r} not in web_allowlist",
        hostname=hostname,
        url=url,
    )


# ─────────────────────────────────────────────────────────────────────────
# Response sanitization
# ─────────────────────────────────────────────────────────────────────────


def sanitize_response_content(content: Any) -> Any:
    """Redact secret patterns from string content. Non-strings passed through.

    Used on the fetched response body text (5000-char truncated).
    Non-destructive: if no matches, returns input unchanged.
    """
    if not isinstance(content, str) or not content:
        return content
    out = content
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _sanitize_record(
    obj: Any,
    _depth: int = 0,
    _count: list[int] | None = None,
) -> Any:
    """Recursively sanitize string leaves in dict/list/tuple.

    Bounded by:
      - ``_SANITIZE_MAX_DEPTH`` (default 5): prevents deep recursion.
      - ``_SANITIZE_MAX_ITEMS`` (default 500): prevents pathological
        fan-out.

    Fail-closed on limit: returns ``TRUNCATION_SENTINEL`` (a string
    marker) instead of the original subtree. Callers can detect the
    sentinel without confusing it with legitimate content.

    Preserves: ``int``, ``float``, ``bool``, ``None`` as-is.
    Does NOT recurse into: sets, custom objects (returned as-is).
    """
    if _count is None:
        _count = [0]
    if _depth >= _SANITIZE_MAX_DEPTH or _count[0] >= _SANITIZE_MAX_ITEMS:
        return TRUNCATION_SENTINEL
    _count[0] += 1
    if isinstance(obj, str):
        return sanitize_response_content(obj)
    if isinstance(obj, dict):
        return {
            k: _sanitize_record(v, _depth + 1, _count)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize_record(v, _depth + 1, _count) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_record(v, _depth + 1, _count) for v in obj)
    return obj
