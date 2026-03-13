"""Tests for async event-driven message passing."""

import pytest

from graqle.backends.mock import MockBackend
from graqle.core.graph import Graqle
from graqle.orchestration.async_protocol import AsyncMessageProtocol, NodeMailbox


@pytest.fixture
def graph_with_backend(sample_graph):
    """Sample graph with mock backend assigned."""
    backend = MockBackend(responses=[
        "Async analysis of the topic. Confidence: 75%",
        "Updated analysis with neighbor context. Confidence: 82%",
        "Final synthesis across all inputs. Confidence: 90%",
    ])
    sample_graph.set_default_backend(backend)
    for nid in sample_graph.nodes:
        sample_graph.nodes[nid].activate(backend)
    return sample_graph


@pytest.mark.asyncio
async def test_node_mailbox():
    """NodeMailbox queues and dequeues messages."""
    from graqle.core.message import Message
    from graqle.core.types import ReasoningType

    mailbox = NodeMailbox("n1", capacity=10)
    assert mailbox.pending == 0

    msg = Message(
        source_node_id="n2", target_node_id="n1", round=0,
        content="hello", reasoning_type=ReasoningType.ASSERTION,
        confidence=0.7, evidence=["n2"],
    )
    await mailbox.send(msg)
    assert mailbox.pending == 1

    received = await mailbox.receive()
    assert received is not None
    assert received.content == "hello"
    assert mailbox.processed == 1


@pytest.mark.asyncio
async def test_async_protocol_basic(graph_with_backend):
    """AsyncMessageProtocol processes messages across nodes."""
    protocol = AsyncMessageProtocol(max_waves=2)
    node_ids = list(graph_with_backend.nodes.keys())

    all_messages = await protocol.run(graph_with_backend, "test query", node_ids)

    assert len(all_messages) == len(node_ids)
    # Each node should have at least one message from wave 0
    for nid in node_ids:
        assert len(all_messages[nid]) >= 1


@pytest.mark.asyncio
async def test_async_protocol_streaming(graph_with_backend):
    """AsyncMessageProtocol streams results via async iterator."""
    protocol = AsyncMessageProtocol(max_waves=2)
    node_ids = list(graph_with_backend.nodes.keys())

    chunks = []
    async for wave, node_id, message in protocol.stream(
        graph_with_backend, "stream test", node_ids
    ):
        chunks.append((wave, node_id, message))

    assert len(chunks) >= len(node_ids)  # At least one per node from wave 0
    # Check wave numbers are non-negative
    assert all(w >= 0 for w, _, _ in chunks)
