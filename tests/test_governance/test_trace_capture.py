"""Tests for R18 Governed Execution Trace Capture (ADR-201).

Covers: trace_schema.py, trace_capture.py, trace_store.py.
Acceptance criteria: AC-1 through AC-7.
"""

import asyncio
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from graqle.governance.trace_schema import (
    ClearanceLevel,
    Decision,
    GateType,
    GovernanceDecision,
    GovernedTrace,
    Outcome,
    ToolCall,
)
from graqle.governance.trace_capture import (
    GOVERNED_TOOLS,
    TraceCapture,
    is_governed,
    _extract_query,
    _extract_outcome_from_result,
)
from graqle.governance.trace_store import TraceStore


# ═══════════════════════════════════════════════════════════════════
# trace_schema.py tests
# ═══════════════════════════════════════════════════════════════════


class TestGovernedTraceCreation:
    """Basic GovernedTrace creation and defaults."""

    def test_minimal_creation(self):
        t = GovernedTrace(
            tool_name="graq_reason",
            query="test query",
            outcome=Outcome.SUCCESS,
            confidence=0.85,
        )
        assert isinstance(t.id, UUID)
        assert t.tool_name == "graq_reason"
        assert t.clearance_level == ClearanceLevel.INTERNAL
        assert t.human_override is False
        assert t.override_reason is None
        assert t.error is None
        assert t.context_nodes == []
        assert t.tool_calls == []
        assert t.governance_decisions == []

    def test_timestamp_default_is_utc(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
        )
        assert t.timestamp.tzinfo is not None
        assert t.timestamp.tzinfo == timezone.utc

    def test_all_fields_populated(self):
        t = GovernedTrace(
            tool_name="graq_generate",
            query="build a thing",
            outcome=Outcome.PARTIAL,
            confidence=0.72,
            cost_usd=0.05,
            latency_ms=1234.5,
            clearance_level=ClearanceLevel.CONFIDENTIAL,
            context_nodes=["node1", "node2"],
            tool_calls=[ToolCall(tool="sub_tool", args={"x": 1}, result_summary="ok")],
            governance_decisions=[
                GovernanceDecision(
                    gate_id="CG-01",
                    gate_type=GateType.CLEARANCE,
                    decision=Decision.PASS,
                    reason="session active",
                )
            ],
            error="partial failure",
        )
        assert t.outcome == Outcome.PARTIAL
        assert len(t.context_nodes) == 2
        assert len(t.tool_calls) == 1
        assert len(t.governance_decisions) == 1


class TestQuerySanitization:
    """AC-2: Schema validation for query field."""

    def test_strips_whitespace(self):
        t = GovernedTrace(
            tool_name="t", query="  hello  ", outcome=Outcome.SUCCESS, confidence=0.5,
        )
        assert t.query == "hello"

    def test_removes_non_printable(self):
        t = GovernedTrace(
            tool_name="t", query="hello\x00world", outcome=Outcome.SUCCESS, confidence=0.5,
        )
        assert t.query == "helloworld"

    def test_truncates_to_4000(self):
        long_q = "a" * 5000
        t = GovernedTrace(
            tool_name="t", query=long_q, outcome=Outcome.SUCCESS, confidence=0.5,
        )
        assert len(t.query) == 4000

    def test_rejects_empty_after_sanitization(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="   ", outcome=Outcome.SUCCESS, confidence=0.5,
            )

    def test_rejects_only_control_chars(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="\x00\x01\x02", outcome=Outcome.SUCCESS, confidence=0.5,
            )


class TestTimestampNormalization:
    """AC-6: Governance labels attached at write time (timestamp integrity)."""

    def test_naive_datetime_gets_utc(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
            timestamp=datetime(2026, 4, 9, 12, 0, 0),
        )
        assert t.timestamp.tzinfo is not None

    def test_aware_datetime_converted_to_utc(self):
        from datetime import timedelta
        est = timezone(timedelta(hours=-5))
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
            timestamp=datetime(2026, 4, 9, 12, 0, 0, tzinfo=est),
        )
        assert t.timestamp.tzinfo == timezone.utc
        assert t.timestamp.hour == 17  # 12 EST = 17 UTC


class TestConfidenceValidation:
    """AC-2: Schema validation for confidence field."""

    def test_valid_confidence(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
        )
        assert t.confidence == 0.5

    def test_confidence_zero(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.0,
        )
        assert t.confidence == 0.0

    def test_confidence_one(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=1.0,
        )
        assert t.confidence == 1.0

    def test_rejects_above_one(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=1.5,
            )

    def test_rejects_negative(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=-0.1,
            )

    def test_rejects_nan(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=float("nan"),
            )

    def test_rejects_infinity(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=float("inf"),
            )


