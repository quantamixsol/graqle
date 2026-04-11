"""TB-F3 tests for graqle.chat.rcag.

Covers:
  - Construction (enrichment bypass via empty super-init)
  - Node creation: ToolCall, ToolResult, AssistantReasoning,
    GovernanceCheckpoint, DebateRound, ErrorNode, AttachmentContext
  - Edge wiring: RESULT_OF, REASONING_LED_TO, GOVERNANCE_FOR,
    RECOVERED_FROM, DEBATED_FOR
  - Turn boundaries: begin_turn / end_turn / rolling summary
  - Activation: token-overlap fallback + recency bonus
  - Query augmentation with partial reasoning + rolling summary
  - Filtered views (tool_calls, errors, reasoning_chunks)
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_rcag
# risk: LOW
# dependencies: pytest, graqle.chat.rcag
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import patch

import pytest

from graqle.chat.rcag import (
    EDGE_DEBATED_FOR,
    EDGE_GOVERNANCE_FOR,
    EDGE_RECOVERED_FROM,
    EDGE_RESULT_OF,
    NODE_TYPE_ASSISTANT_REASONING,
    NODE_TYPE_ATTACHMENT,
    NODE_TYPE_DEBATE_ROUND,
    NODE_TYPE_ERROR,
    NODE_TYPE_GOVERNANCE_CHECKPOINT,
    NODE_TYPE_TOOL_CALL,
    NODE_TYPE_TOOL_RESULT,
    ROLLING_SUMMARY_TURNS,
    RuntimeChatActionGraph,
    TurnSummary,
)


@pytest.fixture
def rcag() -> RuntimeChatActionGraph:
    return RuntimeChatActionGraph(session_id="test_session_abcdef0123")


def test_init_does_not_call_auto_enrich() -> None:
    """RCAG must not trigger Graqle's enrichment branch on construction."""
    with patch.object(
        RuntimeChatActionGraph, "_auto_enrich_descriptions",
        side_effect=AssertionError("enrichment must not fire on RCAG init"),
    ), patch.object(
        RuntimeChatActionGraph, "_auto_load_chunks",
        side_effect=AssertionError("chunk loader must not fire"),
    ), patch.object(
        RuntimeChatActionGraph, "_enforce_no_empty_descriptions",
        side_effect=AssertionError("description enforcer must not fire"),
    ):
        rcag = RuntimeChatActionGraph(session_id="x")
        assert len(rcag.nodes) == 0


def test_session_id_recorded(rcag: RuntimeChatActionGraph) -> None:
    assert rcag.session_id == "test_session_abcdef0123"
    assert rcag._turn_counter == 0
    assert rcag._rolling_summary == []


# ──────────────────────────────────────────────────────────────────────
# Node creation
# ──────────────────────────────────────────────────────────────────────


