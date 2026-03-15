"""Tests for CogniNode."""

# ── graqle:intelligence ──
# module: tests.test_core.test_node
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, node, types, mock
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.core.node import CogniNode
from graqle.core.types import NodeStatus
from graqle.backends.mock import MockBackend


def test_node_creation():
    node = CogniNode(id="gdpr", label="GDPR", entity_type="Regulation")
    assert node.id == "gdpr"
    assert node.label == "GDPR"
    assert node.entity_type == "Regulation"
    assert node.status == NodeStatus.IDLE
    assert node.backend is None


def test_node_activate_deactivate():
    node = CogniNode(id="n1", label="Test")
    backend = MockBackend()
    node.activate(backend)
    assert node.status == NodeStatus.ACTIVATED
    assert node.backend is backend

    node.deactivate()
    assert node.status == NodeStatus.IDLE
    assert node.backend is None


@pytest.mark.asyncio
async def test_node_reason():
    node = CogniNode(
        id="gdpr",
        label="GDPR",
        entity_type="Regulation",
        description="EU data protection regulation",
    )
    backend = MockBackend(response="GDPR requires consent. Confidence: 80%")
    node.activate(backend)

    msg = await node.reason("What does GDPR require?", [])
    assert msg.source_node_id == "gdpr"
    assert "GDPR" in msg.content or "consent" in msg.content
    assert msg.confidence == 0.8


@pytest.mark.asyncio
async def test_node_reason_without_backend():
    node = CogniNode(id="n1", label="Test")
    with pytest.raises(RuntimeError, match="no backend"):
        await node.reason("test", [])


def test_node_degree():
    node = CogniNode(id="n1", label="Test")
    node.incoming_edges = ["e1", "e2"]
    node.outgoing_edges = ["e3"]
    assert node.degree == 3
    assert not node.is_hub

    node.outgoing_edges = ["e3", "e4", "e5", "e6"]
    assert node.degree == 6
    assert node.is_hub
