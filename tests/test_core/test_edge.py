"""Tests for CogniEdge."""

from graqle.core.edge import CogniEdge
from graqle.core.message import Message


def test_edge_creation():
    edge = CogniEdge(id="e1", source_id="n1", target_id="n2", relationship="RELATED_TO")
    assert edge.id == "e1"
    assert edge.source_id == "n1"
    assert edge.target_id == "n2"
    assert edge.weight == 1.0


def test_edge_send_receive():
    edge = CogniEdge(id="e1", source_id="n1", target_id="n2")
    msg = Message(source_node_id="n1", target_node_id="n2", round=0, content="test")

    edge.send(msg)
    assert edge.pending_count == 1

    received = edge.receive()
    assert received is not None
    assert received.content == "test"
    assert edge.pending_count == 0


def test_edge_capacity():
    edge = CogniEdge(id="e1", source_id="n1", target_id="n2", capacity=2)
    for i in range(3):
        msg = Message(source_node_id="n1", target_node_id="n2", round=0, content=f"msg{i}")
        edge.send(msg)

    # Capacity is 2, so first message should be dropped
    assert edge.pending_count == 2
    msgs = edge.receive_all()
    assert len(msgs) == 2
    assert msgs[0].content == "msg1"


def test_edge_semantic_distance():
    edge = CogniEdge(id="e1", source_id="n1", target_id="n2", weight=0.8)
    assert edge.semantic_distance == pytest.approx(0.2)

    edge2 = CogniEdge(id="e2", source_id="n1", target_id="n2", weight=1.0)
    assert edge2.semantic_distance == pytest.approx(0.01)  # clamped


# Need pytest import for approx
import pytest
