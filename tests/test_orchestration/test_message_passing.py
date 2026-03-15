"""Tests for MessagePassingProtocol."""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_message_passing
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, graph, mock, message_passing
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.backends.mock import MockBackend
from graqle.orchestration.message_passing import MessagePassingProtocol


@pytest.mark.asyncio
async def test_initial_round(sample_graph):
    backend = MockBackend(response="Initial analysis. Confidence: 70%")
    for node in sample_graph.nodes.values():
        node.activate(backend)

    protocol = MessagePassingProtocol(parallel=True)
    messages = await protocol.run_round(
        graph=sample_graph,
        query="test query",
        active_node_ids=list(sample_graph.nodes.keys()),
        round_num=0,
    )

    assert len(messages) == 5  # all nodes respond
    assert all(m.round == 0 for m in messages.values())


@pytest.mark.asyncio
async def test_exchange_round(sample_graph):
    backend = MockBackend(response="Updated analysis. Confidence: 80%")
    for node in sample_graph.nodes.values():
        node.activate(backend)

    protocol = MessagePassingProtocol(parallel=True)

    # Round 0
    round0 = await protocol.run_round(
        sample_graph, "test", list(sample_graph.nodes.keys()), 0
    )

    # Round 1 (with previous messages)
    round1 = await protocol.run_round(
        sample_graph, "test", list(sample_graph.nodes.keys()), 1, round0
    )

    assert len(round1) == 5
    assert all(m.round == 1 for m in round1.values())
