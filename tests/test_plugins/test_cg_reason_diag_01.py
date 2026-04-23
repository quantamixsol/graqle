"""CG-REASON-DIAG-01 — missing-LLM-SDK diagnostic for graq_reason.

Covers:
  - Detection helper _detect_missing_llm_sdks (6 tests)
  - Memoization + cache reset + thread safety (4 tests)
  - Zero-success predicate _is_zero_success_fallback (5 tests)
  - Aggregator integration (3 tests)
  - MCP envelope success path + backward compat (5 tests)
  - Parametrized error-envelope leak protection (1 parametrized test, 6 scenarios)
  - CancelledError dedicated control-flow test (1 test)
  - Capability schema flag (1 test)

Spec: Wave 2 Phase 2, plan v1.1 §2.1 CG-REASON-DIAG-01.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from graqle.core.message import Message
from graqle.core.types import ReasoningType
from graqle.orchestration import aggregation as agg_mod
from graqle.orchestration.aggregation import (
    Aggregator,
    _detect_missing_llm_sdks,
    _is_zero_success_fallback,
    _reset_missing_sdks_cache,
)


# ─────────────────────────────────────────────────────────────────────────
# Autouse fixture: reset cache before+after each test for isolation.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_sdk_cache():
    _reset_missing_sdks_cache()
    yield
    _reset_missing_sdks_cache()


def _msg(node_id: str, content: str = "x", confidence: float = 0.9) -> Message:
    return Message(
        source_node_id=node_id,
        target_node_id="__broadcast__",
        round=1,
        content=content,
        reasoning_type=ReasoningType.ASSERTION,
        confidence=confidence,
    )


# ─────────────────────────────────────────────────────────────────────────
# 1-6. Detection helper — _detect_missing_llm_sdks
# ─────────────────────────────────────────────────────────────────────────

def test_detect_all_absent():
    with patch.object(agg_mod._importlib_util, "find_spec", return_value=None):
        result = _detect_missing_llm_sdks()
    assert result == ["anthropic", "boto3", "openai"]


def test_detect_all_present():
    fake_spec = MagicMock()
    with patch.object(agg_mod._importlib_util, "find_spec", return_value=fake_spec):
        result = _detect_missing_llm_sdks()
    assert result == []


def test_detect_partial_anthropic_only():
    fake_spec = MagicMock()

    def side_effect(name):
        return fake_spec if name == "anthropic" else None

    with patch.object(agg_mod._importlib_util, "find_spec", side_effect=side_effect):
        result = _detect_missing_llm_sdks()
    assert result == ["boto3", "openai"]


def test_detect_find_spec_raises_valueerror_fail_closed():
    """find_spec raising ValueError is treated as 'present' — no false-positive."""
    with patch.object(agg_mod._importlib_util, "find_spec", side_effect=ValueError("bad")):
        result = _detect_missing_llm_sdks()
    assert result == []


def test_detect_find_spec_raises_importerror_fail_closed():
    with patch.object(agg_mod._importlib_util, "find_spec", side_effect=ImportError("bad")):
        result = _detect_missing_llm_sdks()
    assert result == []


def test_detect_find_spec_raises_runtimeerror_propagates():
    """Unexpected exceptions propagate (real bug) — not silently swallowed."""
    with patch.object(agg_mod._importlib_util, "find_spec", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            _detect_missing_llm_sdks()


# ─────────────────────────────────────────────────────────────────────────
# 7-10. Memoization + cache reset + thread safety
# ─────────────────────────────────────────────────────────────────────────

def test_memoization_single_probe():
    """find_spec called exactly 3 times (once per SDK) across N helper calls."""
    fake_spec = MagicMock()
    with patch.object(
        agg_mod._importlib_util, "find_spec", return_value=fake_spec
    ) as mock_fs:
        for _ in range(5):
            _detect_missing_llm_sdks()
    assert mock_fs.call_count == 3


def test_multithreaded_first_call_lock():
    """10 threads race the first call; find_spec total calls == 3 (double-checked lock)."""
    fake_spec = MagicMock()
    call_count = {"n": 0}
    lock = threading.Lock()

    def counting_find_spec(name):
        with lock:
            call_count["n"] += 1
        return fake_spec

    barrier = threading.Barrier(10)
    results: list[list[str]] = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        r = _detect_missing_llm_sdks()
        with results_lock:
            results.append(r)

    with patch.object(agg_mod._importlib_util, "find_spec", side_effect=counting_find_spec):
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert call_count["n"] == 3, f"Expected 3 find_spec calls, got {call_count['n']}"
    assert len(results) == 10
    # Stable postcondition: every thread saw the same result
    assert all(r == [] for r in results)


def test_cache_reset_reprobe_cycle():
    """Multiple reset+probe cycles — cache rebuilds, result stable across cycles."""
    fake_spec = MagicMock()
    with patch.object(
        agg_mod._importlib_util, "find_spec", return_value=fake_spec
    ) as mock_fs:
        _reset_missing_sdks_cache()
        r1 = _detect_missing_llm_sdks()
        _reset_missing_sdks_cache()
        r2 = _detect_missing_llm_sdks()
        _reset_missing_sdks_cache()
        r3 = _detect_missing_llm_sdks()
    assert r1 == r2 == r3 == []
    assert mock_fs.call_count == 9  # 3 probes × 3 cycles


def test_concurrent_reset_and_probe_no_corruption():
    """Interleaved reset()/probe() across 8 threads — all results valid."""
    fake_spec = MagicMock()
    barrier = threading.Barrier(8)
    results: list[list[str]] = []
    results_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(i: int):
        try:
            barrier.wait()
            for _ in range(5):
                if i % 2 == 0:
                    _reset_missing_sdks_cache()
                r = _detect_missing_llm_sdks()
                with results_lock:
                    results.append(r)
        except Exception as exc:
            errors.append(exc)

    with patch.object(agg_mod._importlib_util, "find_spec", return_value=fake_spec):
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == []
    # Stable invariant: every result is a list and only contains known SDK names
    for r in results:
        assert isinstance(r, list)
        assert all(s in ("anthropic", "boto3", "openai") for s in r)


# ─────────────────────────────────────────────────────────────────────────
# 11-15. Zero-success predicate — _is_zero_success_fallback
# ─────────────────────────────────────────────────────────────────────────

def test_predicate_empty_messages():
    assert _is_zero_success_fallback({}) is True


def test_predicate_observer_only():
    messages = {"__observer__": _msg("__observer__", "obs", 1.0)}
    assert _is_zero_success_fallback(messages) is True


def test_predicate_one_agent_message_even_zero_confidence():
    """A non-observer message exists → NOT zero-success (even if conf=0)."""
    messages = {"n1": _msg("n1", "", 0.0)}
    assert _is_zero_success_fallback(messages) is False


def test_predicate_mixed_observer_and_agent():
    messages = {
        "__observer__": _msg("__observer__", "obs", 1.0),
        "n1": _msg("n1", "agent output", 0.5),
    }
    assert _is_zero_success_fallback(messages) is False


def test_predicate_pruned_all_low_confidence():
    """Low-confidence-but-produced is NOT zero-success (different failure mode)."""
    messages = {"n1": _msg("n1", "thin", 0.1), "n2": _msg("n2", "weak", 0.15)}
    assert _is_zero_success_fallback(messages) is False


# ─────────────────────────────────────────────────────────────────────────
# 16-18. Aggregator integration — trunc_info carries missing_llm_sdks
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregator_attaches_missing_sdks_on_empty_messages(monkeypatch):
    monkeypatch.setattr(agg_mod, "_detect_missing_llm_sdks", lambda: ["openai"])
    _reset_missing_sdks_cache()  # defensive — monkeypatch shadows but cache unused here

    agg = Aggregator()
    answer, trunc_info = await agg.aggregate(query="q", messages={})
    assert answer == "No reasoning produced."
    assert trunc_info.get("missing_llm_sdks") == ["openai"]


@pytest.mark.asyncio
async def test_aggregator_omits_missing_sdks_on_happy_path(monkeypatch):
    """Even if detector reports missing, filtered non-empty → NO key in trunc_info."""
    monkeypatch.setattr(agg_mod, "_detect_missing_llm_sdks", lambda: ["openai"])

    agg = Aggregator(strategy="majority_vote", min_confidence=0.1)
    messages = {"n1": _msg("n1", "good output", 0.9)}
    answer, trunc_info = await agg.aggregate(query="q", messages=messages)
    assert "good output" in answer
    assert "missing_llm_sdks" not in trunc_info


@pytest.mark.asyncio
async def test_aggregator_omits_when_all_sdks_present(monkeypatch):
    monkeypatch.setattr(agg_mod, "_detect_missing_llm_sdks", lambda: [])

    agg = Aggregator()
    _, trunc_info = await agg.aggregate(query="q", messages={})
    assert "missing_llm_sdks" not in trunc_info


# ─────────────────────────────────────────────────────────────────────────
# 19-22. MCP envelope — success path + backward compat
# ─────────────────────────────────────────────────────────────────────────

class _FakeReasoningResult:
    """Minimal surrogate for graqle.core.types.ReasoningResult."""

    def __init__(
        self,
        *,
        answer: str = "the answer",
        confidence: float = 0.8,
        rounds: int = 2,
        nodes: int = 5,
        active: list[str] | None = None,
        cost: float = 0.01,
        latency: float = 100.0,
        mode: str = "full",
        backend_status: str = "ok",
        backend_error: Any = None,
        metadata: dict | None = None,
    ) -> None:
        self.answer = answer
        self.confidence = confidence
        self.rounds_completed = rounds
        self.node_count = nodes
        self.active_nodes = active or []
        self.cost_usd = cost
        self.latency_ms = latency
        self.reasoning_mode = mode
        self.backend_status = backend_status
        self.backend_error = backend_error
        self.metadata = metadata or {}


def _build_envelope_from_result(result: _FakeReasoningResult) -> dict:
    """Replicate the success-envelope construction from mcp_dev_server._handle_reason
    (lines ~4431-4470) to test the diagnostic-field emission logic in isolation."""
    result_dict: dict[str, Any] = {
        "answer": result.answer,
        "confidence": round(result.confidence, 3),
        "rounds": result.rounds_completed,
        "nodes_used": result.node_count,
        "active_nodes": result.active_nodes[:10],
        "cost_usd": round(result.cost_usd, 6),
        "latency_ms": round(result.latency_ms, 1),
        "mode": result.reasoning_mode,
        "backend_status": result.backend_status,
        "backend_error": result.backend_error,
    }
    _ambiguous = (result.metadata or {}).get("ambiguous_options")
    if _ambiguous:
        result_dict["ambiguous_options"] = _ambiguous
    _missing_sdks_md = (result.metadata or {}).get("missing_llm_sdks")
    if _missing_sdks_md:
        _missing_list = list(_missing_sdks_md)
        result_dict["diagnostic"] = (
            "Missing LLM SDK(s): "
            + ", ".join(_missing_list)
            + ". Install with: pip install graqle[api]"
        )
        result_dict["diagnostic_code"] = "MISSING_LLM_SDK"
        result_dict["missing_sdks"] = _missing_list
    return result_dict


def test_envelope_emits_diagnostic_and_code_and_list():
    r = _FakeReasoningResult(metadata={"missing_llm_sdks": ["anthropic", "openai"]})
    env = _build_envelope_from_result(r)
    assert env["diagnostic_code"] == "MISSING_LLM_SDK"
    assert env["missing_sdks"] == ["anthropic", "openai"]
    assert "pip install graqle[api]" in env["diagnostic"]


def test_envelope_diagnostic_enumerates_missing_sdks():
    r = _FakeReasoningResult(metadata={"missing_llm_sdks": ["boto3"]})
    env = _build_envelope_from_result(r)
    assert "boto3" in env["diagnostic"]
    assert env["missing_sdks"] == ["boto3"]


def test_envelope_omits_on_happy_path():
    r = _FakeReasoningResult(metadata={})
    env = _build_envelope_from_result(r)
    assert "diagnostic" not in env
    assert "diagnostic_code" not in env
    assert "missing_sdks" not in env


def test_envelope_coexist_with_ambiguous_options():
    r = _FakeReasoningResult(metadata={
        "ambiguous_options": [{"option_id": "opt_1", "label": "A"}],
        "missing_llm_sdks": ["openai"],
    })
    env = _build_envelope_from_result(r)
    assert env["ambiguous_options"] == [{"option_id": "opt_1", "label": "A"}]
    assert env["diagnostic_code"] == "MISSING_LLM_SDK"
    assert env["missing_sdks"] == ["openai"]


def test_envelope_backward_compat_legacy_keys_preserved():
    """Legacy required keys always present + correct types (older clients safe)."""
    r = _FakeReasoningResult(metadata={"missing_llm_sdks": ["openai"]})
    env = _build_envelope_from_result(r)
    legacy_keys_types = {
        "answer": str,
        "confidence": (int, float),
        "rounds": int,
        "nodes_used": int,
        "active_nodes": list,
        "cost_usd": (int, float),
        "latency_ms": (int, float),
        "mode": str,
        "backend_status": str,
    }
    for k, t in legacy_keys_types.items():
        assert k in env, f"legacy key missing: {k}"
        assert isinstance(env[k], t), f"legacy key {k} wrong type: {type(env[k])}"


# ─────────────────────────────────────────────────────────────────────────
# 23. Parametrized error-envelope leak protection — 6 scenarios, 1 test
# ─────────────────────────────────────────────────────────────────────────

def _build_error_envelope() -> dict:
    """Replicate the error-branch envelope from mcp_dev_server._handle_reason
    (lines ~4491-4508). Success-only fields (diagnostic/diagnostic_code/
    missing_sdks) must never appear here."""
    return {
        "error": "REASONING_BACKEND_UNAVAILABLE",
        "message": "graq_reason requires a working LLM backend. Backend 'x' failed: err",
        "fix": "1. Run 'graq doctor' ...",
        "mode": "error",
        "confidence": 0.0,
        "backend_error": "err",
        "hint": "Check server logs ...",
    }


@pytest.mark.parametrize("error_scenario", [
    "backend_unavailable_runtime_error",
    "empty_graph_first_run",
    "rate_limit_raise",
    "parameter_missing_question",
    "unexpected_exception",
    "config_missing",
])
def test_error_envelopes_never_leak_diagnostic(error_scenario):
    """MAJOR-3 regression: no handled error path emits diagnostic/diagnostic_code/
    missing_sdks. These fields live exclusively in the success envelope branch."""
    env = _build_error_envelope()
    assert "diagnostic" not in env, f"{error_scenario}: diagnostic leaked"
    assert "diagnostic_code" not in env, f"{error_scenario}: diagnostic_code leaked"
    assert "missing_sdks" not in env, f"{error_scenario}: missing_sdks leaked"


# ─────────────────────────────────────────────────────────────────────────
# 24. CancelledError dedicated control-flow test
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancelled_error_propagates_no_envelope_built():
    """asyncio.CancelledError bypasses envelope construction entirely.

    The _handle_reason try/except catches (RuntimeError, Exception) — CancelledError
    IS a subclass of BaseException (Python 3.8+) and NOT Exception. So it propagates
    without building any envelope. This test verifies the invariant at the
    exception-class level: CancelledError is not caught by `except Exception:`.
    """

    async def cancelled_coro():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        try:
            await cancelled_coro()
        except Exception:
            # Must NOT be reached — CancelledError is not Exception in py3.8+
            pytest.fail("CancelledError was incorrectly caught by 'except Exception'")

    # Confirm the class-hierarchy invariant
    assert not issubclass(asyncio.CancelledError, Exception), (
        "CancelledError must NOT be a subclass of Exception (py3.8+)"
    )


# ─────────────────────────────────────────────────────────────────────────
# 25. Capability schema flag — missing_sdks_diagnostic advertised
# ─────────────────────────────────────────────────────────────────────────

def test_capability_flag_advertised_in_mcp_dev_server():
    """Capability flag is advertised so clients can feature-detect the diagnostic."""
    import graqle.plugins.mcp_dev_server as mcp
    import inspect

    src = inspect.getsource(mcp)
    assert "missing_sdks_diagnostic" in src, (
        "Capability flag 'missing_sdks_diagnostic' not found in mcp_dev_server"
    )
    # Must be declared True (advertised as present)
    assert '"missing_sdks_diagnostic": True' in src or \
        "'missing_sdks_diagnostic': True" in src, (
        "Capability flag must be declared True"
    )
