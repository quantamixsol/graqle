"""Tests for relevance-weighted confidence calibration (Bug 18 fix).

Verifies that the orchestrator uses relevance scores to weight confidence
instead of simple averaging: calibrated = sum(conf_i * rel_i) / sum(rel_i).
"""

import asyncio
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
    from cognigraph.orchestration.orchestrator import Orchestrator
    from cognigraph.config.settings import OrchestrationConfig, ObserverConfig

    orch = Orchestrator(
        config=OrchestrationConfig(max_rounds=1),
        observer_config=ObserverConfig(enabled=False),
    )
    return orch


def _make_graph(node_ids):
    """Create a mock CogniGraph with specified nodes."""
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
    # message_protocol.run_round returns messages
    orch.message_protocol.run_round = AsyncMock(return_value=messages_dict)
    # convergence after first round
    orch.convergence_detector.check = MagicMock(return_value=True)
    # aggregator returns a string
    orch.aggregator.aggregate = AsyncMock(return_value="synthesized answer")
    # observer does nothing
    orch.observer.observe_round = AsyncMock(return_value=[])


class TestConfidenceCalibration:
    """Tests for relevance-weighted confidence in Orchestrator.run()."""

    def test_weighted_confidence_high_relevance_dominates(self):
        """High-relevance node with high confidence should dominate."""
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

            # Weighted: (0.95*0.95 + 0.90*0.10) / (0.95+0.10) = 0.945
            # Unweighted: (0.95+0.90)/2 = 0.925
            assert result.confidence > 0.925

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

            # Weighted: (0.8*0.9 + 0.95*0.05) / (0.9+0.05) = 0.808
            # Unweighted: (0.8+0.95)/2 = 0.875
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
        """Single node: weighted confidence equals that node's confidence."""
        async def _run():
            orch = _make_orchestrator()
            messages = {"x": _make_message("x", confidence=0.85)}
            _setup_mocks(orch, messages)
            graph = _make_graph(["x"])

            result = await orch.run(
                graph, "query", ["x"],
                relevance_scores={"x": 0.7},
            )
            # (0.85*0.7)/0.7 = 0.85
            assert abs(result.confidence - 0.85) < 0.01

        asyncio.run(_run())
