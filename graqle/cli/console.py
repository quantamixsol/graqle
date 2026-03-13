"""Console-safe Unicode symbols for Windows cp1252 compatibility.

On Windows consoles using cp1252 encoding, certain Unicode characters
(e.g. U+2713 CHECK MARK) cause UnicodeEncodeError.  This module provides
safe fallbacks so CLI output works on every terminal.
"""

import sys


def safe_symbol(unicode_char: str, ascii_fallback: str) -> str:
    """Return *unicode_char* if the console can encode it, else *ascii_fallback*."""
    try:
        unicode_char.encode(sys.stdout.encoding or "utf-8")
        return unicode_char
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


# ── Pre-defined safe symbols ────────────────────────────────────────
CHECK = safe_symbol("\u2713", "[OK]")   # ✓
CROSS = safe_symbol("\u2717", "[X]")    # ✗
ARROW = safe_symbol("\u2192", "->")     # →
BULLET = safe_symbol("\u2022", "*")     # •
