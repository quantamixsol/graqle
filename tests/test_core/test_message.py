"""Tests for Message."""

# ── graqle:intelligence ──
# module: tests.test_core.test_message
# risk: LOW (impact radius: 0 modules)
# dependencies: message, types
# constraints: none
# ── /graqle:intelligence ──

from graqle.core.message import Message
from graqle.core.types import ReasoningType


def test_message_creation():
    msg = Message(
        source_node_id="src",
        target_node_id="tgt",
        round=1,
        content="Test content",
    )
    assert msg.source_node_id == "src"
    assert msg.target_node_id == "tgt"
    assert msg.round == 1
    assert msg.content == "Test content"
    assert msg.reasoning_type == ReasoningType.ASSERTION
    assert msg.confidence == 0.5
    assert msg.id  # auto-generated


def test_message_to_prompt_context():
    msg = Message(
        source_node_id="gdpr",
        target_node_id="ai_act",
        round=1,
        content="GDPR requires consent",
        reasoning_type=ReasoningType.ASSERTION,
        confidence=0.85,
    )
    ctx = msg.to_prompt_context()
    assert "ASSERTION" in ctx
    assert "gdpr" in ctx
    assert "85%" in ctx
    assert "GDPR requires consent" in ctx


def test_message_to_dict():
    msg = Message(
        source_node_id="n1",
        target_node_id="n2",
        round=0,
        content="test",
    )
    d = msg.to_dict()
    assert d["source"] == "n1"
    assert d["target"] == "n2"
    assert d["round"] == 0
    assert "timestamp" in d


def test_query_broadcast():
    msg = Message.create_query_broadcast("What is GDPR?", "gdpr_node")
    assert msg.source_node_id == "__query__"
    assert msg.target_node_id == "gdpr_node"
    assert msg.reasoning_type == ReasoningType.QUESTION
    assert msg.confidence == 1.0
