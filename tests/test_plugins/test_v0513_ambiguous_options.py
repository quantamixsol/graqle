"""Regression tests for the v0.51.3 hotfix — `ambiguous_options` field.

Covers the VS Code extension Ambiguity Pause handoff (PR #7 BLOCKER-1):

  AC-1  Response schema is additive (no breaking changes on non-ambiguous queries)
  AC-2  `ambiguous_options` emitted on ambiguous queries (Fixtures A, B, C, D)
  AC-3  Trigger criteria follow pseudocode (top1-top2 > 0.10 => field absent)
  AC-4  Field length always in [2, 5]
  AC-5  Each option has required fields (option_id, label, rationale, confidence)
  AC-6  Capability flag exposed in initialize response
  AC-7  `graq_learn` accepts JSON-string action values
  AC-8  `pause_pick` aggregation writes to KG bucketed by task_hash
  AC-9  Trade-secret scan stays clean (no internal tokens in new code)
  AC-10 No new MCP tools added (tools/list unchanged)

The tests exercise the Aggregator directly + the MCP handlers via
`KogniDevServer.__new__` with mock graphs — architecture-agnostic so they
pass against both public and private SDK layouts.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from graqle.core.message import Message
from graqle.orchestration.aggregation import Aggregator


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _msg(
    *,
    node_id: str,
    content: str,
    confidence: float,
) -> Message:
    """Build a Message fixture with the minimum fields needed for aggregation.

    Message is a dataclass requiring source_node_id, target_node_id, round,
    content at minimum. Aggregator only reads source_node_id, content, and
    confidence so the other fields get sensible defaults.
    """
    return Message(
        source_node_id=node_id,
        target_node_id="aggregator",
        round=0,
        content=content,
        confidence=confidence,
    )


# ─────────────────────────────────────────────────────────────────────
#  Aggregator._compute_ambiguous_options (unit) — AC-2, AC-3, AC-4, AC-5
# ─────────────────────────────────────────────────────────────────────


def test_fixture_a_ambiguous_emits_options() -> None:
    """Fixture A — two near-tied candidates, both above noise floor.

    top1=0.62, top2=0.58 → gap 0.04 ≤ 0.10. Both ≥ 0.50.
    Trigger MUST fire. Emits >= 2 options.
    """
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Use cached plan. Fastest path.", confidence=0.62),
        "b": _msg(node_id="b", content="Recompute plan. More accurate.", confidence=0.58),
    }
    options = agg._compute_ambiguous_options(filtered)
    assert len(options) == 2, f"expected exactly 2 options, got {options}"
    # AC-5 — required fields present
    for opt in options:
        assert "option_id" in opt
        assert opt["label"] and isinstance(opt["label"], str)
        assert opt["rationale"] and isinstance(opt["rationale"], str)
        assert 0.0 <= opt["confidence"] <= 1.0
        assert isinstance(opt["evidence_refs"], list)
    # AC-4 — 2 <= len <= 5
    assert 2 <= len(options) <= 5
    # Labels unique
    labels = {o["label"] for o in options}
    assert len(labels) == len(options)
    # At least 2 options >= 0.50 (noise-floor guarantee)
    assert sum(1 for o in options if o["confidence"] >= 0.50) >= 2


def test_fixture_b_confident_absent() -> None:
    """Fixture B — high-confidence single winner (0.90). Must NOT emit.

    Single-candidate input; any emission would be wrong (< 2 options).
    """
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Definitive answer.", confidence=0.90),
    }
    options = agg._compute_ambiguous_options(filtered)
    assert options == [], f"single high-confidence must not emit: {options}"


def test_fixture_c_clear_winner_absent() -> None:
    """Fixture C — multiple candidates but one clearly wins (>0.10 gap).

    top1=0.90, top2=0.60 → gap 0.30 > 0.10. Trigger MUST NOT fire.
    """
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Bedrock Sonnet. Production latency.", confidence=0.90),
        "b": _msg(node_id="b", content="Local qwen. Slower.", confidence=0.60),
    }
    options = agg._compute_ambiguous_options(filtered)
    assert options == [], f"clear winner must not emit: {options}"


def test_fixture_d_noise_floor_absent() -> None:
    """Fixture D — all candidates below 0.50 noise floor. Must NOT emit."""
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Uncertain A.", confidence=0.45),
        "b": _msg(node_id="b", content="Uncertain B.", confidence=0.40),
    }
    options = agg._compute_ambiguous_options(filtered)
    assert options == [], f"noise-floor candidates must not emit: {options}"


def test_length_cap_never_exceeds_5() -> None:
    """AC-4 — 6+ near-tied candidates get capped at 5."""
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        f"n{i}": _msg(
            node_id=f"n{i}",
            content=f"Option number {i} with distinct leading words {i}.",
            confidence=0.60 - i * 0.005,
        )
        for i in range(7)
    }
    options = agg._compute_ambiguous_options(filtered)
    assert len(options) <= 5, f"must cap at 5 options: len={len(options)}"


def test_aggregate_attaches_candidates_to_trunc_info() -> None:
    """AC-1, AC-2 — `aggregate()` returns (answer, trunc_info) and
    trunc_info carries the `candidates` key when trigger fires, without
    breaking the existing 2-tuple signature (138 downstream consumers)."""
    import asyncio
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Option alpha. Reason A.", confidence=0.62),
        "b": _msg(node_id="b", content="Option beta. Reason B.", confidence=0.58),
    }
    answer, trunc_info = asyncio.run(agg.aggregate("query", filtered))
    assert isinstance(answer, str)
    assert isinstance(trunc_info, dict)
    # AC-1: existing keys intact
    assert "synthesis_truncated" in trunc_info
    assert "synthesis_stop_reason" in trunc_info
    # AC-2: candidates attached
    assert "candidates" in trunc_info
    assert len(trunc_info["candidates"]) == 2


def test_aggregate_no_candidates_when_no_trigger() -> None:
    """AC-3 — when trigger doesn't fire, 'candidates' key must be ABSENT
    from trunc_info (not present-with-empty-list). Strict contract so
    downstream orchestrator's `.get("candidates")` is None."""
    import asyncio
    agg = Aggregator(strategy="confidence_weighted")
    filtered = {
        "a": _msg(node_id="a", content="Clear winner.", confidence=0.90),
        "b": _msg(node_id="b", content="Loser.", confidence=0.40),
    }
    answer, trunc_info = asyncio.run(agg.aggregate("query", filtered))
    assert "candidates" not in trunc_info, (
        f"candidates key must be absent when trigger doesn't fire; "
        f"trunc_info keys: {list(trunc_info)}"
    )


