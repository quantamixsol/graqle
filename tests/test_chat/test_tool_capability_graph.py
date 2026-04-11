"""TB-F2 tests for graqle.chat.tool_capability_graph.

Covers:
  - Seed loading + bootstrap counts
  - BLOCKER-1 enrichment-bypass regression test
  - BLOCKER-2 single-source-of-truth (no runtime augmentation)
  - activate_for_query: codegen → graq_generate near top of list
  - activate_for_query: convention_inference for write-new-artifact intent
  - MAJOR-3 probationary patterns filtered BEFORE scoring
  - MAJOR-2 destructive-edge safety filter
  - MAJOR-4 atomic save with .bak rollback
  - MAJOR-5 negative paths (corrupt JSON, missing seed, unwritable path)
  - MINOR-1 weight clamp [0.0, 10.0]
  - MINOR-2 probation thresholds (3 obs / 2 holdouts / 0.2 lift)
  - Reinforcement: success/failure deltas, intent reinforcement
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_tool_capability_graph
# risk: LOW (impact radius: 0)
# dependencies: pytest, pathlib, json, graqle.chat.tool_capability_graph
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.chat.tool_capability_graph import (
    EDGE_MATCHES_INTENT,
    EDGE_USED_AFTER,
    NODE_TYPE_INTENT,
    NODE_TYPE_LESSON,
    NODE_TYPE_TOOL,
    NODE_TYPE_WORKFLOW_PATTERN,
    PROBATION_MIN_HOLDOUTS,
    PROBATION_MIN_OBSERVATIONS,
    PROBATION_NOVELTY_LIFT_MIN,
    WEIGHT_MAX,
    WEIGHT_MIN,
    ToolCandidate,
    ToolCapabilityGraph,
    load_default_seed,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_tcg() -> ToolCapabilityGraph:
    """A TCG built from the packaged seed, no user file."""
    return ToolCapabilityGraph.from_seed()


@pytest.fixture
def tmp_user_path(tmp_path: Path) -> Path:
    return tmp_path / "tcg.json"


# ──────────────────────────────────────────────────────────────────────
# Seed loading
# ──────────────────────────────────────────────────────────────────────


def test_load_default_seed_returns_payload() -> None:
    payload = load_default_seed()
    assert "nodes" in payload
    assert "edges" in payload
    assert isinstance(payload["nodes"], dict)
    assert isinstance(payload["edges"], list)
    assert len(payload["nodes"]) > 30
    assert len(payload["edges"]) > 50


def test_load_default_seed_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_default_seed(tmp_path / "nope.json")


def test_load_default_seed_corrupt_payload_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        load_default_seed(bad)


def test_seed_node_counts(fresh_tcg: ToolCapabilityGraph) -> None:
    """Seed must contain ≥ 30 tools / 12 intents / 5 graduated workflows / 20 lessons."""
    assert len(fresh_tcg.tools()) >= 30
    assert len(fresh_tcg.intents()) >= 12
    grads = fresh_tcg.workflow_patterns(graduated_only=True)
    assert len(grads) >= 5
    assert len(fresh_tcg.lessons()) >= 20


# ──────────────────────────────────────────────────────────────────────
# BLOCKER-1: enrichment bypass
# ──────────────────────────────────────────────────────────────────────


def test_init_does_not_call_auto_enrich() -> None:
    """BLOCKER-1: TCG construction must NOT trigger Graqle's
    _auto_enrich_descriptions / _auto_load_chunks /
    _enforce_no_empty_descriptions branches.
    """
    with patch.object(
        ToolCapabilityGraph, "_auto_enrich_descriptions",
        side_effect=AssertionError("enrichment must not fire on TCG init"),
    ), patch.object(
        ToolCapabilityGraph, "_auto_load_chunks",
        side_effect=AssertionError("chunk loader must not fire on TCG init"),
    ), patch.object(
        ToolCapabilityGraph, "_enforce_no_empty_descriptions",
        side_effect=AssertionError("description enforcer must not fire on TCG init"),
    ):
        tcg = ToolCapabilityGraph.from_seed()
        # Sanity: still got the seed loaded.
        assert len(tcg.tools()) >= 30


# ──────────────────────────────────────────────────────────────────────
# BLOCKER-2: single source of truth (no runtime augmentation)
# ──────────────────────────────────────────────────────────────────────


def test_seed_is_only_source(fresh_tcg: ToolCapabilityGraph) -> None:
    """Tools that are NOT in the seed must NOT exist on a fresh TCG.

    The TCG bootstraps only from tcg_default.json. There is no
    list_tools() augmentation path. Future tools enter via
    reinforce_sequence learning, not via runtime discovery.
    """
    # Pick a plausible-but-not-seeded tool name.
    fake_tool = "tool_graq_imaginary_does_not_exist"
    assert fake_tool not in fresh_tcg.nodes


# ──────────────────────────────────────────────────────────────────────
# Activation
# ──────────────────────────────────────────────────────────────────────


def test_activate_codegen_returns_graq_generate_near_top(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """SDK-HF-01 structural fix: codegen intent activation must put
    graq_generate among the top 3 candidates.
    """
    result = fresh_tcg.activate_for_query(
        "write a Python function that returns graph statistics"
    )
    assert result.intent_id == "intent_codegen"
    labels = [c.label for c in result.candidates[:3]]
    assert "graq_generate" in labels, (
        f"expected graq_generate in top 3, got {labels}"
    )


def test_activate_write_new_artifact_uses_convention_inference(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Convention inference: 'write an ADR' intent activates the
    glob → read → write workflow pattern.
    """
    result = fresh_tcg.activate_for_query("please write an ADR for this decision")
    assert result.intent_id == "intent_write_new_artifact"
    assert result.workflow_pattern_id == "workflow_convention_inference"
    labels = [c.label for c in result.candidates[:5]]
    assert "graq_glob" in labels
    assert "graq_read" in labels
    assert "graq_write" in labels


