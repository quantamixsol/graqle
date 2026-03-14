"""Console utilities for universal Unicode-safe output.

Handles the Windows cp1252 crash (P0-002) universally across
Windows, Linux, and macOS by:

1. Reconfiguring sys.stdout/stderr to UTF-8 BEFORE Rich loads
2. Creating Rich Console with force_terminal=True to bypass Win32 console writes
3. Providing safe_symbol() for inline Unicode with ASCII fallbacks
4. Sanitizing strings that may contain problematic Unicode

This is the SINGLE source of truth for console output in the CLI.
"""

from __future__ import annotations

import io
import os
import sys


def _ensure_utf8_streams() -> None:
    """Reconfigure stdout/stderr to use UTF-8 encoding.

    This MUST run before any Rich import or console creation.
    Works on Windows (cp1252), Linux, and macOS.
    """
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Python 3.7+ has reconfigure()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Fallback: wrap with a UTF-8 TextIOWrapper
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace",
                line_buffering=True,
            )
        except (AttributeError, TypeError):
            pass
    if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace",
                line_buffering=True,
            )
        except (AttributeError, TypeError):
            pass


# Run immediately on import — before Rich or any other library
_ensure_utf8_streams()


def create_console():
    """Create a Rich Console configured for universal Unicode support.

    Returns a Console that works on Windows cp1252, Linux, and macOS.
    """
    from rich.console import Console

    # On Windows, force Rich to use standard file output (not Win32 console API)
    # This avoids the _win32_console.py crash entirely
    if sys.platform == "win32":
        return Console(force_terminal=True, force_jupyter=False)

    return Console()


def safe_symbol(unicode_char: str, ascii_fallback: str) -> str:
    """Return *unicode_char* if the console can encode it, else *ascii_fallback*."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        unicode_char.encode(encoding)
        return unicode_char
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


def sanitize_output(text: str) -> str:
    """Replace problematic Unicode characters with safe ASCII equivalents.

    Use this for any text that may contain Unicode arrows, symbols, etc.
    from graph data before printing.
    """
    replacements = {
        "\u2192": "->",   # ->
        "\u2190": "<-",   # <-
        "\u2194": "<->",  # <->
        "\u2713": "[OK]", # checkmark
        "\u2717": "[X]",  # X mark
        "\u2022": "*",    # bullet
        "\u2023": ">",    # triangular bullet
        "\u25cf": "(o)",  # black circle
        "\u25cb": "()",   # white circle
        "\u2605": "*",    # black star
        "\u2606": "*",    # white star
        "\u26a0": "!",    # warning
        "\u2714": "[OK]", # heavy checkmark
        "\u2716": "[X]",  # heavy X mark
    }
    # Only apply on Windows with non-UTF-8 encoding
    encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    if encoding.lower() in ("utf-8", "utf8"):
        return text
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


# ── Pre-defined safe symbols ────────────────────────────────────────
CHECK = safe_symbol("\u2713", "[OK]")   # checkmark
CROSS = safe_symbol("\u2717", "[X]")    # X mark
ARROW = safe_symbol("\u2192", "->")     # arrow
BULLET = safe_symbol("\u2022", "*")     # bullet

# ── Brand constants (Rich markup) ──────────────────────────────────
# The Q is the visual anchor — Ring Blue (#1998D5), always bold.
# Use BRAND_NAME in all console.print() calls for consistent branding.
BRAND_NAME = "gra[bold #1998D5]Q[/bold #1998D5]le"
BRAND_NAME_PLAIN = "graQle"  # for non-Rich contexts (logs, plain text)