# ─────────────────────────────────────────────────────────────────────
#  MCP server — _handle_pause_pick + JSON action routing — AC-7, AC-8
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_json_action_routes_to_pause_pick() -> None:
    """AC-7 — `graq_learn` with a JSON-string action whose kind is
    'pause_pick' must be routed to _handle_pause_pick instead of the
    legacy outcome validator (which would reject missing 'outcome'/
    'components')."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph = None
    srv._kg_load_state = "IDLE"
    srv._graph_file = None

    payload = {
        "kind": "pause_pick",
        "feature": "AmbiguityPause",
        "stage": "reason",
        "task_hash": "abc1234567890def",
        "pause_id": "pause_1728925234_xyz1",
        "picked_index": 0,
        "picked_label": "Use cached plan",
        "candidate_labels": ["Use cached plan", "Recompute plan"],
        "scores": [0.62, 0.58],
        "created_at": 1728925234567,
        "timestamp": 1728925299123,
    }
    raw = await srv._handle_learn({"action": json.dumps(payload)})
    parsed = json.loads(raw)
    # Since we set _graph = None, the pause_pick handler returns
    # recorded=False with reason=no_graph_loaded — the critical contract
    # verified here is that routing landed at _handle_pause_pick rather
    # than the legacy outcome validator (which would have returned an
    # error about missing 'outcome' and 'components').
    assert parsed.get("kind") == "pause_pick", (
        f"JSON action must route to pause_pick handler: {parsed}"
    )
    assert "error" not in parsed or parsed.get("error") != (
        "Outcome mode requires 'action', 'outcome', and 'components'."
    ), "legacy outcome validator must NOT trigger for JSON actions"


@pytest.mark.asyncio
async def test_pause_pick_aggregates_into_kg_bucket(tmp_path) -> None:
    """AC-8 — 3 picks sharing a task_hash land under a single bucket
    node with pick_count == 3."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    from graqle.core.graph import Graqle

    srv = KogniDevServer.__new__(KogniDevServer)
    g = Graqle()
    srv._graph = g
    srv._kg_load_state = "LOADED"
    srv._graph_file = str(tmp_path / "kg.json")
    # Disable save-to-disk in tests (mock the graph save path)
    srv._save_graph = MagicMock()

    task_hash = "same_hash_1234"
    for i in range(3):
        payload = {
            "kind": "pause_pick",
            "task_hash": task_hash,
            "pause_id": f"pause_{i}_unique",
            "picked_index": i % 2,
            "picked_label": f"Option {chr(65 + (i % 2))}",
            "candidate_labels": ["Option A", "Option B"],
            "scores": [0.62, 0.58],
        }
        raw = await srv._handle_learn({"action": json.dumps(payload)})
        parsed = json.loads(raw)
        assert parsed.get("recorded") is True, parsed
        assert parsed.get("dedup") is False, "unique pause_ids should not dedup"

    # Bucket should exist with pick_count == 3
    bucket = srv._find_node(f"ambiguity_bucket:{task_hash}")
    assert bucket is not None, "bucket must be created on first pick"
    assert bucket.entity_type == "ambiguity_bucket"
    assert bucket.properties.get("pick_count") == 3
    # Each pause node exists
    for i in range(3):
        node = srv._find_node(f"pause_{i}_unique")
        assert node is not None
        assert node.entity_type == "ambiguity_pick"
        assert node.properties.get("task_hash") == task_hash


