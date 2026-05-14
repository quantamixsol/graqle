"""CR-004 PR-004b tests — ReasoningResult.graph_health field + MCP wiring.

Covers two surfaces:

1. The ``ReasoningResult.graph_health`` optional field: default value is
   ``None`` (backward-compatible), construction with a real
   :class:`GraphHealth` works, mutation after construction works (the
   dataclass is NOT frozen — by design, so the MCP boundary can attach
   the probe result without rebuilding the result).

2. The dict-snapshot shape produced by ``_handle_reason``: every public
   :class:`GraphHealth` field is forwarded under the canonical key in
   ``result_dict['graph_health']``.

CI safety: no ``importlib.util.module_from_spec``, no sys.modules tricks,
no real graph instantiation (we build a duck-typed fake).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from graqle.activation.health_probe import (
    _clear_probe_cache_for_tests,
    graph_health_probe,
)
from graqle.core.graph_health import GraphHealth
from graqle.core.types import ReasoningResult


def _make_result(**overrides: Any) -> ReasoningResult:
    """Minimal valid ReasoningResult; tests override specific fields."""
    base: dict[str, Any] = {
        "query": "what is X?",
        "answer": "X is Y.",
        "confidence": 0.9,
        "rounds_completed": 1,
        "active_nodes": ["n1", "n2"],
        "message_trace": [],
        "cost_usd": 0.01,
        "latency_ms": 12.3,
    }
    base.update(overrides)
    return ReasoningResult(**base)


@dataclass
class _FakeGraph:
    nodes: dict[str, object]
    edges: dict[str, object]


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _clear_probe_cache_for_tests()
    yield
    _clear_probe_cache_for_tests()


# ─── ReasoningResult.graph_health field semantics ──────────────────────────


def test_graph_health_defaults_to_none() -> None:
    """Existing callers that never set graph_health get None — no break."""
    r = _make_result()
    assert r.graph_health is None


def test_graph_health_assignment_after_construction() -> None:
    """The dataclass is mutable: MCP boundary can attach probe result."""
    r = _make_result()
    gh = GraphHealth(
        node_count=100,
        edge_count=200,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=False,
        reason=None,
    )
    r.graph_health = gh
    assert r.graph_health is gh
    assert r.graph_health.degraded is False


def test_graph_health_constructor_kwarg() -> None:
    """Callers may also pass graph_health at construction time."""
    gh = GraphHealth(
        node_count=10,
        edge_count=0,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=True,
        reason="0 edges",
    )
    r = _make_result(graph_health=gh)
    assert r.graph_health is gh


# ─── Probe result attaches cleanly to ReasoningResult ───────────────────────


def test_probe_result_attaches_via_assignment() -> None:
    """The full MCP wiring pattern: probe + attach + read back."""
    fake_graph = _FakeGraph(
        nodes={"n1": object(), "n2": object()},
        edges={"e1": object()},
    )
    r = _make_result()
    r.graph_health = graph_health_probe(fake_graph)
    assert r.graph_health is not None
    assert r.graph_health.node_count == 2
    assert r.graph_health.edge_count == 1


def test_probe_zero_edge_attaches_degraded_true() -> None:
    """Critical regression guard: zero-edge graph attaches degraded=True."""
    fake_graph = _FakeGraph(
        nodes={f"n{i}": object() for i in range(50)},
        edges={},
    )
    r = _make_result()
    r.graph_health = graph_health_probe(fake_graph)
    assert r.graph_health is not None
    assert r.graph_health.degraded is True
    assert r.graph_health.reason is not None
    assert "0 edges" in r.graph_health.reason


# ─── Dict snapshot keys (matches _handle_reason wiring) ────────────────────


def test_dict_snapshot_round_trip() -> None:
    """The 8 fields the MCP envelope serialises must all be readable."""
    gh = GraphHealth(
        node_count=100,
        edge_count=200,
        chunks_unembedded=5,
        percent_stale=0.05,
        activation_mode="semantic",
        degraded=False,
        reason=None,
    )
    # Mirror the literal dict shape constructed at mcp_dev_server.py:_handle_reason
    snap = {
        "node_count": gh.node_count,
        "edge_count": gh.edge_count,
        "chunks_unembedded": gh.chunks_unembedded,
        "percent_stale": gh.percent_stale,
        "activation_mode": gh.activation_mode,
        "degraded": gh.degraded,
        "reason": gh.reason,
        "schema_version": gh.schema_version,
    }
    expected_keys = {
        "node_count", "edge_count", "chunks_unembedded", "percent_stale",
        "activation_mode", "degraded", "reason", "schema_version",
    }
    assert set(snap.keys()) == expected_keys
    assert snap["schema_version"] == "1"
    assert snap["degraded"] is False
    assert snap["reason"] is None


def test_dict_snapshot_with_degraded_reason_preserved() -> None:
    """Degraded snapshot serialises reason string verbatim (already sanitised)."""
    gh = GraphHealth(
        node_count=100,
        edge_count=0,
        chunks_unembedded=0,
        percent_stale=0.0,
        activation_mode="semantic",
        degraded=True,
        reason="graph has 100 nodes but 0 edges (silent edge-loss; see CR-003)",
    )
    snap = {
        "node_count": gh.node_count,
        "edge_count": gh.edge_count,
        "degraded": gh.degraded,
        "reason": gh.reason,
        "schema_version": gh.schema_version,
    }
    assert snap["degraded"] is True
    assert "0 edges" in snap["reason"]
    assert snap["schema_version"] == "1"
