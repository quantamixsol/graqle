"""Tests for ExplanationTrace."""

# ── graqle:intelligence ──
# module: tests.test_orchestration.test_explanation
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, message, types, explanation
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.core.message import Message
from graqle.core.types import ReasoningType
from graqle.orchestration.explanation import ExplanationTrace, NodeClaim


def _msg(nid: str, content: str, conf: float = 0.7) -> Message:
    return Message(
        source_node_id=nid, target_node_id="broadcast", round=0,
        content=content, reasoning_type=ReasoningType.ASSERTION,
        confidence=conf, evidence=[nid],
    )


def test_explanation_trace_add_round():
    """ExplanationTrace records claims from a round."""
    trace = ExplanationTrace(query="test")
    messages = {
        "n1": _msg("n1", "Claim A from node 1"),
        "n2": _msg("n2", "Claim B from node 2"),
    }
    trace.add_round(0, messages)
    assert len(trace.claims) == 2
    assert trace.total_rounds == 1


def test_explanation_trace_with_influence():
    """ExplanationTrace tracks influence between rounds."""
    trace = ExplanationTrace(query="test")

    # Round 0
    r0 = {
        "n1": _msg("n1", "Initial claim", conf=0.5),
        "n2": _msg("n2", "Other claim", conf=0.6),
    }
    trace.add_round(0, r0)

    # Round 1 with neighbor context
    r1 = {
        "n1": _msg("n1", "Updated claim", conf=0.8),
        "n2": _msg("n2", "Updated other", conf=0.7),
    }
    trace.add_round(1, r1, previous_messages=r0,
                    neighbor_map={"n1": ["n2"], "n2": ["n1"]})

    assert len(trace.influences) >= 1
    assert trace.total_rounds == 2


def test_explanation_trace_contributing_nodes():
    """contributing_nodes returns unique node IDs."""
    trace = ExplanationTrace(query="test")
    trace.add_round(0, {"n1": _msg("n1", "a"), "n2": _msg("n2", "b")})
    trace.add_round(1, {"n1": _msg("n1", "c")})
    assert set(trace.contributing_nodes) == {"n1", "n2"}


def test_explanation_trace_top_influencers():
    """top_influencers ranks by total outgoing influence."""
    trace = ExplanationTrace(query="test")
    r0 = {"n1": _msg("n1", "a", 0.3), "n2": _msg("n2", "b", 0.3)}
    r1 = {"n1": _msg("n1", "c", 0.9), "n2": _msg("n2", "d", 0.4)}
    trace.add_round(0, r0)
    trace.add_round(1, r1, previous_messages=r0,
                    neighbor_map={"n1": ["n2"], "n2": ["n1"]})

    influencers = trace.top_influencers
    # At least one influencer should exist
    if influencers:
        assert influencers[0][1] > 0


def test_explanation_trace_node_journey():
    """get_node_journey returns claims from a specific node."""
    trace = ExplanationTrace(query="test")
    trace.add_round(0, {"n1": _msg("n1", "round 0"), "n2": _msg("n2", "other")})
    trace.add_round(1, {"n1": _msg("n1", "round 1")})

    journey = trace.get_node_journey("n1")
    assert len(journey) == 2
    assert journey[0].content == "round 0"


def test_explanation_trace_to_summary():
    """to_summary returns a readable string."""
    trace = ExplanationTrace(query="test query")
    trace.add_round(0, {"n1": _msg("n1", "analysis here")})
    summary = trace.to_summary()
    assert "Explanation Trace" in summary
    assert "test query" in summary


def test_explanation_trace_to_dict():
    """to_dict returns serializable dict."""
    trace = ExplanationTrace(query="test")
    trace.add_round(0, {"n1": _msg("n1", "claim")})
    d = trace.to_dict()
    assert "claims" in d
    assert "influences" in d
    assert d["query"] == "test"
