"""Tests for OT-028 Layer 2: Continuation loop for truncated responses.

Tests the helpers (_build_continuation_prompt, _extract_overlap_anchor,
_deduplicate_seam) and the loop integration in CogniNode.reason().
Tests the helpers and loop integration in CogniNode.reason().
"""

import pytest

from graqle.core.node import (
    _build_continuation_prompt,
    _deduplicate_seam,
    _extract_overlap_anchor,
)


class TestExtractOverlapAnchor:
    def test_extracts_last_n_lines(self):
        content = "\n".join(f"line {i}" for i in range(20))
        anchor = _extract_overlap_anchor(content, n_lines=5)
        assert anchor == "line 15\nline 16\nline 17\nline 18\nline 19"

    def test_short_content_returns_all(self):
        content = "line 1\nline 2"
        anchor = _extract_overlap_anchor(content, n_lines=15)
        assert anchor == "line 1\nline 2"

    def test_empty_content(self):
        assert _extract_overlap_anchor("", n_lines=15) == ""

    def test_single_line(self):
        assert _extract_overlap_anchor("hello", n_lines=15) == "hello"


class TestBuildContinuationPrompt:
    def test_contains_overlap(self):
        prompt = _build_continuation_prompt("last line here")
        assert "last line here" in prompt

    def test_contains_instructions(self):
        prompt = _build_continuation_prompt("anchor")
        assert "Continue EXACTLY" in prompt
        assert "Do not repeat" in prompt

    def test_contains_markers(self):
        prompt = _build_continuation_prompt("anchor")
        assert "=== LAST LINES" in prompt
        assert "=== END PREVIOUS ===" in prompt


class TestDeduplicateSeam:
    def test_exact_overlap_removed(self):
        prev = "line 1\nline 2\nline 3\nline 4\nline 5"
        cont = "line 4\nline 5\nline 6\nline 7"
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7"

    def test_no_overlap_concatenates(self):
        prev = "line 1\nline 2"
        cont = "line 3\nline 4"
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "line 1\nline 2\nline 3\nline 4"

    def test_empty_continuation_returns_previous(self):
        prev = "line 1\nline 2"
        result = _deduplicate_seam(prev, "", overlap_lines=5)
        assert result == prev

    def test_empty_continuation_whitespace(self):
        prev = "line 1\nline 2"
        result = _deduplicate_seam(prev, "   \n  ", overlap_lines=5)
        assert result == prev

    def test_similar_but_different_lines_no_false_dedup(self):
        prev = "the quick brown fox"
        cont = "the slow red cat"  # Different content — no overlap
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "the quick brown fox\nthe slow red cat"

    def test_identical_single_line_overlap(self):
        prev = "the quick brown fox"
        cont = "the quick brown fox\njumps over"
        # Identical line = 1-line overlap, dedup correctly
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "the quick brown fox\njumps over"

    def test_single_line_overlap(self):
        prev = "line 1\nline 2\nline 3"
        cont = "line 3\nline 4"
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "line 1\nline 2\nline 3\nline 4"

    def test_full_overlap_returns_previous(self):
        prev = "line 1\nline 2\nline 3"
        cont = "line 1\nline 2\nline 3"
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "line 1\nline 2\nline 3"

    def test_multi_line_overlap(self):
        prev = "a\nb\nc\nd\ne"
        cont = "c\nd\ne\nf\ng"
        result = _deduplicate_seam(prev, cont, overlap_lines=5)
        assert result == "a\nb\nc\nd\ne\nf\ng"
