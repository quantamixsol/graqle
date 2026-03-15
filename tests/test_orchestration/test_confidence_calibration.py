"""Tests for relevance-weighted confidence calibration (Bug 18 fix).

v0.14.0: Top-k weighted + coverage factor
v0.15.0: Recalibrated for large KGs (>5K nodes) — 75/25 weighting,
         logarithmic coverage, tiered floors.
"""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_confidence_calibration
# risk: LOW (impact radius: 0 modules)
# dependencies: asyncio, math, mock, pytest
# constraints: none
# ── /graqle:intelligence ──

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_message(nid, confidence=0.9, content="answer", tokens=100):
    """Create a mock Message."""
    msg = MagicMock()
    msg.confidence = confidence
    msg.content = content
    msg.token_count = tokens
    msg.tokens_used = tokens
    msg.to_dict = lambda: {"confidence": confidence, "content": content}
    return msg


def _make_orchestrator():
    """Create an Orchestrator with mocked sub-components."""
    from graqle.orchestration.orchestrator import Orchestrator
    from graqle.config.settings import OrchestrationConfig, ObserverConfig

    orch = Orchestrator(
        config=OrchestrationConfig(max_rounds=1),
        observer_config=ObserverConfig(enabled=False),
    )
    return orch


def _make_graph(node_ids):
    """Create a mock Graqle with specified nodes."""
    graph = MagicMock()
    graph.config = MagicMock()
    graph.config.cost = MagicMock()
    graph.config.cost.budget_per_query = 10.0
    graph.nodes = {}
    for nid in node_ids:
        node = MagicMock()
        node.id = nid
        node.label = nid
        node.backend = MagicMock()
        node.backend.cost_per_1k_tokens = 0.001
        graph.nodes[nid] = node
    return graph


def _setup_mocks(orch, messages_dict):
    """Wire up mocks so run() executes one round and returns."""
    orch.message_protocol.run_round = AsyncMock(return_value=messages_dict)
    orch.convergence_detector.check = MagicMock(return_value=True)
    orch.aggregator.aggregate = AsyncMock(return_value="synthesized answer")
    orch.observer.observe_round = AsyncMock(return_value=[])


