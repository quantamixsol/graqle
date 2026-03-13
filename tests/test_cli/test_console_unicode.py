"""Tests for graqle.cli.console — safe Unicode symbol fallback."""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

from graqle.cli.console import safe_symbol


class TestSafeSymbol:
    """safe_symbol returns unicode when supported, ASCII fallback otherwise."""

    def test_returns_unicode_when_encoding_supports_it(self):
        """UTF-8 consoles should get the real Unicode character."""
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2713", "[OK]") == "\u2713"  # checkmark
            assert safe_symbol("\u2192", "->") == "\u2192"    # arrow
            assert safe_symbol("\u2022", "*") == "\u2022"     # bullet

    def test_returns_fallback_on_cp1252(self):
        """Windows cp1252 cannot encode checkmark or arrow; fallback must be used."""
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2713", "[OK]") == "[OK]"   # checkmark NOT in cp1252
            assert safe_symbol("\u2192", "->") == "->"       # arrow NOT in cp1252

    def test_returns_fallback_on_ascii(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2713", "[OK]") == "[OK]"

    def test_returns_unicode_for_cp1252_compatible_chars(self):
        """Em-dash (U+2014) IS in cp1252, so it should pass through."""
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2014", "--") == "\u2014"

    def test_handles_none_encoding(self):
        """If sys.stdout.encoding is None, fall back to utf-8 (safe)."""
        mock_stdout = MagicMock()
        mock_stdout.encoding = None
        with patch.object(sys, "stdout", mock_stdout):
            # Falls back to utf-8 internally, so unicode should work
            assert safe_symbol("\u2713", "[OK]") == "\u2713"

    def test_handles_unknown_encoding(self):
        """If encoding is an unrecognized name, use the fallback."""
        mock_stdout = MagicMock()
        mock_stdout.encoding = "bogus-999"
        with patch.object(sys, "stdout", mock_stdout):
            assert safe_symbol("\u2713", "[OK]") == "[OK]"
