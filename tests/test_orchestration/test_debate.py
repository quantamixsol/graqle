"""Tests for DebateProtocol."""

import pytest

from graqle.backends.mock import MockBackend
from graqle.orchestration.debate import DebateProtocol


@pytest.fixture
def debate_graph(sample_graph):
    backend = MockBackend(responses=[
        "My position on this topic is X. Confidence: 75%",
        "I challenge this claim because Y contradicts it. Confidence: 70%",
        "After considering challenges, my refined position is Z. Confidence: 85%",
    ])
    sample_graph.set_default_backend(backend)
    for nid in sample_graph.nodes:
        sample_graph.nodes[nid].activate(backend)
    return sample_graph


@pytest.mark.asyncio
async def test_debate_produces_messages(debate_graph):
    """Debate protocol produces messages for all nodes."""
    protocol = DebateProtocol(challenge_rounds=1)
    node_ids = list(debate_graph.nodes.keys())[:3]

    result = await protocol.run(debate_graph, "test query", node_ids)

    assert len(result) == len(node_ids)
    for nid in node_ids:
        assert len(result[nid]) >= 1  # At least opening


@pytest.mark.asyncio
async def test_debate_has_rebuttals(debate_graph):
    """Debate protocol includes rebuttal phase."""
    protocol = DebateProtocol(challenge_rounds=1)
    # Use connected nodes so challenges flow
    node_ids = ["n1", "n2"]  # These are connected in sample_graph

    result = await protocol.run(debate_graph, "debate test", node_ids)

    # Each node should have opening + rebuttal at minimum
    for nid in node_ids:
        assert len(result[nid]) >= 2  # opening + rebuttal