class TestOverrideValidation:
    """AC-7: Human override explicitly recorded."""

    def test_override_requires_reason(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS,
                confidence=0.5, human_override=True,
            )

    def test_override_rejects_empty_reason(self):
        with pytest.raises(Exception):
            GovernedTrace(
                tool_name="t", query="q", outcome=Outcome.SUCCESS,
                confidence=0.5, human_override=True, override_reason="   ",
            )

    def test_override_with_valid_reason(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS,
            confidence=0.5, human_override=True, override_reason="user requested",
        )
        assert t.override_reason == "user requested"

    def test_no_override_clears_reason(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS,
            confidence=0.5, human_override=False, override_reason="stale",
        )
        assert t.override_reason is None


class TestSerialization:
    """TS-2 Gate: governance_decisions excluded from public serialization."""

    def test_public_dict_excludes_governance_decisions(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
            governance_decisions=[
                GovernanceDecision(
                    gate_id="g1", gate_type=GateType.CLEARANCE,
                    decision=Decision.PASS, reason="ok",
                )
            ],
        )
        pub = t.to_public_dict()
        assert "governance_decisions" not in pub
        assert "tool_name" in pub

    def test_internal_dict_includes_governance_decisions(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
            governance_decisions=[
                GovernanceDecision(
                    gate_id="g1", gate_type=GateType.CLEARANCE,
                    decision=Decision.PASS, reason="ok",
                )
            ],
        )
        internal = t.to_internal_dict()
        assert "governance_decisions" in internal
        assert len(internal["governance_decisions"]) == 1

    def test_serialization_is_json_compatible(self):
        t = GovernedTrace(
            tool_name="t", query="q", outcome=Outcome.SUCCESS, confidence=0.5,
        )
        # Should not raise
        json.dumps(t.to_public_dict(), default=str)
        json.dumps(t.to_internal_dict(), default=str)


# ═══════════════════════════════════════════════════════════════════
# trace_capture.py tests
# ═══════════════════════════════════════════════════════════════════


class TestIsGoverned:
    """Governed tool detection."""

    def test_graq_reason_is_governed(self):
        assert is_governed("graq_reason") is True

    def test_kogni_reason_is_governed(self):
        assert is_governed("kogni_reason") is True

    def test_unknown_tool_not_governed(self):
        assert is_governed("unknown_tool") is False

    def test_all_governed_tools_recognized(self):
        for tool in GOVERNED_TOOLS:
            assert is_governed(tool) is True


class TestExtractQuery:
    """Query extraction from tool arguments."""

    def test_extracts_question(self):
        assert _extract_query({"question": "How?"}) == "How?"

    def test_extracts_task(self):
        assert _extract_query({"task": "Build it"}) == "Build it"

    def test_fallback_to_json(self):
        result = _extract_query({"x": 1, "y": 2})
        assert "x" in result

    def test_truncates_long_query(self):
        result = _extract_query({"question": "a" * 5000})
        assert len(result) == 4000


class TestExtractOutcome:
    """Outcome extraction from handler result JSON."""

    def test_success_with_confidence(self):
        outcome, conf, cost = _extract_outcome_from_result(
            '{"answer": "yes", "confidence": 0.85, "cost_usd": 0.02}'
        )
        assert outcome == Outcome.SUCCESS
        assert conf == 0.85
        assert cost == 0.02

    def test_error_result(self):
        outcome, conf, cost = _extract_outcome_from_result(
            '{"error": "something broke"}'
        )
        assert outcome == Outcome.FAILURE

    def test_invalid_json(self):
        outcome, conf, cost = _extract_outcome_from_result("not json")
        assert outcome == Outcome.SUCCESS
        assert conf == 0.0


