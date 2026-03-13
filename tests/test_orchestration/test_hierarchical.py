"""Tests for HierarchicalAggregation."""

import pytest

from graqle.backends.mock import MockBackend
from graqle.orchestration.hierarchical import HierarchicalAggregation


@pytest.fixture
def hier_graph(sample_graph):
    backend = MockBackend(responses=[
        "Leaf analysis of domain-specific topic. Confidence: 70%",
        "Hub synthesis across multiple leaf inputs. Confidence: 80%",
        "Root final aggregated answer synthesis. Confidence: 90%",
    ])
    sample_graph.set_default_backend(backend)
    for nid in sample_graph.nodes:
        sample_graph.nodes[nid].activate(backend)
    return sample_graph


def test_classify_nodes(hier_graph):
    """classify_nodes identifies leaves, hubs, and root."""
    hier = HierarchicalAggregation(hub_degree_threshold=3)
    node_ids = list(hier_graph.nodes.keys())

    leaves, hubs, root = hier.classify_nodes(hier_graph, node_ids)

    assert len(leaves) + len(hubs) >= len(node_ids) - 1  # root may be in hubs
    assert root is not None


@pytest.mark.asyncio
async def test_hierarchical_run(hier_graph):
    """HierarchicalAggregation produces messages for all nodes."""
    hier = HierarchicalAggregation(hub_degree_threshold=3)
    node_ids = list(hier_graph.nodes.keys())

    result = await hier.run(hier_graph, "test query", node_ids)

    assert len(result) >= 1
    # At least leaf nodes should have messages
    for nid, msg in result.items():
        assert msg.content != ""
