# tests/test_workflow/test_test_result_parser.py
"""
Tests for TestResultParser — pytest stdout parsing.

Covers:
- Standard pytest output formats
- Failed test extraction
- Error message extraction
- File location extraction
- Collection errors
- Empty/missing output
- Duration parsing
- Edge cases (unicode, multiline, malformed)
"""
from __future__ import annotations

import json
import pytest

from graqle.workflow.test_result_parser import ParsedTestResult, TestResultParser


@pytest.fixture
def parser():
    return TestResultParser()


# ============================================================================
# Standard Output Parsing (8 tests)
# ============================================================================


class TestStandardOutput:
    """Parse standard pytest output formats."""

    def test_all_passed(self, parser):
        """Parse output with all tests passing."""
        output = "========================= 5 passed in 0.42s ========================="
        result = parser.parse(output, exit_code=0)
        assert result.passed is True
        assert result.passed_count == 5
        assert result.total == 5
        assert result.failed_count == 0

    def test_mixed_passed_failed(self, parser):
        """Parse output with some passed and some failed."""
        output = """
FAILED tests/test_auth.py::test_login - AssertionError: expected 200
FAILED tests/test_auth.py::test_logout - KeyError: 'session'
=================== 2 failed, 8 passed in 1.23s ===================
"""
        result = parser.parse(output, exit_code=1)
        assert result.passed is False
        assert result.failed_count == 2
        assert result.passed_count == 8
        assert result.total == 10
        assert len(result.failed_tests) == 2
        assert "tests/test_auth.py::test_login" in result.failed_tests

    def test_all_failed(self, parser):
        """Parse output with all tests failing."""
        output = "========================= 3 failed in 0.15s ========================="
        result = parser.parse(output, exit_code=1)
        assert result.passed is False
        assert result.failed_count == 3
        assert result.passed_count == 0

    def test_with_skipped(self, parser):
        """Parse output with skipped tests."""
        output = "=============== 10 passed, 2 skipped in 2.50s ==============="
        result = parser.parse(output, exit_code=0)
        assert result.passed is True
        assert result.skipped_count == 2
        assert result.passed_count == 10
        assert result.total == 12

    def test_with_errors(self, parser):
        """Parse output with collection or runtime errors."""
        output = "=============== 1 failed, 2 error in 0.30s ==============="
        result = parser.parse(output, exit_code=1)
        assert result.passed is False
        assert result.error_count == 2
        assert result.failed_count == 1

    def test_duration_parsing(self, parser):
        """Duration is parsed correctly."""
        output = "========================= 5 passed in 3.14s ========================="
        result = parser.parse(output, exit_code=0)
        assert abs(result.duration_seconds - 3.14) < 0.01

    def test_no_duration(self, parser):
        """Missing duration defaults to 0."""
        output = "========================= 5 passed ========================="
        result = parser.parse(output, exit_code=0)
        assert result.duration_seconds == 0.0

    def test_raw_output_preserved(self, parser):
        """Raw output is preserved in result."""
        output = "some test output"
        result = parser.parse(output, exit_code=0)
        assert result.raw_output == output


# ============================================================================
# Failed Test Extraction (4 tests)
# ============================================================================


class TestFailedTestExtraction:
    """Extract failed test names from FAILED lines."""

    def test_single_failed_test(self, parser):
        """Extract one failed test."""
        output = "FAILED tests/test_api.py::test_endpoint"
        result = parser.parse(output, exit_code=1)
        assert result.failed_tests == ["tests/test_api.py::test_endpoint"]

    def test_parametrized_failed_test(self, parser):
        """Extract parametrized test with bracket notation."""
        output = "FAILED tests/test_api.py::test_endpoint[param1]"
        result = parser.parse(output, exit_code=1)
        assert result.failed_tests == ["tests/test_api.py::test_endpoint[param1]"]

    def test_multiple_failed_tests(self, parser):
        """Extract multiple failed tests."""
        output = """
FAILED tests/a.py::test_one
FAILED tests/b.py::test_two
FAILED tests/c.py::test_three
"""
        result = parser.parse(output, exit_code=1)
        assert len(result.failed_tests) == 3

    def test_no_failed_tests_returns_empty(self, parser):
        """No FAILED lines returns empty list."""
        output = "5 passed"
        result = parser.parse(output, exit_code=0)
        assert result.failed_tests == []


