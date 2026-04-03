"""Tests for GenerateResult dataclass — OT-028/030 Layer 1.

Covers: str backward-compat dunders, allowlist __getattr__, truncation fields.
Covers: str backward-compat dunders, allowlist __getattr__, truncation fields.
"""

import pytest

from graqle.backends.base import GenerateResult, TruncationError


class TestGenerateResultStrCompat:
    """str backward-compat: __str__, __add__, __radd__, __len__, etc."""

    def setup_method(self):
        self.result = GenerateResult(text="  hello world  ", model="test")

    def test_str_returns_text(self):
        assert str(self.result) == "  hello world  "

    def test_format_returns_text(self):
        assert f"{self.result}" == "  hello world  "

    def test_add_str(self):
        assert self.result + " suffix" == "  hello world   suffix"

    def test_radd_str(self):
        assert "prefix " + self.result == "prefix   hello world  "

    def test_add_generate_result(self):
        other = GenerateResult(text=" other")
        assert self.result + other == "  hello world   other"

    def test_contains(self):
        assert "hello" in self.result
        assert "xyz" not in self.result

    def test_len(self):
        assert len(self.result) == 15

    def test_bool_truthy(self):
        assert bool(self.result)

    def test_bool_falsy(self):
        assert not bool(GenerateResult(text=""))

    def test_eq_str(self):
        assert self.result == "  hello world  "

    def test_eq_generate_result(self):
        other = GenerateResult(text="  hello world  ", model="different")
        assert self.result == other

    def test_hash_matches_str(self):
        assert hash(self.result) == hash("  hello world  ")

    def test_getitem_index(self):
        assert self.result[0] == " "
        assert self.result[2] == "h"

    def test_getitem_slice(self):
        assert self.result[2:7] == "hello"

    def test_iter_chars(self):
        chars = list(self.result)
        assert chars == list("  hello world  ")


class TestGenerateResultAllowlist:
    """B3 fix: __getattr__ restricted to allowlist."""

    def setup_method(self):
        self.result = GenerateResult(text="  hello world  ")

    def test_strip_delegates(self):
        assert self.result.strip() == "hello world"

    def test_split_delegates(self):
        stripped = GenerateResult(text="hello world")
        assert stripped.split() == ["hello", "world"]

    def test_typo_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="truncatd"):
            self.result.truncatd

    def test_typo_error_message_includes_allowlist(self):
        with pytest.raises(AttributeError, match="Delegated str methods"):
            self.result.stop_resaon

    def test_allowlisted_upper_works(self):
        assert self.result.upper() == "  HELLO WORLD  "

    def test_allowlisted_lower_works(self):
        assert self.result.lower() == "  hello world  "

    def test_allowlisted_startswith(self):
        assert self.result.startswith("  h")

    def test_allowlisted_endswith(self):
        assert self.result.endswith("  ")

    def test_allowlisted_replace(self):
        assert self.result.replace("hello", "hi") == "  hi world  "

    def test_allowlisted_find(self):
        assert self.result.find("world") == 8

    def test_allowlisted_encode(self):
        assert isinstance(self.result.encode(), bytes)

    def test_non_str_attribute_raises(self):
        with pytest.raises(AttributeError, match="truncatd"):
            self.result.truncatd

    def test_text_dot_method_workaround(self):
        """Verify the error message's suggested workaround works."""
        assert self.result.text.upper() == "  HELLO WORLD  "
        assert self.result.text.lower() == "  hello world  "


class TestGenerateResultTruncation:
    """Truncation detection fields."""

    def test_not_truncated_by_default(self):
        r = GenerateResult(text="hello")
        assert not r.truncated
        assert r.is_complete
        assert r.stop_reason == ""
        assert r.tokens_used is None

    def test_truncated_flag(self):
        r = GenerateResult(
            text="partial...", truncated=True,
            stop_reason="max_tokens", tokens_used=512, model="claude",
        )
        assert r.truncated
        assert not r.is_complete
        assert r.stop_reason == "max_tokens"
        assert r.tokens_used == 512
        assert r.model == "claude"

    def test_repr_shows_truncated(self):
        r = GenerateResult(text="x", truncated=True, stop_reason="max_tokens")
        assert "[TRUNCATED]" in repr(r)

    def test_repr_no_truncated(self):
        r = GenerateResult(text="x")
        assert "[TRUNCATED]" not in repr(r)


class TestTruncationError:
    def test_raises_with_result(self):
        r = GenerateResult(text="partial", truncated=True, stop_reason="max_tokens")
        with pytest.raises(TruncationError) as exc_info:
            raise TruncationError("test", result=r)
        assert exc_info.value.result is r
        assert "test" in str(exc_info.value)