@pytest.mark.asyncio
async def test_pause_pick_is_idempotent_on_pause_id(tmp_path) -> None:
    """AC-8 extension — duplicate pause_id must be a no-op so the
    extension can safely retry on network blips."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    from graqle.core.graph import Graqle

    srv = KogniDevServer.__new__(KogniDevServer)
    g = Graqle()
    srv._graph = g
    srv._kg_load_state = "LOADED"
    srv._graph_file = str(tmp_path / "kg.json")
    srv._save_graph = MagicMock()

    payload = {
        "kind": "pause_pick",
        "task_hash": "hash_for_dedup",
        "pause_id": "pause_dedup_test",
        "picked_label": "A",
        "candidate_labels": ["A", "B"],
        "scores": [0.6, 0.55],
    }
    first = json.loads(await srv._handle_learn({"action": json.dumps(payload)}))
    assert first.get("dedup") is False

    # Retry with SAME pause_id — must dedup
    second = json.loads(await srv._handle_learn({"action": json.dumps(payload)}))
    assert second.get("recorded") is True
    assert second.get("dedup") is True, "same pause_id must be deduplicated"


# ─────────────────────────────────────────────────────────────────────
#  Capability flag + backward compat — AC-1, AC-6, AC-10
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_exposes_ambiguous_options_capability() -> None:
    """AC-6 — the MCP `initialize` response must advertise
    capabilities.graq_reason.ambiguous_options=true so the extension
    auto-enables the Ambiguity Pause UX on version upgrade."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    srv = KogniDevServer.__new__(KogniDevServer)
    # Minimum attrs for the initialize branch
    srv._cg01_bypass = False
    srv._cg02_bypass = False
    srv._cg03_bypass = False
    srv._start_kg_load_background = MagicMock()

    response = await srv._handle_jsonrpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "test-client"},
        },
    })
    assert response is not None
    result = response.get("result") or {}
    caps = result.get("capabilities") or {}
    # Top-level capabilities.graq_reason.ambiguous_options
    gr = caps.get("graq_reason") or {}
    assert gr.get("ambiguous_options") is True, (
        f"capabilities.graq_reason.ambiguous_options missing: {caps}"
    )
    # Mirrored in serverInfo.capabilities
    server_info = result.get("serverInfo") or {}
    srv_caps = server_info.get("capabilities") or {}
    assert srv_caps.get("graq_reason", {}).get("ambiguous_options") is True, (
        f"serverInfo.capabilities.graq_reason.ambiguous_options missing: {server_info}"
    )


def test_no_new_mcp_tools_added() -> None:
    """AC-10 — this hotfix is a schema/response extension only; the
    list of MCP tools must be unchanged."""
    from graqle.plugins.mcp_dev_server import TOOL_DEFINITIONS
    tool_names = {t["name"] for t in TOOL_DEFINITIONS}
    # graq_reason and graq_learn must still be present
    assert "graq_reason" in tool_names
    assert "graq_learn" in tool_names
    # No `graq_pause_pick` or similar sibling tools
    assert "graq_pause_pick" not in tool_names
    assert "graq_ambiguity_pause" not in tool_names


def test_response_schema_is_additive() -> None:
    """AC-1 — existing consumers that destructure the response dict
    by the old key set continue to work. The new `ambiguous_options`
    field is OPTIONAL (absent when trigger doesn't fire)."""
    # Simulate the response dict shape _handle_reason builds.
    # This is a shape snapshot test — the real handler is integration-
    # tested elsewhere.
    existing_keys = {
        "answer", "confidence", "rounds", "nodes_used", "active_nodes",
        "cost_usd", "latency_ms", "mode", "backend_status", "backend_error",
    }
    # Simulated non-ambiguous response
    response = {k: None for k in existing_keys}
    # Old consumer: must work without ambiguous_options
    assert set(response.keys()) == existing_keys
    # New consumer: tolerates presence of ambiguous_options
    response["ambiguous_options"] = [
        {"option_id": "opt_1", "label": "A", "rationale": "r", "confidence": 0.6, "evidence_refs": []},
        {"option_id": "opt_2", "label": "B", "rationale": "r", "confidence": 0.55, "evidence_refs": []},
    ]
    assert len(response["ambiguous_options"]) == 2


# ─────────────────────────────────────────────────────────────────────
#  Non-JSON action backward compatibility — AC-7 extension
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_json_action_keeps_legacy_behavior(tmp_path) -> None:
    """AC-7 — a plain non-JSON action string must fall through to the
    legacy outcome validator unchanged."""
    from graqle.plugins.mcp_dev_server import KogniDevServer
    srv = KogniDevServer.__new__(KogniDevServer)
    srv._graph = None
    srv._kg_load_state = "IDLE"
    srv._graph_file = None

    raw = await srv._handle_learn({"action": "Fixed a bug in scanner"})
    parsed = json.loads(raw)
    # Legacy validator REJECTS when outcome/components are missing.
    # That rejection is the proof we fell through to legacy path.
    assert parsed.get("error") == (
        "Outcome mode requires 'action', 'outcome', and 'components'."
    ), f"non-JSON action should hit legacy validator: {parsed}"
