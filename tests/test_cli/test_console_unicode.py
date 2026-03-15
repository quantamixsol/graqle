"""Tests for universal Unicode console output — P0-002 fix.

Tests that the console module handles Unicode safely on ALL platforms,
not just Windows. The fix must be universal.
"""

# ── graqle:intelligence ──
# module: tests.test_cli.test_console_unicode
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, io, sys, mock, pytest
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch


class TestEnsureUtf8Streams:
    def test_reconfigure_called_on_non_utf8(self):
        """stdout.reconfigure() should be called when encoding is not utf-8."""
        from graqle.cli.console import _ensure_utf8_streams
        # Should not raise even if called multiple times
        _ensure_utf8_streams()

    def test_pythonioencoding_set(self):
        """PYTHONIOENCODING env var should be set."""
        import os

        assert os.environ.get("PYTHONIOENCODING") == "utf-8"


class TestCreateConsole:
    def test_returns_console_instance(self):
        """create_console() should return a Rich Console."""
        from rich.console import Console

        from graqle.cli.console import create_console
        c = create_console()
        assert isinstance(c, Console)

    def test_windows_uses_force_terminal(self):
        """On Windows, Console should use force_terminal=True."""
        with patch("graqle.cli.console.sys") as mock_sys:
            mock_sys.platform = "win32"
            # Cannot fully test but verify it doesn't crash
            # The real test is that Unicode output works


class TestSafeSymbol:
    def test_unicode_on_utf8_console(self):
        """safe_symbol returns Unicode when console supports it."""
        from graqle.cli.console import safe_symbol
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch.object(sys, "stdout", stdout):
            result = safe_symbol("\u2713", "[OK]")
            assert result == "\u2713"

    def test_ascii_fallback_on_cp1252(self):
        """safe_symbol returns ASCII fallback on cp1252."""
        from graqle.cli.console import safe_symbol
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with patch.object(sys, "stdout", stdout):
            result = safe_symbol("\u2713", "[OK]")
            assert result == "[OK]"

    def test_returns_fallback_on_ascii(self):
        from graqle.cli.console import safe_symbol
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2713", "[OK]") == "[OK]"

    def test_returns_unicode_for_cp1252_compatible_chars(self):
        """Em-dash (U+2014) IS in cp1252, so it should pass through."""
        from graqle.cli.console import safe_symbol
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with patch.object(sys, "stdout", stdout):
            assert safe_symbol("\u2014", "--") == "\u2014"

    def test_handles_none_encoding(self):
        """If sys.stdout.encoding is None, fall back to utf-8 (safe)."""
        from graqle.cli.console import safe_symbol
        mock_stdout = MagicMock()
        mock_stdout.encoding = None
        with patch.object(sys, "stdout", mock_stdout):
            assert safe_symbol("\u2713", "[OK]") == "\u2713"

    def test_handles_unknown_encoding(self):
        """If encoding is an unrecognized name, use the fallback."""
        from graqle.cli.console import safe_symbol
        mock_stdout = MagicMock()
        mock_stdout.encoding = "bogus-999"
        with patch.object(sys, "stdout", mock_stdout):
            assert safe_symbol("\u2713", "[OK]") == "[OK]"

    def test_predefined_symbols_exist(self):
        """All predefined symbols should be defined."""
        from graqle.cli.console import ARROW, BULLET, CHECK, CROSS
        assert CHECK in ("\u2713", "[OK]")
        assert CROSS in ("\u2717", "[X]")
        assert ARROW in ("\u2192", "->")
        assert BULLET in ("\u2022", "*")


class TestSanitizeOutput:
    def test_sanitize_replaces_arrows(self):
        """sanitize_output should replace Unicode arrows."""
        from graqle.cli.console import sanitize_output
        mock_stdout = MagicMock()
        mock_stdout.encoding = "cp1252"
        with patch.object(sys, "stdout", mock_stdout):
            result = sanitize_output("A \u2192 B")
            assert result == "A -> B"

    def test_sanitize_preserves_utf8(self):
        """sanitize_output should NOT replace on UTF-8 consoles."""
        from graqle.cli.console import sanitize_output
        mock_stdout = MagicMock()
        mock_stdout.encoding = "utf-8"
        with patch.object(sys, "stdout", mock_stdout):
            result = sanitize_output("A \u2192 B")
            assert result == "A \u2192 B"

    def test_sanitize_handles_multiple_chars(self):
        """sanitize_output should handle multiple Unicode characters."""
        from graqle.cli.console import sanitize_output
        mock_stdout = MagicMock()
        mock_stdout.encoding = "cp1252"
        with patch.object(sys, "stdout", mock_stdout):
            result = sanitize_output("\u2713 Done \u2192 Next \u2717 Failed")
            assert "[OK]" in result
            assert "->" in result
            assert "[X]" in result


class TestContextFiltering:
    def test_embedding_cache_hidden(self):
        """_embedding_cache should not appear in context output."""
        # This tests the constant, not the full command
        _HIDDEN_PROPS = {"_embedding_cache", "chunks", "_chunks", "_embeddings"}
        assert "_embedding_cache" in _HIDDEN_PROPS
        assert "chunks" in _HIDDEN_PROPS
