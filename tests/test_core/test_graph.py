"""Tests for Graqle."""

import pytest
import networkx as nx

from graqle.core.graph import Graqle
from graqle.backends.mock import MockBackend


def test_graph_from_networkx(sample_nx_graph):
    graph = Graqle.from_networkx(sample_nx_graph)
    assert len(graph.nodes) == 5
    assert len(graph.edges) == 7
    assert graph.nodes["n1"].label == "Node A"


def test_graph_neighbors(sample_graph):
    neighbors = sample_graph.get_neighbors("n5")
    assert len(neighbors) == 4  # hub connected to all
    assert "n1" in neighbors
    assert "n2" in neighbors


def test_graph_edges_between(sample_graph):
    edges = sample_graph.get_edges_between("n1", "n2")
    assert len(edges) >= 1
    assert edges[0].relationship == "RELATED_TO"


def test_graph_stats(sample_graph):
    stats = sample_graph.stats
    assert stats.total_nodes == 5
    assert stats.total_edges == 7
    assert stats.avg_degree > 0
    assert len(stats.hub_nodes) >= 1


def test_graph_to_networkx(sample_graph):
    G = sample_graph.to_networkx()
    assert isinstance(G, nx.Graph)
    assert len(G.nodes) == 5


def test_graph_add_node(sample_graph):
    from graqle.core.node import CogniNode
    new_node = CogniNode(id="n6", label="New Node")
    sample_graph.add_node(new_node)
    assert "n6" in sample_graph.nodes


@pytest.mark.asyncio
async def test_graph_reason(sample_graph):
    backend = MockBackend(response="Synthesized answer. Confidence: 85%")
    sample_graph.set_default_backend(backend)

    result = await sample_graph.areason(
        "What is the relationship between concepts?",
        max_rounds=2,
        strategy="full",
    )
    assert result.answer
    assert result.rounds_completed >= 1
    assert result.node_count == 5
    assert result.confidence > 0


def test_graph_repr(sample_graph):
    r = repr(sample_graph)
    assert "Graqle" in r
    assert "nodes=5" in r
