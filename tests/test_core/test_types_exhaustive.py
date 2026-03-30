"""Exhaustive ReasoningType enum guard tests (Phase 0B, ADR-128).

These tests serve as canaries — they FORCE a review of all consumers
when the ReasoningType enum grows. Added as part of the R3 MCP Protocol
Domain zero-regression implementation plan.
"""

import pytest

from graqle.core.types import ReasoningType


# All known enum values — update this set when adding new types
EXPECTED_TYPES = {
    "assertion",
    "question",
    "contradiction",
    "synthesis",
    "evidence",
    "hypothesis",
    "protocol_trace",
}


def test_enum_completeness():
    """Fails when a new type is added without updating this test.

    This forces the developer to consciously acknowledge the new type
    and audit all consumers before merging.
    """
    actual = {rt.value for rt in ReasoningType}
    assert actual == EXPECTED_TYPES, (
        f"ReasoningType changed! "
        f"Added: {actual - EXPECTED_TYPES}, "
        f"Removed: {EXPECTED_TYPES - actual}. "
        "Audit all consumers before updating this test."
    )


@pytest.mark.parametrize("rt", ReasoningType)
def test_no_silent_drop(rt):
    """Every ReasoningType member must have a non-empty string value.

    Guards against accidentally creating a member with None or empty value,
    which would cause silent failures in equality checks.
    """
    assert rt.value, f"{rt.name} has empty/falsy value"
    assert isinstance(rt.value, str), f"{rt.name} value is not a string"


def test_enum_count_guard():
    """Canary test — forces review when enum grows.

    When this test fails, the developer MUST:
    1. Run Phase 0A audit (grep ReasoningType consumers)
    2. Verify no dispatcher silently drops the new type
    3. Update EXPECTED_TYPES above
    4. Update this count
    """
    assert len(ReasoningType) == 7, (
        f"ReasoningType has {len(ReasoningType)} members (expected 7). "
        "Update all consumers and this test. "
        "See .gcc/branches/feature-r3-mcp-domain/plan.md Phase 0A."
    )


def test_string_enum_serialization():
    """ReasoningType(str, Enum) must support direct string comparison.

    This is critical for message serialization/deserialization —
    older consumers may compare against raw string values.
    """
    assert ReasoningType.PROTOCOL_TRACE == "protocol_trace"
    assert ReasoningType.PROTOCOL_TRACE.value == "protocol_trace"
    assert ReasoningType("protocol_trace") == ReasoningType.PROTOCOL_TRACE


def test_protocol_trace_does_not_break_existing_constructors():
    """Adding PROTOCOL_TRACE must not change behavior of existing constructors.

    All existing code creates messages with ASSERTION, QUESTION, SYNTHESIS,
    or CONTRADICTION. Verify these still resolve correctly.
    """
    for name in ["assertion", "question", "contradiction", "synthesis",
                  "evidence", "hypothesis"]:
        rt = ReasoningType(name)
        assert rt.value == name
