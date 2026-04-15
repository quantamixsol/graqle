"""
tests/test_generation/test_ot023_hardening.py
OT-023 hardening — Verify _apply_patch_to_lines rejects misaligned diffs
with configurable threshold, positional coherence, and deletion tracking.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from graqle.core.file_writer import (
    ApplyResult,
    DiffApplicationError,
    _apply_patch_to_lines,
    _parse_unified_diff,
    apply_diff,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORIGINAL_LINES = [
    "def greet(name):\n",
    '    """Say hello."""\n',
    '    return f"Hello, {name}"\n',
    "\n",
    "def farewell(name):\n",
    '    """Say goodbye."""\n',
    '    return f"Goodbye, {name}"\n',
]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Parameter validation for context_match_threshold and max_gap."""

    def test_threshold_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="context_match_threshold"):
            _apply_patch_to_lines(ORIGINAL_LINES, [], context_match_threshold=0.0)

    def test_threshold_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="context_match_threshold"):
            _apply_patch_to_lines(ORIGINAL_LINES, [], context_match_threshold=1.5)

    def test_negative_max_gap_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_gap"):
            _apply_patch_to_lines(ORIGINAL_LINES, [], max_gap=-1)

    def test_max_gap_zero_uses_auto(self) -> None:
        """max_gap=0 (default) auto-computes from file size."""
        diff_ops = [
            (" ", 'def greet(name):'),
            ("+", "    # test\n"),
        ]
        # Should not raise — auto max_gap = max(50, 7//5) = 50
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)
        assert "# test" in "".join(result)


# ---------------------------------------------------------------------------
# Threshold tests
# ---------------------------------------------------------------------------

class TestContextMatchThreshold:
    """configurable context_match_threshold parameter."""

    def test_default_threshold_rejects_low_match(self) -> None:
        """0 of 4 context lines match → should raise DiffApplicationError."""
        diff_ops = [
            (" ", "NONEXISTENT LINE 1"),
            (" ", "NONEXISTENT LINE 2"),
            (" ", "NONEXISTENT LINE 3"),
            (" ", "NONEXISTENT LINE 4"),
            ("+", "    # new comment\n"),
        ]
        with pytest.raises(DiffApplicationError, match="context mismatch"):
            _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)

    def test_custom_threshold_strict(self) -> None:
        """With threshold=0.8, even 50% match is rejected."""
        diff_ops = [
            (" ", 'def greet(name):'),             # matches line 0
            (" ", "NONEXISTENT"),                    # doesn't match
            (" ", "NONEXISTENT2"),                   # doesn't match
            (" ", '    return f"Hello, {name}"'),    # matches line 2
            ("+", "    # new line\n"),
        ]
        with pytest.raises(DiffApplicationError, match="context mismatch"):
            _apply_patch_to_lines(
                ORIGINAL_LINES, diff_ops, context_match_threshold=0.8
            )

    def test_custom_threshold_lenient(self) -> None:
        """With threshold=0.2, 50% match is accepted."""
        diff_ops = [
            (" ", 'def greet(name):'),
            (" ", "NONEXISTENT"),
            ("+", "    # added\n"),
        ]
        # 1 of 2 = 50%, which is above 0.2
        result = _apply_patch_to_lines(
            ORIGINAL_LINES, diff_ops, context_match_threshold=0.2
        )
        assert "# added" in "".join(result)

    def test_all_context_matches_passes(self) -> None:
        """When all context lines match, patch applies successfully."""
        diff_ops = [
            (" ", 'def greet(name):'),
            (" ", '    """Say hello."""'),
            ("+", "    # OT-023 test\n"),
            (" ", '    return f"Hello, {name}"'),
        ]
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)
        joined = "".join(result)
        assert "# OT-023 test" in joined
        assert "def greet(name):" in joined
        assert "def farewell(name):" in joined


# ---------------------------------------------------------------------------
# Positional coherence tests
# ---------------------------------------------------------------------------

