"""Shannon entropy detection for secrets — Layer 2.

Identifies high-entropy strings that may be leaked secrets, API keys,
or tokens.  Part of the multi-layer detection pipeline:

  Layer 1 — regex pattern matching
  Layer 2 — Shannon entropy analysis  <-- this module
  Layer 3 — contextual validation

Pure functions, no side effects, no external dependencies beyond ``math``
and ``re``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntropyMatch:
    """A substring flagged as high-entropy."""

    text: str
    start: int
    end: int
    entropy_value: float
    length: int


# ---------------------------------------------------------------------------
# Safe-pattern filters (skip known non-secret high-entropy strings)
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_HEX_ONLY_RE = re.compile(r"^[0-9a-fA-F]+$")
_BASE64_SHORT_RE = re.compile(r"^[A-Za-z0-9+/]{1,24}={0,2}$")

# Common SHA digest lengths (hex-encoded): SHA-1(40), SHA-256(64),
# SHA-384(96), SHA-512(128)
_SHA_HEX_LENGTHS: frozenset[int] = frozenset({40, 64, 96, 128})

# Tokeniser: split on whitespace, quotes, common delimiters
_TOKEN_RE = re.compile(r"""[^\s"'`,;:=\[\]\{\}\(\)<>]+""")


def _is_safe_pattern(token: str) -> bool:
    """Return ``True`` if *token* matches a known safe high-entropy pattern."""
    # UUIDs (with hyphens)
    if _UUID_RE.match(token):
        return True
    # Pure hex strings at standard SHA digest lengths
    if _HEX_ONLY_RE.match(token) and len(token) in _SHA_HEX_LENGTHS:
        return True
    # Short base64-encoded values (<=24 chars before padding)
    if _BASE64_SHORT_RE.match(token):
        return True
    return False


# ---------------------------------------------------------------------------
# Core entropy calculation
# ---------------------------------------------------------------------------


def shannon_entropy(data: str) -> float:
    """Compute Shannon entropy in bits per character.

    Formula: ``-sum p(c) * log2(p(c))`` over the character frequency
    distribution of *data*.  Returns ``0.0`` for empty strings.
    """
    if not data:
        return 0.0
    length = len(data)
    freq: dict[str, int] = {}
    for ch in data:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum(
        (count / length) * math.log2(count / length)
        for count in freq.values()
    )


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class EntropyDetector:
    """Detect high-entropy tokens that may be embedded secrets.

    Parameters
    ----------
    threshold:
        Minimum Shannon entropy (bits/char) to flag a token.
    min_length:
        Minimum token length to consider.
    """

    def __init__(
        self,
        threshold: float = 4.5,
        min_length: int = 12,  # N4 fix: lowered from 16 to catch short API keys
    ) -> None:
        self.threshold = threshold
        self.min_length = min_length

    def detect_high_entropy_strings(self, text: str) -> list[EntropyMatch]:
        """Find all high-entropy tokens in *text*."""
        matches: list[EntropyMatch] = []
        for m in _TOKEN_RE.finditer(text):
            token = m.group()
            if len(token) < self.min_length:
                continue
            if _is_safe_pattern(token):
                continue
            ent = shannon_entropy(token)
            if ent >= self.threshold:
                matches.append(
                    EntropyMatch(
                        text=token,
                        start=m.start(),
                        end=m.end(),
                        entropy_value=round(ent, 4),
                        length=len(token),
                    )
                )
        return matches
