"""Content redaction for LLM-bound data paths.

Prevents sensitive node properties (passwords, API keys, tokens, credentials)
from being sent to external LLM providers during reasoning.

Security context: C1 vulnerability — zero redaction gates existed between
KG content and backend.generate() across all reasoning paths.

This module provides pure functions with no side effects. It never mutates
the input data structures.
"""

# ── graqle:intelligence ──
# module: graqle.core.redaction
# risk: HIGH (security-critical path)
# consumers: graph, mcp_dev_server, mcp_server
# dependencies: __future__, re
# constraints: never mutate input, never import heavy deps
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from typing import Any

# Keys that indicate sensitive content. Matching is case-insensitive
# and uses substring containment (e.g., "db_password" matches "password").
DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "auth_token",
    "access_key",
    "secret_key",
    "ssn",
    "pii",
})

# Internal/cache keys that should never be sent to LLMs
_INTERNAL_KEYS: frozenset[str] = frozenset({
    "_embedding_cache",
    "_activation_score",
    "_last_reasoning",
})

_DEFAULT_MARKER = "[REDACTED]"


def _is_sensitive_key(key: str, sensitive_keys: frozenset[str]) -> bool:
    """Check if a property key matches any sensitive pattern (substring, case-insensitive)."""
    key_lower = key.lower()
    return any(s in key_lower for s in sensitive_keys) or key in _INTERNAL_KEYS


def redact_node_properties(
    properties: dict[str, Any],
    sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS,
    marker: str = _DEFAULT_MARKER,
) -> dict[str, Any]:
    """Return a new dict with sensitive property values replaced by marker.

    Pure function — never mutates the input dict.

    Args:
        properties: Node properties dict to redact.
        sensitive_keys: Set of substrings to match against lowercased key names.
        marker: Replacement string for redacted values.

    Returns:
        New dict with sensitive values replaced.
    """
    return {
        k: marker if _is_sensitive_key(k, sensitive_keys) else v
        for k, v in properties.items()
    }


def redact_chunks(
    chunks: list[Any],
    sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS,
    marker: str = _DEFAULT_MARKER,
) -> list[Any]:
    """Scrub inline key=value patterns from chunk text.

    Handles synthesized chunks from _auto_load_chunks() where properties
    are concatenated as "key: value" lines.

    Pure function — never mutates input chunks.

    Args:
        chunks: List of chunk dicts (each with "text" and "type" keys).
        sensitive_keys: Sensitive key substrings to match.
        marker: Replacement string.

    Returns:
        New list with scrubbed chunk text.
    """
    result = []
    for chunk in chunks:
        if isinstance(chunk, dict) and "text" in chunk:
            chunk = dict(chunk)  # shallow copy
            text = chunk["text"]
            for key in sensitive_keys:
                # Match patterns like "password: secret123" or "api_key=abc"
                text = re.sub(
                    rf"(?im)^.*{re.escape(key)}.*[:=]\s*\S+.*$",
                    f"{key}: {marker}",
                    text,
                )
            chunk["text"] = text
            result.append(chunk)
        else:
            result.append(chunk)
    return result


def redact_text(
    text: str,
    sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS,
    marker: str = _DEFAULT_MARKER,
) -> str:
    """Scrub inline key=value patterns from arbitrary text.

    Useful for redacting graph_summary or other free-text fields
    before sending to LLM backends.

    Args:
        text: Text to redact.
        sensitive_keys: Sensitive key substrings.
        marker: Replacement string.

    Returns:
        Redacted text.
    """
    for key in sensitive_keys:
        text = re.sub(
            rf"(?im)^.*{re.escape(key)}.*[:=]\s*\S+.*$",
            f"{key}: {marker}",
            text,
        )
    return text
