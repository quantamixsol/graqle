# graqle/workflow/test_result_parser.py
"""
TestResultParser: parse pytest stdout into structured results.

Extracts failed_tests, error_messages, and file_locations from pytest output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedTestResult:
    """Structured parse of pytest output."""

    passed: bool
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    failed_tests: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    file_locations: list[str] = field(default_factory=list)
    raw_output: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "failed_tests": self.failed_tests,
            "error_messages": self.error_messages[:10],  # cap for LLM context
            "file_locations": self.file_locations[:10],
            "duration_seconds": self.duration_seconds,
        }


# Individual count patterns (order-independent)
_FAILED_COUNT_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
_PASSED_COUNT_RE = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
_ERROR_COUNT_RE = re.compile(r"(\d+)\s+error", re.IGNORECASE)
_SKIPPED_COUNT_RE = re.compile(r"(\d+)\s+skipped", re.IGNORECASE)
_DURATION_RE = re.compile(r"in\s+([\d.]+)s", re.IGNORECASE)

# Summary line pattern — matches the === border lines
_SUMMARY_LINE_RE = re.compile(r"={3,}\s+.*(?:passed|failed|error).*\s+={3,}", re.IGNORECASE)

# Match "FAILED tests/test_foo.py::test_bar - ..." at start of line
# (the short test summary section format)
_FAILED_TEST_RE = re.compile(
    r"^FAILED\s+([\w/.\\]+::\w+(?:\[.*?\])?)",
    re.MULTILINE,
)

# Match "E   AssertionError: ..." or "E   TypeError: ..."
_ERROR_MSG_RE = re.compile(
    r"^E\s+(\w+(?:Error|Exception|Warning):\s*.+)$",
    re.MULTILINE,
)

# Match file locations like "tests/test_foo.py:42: AssertionError"
_FILE_LOCATION_RE = re.compile(
    r"([\w/.]+\.py):(\d+):\s+(\w+(?:Error|Exception))"
)

# Match "no tests ran" or collection errors
_NO_TESTS_RE = re.compile(r"no\s+tests\s+ran", re.IGNORECASE)
_COLLECTION_ERROR_RE = re.compile(
    r"(?:ERROR\s+collecting|ERRORS?\s+during\s+collection)", re.IGNORECASE
)


class TestResultParser:
    """Parse pytest stdout into structured ParsedTestResult."""

    def parse(self, stdout: str, exit_code: int = -1) -> ParsedTestResult:
        """
        Parse pytest output.

        Parameters
        ----------
        stdout : str
            Raw pytest stdout/stderr combined output.
        exit_code : int
            Process exit code. 0 = all passed, 1 = failures, 2 = error, etc.

        Returns
        -------
        ParsedTestResult
        """
        result = ParsedTestResult(
            passed=exit_code == 0,
            raw_output=stdout,
        )

        if not stdout:
            return result

        # Find the summary line (=== ... passed/failed ... ===)
        summary_line = _SUMMARY_LINE_RE.search(stdout)
        summary_text = summary_line.group(0) if summary_line else stdout

        # Parse counts (order-independent)
        failed_m = _FAILED_COUNT_RE.search(summary_text)
        passed_m = _PASSED_COUNT_RE.search(summary_text)
        error_m = _ERROR_COUNT_RE.search(summary_text)
        skipped_m = _SKIPPED_COUNT_RE.search(summary_text)
        duration_m = _DURATION_RE.search(summary_text)

        if failed_m:
            result.failed_count = int(failed_m.group(1))
        if passed_m:
            result.passed_count = int(passed_m.group(1))
        if error_m:
            result.error_count = int(error_m.group(1))
        if skipped_m:
            result.skipped_count = int(skipped_m.group(1))

        result.total = (
            result.failed_count
            + result.passed_count
            + result.error_count
            + result.skipped_count
        )

        if duration_m:
            try:
                result.duration_seconds = float(duration_m.group(1))
            except ValueError:
                pass

        # Extract failed test names
        result.failed_tests = _FAILED_TEST_RE.findall(stdout)

        # Extract error messages
        result.error_messages = _ERROR_MSG_RE.findall(stdout)

        # Extract file locations
        for match in _FILE_LOCATION_RE.finditer(stdout):
            result.file_locations.append(
                f"{match.group(1)}:{match.group(2)}"
            )

        # Handle collection errors
        if _COLLECTION_ERROR_RE.search(stdout):
            result.passed = False
            if not result.error_messages:
                result.error_messages.append("Collection error during test discovery")

        # Handle "no tests ran"
        if _NO_TESTS_RE.search(stdout):
            result.passed = False
            if not result.error_messages:
                result.error_messages.append("No tests ran")

        # Override passed based on counts if exit_code was not provided
        if exit_code == -1:
            result.passed = (
                result.failed_count == 0
                and result.error_count == 0
                and result.total > 0
            )

        return result
