"""Tests for StreamingOrchestrator."""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_streaming
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, mock, streaming
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.backends.mock import MockBackend
from graqle.orchestration.streaming import StreamChunk, StreamingOrchestrator


@pytest.fixture
def graph_with_backend(sample_graph):
    backend = MockBackend(responses=[
        "Initial analysis of this topic area. Confidence: 70%",
        "Refined analysis with more context now. Confidence: 85%",
    ])
    sample_graph.set_default_backend(backend)
    for nid in sample_graph.nodes:
        sample_graph.nodes[nid].activate(backend)
    return sample_graph


@pytest.mark.asyncio
async def test_streaming_yields_chunks(graph_with_backend):
    """StreamingOrchestrator yields StreamChunk objects."""
    streamer = StreamingOrchestrator(graph_with_backend, max_rounds=2)
    node_ids = list(graph_with_backend.nodes.keys())

    chunks = []
    async for chunk in streamer.stream("test query", active_node_ids=node_ids):
        chunks.append(chunk)

    assert len(chunks) >= 2  # At least node results + final answer
    assert any(c.chunk_type == "node_result" for c in chunks)
    assert any(c.chunk_type == "final_answer" for c in chunks)


@pytest.mark.asyncio
async def test_streaming_final_has_content(graph_with_backend):
    """Final answer chunk has non-empty content."""
    streamer = StreamingOrchestrator(graph_with_backend, max_rounds=1)
    node_ids = list(graph_with_backend.nodes.keys())

    final = None
    async for chunk in streamer.stream("test", active_node_ids=node_ids):
        if chunk.chunk_type == "final_answer":
            final = chunk

    assert final is not None
    assert len(final.content) > 0
    assert final.confidence > 0


def test_stream_chunk_to_dict():
    """StreamChunk serializes to dict."""
    chunk = StreamChunk(
        chunk_type="node_result", node_id="n1",
        round_num=0, content="test", confidence=0.8,
    )
    d = chunk.to_dict()
    assert d["type"] == "node_result"
    assert d["node_id"] == "n1"
    assert d["confidence"] == 0.8
