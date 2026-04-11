"""CG-REASON-01 (v0.47.3) regression tests for Graqle.areason_batch.

These cover the consolidated test set after the second graq_review round:

  1. Mixed batch (some succeed, some fail) → result count == query count,
     failures preserve query, successes pass through unchanged
  2. All-fail batch → all results are error fallbacks
  3. Direct _make_error_result helper → all required fields populated,
     no TypeError on dataclass construction, node_count property works
  4. Downstream consumer compatibility → fallback object exposes the
     fields that mcp_dev_server._handle_reason_batch reads
     (.answer, .confidence, .node_count, .cost_usd, .reasoning_mode)
"""

# ── graqle:intelligence ──
# module: tests.test_core.test_areason_batch
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, asyncio, graqle.core.graph
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import patch

import networkx as nx
import pytest

from graqle.core.graph import Graqle, _make_error_result
from graqle.core.types import ReasoningResult


def _build_graph() -> Graqle:
    """Build a tiny 3-node graph for batch reasoning tests."""
    G = nx.Graph()
    G.add_node("n1", label="Node 1", entity_type="Entity", description="first")
    G.add_node("n2", label="Node 2", entity_type="Entity", description="second")
    G.add_node("n3", label="Node 3", entity_type="Entity", description="third")
    G.add_edge("n1", "n2", relationship="RELATED_TO")
    G.add_edge("n2", "n3", relationship="RELATED_TO")
    return Graqle.from_networkx(G)


# ── 1. _make_error_result helper (direct construction) ────────────────


def test_make_error_result_constructs_without_typeerror() -> None:
    """The bug was: ReasoningResult(node_count=0, ...) raised TypeError."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # confidence=0.0 warning is intentional
        result = _make_error_result("the failing query", RuntimeError("backend down"))
    assert isinstance(result, ReasoningResult)


def test_make_error_result_has_all_required_fields() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = _make_error_result("q", RuntimeError("boom"))
    assert result.query == "q"
    assert result.answer == "Error: boom"
    assert result.confidence == 0.0
    assert result.rounds_completed == 0
    assert result.active_nodes == []
    assert result.message_trace == []
    assert result.cost_usd == 0.0
    assert result.latency_ms == 0.0
    assert result.backend_status == "failed"
    assert result.backend_error == "boom"
    assert result.reasoning_mode == "error"


def test_make_error_result_node_count_property_works() -> None:
    """node_count is a @property derived from active_nodes — verify it
    is accessible and returns 0 for the empty active_nodes list."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = _make_error_result("q", ValueError("nope"))
    assert result.node_count == 0  # property, not constructor field


def test_make_error_result_emits_warning_on_zero_confidence() -> None:
    """confidence=0.0 is intentional failure telemetry — verify the warning
    fires (it can be muted via warnings.simplefilter('ignore') if it gets
    noisy in large failing batches, but the default is to surface it)."""
    with pytest.warns(UserWarning, match="confidence"):
        _make_error_result("q", RuntimeError("boom"))


# ── 2. areason_batch end-to-end with mixed success/failure ────────────


@pytest.mark.asyncio
async def test_areason_batch_mixed_success_and_failure() -> None:
    """One failing query in a batch of 3 — result count == 3, failure
    preserves query string, successes pass through unchanged."""
    graph = _build_graph()

    # Patch areason: first call succeeds, second raises, third succeeds.
    call_count = {"n": 0}
    real_results = {
        "q1": ReasoningResult(
            query="q1", answer="A1", confidence=0.9, rounds_completed=1,
            active_nodes=["n1"], message_trace=[], cost_usd=0.001, latency_ms=10.0,
        ),
        "q3": ReasoningResult(
            query="q3", answer="A3", confidence=0.8, rounds_completed=1,
            active_nodes=["n3"], message_trace=[], cost_usd=0.002, latency_ms=20.0,
        ),
    }

    async def fake_areason(self, q, **kw):
        call_count["n"] += 1
        if q == "q2":
            raise RuntimeError("simulated backend failure for q2")
        return real_results[q]

    with patch.object(Graqle, "areason", fake_areason):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = await graph.areason_batch(["q1", "q2", "q3"])

    assert len(results) == 3
    assert results[0].query == "q1" and results[0].answer == "A1"
    assert results[1].query == "q2"  # query preserved on failure
    assert results[1].answer == "Error: simulated backend failure for q2"
    assert results[1].backend_status == "failed"
    assert results[1].reasoning_mode == "error"
    assert results[2].query == "q3" and results[2].answer == "A3"


@pytest.mark.asyncio
async def test_areason_batch_all_failures() -> None:
    """Every query fails — every result is an error fallback."""
    graph = _build_graph()

    async def always_raises(self, q, **kw):
        raise RuntimeError(f"failed: {q}")

    with patch.object(Graqle, "areason", always_raises):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = await graph.areason_batch(["a", "b", "c"])

    assert len(results) == 3
    for q, r in zip(["a", "b", "c"], results):
        assert r.query == q
        assert r.backend_status == "failed"
        assert r.confidence == 0.0
        assert r.node_count == 0
        assert r.active_nodes == []


# ── 3. Downstream consumer compatibility (mcp_dev_server contract) ────


@pytest.mark.asyncio
async def test_areason_batch_error_result_consumable_by_mcp_handler() -> None:
    """The mcp_dev_server._handle_reason_batch downstream code reads:
        .answer, .confidence, .node_count, .cost_usd, .reasoning_mode
    Verify each is accessible on an error fallback without AttributeError
    and returns sensible values."""
    graph = _build_graph()

    async def always_raises(self, q, **kw):
        raise RuntimeError("simulated")

    with patch.object(Graqle, "areason", always_raises):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = await graph.areason_batch(["q"])

    r = results[0]
    # Simulate the exact field access pattern from
    # mcp_dev_server.py:_handle_reason_batch lines 3614-3624
    consumer_view = {
        "question": "q",
        "answer": r.answer,
        "confidence": round(r.confidence, 3),
        "nodes_used": r.node_count,  # @property — must work
        "cost_usd": round(r.cost_usd, 6),
        "mode": r.reasoning_mode,
    }
    assert consumer_view["answer"].startswith("Error:")
    assert consumer_view["confidence"] == 0.0
    assert consumer_view["nodes_used"] == 0
    assert consumer_view["cost_usd"] == 0.0
    assert consumer_view["mode"] == "error"


# ── 4. Empty batch (defensive) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_areason_batch_empty_queries() -> None:
    """Empty query list returns empty result list — no crash."""
    graph = _build_graph()
    results = await graph.areason_batch([])
    assert results == []


# ── 5. Single-query batch ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_areason_batch_single_query_failure() -> None:
    graph = _build_graph()

    async def raises(self, q, **kw):
        raise ValueError("only one")

    with patch.object(Graqle, "areason", raises):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = await graph.areason_batch(["only"])
    assert len(results) == 1
    assert results[0].query == "only"
    assert "only one" in results[0].answer
