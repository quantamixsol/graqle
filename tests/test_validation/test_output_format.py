"""Tests for Layer 3 format-aware output validation (OT-028/030/035).

Tests format checks: balanced delimiters, SUMMARY marker, diff hunks, formula markers.
"""

import pytest

from graqle.validation.output_format import validate_generate_output


class TestBalancedDelimiters:
    def test_balanced_passes(self):
        r = validate_generate_output(
            "def foo():\n    return {1: [2, (3,)]}\n\nSUMMARY: done",
            expect_summary=True,
        )
        assert not any(d.check == "balanced_delimiters" for d in r.diagnostics)

    def test_unclosed_brace_fails(self):
        r = validate_generate_output(
            "def foo():\n    x = {\n" + "x" * 300 + "\nSUMMARY: done",
        )
        assert not r.valid
        assert any(d.check == "balanced_delimiters" for d in r.diagnostics)
        assert r.truncation_suspected

    def test_unclosed_paren_fails(self):
        r = validate_generate_output(
            "print(foo(\n" + "x" * 300 + "\nSUMMARY: done",
        )
        assert not r.valid

    def test_braces_in_strings_ignored(self):
        r = validate_generate_output(
            'x = "unclosed { brace in string"\n\nSUMMARY: done\n' + "x" * 200,
        )
        assert not any(d.check == "balanced_delimiters" for d in r.diagnostics)

    def test_braces_in_comments_ignored(self):
        r = validate_generate_output(
            "# unclosed { in comment\ndef f(): pass\n\nSUMMARY: done\n" + "x" * 200,
        )
        assert not any(d.check == "balanced_delimiters" for d in r.diagnostics)


class TestSummaryMarker:
    def test_summary_present_passes(self):
        r = validate_generate_output("code\n" * 30 + "SUMMARY: all good")
        assert not any(d.check == "summary_marker" for d in r.diagnostics)

    def test_summary_missing_on_long_output_fails(self):
        r = validate_generate_output("x\n" * 300)
        assert any(d.check == "summary_marker" for d in r.diagnostics)
        assert r.truncation_suspected

    def test_summary_not_required_on_short_output(self):
        r = validate_generate_output("short output")
        assert not any(d.check == "summary_marker" for d in r.diagnostics)

    def test_summary_skipped_for_raw_format(self):
        r = validate_generate_output(
            "raw output\n" * 50,
            expect_summary=False,
        )
        assert not any(d.check == "summary_marker" for d in r.diagnostics)


class TestDiffHunks:
    def test_valid_diff_passes(self):
        diff = "@@ -1,3 +1,4 @@\n-old\n+new\n context\n\nSUMMARY: done"
        r = validate_generate_output(diff, output_format="diff")
        assert not any(d.check == "diff_hunk_integrity" for d in r.diagnostics)

    def test_empty_hunk_body_fails(self):
        # Hunk header followed only by non-diff lines (no +/-/space content)
        diff = "@@ -1,3 +1,4 @@\nsome text without diff markers\nanother line\nyet another\n\nSUMMARY: done" + "x" * 200
        r = validate_generate_output(diff, output_format="diff")
        assert any(d.check == "diff_hunk_integrity" for d in r.diagnostics)

    def test_non_diff_skips_hunk_check(self):
        r = validate_generate_output(
            "regular code\n" * 30 + "SUMMARY: done",
            output_format="code",
        )
        assert not any(d.check == "diff_hunk_integrity" for d in r.diagnostics)


class TestFormulaMarkers:
    def test_empty_default_skips_check(self):
        """Default SPEC_SENSITIVE_IDENTIFIERS is empty — no check runs."""
        r = validate_generate_output(
            "some_config_var = 0.5\nanother_var = 1.2\n\nSUMMARY: done\n" + "x" * 200,
        )
        # Default markers are empty — nothing flagged
        assert not any(d.check == "formula_divergence_risk" for d in r.diagnostics)

    def test_no_spec_constants_clean(self):
        r = validate_generate_output(
            "x = 42\nreturn x\n\nSUMMARY: done\n" + "x" * 200,
        )
        assert not any(d.check == "formula_divergence_risk" for d in r.diagnostics)


class TestEmptyOutput:
    def test_empty_string_fails(self):
        r = validate_generate_output("")
        assert not r.valid
        assert any(d.check == "empty_output" for d in r.diagnostics)

    def test_whitespace_only_fails(self):
        r = validate_generate_output("   \n  \n  ")
        assert not r.valid

    def test_to_dict_structure(self):
        r = validate_generate_output("code\n" * 30 + "SUMMARY: ok")
        d = r.to_dict()
        assert "format_valid" in d
        assert "format_warnings" in d
        assert "truncation_suspected" in d
