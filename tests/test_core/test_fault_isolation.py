"""S1 Fault Isolation + Clearance Hardening tests (ADR-145).

Covers S1-9, S1-10, S1-18, S1-19, S1-20:
  - ToolResult value object (frozen, factories, audit event)
  - _classify_fault mapping
  - Clearance-based redaction
  - safe_node_reason / gather_settled fault containment
  - Clearance taint propagation & laundering detection
  - GovernanceViolation hierarchy
  - ClearanceLevel enum completeness
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from graqle.core.results import (
    FAULT_ACCESS,
    FAULT_NETWORK,
    FAULT_PARSE,
    FAULT_TIMEOUT,
    FAULT_UNKNOWN,
    ToolResult,
    _classify_fault,
    gather_settled,
    safe_node_reason,
)
from graqle.core.types import ClearanceLevel
from graqle.core.exceptions import GovernanceViolation, GraqleError
from graqle.intelligence.governance.debate_clearance import (
    ClearanceFilter,
    ClearanceViolationError,
)


# ---------------------------------------------------------------------------
# 1. TestToolResult
# ---------------------------------------------------------------------------


class TestToolResult:

    def test_success_factory(self):
        r = ToolResult.success(data="hello")
        assert r.is_error is False
        assert r.data == "hello"
        assert r.fault_code is None

    def test_failure_factory(self):
        r = ToolResult.failure(data="timed out", fault_code=FAULT_TIMEOUT)
        assert r.is_error is True
        assert r.fault_code == FAULT_TIMEOUT

    def test_frozen(self):
        r = ToolResult.success(data="immutable")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            r.data = "mutated"  # type: ignore[misc]

    def test_to_audit_event(self):
        r = ToolResult.success(data="sensitive-payload")
        event = r.to_audit_event()
        assert isinstance(event, dict)
        assert "is_error" in event
        assert "fault_code" in event
        assert "sensitive-payload" not in str(event)


# ---------------------------------------------------------------------------
# 2. TestClassifyFault
# ---------------------------------------------------------------------------


class TestClassifyFault:

    def test_timeout(self):
        assert _classify_fault(TimeoutError("slow")) == FAULT_TIMEOUT

    def test_asyncio_timeout(self):
        assert _classify_fault(asyncio.TimeoutError()) == FAULT_TIMEOUT

    def test_connection(self):
        assert _classify_fault(ConnectionError("refused")) == FAULT_NETWORK

    def test_value_error(self):
        assert _classify_fault(ValueError("bad input")) == FAULT_PARSE

    def test_key_error(self):
        assert _classify_fault(KeyError("missing")) == FAULT_PARSE

    def test_permission(self):
        assert _classify_fault(PermissionError("denied")) == FAULT_ACCESS

    def test_unknown(self):
        assert _classify_fault(RuntimeError("unexpected")) == FAULT_UNKNOWN


# ---------------------------------------------------------------------------
# 3. TestRedaction
# ---------------------------------------------------------------------------


class TestRedaction:

    def _make_result(self, clearance: ClearanceLevel) -> ToolResult:
        return ToolResult.success(data="sensitive-info", clearance=clearance)

    def test_higher_clearance_sees_full(self):
        r = self._make_result(ClearanceLevel.CONFIDENTIAL)
        viewed = r.redacted_for(ClearanceLevel.RESTRICTED)
        assert viewed.data == "sensitive-info"

    def test_same_clearance_sees_full(self):
        r = self._make_result(ClearanceLevel.CONFIDENTIAL)
        viewed = r.redacted_for(ClearanceLevel.CONFIDENTIAL)
        assert viewed.data == "sensitive-info"

    def test_lower_clearance_sees_redacted(self):
        r = self._make_result(ClearanceLevel.CONFIDENTIAL)
        viewed = r.redacted_for(ClearanceLevel.PUBLIC)
        assert "[REDACTED" in viewed.data

    def test_redacted_preserves_fault_code(self):
        r = ToolResult.failure(
            data="secret error details",
            fault_code=FAULT_PARSE,
            clearance=ClearanceLevel.CONFIDENTIAL,
        )
        viewed = r.redacted_for(ClearanceLevel.PUBLIC)
        assert viewed.fault_code == FAULT_PARSE

    def test_public_never_redacted(self):
        r = self._make_result(ClearanceLevel.PUBLIC)
        viewed = r.redacted_for(ClearanceLevel.PUBLIC)
        assert viewed.data == "sensitive-info"


# ---------------------------------------------------------------------------
# 4. TestSafeNodeReason
# ---------------------------------------------------------------------------


class TestSafeNodeReason:

    @pytest.mark.asyncio
    async def test_success_returns_tool_result(self):
        async def llm_fn(prompt: str) -> str:
            return "reasoning output"

        result = await safe_node_reason("node1", "test prompt", llm_fn)
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert "reasoning output" in result.data

    @pytest.mark.asyncio
    async def test_timeout_returns_fault(self):
        async def slow_fn(prompt: str) -> str:
            await asyncio.sleep(60)
            return "never"

        result = await safe_node_reason(
            "node1", "test prompt", slow_fn, timeout_seconds=0.01
        )
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert result.fault_code == FAULT_TIMEOUT

    @pytest.mark.asyncio
    async def test_exception_returns_fault(self):
        async def bad_fn(prompt: str) -> str:
            raise ValueError("parse failure")

        result = await safe_node_reason("node1", "test prompt", bad_fn)
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert result.fault_code == FAULT_PARSE

    @pytest.mark.asyncio
    async def test_never_raises(self):
        async def exploding_fn(prompt: str) -> str:
            raise RuntimeError("kaboom")

        result = await safe_node_reason("node1", "test prompt", exploding_fn)
        assert isinstance(result, ToolResult)
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 5. TestGatherSettled
# ---------------------------------------------------------------------------


class TestGatherSettled:

    @pytest.mark.asyncio
    async def test_all_succeed(self):
        async def ok(v: str) -> str:
            return v

        results = await gather_settled([ok("a"), ok("b"), ok("c")])
        assert len(results) == 3
        assert all(isinstance(r, ToolResult) for r in results)
        assert all(r.is_error is False for r in results)

    @pytest.mark.asyncio
    async def test_mixed(self):
        async def ok(v: str) -> str:
            return v

        async def fail() -> str:
            raise ValueError("boom")

        results = await gather_settled([ok("a"), fail(), ok("c")])
        assert len(results) == 3
        successes = [r for r in results if not r.is_error]
        failures = [r for r in results if r.is_error]
        assert len(successes) == 2
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_all_fail(self):
        async def fail_timeout() -> str:
            raise TimeoutError("slow")

        async def fail_value() -> str:
            raise ValueError("bad")

        async def fail_runtime() -> str:
            raise RuntimeError("oops")

        results = await gather_settled([fail_timeout(), fail_value(), fail_runtime()])
        assert len(results) == 3
        assert all(r.is_error is True for r in results)

    @pytest.mark.asyncio
    async def test_empty(self):
        results = await gather_settled([])
        assert results == []


# ---------------------------------------------------------------------------
# 6. TestClearanceTaintPropagation (via ClearanceFilter)
# ---------------------------------------------------------------------------


class TestClearanceTaintPropagation:

    def test_max_clearance_propagated(self):
        cf = ClearanceFilter()
        inputs = [
            ToolResult.success(data="a", clearance=ClearanceLevel.CONFIDENTIAL),
            ToolResult.success(data="b", clearance=ClearanceLevel.PUBLIC),
        ]
        output = cf.taint_synthesis_output(inputs, "synthesized")
        assert output.clearance == ClearanceLevel.CONFIDENTIAL

    def test_all_public(self):
        cf = ClearanceFilter()
        inputs = [
            ToolResult.success(data="a", clearance=ClearanceLevel.PUBLIC),
            ToolResult.success(data="b", clearance=ClearanceLevel.PUBLIC),
        ]
        output = cf.taint_synthesis_output(inputs, "synthesized")
        assert output.clearance == ClearanceLevel.PUBLIC

    def test_restricted_propagated(self):
        cf = ClearanceFilter()
        inputs = [
            ToolResult.success(data="a", clearance=ClearanceLevel.RESTRICTED),
            ToolResult.success(data="b", clearance=ClearanceLevel.INTERNAL),
        ]
        output = cf.taint_synthesis_output(inputs, "synthesized")
        assert output.clearance == ClearanceLevel.RESTRICTED

    def test_empty_inputs(self):
        cf = ClearanceFilter()
        output = cf.taint_synthesis_output([], "synthesized")
        assert output.clearance == ClearanceLevel.PUBLIC


# ---------------------------------------------------------------------------
# 7. TestValidateNoLaundering (via ClearanceFilter)
# ---------------------------------------------------------------------------


class TestValidateNoLaundering:

    def test_valid_no_laundering(self):
        cf = ClearanceFilter()
        inputs = [ToolResult.success(data="a", clearance=ClearanceLevel.CONFIDENTIAL)]
        output = ToolResult.success(data="b", clearance=ClearanceLevel.CONFIDENTIAL)
        assert cf.validate_no_laundering(inputs, output) is True

    def test_laundering_detected(self):
        cf = ClearanceFilter()
        inputs = [ToolResult.success(data="a", clearance=ClearanceLevel.CONFIDENTIAL)]
        output = ToolResult.success(data="b", clearance=ClearanceLevel.PUBLIC)
        assert cf.validate_no_laundering(inputs, output) is False

    def test_higher_output_ok(self):
        cf = ClearanceFilter()
        inputs = [ToolResult.success(data="a", clearance=ClearanceLevel.PUBLIC)]
        output = ToolResult.success(data="b", clearance=ClearanceLevel.RESTRICTED)
        assert cf.validate_no_laundering(inputs, output) is True


# ---------------------------------------------------------------------------
# 8. TestGovernanceViolationHierarchy
# ---------------------------------------------------------------------------


class TestGovernanceViolationHierarchy:

    def test_is_graqle_error(self):
        assert issubclass(GovernanceViolation, GraqleError)

    def test_clearance_violation_is_governance(self):
        assert issubclass(ClearanceViolationError, GovernanceViolation)

    def test_input_state_stored(self):
        state = {"node": "n1", "clearance": "CONFIDENTIAL"}
        exc = GovernanceViolation("test violation", input_state=state)
        assert exc.input_state == state

    def test_clearance_violation_stores_input_state(self):
        exc = ClearanceViolationError(
            "laundering",
            max_seen=ClearanceLevel.CONFIDENTIAL,
            output_level=ClearanceLevel.PUBLIC,
        )
        assert exc.input_state == {
            "max_seen": "CONFIDENTIAL",
            "output_level": "PUBLIC",
        }


# ---------------------------------------------------------------------------
# 9. TestClearanceLevelRestricted
# ---------------------------------------------------------------------------


class TestClearanceLevelRestricted:

    def test_restricted_exists(self):
        assert ClearanceLevel.RESTRICTED.value == 3

    def test_ordering(self):
        assert ClearanceLevel.PUBLIC < ClearanceLevel.INTERNAL
        assert ClearanceLevel.INTERNAL < ClearanceLevel.CONFIDENTIAL
        assert ClearanceLevel.CONFIDENTIAL < ClearanceLevel.RESTRICTED

    def test_four_members(self):
        assert len(ClearanceLevel) == 4