class TestTraceCaptureContextManager:
    """Async context manager behavior."""

    def test_basic_capture(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            async with TraceCapture("graq_reason", {"question": "test"}, store) as tc:
                tc.set_result('{"answer": "x", "confidence": 0.9}')
            assert store.count == 1
            traces = store.read_traces()
            assert len(traces) == 1
            assert traces[0]["tool_name"] == "graq_reason"
            assert traces[0]["confidence"] == 0.9

        asyncio.run(_test())

    def test_captures_latency(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            async with TraceCapture("graq_inspect", {"stats": True}, store) as tc:
                tc.set_result('{"total_nodes": 100}')
            traces = store.read_traces()
            assert traces[0]["latency_ms"] >= 0

        asyncio.run(_test())

    def test_captures_exception(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            try:
                async with TraceCapture("graq_reason", {"question": "q"}, store) as tc:
                    raise RuntimeError("handler exploded")
            except RuntimeError:
                pass
            traces = store.read_traces()
            assert traces[0]["outcome"] == "FAILURE"
            assert "handler exploded" in traces[0]["error"]

        asyncio.run(_test())

    def test_records_gate_decision(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            async with TraceCapture("graq_bash", {"command": "ls"}, store) as tc:
                tc.record_gate_decision(
                    "CG-02", GateType.GIT_GOVERNANCE, Decision.PASS, "plan active"
                )
                tc.set_result('{"stdout": "file.txt"}')
            traces = store.read_traces()
            gd = traces[0]["governance_decisions"]
            assert len(gd) == 1
            assert gd[0]["gate_id"] == "CG-02"
            assert gd[0]["decision"] == "PASS"

        asyncio.run(_test())

    def test_blocked_gate_sets_outcome(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            async with TraceCapture("graq_write", {"file_path": "x.py"}, store) as tc:
                tc.record_gate_decision(
                    "CG-03", GateType.GIT_GOVERNANCE, Decision.BLOCK,
                    "code file requires graq_edit"
                )
                tc.set_result('{"error": "CG-03_EDIT_GATE"}')
            traces = store.read_traces()
            assert traces[0]["outcome"] == "BLOCKED"

        asyncio.run(_test())

    def test_context_nodes_recorded(self):
        async def _test():
            store = TraceStore(trace_dir=tempfile.mkdtemp())
            async with TraceCapture("graq_context", {"task": "test"}, store) as tc:
                tc.set_context_nodes(["node_a", "node_b", "node_c"])
                tc.set_result('{"context": "..."}')
            traces = store.read_traces()
            assert traces[0]["context_nodes"] == ["node_a", "node_b", "node_c"]

        asyncio.run(_test())

    def test_no_store_does_not_crash(self):
        async def _test():
            async with TraceCapture("graq_reason", {"question": "q"}, store=None) as tc:
                tc.set_result('{"answer": "x"}')
            # Should not raise

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════
# trace_store.py tests
# ═══════════════════════════════════════════════════════════════════


class TestTraceStore:
    """Append-only trace persistence."""

    def _make_trace(self, tool_name="graq_test"):
        return GovernedTrace(
            tool_name=tool_name, query="test", outcome=Outcome.SUCCESS, confidence=0.5,
        )

    def test_append_creates_file(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = TraceStore(trace_dir=d)
            await store.append(self._make_trace())
            files = list(Path(d).glob("*.jsonl"))
            assert len(files) == 1
            assert store.count == 1

        asyncio.run(_test())

    def test_corpus_growth_monotonic(self):
        """AC-3: T(n+1) >= T(n)."""
        async def _test():
            d = tempfile.mkdtemp()
            store = TraceStore(trace_dir=d)
            sizes = []
            for i in range(5):
                await store.append(self._make_trace(f"tool_{i}"))
                sizes.append(store.corpus_size())
            # Verify monotonic growth
            for i in range(1, len(sizes)):
                assert sizes[i] >= sizes[i - 1]

        asyncio.run(_test())

    def test_read_traces_returns_recent_first(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = TraceStore(trace_dir=d)
            await store.append(self._make_trace("first"))
            await store.append(self._make_trace("second"))
            traces = store.read_traces()
            assert traces[0]["tool_name"] == "second"
            assert traces[1]["tool_name"] == "first"

        asyncio.run(_test())

    def test_read_traces_empty_date(self):
        d = tempfile.mkdtemp()
        store = TraceStore(trace_dir=d)
        assert store.read_traces(date="1999-01-01") == []

    def test_list_dates(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = TraceStore(trace_dir=d)
            await store.append(self._make_trace())
            dates = store.list_dates()
            assert len(dates) >= 1
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            assert today in dates

        asyncio.run(_test())

    def test_on_trace_callback(self):
        async def _test():
            d = tempfile.mkdtemp()
            captured = []
            store = TraceStore(trace_dir=d, on_trace=lambda t: captured.append(t))
            await store.append(self._make_trace())
            assert len(captured) == 1
            assert captured[0].tool_name == "graq_test"

        asyncio.run(_test())

    def test_trace_file_is_valid_jsonl(self):
        async def _test():
            d = tempfile.mkdtemp()
            store = TraceStore(trace_dir=d)
            for i in range(3):
                await store.append(self._make_trace(f"tool_{i}"))
            # Read raw file and validate each line is valid JSON
            files = list(Path(d).glob("*.jsonl"))
            with open(files[0], "r") as f:
                for line in f:
                    data = json.loads(line)  # Should not raise
                    assert "tool_name" in data
                    assert "id" in data

        asyncio.run(_test())