class TestPositionalCoherence:
    """max_gap parameter catches scattered matches on duplicate lines."""

    def test_large_gap_rejected(self) -> None:
        """Context lines that match positions far apart are rejected."""
        lines_with_gaps = [
            "def a():\n",      # 0
            "    pass\n",       # 1
            "\n",               # 2
            "# filler 1\n",    # 3
            "# filler 2\n",    # 4
            "# filler 3\n",    # 5
            "# filler 4\n",    # 6
            "# filler 5\n",    # 7
            "# filler 6\n",    # 8
            "# filler 7\n",    # 9
            "# filler 8\n",    # 10
            "# filler 9\n",    # 11
            "# filler 10\n",   # 12
            "# filler 11\n",   # 13
            "def b():\n",      # 14
            "    pass\n",       # 15
        ]
        # Context lines match at positions 0 and 14 → gap = 14 > explicit 10
        diff_ops = [
            (" ", "def a():"),
            (" ", "def b():"),
            ("+", "    # inserted\n"),
        ]
        with pytest.raises(DiffApplicationError, match="non-contiguous"):
            _apply_patch_to_lines(lines_with_gaps, diff_ops, max_gap=10)

    def test_small_gap_accepted(self) -> None:
        """Context lines within max_gap are accepted."""
        diff_ops = [
            (" ", 'def greet(name):'),
            (" ", '    """Say hello."""'),
            ("+", "    # comment\n"),
            (" ", '    return f"Hello, {name}"'),
        ]
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops, max_gap=5)
        assert "# comment" in "".join(result)

    def test_custom_max_gap(self) -> None:
        """max_gap=3 rejects a gap of 4."""
        # greet is at line 0, farewell at line 4 → gap = 4
        diff_ops = [
            (" ", "def greet(name):"),
            (" ", "def farewell(name):"),
            ("+", "    # added\n"),
        ]
        with pytest.raises(DiffApplicationError, match="non-contiguous"):
            _apply_patch_to_lines(ORIGINAL_LINES, diff_ops, max_gap=3)

    def test_single_context_line_skips_coherence(self) -> None:
        """Single context line — no gap to check, should pass."""
        diff_ops = [
            (" ", 'def greet(name):'),
            ("+", "    # only one context line\n"),
        ]
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)
        assert "# only one context line" in "".join(result)

    def test_auto_max_gap_scales_with_file_size(self) -> None:
        """Default max_gap=0 auto-computes: max(200, n//3).

        v0.51.4 (BUG-4): default raised from max(50, n//5) to max(200, n//3)
        so edits on medium-to-large files with repeated tokens like ``try {``
        no longer reject valid diffs. Reject now requires a much larger gap.
        """
        # 900-line file → auto max_gap = max(200, 300) = 300
        big_file = [f"# line {i}\n" for i in range(900)]
        big_file[0] = "def start():\n"
        big_file[500] = "def middle():\n"
        diff_ops = [
            (" ", "def start():"),
            (" ", "def middle():"),
            ("+", "    # inserted\n"),
        ]
        # Gap of 500 > auto max_gap of 300 → should reject
        with pytest.raises(DiffApplicationError, match="non-contiguous"):
            _apply_patch_to_lines(big_file, diff_ops)  # max_gap=0 → auto=300


# ---------------------------------------------------------------------------
# Deletion mismatch tracking
# ---------------------------------------------------------------------------

class TestDeletionMismatch:
    """Unmatched delete lines should raise DiffApplicationError."""

    def test_unmatched_delete_raises(self) -> None:
        """Deleting a line that doesn't exist in the file → error."""
        diff_ops = [
            (" ", "def greet(name):"),
            ("-", "    THIS LINE DOES NOT EXIST"),
            ("+", "    # replacement\n"),
        ]
        with pytest.raises(DiffApplicationError, match="delete line not found"):
            _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)

    def test_matched_delete_works(self) -> None:
        """Deleting an existing line → works correctly."""
        diff_ops = [
            (" ", 'def greet(name):'),
            ("-", '    """Say hello."""'),
            (" ", '    return f"Hello, {name}"'),
        ]
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)
        joined = "".join(result)
        assert '"""Say hello."""' not in joined
        assert "def greet(name):" in joined


# ---------------------------------------------------------------------------
# Integration: apply_diff surfaces DiffApplicationError correctly
# ---------------------------------------------------------------------------

class TestApplyDiffOT023Integration:
    """apply_diff() catches DiffApplicationError and returns ApplyResult."""

    def test_mismatched_diff_returns_failure(self, tmp_path: Path) -> None:
        """Diff with wrong context lines → success=False, error message."""
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")

        bad_diff = """\
--- a/test.py
+++ b/test.py
@@ -1,2 +1,3 @@
 WRONG CONTEXT LINE 1
 WRONG CONTEXT LINE 2
+    # new code
"""
        result = apply_diff(f, bad_diff)
        assert result.success is False
        assert "context mismatch" in result.error.lower() or "mismatch" in result.error.lower()

    def test_good_diff_applies_successfully(self, tmp_path: Path) -> None:
        """Diff with correct context → success=True."""
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")

        good_diff = """\
--- a/test.py
+++ b/test.py
@@ -1,2 +1,3 @@
 def hello():
+    \"\"\"Say hello.\"\"\"
     pass
"""
        result = apply_diff(f, good_diff, dry_run=True)
        assert result.success is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestOT023EdgeCases:
    """Edge cases for the hardened _apply_patch_to_lines."""

    def test_no_context_lines_in_diff(self) -> None:
        """Diff with only additions — no context to check."""
        diff_ops = [
            ("+", "# line 1\n"),
            ("+", "# line 2\n"),
        ]
        result = _apply_patch_to_lines(ORIGINAL_LINES, diff_ops)
        joined = "".join(result)
        assert "# line 1" in joined

    def test_empty_original_raises_on_context(self) -> None:
        """Empty file + context lines → 0 matches → raises."""
        diff_ops = [
            (" ", "some context"),
            ("+", "# new\n"),
        ]
        with pytest.raises(DiffApplicationError, match="context mismatch"):
            _apply_patch_to_lines([], diff_ops)

    def test_empty_diff_ops(self) -> None:
        """Empty diff_ops → returns original unchanged."""
        result = _apply_patch_to_lines(ORIGINAL_LINES, [])
        assert result == ORIGINAL_LINES