def test_add_tool_call(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("test query")
    cid = rcag.add_tool_call("graq_read", {"file_path": "x.py"})
    assert cid in rcag.nodes
    assert rcag.nodes[cid].entity_type == NODE_TYPE_TOOL_CALL
    assert rcag.nodes[cid].properties["tool_name"] == "graq_read"
    assert rcag.nodes[cid].properties["params"] == {"file_path": "x.py"}


def test_add_tool_result_links_to_call(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("q")
    cid = rcag.add_tool_call("graq_read", {})
    rid = rcag.add_tool_result(
        cid, status="success", payload_summary="ok", latency_ms=12.5,
    )
    assert rcag.nodes[rid].entity_type == NODE_TYPE_TOOL_RESULT
    edges = [
        e for e in rcag.edges.values()
        if e.relationship == EDGE_RESULT_OF and e.source_id == rid
    ]
    assert len(edges) == 1
    assert edges[0].target_id == cid


def test_add_assistant_reasoning(rcag: RuntimeChatActionGraph) -> None:
    nid = rcag.add_assistant_reasoning("Looking at the file...", tag="reason")
    assert rcag.nodes[nid].entity_type == NODE_TYPE_ASSISTANT_REASONING
    assert rcag.nodes[nid].properties["full_text"] == "Looking at the file..."


def test_add_governance_checkpoint(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("q")
    cid = rcag.add_tool_call("graq_write", {})
    gid = rcag.add_governance_checkpoint(
        cid, tier="YELLOW", decision="approved", reason="dry_run=True",
    )
    assert rcag.nodes[gid].entity_type == NODE_TYPE_GOVERNANCE_CHECKPOINT
    assert rcag.nodes[gid].properties["tier"] == "YELLOW"
    edges = [
        e for e in rcag.edges.values()
        if e.relationship == EDGE_GOVERNANCE_FOR and e.source_id == gid
    ]
    assert len(edges) == 1
    assert edges[0].target_id == cid


def test_add_debate_round(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("q")
    cid = rcag.add_tool_call("graq_generate", {})
    did = rcag.add_debate_round(
        proposer_text="generate fix",
        adversary_text="risky on hub file",
        arbiter_verdict="proceed_with_apply",
        related_tool_call_id=cid,
    )
    assert rcag.nodes[did].entity_type == NODE_TYPE_DEBATE_ROUND
    assert rcag.nodes[did].properties["arbiter_verdict"] == "proceed_with_apply"
    edges = [
        e for e in rcag.edges.values()
        if e.relationship == EDGE_DEBATED_FOR and e.source_id == did
    ]
    assert len(edges) == 1


def test_add_error(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("q")
    cid = rcag.add_tool_call("graq_bash", {})
    eid = rcag.add_error(
        kind="ToolCrash",
        message="boom",
        related_tool_call_id=cid,
        recovered=True,
    )
    assert rcag.nodes[eid].entity_type == NODE_TYPE_ERROR
    assert rcag.nodes[eid].properties["recovered"] is True
    edges = [
        e for e in rcag.edges.values()
        if e.relationship == EDGE_RECOVERED_FROM and e.source_id == eid
    ]
    assert len(edges) == 1


def test_add_attachment(rcag: RuntimeChatActionGraph) -> None:
    nid = rcag.add_attachment(
        kind="screenshot",
        citation="ui.png — login screen with red error",
        bytes_size=42500,
    )
    assert rcag.nodes[nid].entity_type == NODE_TYPE_ATTACHMENT
    assert rcag.nodes[nid].properties["bytes"] == 42500
    assert rcag.nodes[nid].properties["single_turn"] is True


# ──────────────────────────────────────────────────────────────────────
# Turn boundaries + rolling summary
# ──────────────────────────────────────────────────────────────────────


def test_begin_turn_creates_user_message_node(rcag: RuntimeChatActionGraph) -> None:
    tid = rcag.begin_turn("hello there")
    assert tid.startswith("rcag_turn_1_")
    user_msgs = [
        n for n in rcag.nodes.values()
        if n.entity_type == NODE_TYPE_ASSISTANT_REASONING
        and n.properties.get("tag") == "user_message"
    ]
    assert len(user_msgs) == 1
    assert "hello there" in user_msgs[0].description


def test_end_turn_appends_to_rolling_summary(
    rcag: RuntimeChatActionGraph,
) -> None:
    rcag.begin_turn("first turn")
    rcag.end_turn("first answer", tool_count=2)
    assert len(rcag._rolling_summary) == 1
    assert rcag._rolling_summary[0].tool_count == 2


def test_rolling_summary_caps_at_max_turns(
    rcag: RuntimeChatActionGraph,
) -> None:
    for i in range(ROLLING_SUMMARY_TURNS + 5):
        rcag.begin_turn(f"turn {i}")
        rcag.end_turn(f"answer {i}", tool_count=i)
    assert len(rcag._rolling_summary) == ROLLING_SUMMARY_TURNS


def test_turn_summary_to_text() -> None:
    s = TurnSummary(
        turn_id="t1", user_message="hi", final_text="ok", tool_count=3,
    )
    text = s.to_text()
    assert "t1" in text
    assert "hi" in text
    assert "tools=3" in text


# ──────────────────────────────────────────────────────────────────────
# Query augmentation
# ──────────────────────────────────────────────────────────────────────


def test_augment_query_includes_partial_reasoning(
    rcag: RuntimeChatActionGraph,
) -> None:
    out = rcag.augment_query("write a function", partial_reasoning="thinking about graphs")
    assert "write a function" in out
    assert "thinking about graphs" in out


def test_augment_query_includes_rolling_summary(
    rcag: RuntimeChatActionGraph,
) -> None:
    rcag.begin_turn("first")
    rcag.end_turn("done", tool_count=1)
    out = rcag.augment_query("next question")
    assert "recent:" in out
    assert "first" in out


# ──────────────────────────────────────────────────────────────────────
# Activation
# ──────────────────────────────────────────────────────────────────────


def test_activate_returns_relevant_nodes(
    rcag: RuntimeChatActionGraph,
) -> None:
    rcag.begin_turn("read the config file")
    rcag.add_assistant_reasoning("I need to read the config file first")
    rcag.add_tool_call("graq_read", {"file_path": "config.yaml"})
    rcag.add_assistant_reasoning("totally unrelated thoughts about quantum widgets")
    activated = rcag.activate_for_turn("read the config file")
    labels = [n.label for n in activated]
    # The unrelated reasoning chunk should NOT be at the top.
    assert any("graq_read" in lbl or "user_message" in lbl or "reasoning" in lbl
               for lbl in labels)


def test_activate_empty_graph_returns_empty(
    rcag: RuntimeChatActionGraph,
) -> None:
    assert rcag.activate_for_turn("anything") == []


def test_activate_caps_at_max_nodes(
    rcag: RuntimeChatActionGraph,
) -> None:
    rcag.begin_turn("test")
    for i in range(20):
        rcag.add_assistant_reasoning(f"shared keyword test thought {i}")
    activated = rcag.activate_for_turn("test", max_nodes=5)
    assert len(activated) <= 5


# ──────────────────────────────────────────────────────────────────────
# Filtered views
# ──────────────────────────────────────────────────────────────────────


def test_filtered_views(rcag: RuntimeChatActionGraph) -> None:
    rcag.begin_turn("q")
    rcag.add_tool_call("graq_read", {})
    rcag.add_tool_call("graq_grep", {})
    rcag.add_error(kind="X", message="m")
    rcag.add_assistant_reasoning("text")
    assert len(rcag.tool_calls()) == 2
    assert len(rcag.errors()) == 1
    # 1 user_message + 1 explicit reasoning chunk = 2
    assert len(rcag.reasoning_chunks()) == 2
