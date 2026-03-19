# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""Redaction engine for PII and secrets in document text.

Provides :class:`RedactionEngine` — a configurable, regex-based scanner
that detects and replaces sensitive content (API keys, passwords, tokens,
PII, connection strings, etc.) before text enters the knowledge graph.

Usage
-----
::

    engine = RedactionEngine()
    clean = engine.redact("password=hunter2")
    # -> "password=[REDACTED]"

    # Preview without modifying:
    matches = engine.detect("api_key=AKIAIOSFODNN7EXAMPLE")
    for m in matches:
        print(m.pattern_name, m.start, m.end)

    # Disable specific patterns:
    engine = RedactionEngine(disabled_patterns={"email"})

    # Add custom patterns:
    engine = RedactionEngine(extra_patterns={
        "internal_id": r"INT-\\d{6,}",
    })

    # Turn off entirely:
    engine = RedactionEngine(enabled=False)
    assert engine.redact("secret=abc") == "secret=abc"
"""

# ── graqle:intelligence ──
# module: graqle.scanner.privacy
# risk: LOW (impact radius: 2 modules)
# consumers: docs, test_privacy
# dependencies: __future__, re, dataclasses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionMatch:
    """A single detected sensitive span.

    Attributes
    ----------
    pattern_name:
        Which pattern triggered the match (e.g. ``"api_key"``).
    start:
        Character offset of the match start in the original text.
    end:
        Character offset one past the last matched character.
    original:
        The matched text.  Stored for audit/logging purposes — callers
        should NOT persist this value.
    """

    pattern_name: str
    start: int
    end: int
    original: str


class RedactionEngine:
    """Regex-based redaction engine for PII and secrets.

    Parameters
    ----------
    enabled:
        Master switch.  When ``False``, :meth:`redact` and :meth:`detect`
        are complete no-ops (the text passes through unchanged).
    extra_patterns:
        Additional ``{name: regex}`` pairs that are compiled and applied
        alongside the defaults.  If a name collides with a default, the
        extra pattern **overrides** the default.
    disabled_patterns:
        Set of default pattern names to skip.  Useful when a particular
        default fires too aggressively for your corpus (e.g. ``"email"``
        in a contact-list document).
    """

    # ------------------------------------------------------------------
    # Default pattern library
    # ------------------------------------------------------------------
    # Each regex is designed to match the *entire* sensitive token.
    # Patterns with capture groups still replace the full match — the
    # groups are there only so that :meth:`detect` can report what the
    # sensitive *value* is (as opposed to the key=value pair).
    # ------------------------------------------------------------------

    DEFAULT_PATTERNS: dict[str, str] = {
        "api_key": (
            r'(?i)["\']?(?:api[_-]?key|apikey)["\']?\s*[:=]\s*["\']?(\S{8,})["\']?'
        ),
        "password": (
            r"(?i)(?:password|passwd|pwd)\s*[:=]\s*[\"']?(\S+)[\"']?"
        ),
        "bearer_token": (
            r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"
        ),
        "aws_key": (
            r"(?:AKIA|ASIA)[A-Z0-9]{16}"
        ),
        "aws_secret_key": (
            r"(?i)(?:aws_secret_access_key|aws_secret_key)\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{20,})[\"']?"
        ),
        "private_key": (
            r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |DSA )?PRIVATE KEY-----|$)"
        ),
        "ssn_like": (
            r"\b\d{3}-\d{2}-\d{4}\b"
        ),
        "email": (
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        "jwt": (
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
        ),
        "generic_secret": (
            r"(?i)(?:secret|token|credential)[_\s]*[:=]\s*[\"']?(\S{8,})[\"']?"
        ),
        "env_export": (
            r"(?i)export\s+(?:secret|token|credential|private)[_\w]*\s*=\s*[\"']?(\S{8,})[\"']?"
        ),
        "connection_string": (
            r"(?i)(?:mongodb|postgresql|mysql|redis|amqp)://\S+"
        ),
    }

    REDACTION_PLACEHOLDER: str = "[REDACTED]"

    def __init__(
        self,
        enabled: bool = True,
        extra_patterns: dict[str, str] | None = None,
        disabled_patterns: set[str] | None = None,
    ) -> None:
        self._enabled = enabled

        # Build effective pattern dict: defaults, minus disabled, plus extras.
        effective: dict[str, str] = {}
        disabled = disabled_patterns or set()

        for name, pattern in self.DEFAULT_PATTERNS.items():
            if name not in disabled:
                effective[name] = pattern

        if extra_patterns:
            effective.update(extra_patterns)

        # Compile once — order by descending pattern length so that longer
        # (more specific) patterns are tried before shorter ones.  This
        # reduces the chance of a short generic pattern partially matching
        # what a longer specific pattern would fully cover.
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pat))
            for name, pat in sorted(
                effective.items(), key=lambda kv: len(kv[1]), reverse=True
            )
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the engine is active."""
        return self._enabled

    def redact(self, text: str) -> str:
        """Replace all sensitive spans with :data:`REDACTION_PLACEHOLDER`.

        Parameters
        ----------
        text:
            Raw input text.

        Returns
        -------
        str
            Cleaned text with sensitive content replaced.  If the engine
            is disabled, *text* is returned unchanged.
        """
        if not self._enabled or not text:
            return text

        # We apply patterns sequentially.  Each pattern's replacement is
        # final — subsequent patterns see the already-redacted text.  This
        # is safe because REDACTION_PLACEHOLDER itself never matches any of
        # the patterns.
        result = text
        for _name, compiled in self._patterns:
            result = compiled.sub(self.REDACTION_PLACEHOLDER, result)
        return result

    def detect(self, text: str) -> list[RedactionMatch]:
        """Find all sensitive spans *without* modifying the text.

        Useful for preview / audit UIs where the user wants to see what
        *would* be redacted before committing.

        Parameters
        ----------
        text:
            Raw input text.

        Returns
        -------
        list[RedactionMatch]
            Matches sorted by start offset.  Overlapping matches from
            different patterns are all reported (the caller decides how
            to handle them).
        """
        if not self._enabled or not text:
            return []

        matches: list[RedactionMatch] = []
        for name, compiled in self._patterns:
            for m in compiled.finditer(text):
                matches.append(
                    RedactionMatch(
                        pattern_name=name,
                        start=m.start(),
                        end=m.end(),
                        original=m.group(),
                    )
                )

        # Sort by start offset for deterministic ordering.
        matches.sort(key=lambda rm: (rm.start, rm.end))
        return matches

    def add_pattern(self, name: str, pattern: str) -> None:
        """Register a custom redaction pattern at runtime.

        If *name* already exists it is replaced.  The pattern is compiled
        immediately; a ``re.error`` is raised for invalid regex.

        Parameters
        ----------
        name:
            Identifier for the pattern (used in :class:`RedactionMatch`).
        pattern:
            A valid Python regular expression string.

        Raises
        ------
        re.error
            If *pattern* is not a valid regular expression.
        """
        compiled = re.compile(pattern)  # raises re.error on bad regex

        # Remove existing entry with the same name, if any.
        self._patterns = [
            (n, p) for n, p in self._patterns if n != name
        ]
        self._patterns.append((name, compiled))

    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern by name.

        Parameters
        ----------
        name:
            The pattern identifier to remove.

        Returns
        -------
        bool
            ``True`` if the pattern existed and was removed, ``False``
            otherwise.
        """
        before = len(self._patterns)
        self._patterns = [
            (n, p) for n, p in self._patterns if n != name
        ]
        return len(self._patterns) < before

    @property
    def pattern_names(self) -> list[str]:
        """Return the names of all active patterns."""
        return [name for name, _ in self._patterns]
