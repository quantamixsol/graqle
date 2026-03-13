"""Shared test fixtures for Graqle."""

import pytest
import networkx as nx

from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from graqle.core.edge import CogniEdge
from graqle.core.message import Message
from graqle.core.state import NodeState
from graqle.core.types import ReasoningType
from graqle.backends.mock import MockBackend


@pytest.fixture
def mock_backend():
    """A mock backend that returns configurable responses."""
    return MockBackend(responses=[
        "This is relevant to the query. Based on my knowledge, "
        "the key finding is X. Confidence: 75%",
        "Building on neighbor analysis, I agree with the assessment "
        "but add nuance Y. Confidence: 82%",
        "Synthesizing all inputs: the conclusion is Z with "
        "strong evidence from multiple sources. Confidence: 90%",
    ])


@pytest.fixture
def sample_nx_graph():
    """A small NetworkX graph for testing."""
    G = nx.Graph()
    G.add_node("n1", label="Node A", type="Concept", description="First concept")
    G.add_node("n2", label="Node B", type="Concept", description="Second concept")
    G.add_node("n3", label="Node C", type="Concept", description="Third concept")
    G.add_node("n4", label="Node D", type="Concept", description="Fourth concept")
    G.add_node("n5", label="Node E", type="Concept", description="Fifth concept hub")

    G.add_edge("n1", "n2", relationship="RELATED_TO", weight=0.8)
    G.add_edge("n2", "n3", relationship="RELATED_TO", weight=0.6)
    G.add_edge("n3", "n4", relationship="CONFLICTS_WITH", weight=0.9)
    G.add_edge("n5", "n1", relationship="CONTAINS", weight=0.7)
    G.add_edge("n5", "n2", relationship="CONTAINS", weight=0.7)
    G.add_edge("n5", "n3", relationship="CONTAINS", weight=0.7)
    G.add_edge("n5", "n4", relationship="REFERENCES", weight=0.5)
    return G


@pytest.fixture
def sample_graph(sample_nx_graph):
    """A Graqle built from the sample NetworkX graph."""
    return Graqle.from_networkx(sample_nx_graph)


@pytest.fixture
def sample_message():
    """A sample message for testing."""
    return Message(
        source_node_id="n1",
        target_node_id="n2",
        round=1,
        content="Analysis shows regulatory conflict. Confidence: 80%",
        reasoning_type=ReasoningType.ASSERTION,
        confidence=0.8,
        evidence=["n1"],
    )