class TestConfidenceCalibration:
    """Tests for relevance-weighted confidence in Orchestrator.run()."""

    def test_weighted_confidence_high_relevance_dominates(self):
        """High-relevance node with high confidence should produce good score."""
        async def _run():
            orch = _make_orchestrator()
            messages = {
                "node_a": _make_message("node_a", confidence=0.95),
                "node_b": _make_message("node_b", confidence=0.90),
            }
            _setup_mocks(orch, messages)
            graph = _make_graph(["node_a", "node_b"])

            relevance = {"node_a": 0.95, "node_b": 0.10}
            result = await orch.run(
                graph, "test query", ["node_a", "node_b"],
                relevance_scores=relevance,
            )

            # v0.15.0 formula: 75/25 weighting + log coverage
            # raw = (0.95*0.95 + 0.90*0.10) / (0.95+0.10) = 0.945
            # coverage = log2(1+2)/log2(1+3) = log2(3)/log2(4) = 0.792
            # calibrated = 0.75*0.945 + 0.25*0.792 = 0.907
            assert result.confidence > 0.70

        asyncio.run(_run())

    def test_low_relevance_high_confidence_gets_downweighted(self):
        """A low-relevance node reporting high confidence should be downweighted."""
        async def _run():
            orch = _make_orchestrator()
            messages = {
                "node_a": _make_message("node_a", confidence=0.8),
                "node_b": _make_message("node_b", confidence=0.95),
            }
            _setup_mocks(orch, messages)
            graph = _make_graph(["node_a", "node_b"])

            relevance = {"node_a": 0.9, "node_b": 0.05}
            result = await orch.run(
                graph, "query", ["node_a", "node_b"],
                relevance_scores=relevance,
            )

            # Should be less than unweighted average of 0.875
            assert result.confidence < 0.875

        asyncio.run(_run())

    def test_no_relevance_scores_falls_back_to_average(self):
        """When no relevance scores provided, use simple average."""
        async def _run():
            orch = _make_orchestrator()
            messages = {
                "a": _make_message("a", confidence=0.8),
                "b": _make_message("b", confidence=0.6),
            }
            _setup_mocks(orch, messages)
            graph = _make_graph(["a", "b"])

            result = await orch.run(graph, "query", ["a", "b"])

            expected = (0.8 + 0.6) / 2
            assert abs(result.confidence - expected) < 0.01

        asyncio.run(_run())

    def test_zero_total_relevance_returns_zero_confidence(self):
        """If all relevance scores are 0, confidence should be 0."""
        async def _run():
            orch = _make_orchestrator()
            messages = {"a": _make_message("a", confidence=0.9)}
            _setup_mocks(orch, messages)
            graph = _make_graph(["a"])

            result = await orch.run(
                graph, "query", ["a"],
                relevance_scores={"a": 0.0},
            )
            assert result.confidence == 0.0

        asyncio.run(_run())

    def test_single_node_relevance_weighted(self):
        """Single node: calibrated confidence accounts for low coverage."""
        async def _run():
            orch = _make_orchestrator()
            messages = {"x": _make_message("x", confidence=0.85)}
            _setup_mocks(orch, messages)
            graph = _make_graph(["x"])

            result = await orch.run(
                graph, "query", ["x"],
                relevance_scores={"x": 0.7},
            )
            # v0.15.0: raw=0.85, coverage=log2(2)/log2(4)=0.5
            # calibrated = 0.75*0.85 + 0.25*0.5 = 0.763
            # But single node → low activation, no floor applies
            assert 0.5 < result.confidence < 0.85

        asyncio.run(_run())

    def test_large_kg_many_activated_nodes_gets_high_confidence(self):
        """Large KG (13K+) with 15 activated nodes should report high confidence.

        This is the core fix for the Session 2 evaluation feedback:
        "9-15% confidence for 8/10 quality answers on 13K-node KG"
        """
        async def _run():
            orch = _make_orchestrator()
            # Simulate 15 activated nodes (typical PCST output on large KG)
            node_ids = [f"n{i}" for i in range(15)]
            confs = [0.92, 0.88, 0.85, 0.83, 0.80, 0.78, 0.75,
                     0.72, 0.70, 0.68, 0.65, 0.60, 0.55, 0.50, 0.50]
            rels = [0.95, 0.82, 0.75, 0.65, 0.58, 0.52, 0.48,
                    0.42, 0.38, 0.31, 0.28, 0.22, 0.15, 0.10, 0.05]
            messages = {
                nid: _make_message(nid, confidence=c)
                for nid, c in zip(node_ids, confs)
            }
            _setup_mocks(orch, messages)
            graph = _make_graph(node_ids)

            relevance = dict(zip(node_ids, rels))
            result = await orch.run(
                graph, "cross-product synergies", node_ids,
                relevance_scores=relevance,
            )

            # With 15 nodes activated (all rel > 0.01), raw > 0.15
            # → 10+ node floor of 0.65 applies
            # Actual calibrated should be well above 0.65
            assert result.confidence >= 0.65, (
                f"Large KG confidence {result.confidence:.2f} below 0.65 floor"
            )

        asyncio.run(_run())

    def test_medium_activation_gets_medium_floor(self):
        """5-9 activated nodes should get the 0.55 floor."""
        async def _run():
            orch = _make_orchestrator()
            node_ids = [f"n{i}" for i in range(6)]
            messages = {
                nid: _make_message(nid, confidence=0.50)
                for nid in node_ids
            }
            _setup_mocks(orch, messages)
            graph = _make_graph(node_ids)

            # All nodes with moderate relevance > 0.01
            relevance = {f"n{i}": 0.5 - i * 0.05 for i in range(6)}
            result = await orch.run(
                graph, "query", node_ids,
                relevance_scores=relevance,
            )

            # 6 activated, raw = 0.50 > 0.10 → floor 0.55
            assert result.confidence >= 0.55

        asyncio.run(_run())
