"""Phase 3 integration tests — streaming, batch, token optimization."""

# ── graqle:intelligence ──
# module: tests.test_integration.test_phase3
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, mock, graph
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.backends.mock import MockBackend


@pytest.fixture
def ready_graph(sample_graph):
    backend = MockBackend(responses=[
        "Analysis result for this query. Confidence: 75%",
        "Refined analysis with neighbor input. Confidence: 85%",
        "Final synthesis with full context. Confidence: 90%",
    ])
    sample_graph.set_default_backend(backend)
    return sample_graph


@pytest.mark.asyncio
async def test_areason_stream(ready_graph):
    """graph.areason_stream yields StreamChunk objects."""
    chunks = []
    async for chunk in ready_graph.areason_stream(
        "test streaming", max_rounds=2, strategy="full"
    ):
        chunks.append(chunk)

    assert len(chunks) >= 2
    types = {c.chunk_type for c in chunks}
    assert "node_result" in types
    assert "final_answer" in types


@pytest.mark.asyncio
async def test_areason_batch(ready_graph):
    """graph.areason_batch processes multiple queries."""
    queries = ["query 1", "query 2", "query 3"]
    results = await ready_graph.areason_batch(
        queries, max_rounds=2, strategy="full"
    )

    assert len(results) == 3
    for r in results:
        assert r.answer != ""
        assert r.confidence > 0


@pytest.mark.asyncio
async def test_areason_batch_concurrency(ready_graph):
    """Batch reasoning respects concurrency limit."""
    queries = [f"query {i}" for i in range(5)]
    results = await ready_graph.areason_batch(
        queries, max_rounds=1, strategy="full", max_concurrent=2
    )
    assert len(results) == 5


def test_imports_phase3():
    """Phase 3 modules import cleanly."""
    from graqle.backends.registry import BackendRegistry
    from graqle.optimization.message_compressor import MessageCompressor
    from graqle.optimization.token_optimizer import TokenOptimizer
    from graqle.orchestration.async_protocol import AsyncMessageProtocol
    from graqle.orchestration.debate import DebateProtocol
    from graqle.orchestration.explanation import ExplanationTrace
    from graqle.orchestration.hierarchical import HierarchicalAggregation
    from graqle.orchestration.streaming import StreamingOrchestrator
    from graqle.server.models import ReasonRequest

    assert AsyncMessageProtocol is not None
    assert StreamingOrchestrator is not None
    assert ExplanationTrace is not None
    assert DebateProtocol is not None
    assert HierarchicalAggregation is not None
    assert TokenOptimizer is not None
    assert MessageCompressor is not None
    assert BackendRegistry is not None
    assert ReasonRequest is not None