# ============================================================================
# Error Message Extraction (4 tests)
# ============================================================================


class TestErrorExtraction:
    """Extract error messages from E-prefixed lines."""

    def test_assertion_error(self, parser):
        """Extract AssertionError."""
        output = "E   AssertionError: expected True, got False"
        result = parser.parse(output, exit_code=1)
        assert len(result.error_messages) == 1
        assert "AssertionError" in result.error_messages[0]

    def test_type_error(self, parser):
        """Extract TypeError."""
        output = "E   TypeError: 'NoneType' object is not subscriptable"
        result = parser.parse(output, exit_code=1)
        assert len(result.error_messages) == 1
        assert "TypeError" in result.error_messages[0]

    def test_multiple_errors(self, parser):
        """Extract multiple error messages."""
        output = """
E   AssertionError: first
E   KeyError: second
"""
        result = parser.parse(output, exit_code=1)
        assert len(result.error_messages) == 2

    def test_no_errors_returns_empty(self, parser):
        """No E-prefixed lines returns empty list."""
        output = "5 passed"
        result = parser.parse(output, exit_code=0)
        assert result.error_messages == []


# ============================================================================
# File Location Extraction (3 tests)
# ============================================================================


class TestFileLocationExtraction:
    """Extract file:line locations from error tracebacks."""

    def test_extract_file_location(self, parser):
        """Extract file path and line number."""
        output = "tests/test_auth.py:42: AssertionError"
        result = parser.parse(output, exit_code=1)
        assert "tests/test_auth.py:42" in result.file_locations

    def test_multiple_locations(self, parser):
        """Extract multiple file locations."""
        output = """
tests/test_a.py:10: ValueError
tests/test_b.py:20: TypeError
"""
        result = parser.parse(output, exit_code=1)
        assert len(result.file_locations) == 2

    def test_no_locations_returns_empty(self, parser):
        """No file:line patterns returns empty list."""
        output = "5 passed"
        result = parser.parse(output, exit_code=0)
        assert result.file_locations == []


# ============================================================================
# Edge Cases (6 tests)
# ============================================================================


class TestEdgeCases:
    """Edge cases and special scenarios."""

    def test_empty_output(self, parser):
        """Empty string output returns default result."""
        result = parser.parse("", exit_code=0)
        assert result.passed is True
        assert result.total == 0

    def test_no_tests_ran(self, parser):
        """'no tests ran' is detected."""
        output = "========================= no tests ran ========================="
        result = parser.parse(output, exit_code=5)
        assert result.passed is False
        assert "No tests ran" in result.error_messages

    def test_collection_error(self, parser):
        """Collection errors are detected."""
        output = """
ERROR collecting tests/test_broken.py
ImportError: No module named 'missing_dep'
"""
        result = parser.parse(output, exit_code=2)
        assert result.passed is False

    def test_exit_code_overrides_counts(self, parser):
        """exit_code=0 means passed even if parsing is ambiguous."""
        output = "some weird output"
        result = parser.parse(output, exit_code=0)
        assert result.passed is True

    def test_exit_code_negative_one_uses_counts(self, parser):
        """exit_code=-1 means 'use parsed counts to determine passed'."""
        output = "========================= 5 passed in 0.10s ========================="
        result = parser.parse(output, exit_code=-1)
        assert result.passed is True

    def test_to_dict_json_serializable(self, parser):
        """ParsedTestResult.to_dict() is JSON-serializable."""
        result = ParsedTestResult(
            passed=False, total=10, passed_count=8, failed_count=2,
            failed_tests=["test_a", "test_b"],
            error_messages=["AssertionError"],
            raw_output="output",
        )
        serialized = json.dumps(result.to_dict())
        assert isinstance(serialized, str)