def test_activate_unknown_intent_returns_empty(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    result = fresh_tcg.activate_for_query("zxcvbn random gibberish nothing matches")
    assert result.intent_id is None
    assert result.candidates == []


def test_activate_intent_hint_overrides_classification(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """When an explicit intent_hint is passed, it short-circuits
    keyword classification.
    """
    result = fresh_tcg.activate_for_query(
        "anything", intent_hint="intent_review",
    )
    assert result.intent_id == "intent_review"
    assert result.intent_confidence == 1.0


def test_activate_governance_tier_attached(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Each candidate carries its governance_tier so v4 can pre-disclose
    upfront.
    """
    result = fresh_tcg.activate_for_query(
        "write a Python function that returns graph statistics"
    )
    for c in result.candidates:
        assert c.governance_tier in {"GREEN", "YELLOW", "RED"}


# ──────────────────────────────────────────────────────────────────────
# MAJOR-3: probationary patterns filtered BEFORE scoring
# ──────────────────────────────────────────────────────────────────────


def test_probationary_pattern_invisible_to_activation(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Patterns with graduated=False must NOT influence activation."""
    # Mine a probationary candidate from observations.
    obs = [
        {"tool_sequence": ["tool_graq_inspect", "tool_graq_lessons"],
         "intent_id": "intent_audit", "support_files": ["a.py"], "success": True},
        {"tool_sequence": ["tool_graq_inspect", "tool_graq_lessons"],
         "intent_id": "intent_explain", "support_files": ["b.py"], "success": True},
        {"tool_sequence": ["tool_graq_inspect", "tool_graq_lessons"],
         "intent_id": "intent_review", "support_files": ["c.py"], "success": True},
    ]
    proposed = fresh_tcg.mine_workflow_patterns(obs)
    assert len(proposed) == 1
    cand_id = proposed[0]
    assert fresh_tcg.nodes[cand_id].properties["graduated"] is False
    # Activation for the audit intent must NOT route through the candidate.
    result = fresh_tcg.activate_for_query("audit this", intent_hint="intent_audit")
    assert result.workflow_pattern_id != cand_id


def test_graduate_pattern_promotes_to_visible(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    obs = [
        {"tool_sequence": ["tool_graq_grep", "tool_graq_read", "tool_graq_debug"],
         "intent_id": "intent_audit", "support_files": ["a.py"], "success": True},
        {"tool_sequence": ["tool_graq_grep", "tool_graq_read", "tool_graq_debug"],
         "intent_id": "intent_explain", "support_files": ["b.py"], "success": True},
        {"tool_sequence": ["tool_graq_grep", "tool_graq_read", "tool_graq_debug"],
         "intent_id": "intent_review", "support_files": ["c.py"], "success": True},
    ]
    proposed = fresh_tcg.mine_workflow_patterns(obs)
    assert len(proposed) == 1
    cand_id = proposed[0]
    ok = fresh_tcg.graduate_pattern(
        cand_id, holdout_successes=PROBATION_MIN_HOLDOUTS, novelty_lift=0.2,
    )
    assert ok is True
    assert fresh_tcg.nodes[cand_id].properties["graduated"] is True


def test_graduate_pattern_rejects_below_threshold(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    obs = [
        {"tool_sequence": ["tool_graq_glob", "tool_graq_grep"],
         "intent_id": f"i_{i}", "support_files": [f"f_{i}.py"], "success": True}
        for i in range(3)
    ]
    proposed = fresh_tcg.mine_workflow_patterns(obs)
    cand_id = proposed[0]
    # Below holdout threshold.
    assert fresh_tcg.graduate_pattern(cand_id, holdout_successes=1, novelty_lift=0.2) is False
    # Below novelty lift threshold.
    assert fresh_tcg.graduate_pattern(cand_id, holdout_successes=2, novelty_lift=0.05) is False


# ──────────────────────────────────────────────────────────────────────
# MAJOR-2: destructive-edge safety filter
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "destructive_label",
    ["graq_bash", "graq_write", "graq_git_commit", "graq_ingest", "graq_vendor", "graq_reload"],
)
def test_predict_blocks_destructive_targets(
    fresh_tcg: ToolCapabilityGraph,
    destructive_label: str,
) -> None:
    """Predicted edges must NEVER end at a destructive tool, regardless
    of support count. The filter runs DURING traversal, not after
    ranking.
    """
    suggestions = fresh_tcg.predict_missing_edges(
        min_confidence=0.0, max_suggestions=500,
    )
    for s in suggestions:
        target_node = fresh_tcg.nodes[s["target"]]
        assert target_node.label != destructive_label, (
            f"prediction surfaced destructive target {destructive_label}"
        )
        source_node = fresh_tcg.nodes[s["source"]]
        assert source_node.label != destructive_label, (
            f"prediction surfaced destructive source {destructive_label}"
        )


def test_is_safe_for_prediction_directly(fresh_tcg: ToolCapabilityGraph) -> None:
    """The safety helper itself rejects destructive tools."""
    assert fresh_tcg._is_safe_for_prediction("tool_graq_bash") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_write") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_git_commit") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_ingest") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_vendor") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_reload") is False
    assert fresh_tcg._is_safe_for_prediction("tool_graq_read") is True
    assert fresh_tcg._is_safe_for_prediction("tool_graq_generate") is True


def test_is_safe_unknown_returns_false(fresh_tcg: ToolCapabilityGraph) -> None:
    assert fresh_tcg._is_safe_for_prediction("nonexistent_tool") is False


# ──────────────────────────────────────────────────────────────────────
# MAJOR-4: atomic save + .bak rollback
# ──────────────────────────────────────────────────────────────────────


def test_save_creates_target_file(
    fresh_tcg: ToolCapabilityGraph, tmp_user_path: Path,
) -> None:
    fresh_tcg.save(tmp_user_path)
    assert tmp_user_path.exists()
    payload = json.loads(tmp_user_path.read_text(encoding="utf-8"))
    assert "nodes" in payload
    assert "edges" in payload


def test_save_creates_bak_on_second_write(
    fresh_tcg: ToolCapabilityGraph, tmp_user_path: Path,
) -> None:
    fresh_tcg.save(tmp_user_path)
    fresh_tcg.save(tmp_user_path)
    bak_path = tmp_user_path.with_suffix(tmp_user_path.suffix + ".bak")
    assert bak_path.exists()


def test_save_atomic_rollback_on_failure(
    fresh_tcg: ToolCapabilityGraph, tmp_user_path: Path,
) -> None:
    """If os.replace raises during the final swap, the original file
    must be restored from .bak.
    """
    fresh_tcg.save(tmp_user_path)
    original_bytes = tmp_user_path.read_bytes()

    # Mutate the in-memory TCG so the next save would change content.
    fresh_tcg.reinforce_sequence(
        ["tool_graq_context", "tool_graq_reason"], outcome="success",
    )

    # Force os.replace to fail on the final tmp → target swap. We need
    # the bak rotation to succeed but the second os.replace to raise.
    import os as _os
    real_replace = _os.replace
    call_count = {"n": 0}

    def flaky_replace(src, dst):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        # First call (rotate target → bak) succeeds
        # Second call (tmp → target) raises
        if call_count["n"] == 2:
            raise OSError("simulated swap failure")
        return real_replace(src, dst)

    with patch("graqle.chat.tool_capability_graph.os.replace", side_effect=flaky_replace):
        with pytest.raises(OSError):
            fresh_tcg.save(tmp_user_path)

    # After rollback the target file content must equal the original bytes.
    assert tmp_user_path.exists()
    assert tmp_user_path.read_bytes() == original_bytes


def test_save_without_path_raises(fresh_tcg: ToolCapabilityGraph) -> None:
    with pytest.raises(ValueError):
        fresh_tcg.save()


# ──────────────────────────────────────────────────────────────────────
# MAJOR-5: negative paths
# ──────────────────────────────────────────────────────────────────────


def test_load_or_init_creates_user_file(tmp_user_path: Path) -> None:
    assert not tmp_user_path.exists()
    tcg = ToolCapabilityGraph.load_or_init(user_path=tmp_user_path)
    assert tmp_user_path.exists()
    assert len(tcg.tools()) >= 30


def test_load_or_init_handles_corrupt_user_file(
    tmp_user_path: Path,
) -> None:
    tmp_user_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_user_path.write_text("not valid json {", encoding="utf-8")
    tcg = ToolCapabilityGraph.load_or_init(user_path=tmp_user_path)
    # File restored from seed.
    assert tmp_user_path.exists()
    assert len(tcg.tools()) >= 30
    # Original was backed up.
    corrupt = tmp_user_path.with_suffix(".corrupt")
    assert corrupt.exists()


def test_save_to_unwritable_path_raises(
    fresh_tcg: ToolCapabilityGraph, tmp_path: Path,
) -> None:
    """Save to a path whose parent doesn't exist creates parents.

    For a hard-fail case we point at a path that contains a NUL byte
    on Windows or an obviously bogus colon-only segment.
    """
    # Try a path that mkdir cannot create on any platform.
    bad = tmp_path / "\x00invalid" / "tcg.json"
    with pytest.raises((OSError, ValueError)):
        fresh_tcg.save(bad)


def test_round_trip_save_load(
    fresh_tcg: ToolCapabilityGraph, tmp_user_path: Path,
) -> None:
    """Save then load returns a graph with the same node/edge counts."""
    fresh_tcg.save(tmp_user_path)
    loaded = ToolCapabilityGraph.load_or_init(user_path=tmp_user_path)
    assert len(loaded.tools()) == len(fresh_tcg.tools())
    assert len(loaded.intents()) == len(fresh_tcg.intents())
    assert len(loaded.lessons()) == len(fresh_tcg.lessons())
    assert len(loaded.edges) == len(fresh_tcg.edges)


# ──────────────────────────────────────────────────────────────────────
# Reinforcement
# ──────────────────────────────────────────────────────────────────────


def test_reinforce_sequence_success_bumps_weight(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    # Find an existing USED_AFTER edge.
    edge = fresh_tcg._find_edge(
        "tool_graq_reason", "tool_graq_context", EDGE_USED_AFTER,
    )
    assert edge is not None
    before = edge.weight
    touched = fresh_tcg.reinforce_sequence(
        ["tool_graq_context", "tool_graq_reason"], outcome="success",
    )
    assert touched == 1
    assert edge.weight > before
    assert edge.weight <= WEIGHT_MAX


def test_reinforce_sequence_failure_decreases_weight(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    edge = fresh_tcg._find_edge(
        "tool_graq_reason", "tool_graq_context", EDGE_USED_AFTER,
    )
    assert edge is not None
    before = edge.weight
    fresh_tcg.reinforce_sequence(
        ["tool_graq_context", "tool_graq_reason"], outcome="failure",
    )
    assert edge.weight < before


def test_reinforce_sequence_clamps_to_max(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """MINOR-1: weight must clamp to WEIGHT_MAX even after many bumps."""
    for _ in range(200):
        fresh_tcg.reinforce_sequence(
            ["tool_graq_context", "tool_graq_reason"], outcome="success",
        )
    edge = fresh_tcg._find_edge(
        "tool_graq_reason", "tool_graq_context", EDGE_USED_AFTER,
    )
    assert edge is not None
    assert edge.weight <= WEIGHT_MAX


def test_reinforce_sequence_clamps_to_min(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """MINOR-1: weight must clamp to WEIGHT_MIN even after many failures."""
    for _ in range(500):
        fresh_tcg.reinforce_sequence(
            ["tool_graq_context", "tool_graq_reason"], outcome="failure",
        )
    edge = fresh_tcg._find_edge(
        "tool_graq_reason", "tool_graq_context", EDGE_USED_AFTER,
    )
    assert edge is not None
    assert edge.weight >= WEIGHT_MIN


def test_reinforce_sequence_creates_missing_edge(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """A reinforcement on an unseen pair creates a new edge."""
    # Pick two existing tools with no direct USED_AFTER edge.
    a, b = "tool_graq_inspect", "tool_graq_review"
    before = fresh_tcg._find_edge(b, a, EDGE_USED_AFTER)
    assert before is None
    fresh_tcg.reinforce_sequence([a, b], outcome="success")
    after = fresh_tcg._find_edge(b, a, EDGE_USED_AFTER)
    assert after is not None


def test_reinforce_intent_match_creates_or_bumps(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    ok = fresh_tcg.reinforce_intent_match(
        "intent_codegen", "tool_graq_generate", outcome="success",
    )
    assert ok is True
    edge = fresh_tcg._find_edge(
        "intent_codegen", "tool_graq_generate", EDGE_MATCHES_INTENT,
    )
    assert edge is not None


def test_reinforce_unknown_node_returns_false(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    assert fresh_tcg.reinforce_intent_match(
        "intent_unknown", "tool_graq_generate", outcome="success",
    ) is False


def test_reinforce_short_sequence_is_noop(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    assert fresh_tcg.reinforce_sequence([], outcome="success") == 0
    assert fresh_tcg.reinforce_sequence(["tool_graq_read"], outcome="success") == 0


# ──────────────────────────────────────────────────────────────────────
# Pattern mining edge cases
# ──────────────────────────────────────────────────────────────────────


def test_mine_empty_observations_returns_empty(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    assert fresh_tcg.mine_workflow_patterns([]) == []


def test_mine_filters_failures(fresh_tcg: ToolCapabilityGraph) -> None:
    obs = [
        {"tool_sequence": ["tool_graq_glob", "tool_graq_grep"],
         "intent_id": f"i_{i}", "support_files": [f"f_{i}.py"], "success": False}
        for i in range(5)
    ]
    proposed = fresh_tcg.mine_workflow_patterns(obs)
    assert proposed == []


def test_mine_filters_below_observation_threshold(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Below 3 unrelated observations → no candidate."""
    obs = [
        {"tool_sequence": ["tool_graq_glob", "tool_graq_grep"],
         "intent_id": "i_1", "support_files": ["a.py"], "success": True},
        {"tool_sequence": ["tool_graq_glob", "tool_graq_grep"],
         "intent_id": "i_2", "support_files": ["b.py"], "success": True},
    ]
    proposed = fresh_tcg.mine_workflow_patterns(obs)
    assert proposed == []


# ──────────────────────────────────────────────────────────────────────
# ToolCandidate / ActivationResult dataclasses
# ──────────────────────────────────────────────────────────────────────


def test_tool_candidate_to_dict() -> None:
    c = ToolCandidate(
        tool_id="t1", label="t1", score=1.5, governance_tier="GREEN",
        suggested_position=0, rationale="test",
    )
    d = c.to_dict()
    assert d["tool_id"] == "t1"
    assert d["score"] == 1.5
    assert d["governance_tier"] == "GREEN"


# ──────────────────────────────────────────────────────────────────────
# Round-1 remediation — MAJOR-R1 expanded seed + auto-create probationary
# ──────────────────────────────────────────────────────────────────────


def test_expanded_seed_includes_governance_tools(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Research MAJOR-R1: expanded seed must include governance tools
    so the ChatAgentLoop governance pre-disclosure property holds."""
    labels = {n.label for n in fresh_tcg.tools().values()}
    for required in (
        "graq_gov_gate",
        "graq_safety_check",
        "graq_audit",
        "graq_runtime",
    ):
        assert required in labels, f"governance tool missing: {required}"


def test_expanded_seed_includes_phantom_scorch_coverage(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Expanded seed should include phantom + scorch production tools."""
    labels = {n.label for n in fresh_tcg.tools().values()}
    phantom = sum(1 for lbl in labels if lbl.startswith("graq_phantom_"))
    scorch = sum(1 for lbl in labels if lbl.startswith("graq_scorch_"))
    assert phantom >= 8, f"expected 8+ phantom tools, got {phantom}"
    assert scorch >= 13, f"expected 13+ scorch tools, got {scorch}"


def test_expanded_seed_total_tool_count_at_least_60(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Expanded seed should cover 60+ tools (was 30 pre-Round-1)."""
    assert len(fresh_tcg.tools()) >= 60


def test_audit_intent_activates_governance_tools(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Research MAJOR-R1: `intent_audit` must now surface graq_gov_gate
    / graq_safety_check / graq_audit in its top candidates."""
    result = fresh_tcg.activate_for_query(
        "audit the governance trail on this module"
    )
    labels = [c.label for c in result.candidates[:6]]
    # At least one of the four governance tools should surface.
    governance_hits = [
        lbl for lbl in labels
        if lbl in {"graq_gov_gate", "graq_safety_check", "graq_audit", "graq_runtime"}
    ]
    assert len(governance_hits) >= 1, (
        f"no governance tool surfaced for audit intent: {labels}"
    )


def test_reinforce_sequence_auto_creates_unknown_probationary(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Research MAJOR-R1b: a tool_id observed in reinforcement that is
    NOT in the seed must be auto-created as a probationary YELLOW node
    with safe_for_prediction=False, not silently skipped.
    """
    unknown_a = "tool_graq_experimental_a"
    unknown_b = "tool_graq_experimental_b"
    assert unknown_a not in fresh_tcg.nodes
    assert unknown_b not in fresh_tcg.nodes

    touched = fresh_tcg.reinforce_sequence(
        [unknown_a, unknown_b], outcome="success",
    )
    assert touched >= 1
    # Both nodes must now exist.
    assert unknown_a in fresh_tcg.nodes
    assert unknown_b in fresh_tcg.nodes
    # And be marked probationary + non-predictable.
    node_a = fresh_tcg.nodes[unknown_a]
    assert node_a.properties.get("probation") is True
    assert node_a.properties.get("safe_for_prediction") is False
    assert node_a.properties.get("governance_tier") == "YELLOW"
    # And an edge must exist between them.
    edge = fresh_tcg._find_edge(unknown_b, unknown_a, "USED_AFTER")
    assert edge is not None


def test_auto_created_probationary_excluded_from_prediction(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Auto-created probationary tools must NOT surface in
    predict_missing_edges output (safe_for_prediction=False)."""
    probe = "tool_graq_brand_new_action"
    # Create it via reinforcement.
    fresh_tcg.reinforce_sequence(
        ["tool_graq_context", probe], outcome="success",
    )
    suggestions = fresh_tcg.predict_missing_edges(
        min_confidence=0.0, max_suggestions=500,
    )
    for s in suggestions:
        assert s["source"] != probe, (
            "probationary tool surfaced as prediction source"
        )
        assert s["target"] != probe, (
            "probationary tool surfaced as prediction target"
        )


def test_reinforce_still_ignores_non_tool_prefix_ids(
    fresh_tcg: ToolCapabilityGraph,
) -> None:
    """Auto-create only fires for tool_* prefixed ids so intent/
    workflow/lesson ids never accidentally become tools."""
    before = len(fresh_tcg.tools())
    # Use prefixes that neither exist in the seed nor start with tool_.
    touched = fresh_tcg.reinforce_sequence(
        ["custom_node_alpha", "custom_node_beta"], outcome="success",
    )
    # Non-tool_ ids are still silently skipped — no auto-create fires.
    assert touched == 0
    assert len(fresh_tcg.tools()) == before
    assert "custom_node_alpha" not in fresh_tcg.nodes
    assert "custom_node_beta" not in fresh_tcg.nodes


def test_activation_result_to_dict(fresh_tcg: ToolCapabilityGraph) -> None:
    result = fresh_tcg.activate_for_query("write a function")
    d = result.to_dict()
    assert "intent_id" in d
    assert "candidates" in d
    assert isinstance(d["candidates"], list)
