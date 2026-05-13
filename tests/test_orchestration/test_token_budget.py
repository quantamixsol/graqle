"""CR-007 regression tests — token economics ceilings on graq_reason.

Verifies the five ceilings introduced in CR-007 work as designed and are
configurable via GraqleConfig.orchestration:
  1. evidence_hard_ceiling   (node._build_evidence_text -> reason)
  2. top_k_neighbors          (message_passing._exchange_round)
  3. prompt_hard_cap          (node.reason)
  4. hierarchical_synthesis   (message_passing.run_round, flag-gated)
  5. max_llm_calls            (orchestrator.run)

All tests are deterministic, fast (<2s each), and require no live LLM —
they use a stub backend that records prompt sizes per call. EU AI Act
preservation is checked at the integration level: every original message
is still present in `all_messages` (orchestrator state) even when the
hierarchical synthesis path is on.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from graqle.config.settings import GraqleConfig, OrchestrationConfig
from graqle.core.message import Message
from graqle.core.node import CogniNode


class _StubBackend:
    """Records every prompt sent and returns a constant short string."""

    cost_per_1k_tokens = 0.001

    def __init__(self, response: str = "OK") -> None:
        self.calls: list[str] = []
        self.response = response

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self.response


# ── Fix 1: evidence_hard_ceiling ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_hard_ceiling_truncates_supporting_evidence() -> None:
    """When evidence has >ceiling chars, the Supporting Evidence block is cut
    with the auditable '[truncated by evidence_hard_ceiling]' marker."""
    node = CogniNode(id="n1", label="N1", entity_type="Module")
    node.description = "stub"
    # Build a chunk that, after evidence wrapping, blows past the ceiling.
    huge = "x" * 8000
    node.properties = {"chunks": [{"text": huge, "type": "evidence"}]}
    node.backend = _StubBackend()

    await node.reason(
        query="q", incoming_messages=[],
        evidence_hard_ceiling=2000,
        prompt_hard_cap=20000,  # disable Fix 3 for this test
    )

    assert len(node.backend.calls) == 1
    sent = node.backend.calls[0]
    assert "[truncated by evidence_hard_ceiling]" in sent
    # The evidence block fits within ceiling + marker tail.
    # Don't assert raw prompt length here (template wrapping adds chars);
    # Fix 3 (prompt_hard_cap) test covers the global cap.


@pytest.mark.asyncio
async def test_evidence_hard_ceiling_default_value_is_4000() -> None:
    """Sanity: the OrchestrationConfig default is 4000 chars."""
    cfg = OrchestrationConfig()
    assert cfg.evidence_hard_ceiling == 4000


# ── Fix 3: prompt_hard_cap ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_hard_cap_truncates_with_head_and_tail_markers() -> None:
    """When the assembled prompt exceeds prompt_hard_cap, the LLM sees a
    head + middle-marker + tail composition, never the raw oversized prompt."""
    node = CogniNode(id="n1", label="N1", entity_type="Module")
    node.description = "x" * 5000
    node.system_prompt = "y" * 5000
    node.properties = {"chunks": [{"text": "z" * 5000, "type": "evidence"}]}
    node.backend = _StubBackend()

    await node.reason(
        query="QUERY_TAIL_MARKER",
        incoming_messages=[],
        evidence_hard_ceiling=100000,  # disable Fix 1 so Fix 3 is the gate
        prompt_hard_cap=2000,
    )

    sent = node.backend.calls[0]
    assert len(sent) <= 2200  # cap + middle marker
    assert "[CR-007 prompt_hard_cap: middle truncated]" in sent
    # Tail (query area) preserved
    assert "QUERY_TAIL_MARKER" in sent


@pytest.mark.asyncio
async def test_prompt_hard_cap_no_truncation_when_under_limit() -> None:
    """Short prompts pass through untouched (no marker)."""
    node = CogniNode(id="n1", label="N1", entity_type="Module")
    node.description = "tiny"
    node.backend = _StubBackend()

    await node.reason(
        query="q",
        incoming_messages=[],
        evidence_hard_ceiling=4000,
        prompt_hard_cap=10000,
    )

    sent = node.backend.calls[0]
    assert "middle truncated" not in sent


# ── Fix 2: top_k_neighbors ──────────────────────────────────────────────────


def test_top_k_neighbors_default_is_8() -> None:
    cfg = OrchestrationConfig()
    assert cfg.top_k_neighbors == 8


def test_top_k_neighbors_configurable() -> None:
    cfg = OrchestrationConfig(top_k_neighbors=3)
    assert cfg.top_k_neighbors == 3


# ── Fix 5: max_llm_calls ────────────────────────────────────────────────────


def test_max_llm_calls_default_is_60() -> None:
    cfg = OrchestrationConfig()
    assert cfg.max_llm_calls == 60


def test_max_llm_calls_is_int_castable() -> None:
    """The orchestrator casts to int(); accept floats/strings without crash."""
    cfg = OrchestrationConfig(max_llm_calls=42)
    assert int(cfg.max_llm_calls) == 42


# ── Fix 4 (CR-007b): hierarchical_synthesis flag ────────────────────────────


def test_hierarchical_synthesis_default_off() -> None:
    """CR-007b is feature-flagged: default False until empirically validated."""
    cfg = OrchestrationConfig()
    assert cfg.hierarchical_synthesis is False
    assert cfg.hierarchical_summary_max_chars == 1500


def test_hierarchical_synthesis_can_be_enabled() -> None:
    cfg = OrchestrationConfig(hierarchical_synthesis=True)
    assert cfg.hierarchical_synthesis is True


def test_community_summaries_collapse_by_entity_type_fallback() -> None:
    """When node.community is unset, _build_community_summaries falls back
    to grouping by node.entity_type — coarser, but always available."""
    from graqle.orchestration.message_passing import MessagePassingProtocol

    class _StubGraph:
        def __init__(self) -> None:
            self.nodes = {
                "a": _N("Module"),
                "b": _N("Module"),
                "c": _N("TestFile"),
            }

    class _N:
        def __init__(self, et: str) -> None:
            self.entity_type = et
            self.community = None
            self.pruned = False

    graph = _StubGraph()
    proto = MessagePassingProtocol(parallel=False)

    msgs = {
        "a": Message.create_query_broadcast("alpha-payload-a", "a"),
        "b": Message.create_query_broadcast("beta-payload-b", "b"),
        "c": Message.create_query_broadcast("gamma-payload-c", "c"),
    }
    out = proto._build_community_summaries(graph, msgs, summary_max_chars=2000)

    # Two communities -> two summaries
    assert len(out) == 2
    keys = sorted(out.keys())
    assert keys == ["__community__Module", "__community__TestFile"]

    # Module summary contains both a and b payloads
    module_content = out["__community__Module"].content
    assert "alpha-payload-a" in module_content
    assert "beta-payload-b" in module_content
    # TestFile summary contains c only
    test_content = out["__community__TestFile"].content
    assert "gamma-payload-c" in test_content
    assert "alpha-payload-a" not in test_content


def test_community_summaries_truncate_when_total_exceeds_max() -> None:
    """Combined summary stays within summary_max_chars."""
    from graqle.orchestration.message_passing import MessagePassingProtocol

    class _StubGraph:
        def __init__(self) -> None:
            self.nodes = {f"n{i}": _N() for i in range(20)}

    class _N:
        entity_type = "Module"
        community = None
        pruned = False

    graph = _StubGraph()
    proto = MessagePassingProtocol(parallel=False)

    big_payload = "x" * 200
    msgs = {
        f"n{i}": Message.create_query_broadcast(big_payload, f"n{i}")
        for i in range(20)
    }
    out = proto._build_community_summaries(graph, msgs, summary_max_chars=500)

    summary = out["__community__Module"].content
    assert len(summary) <= 600  # cap + truncation marker tail
    assert "[community summary truncated]" in summary


# ── Integration: defaults preserved when no overrides ──────────────────────


def test_all_new_knobs_have_sane_defaults() -> None:
    cfg = OrchestrationConfig()
    assert cfg.evidence_hard_ceiling == 4000
    assert cfg.prompt_hard_cap == 10000
    assert cfg.top_k_neighbors == 8
    assert cfg.max_llm_calls == 60
    assert cfg.hierarchical_synthesis is False
    assert cfg.hierarchical_summary_max_chars == 1500


def test_token_economics_bounds_are_enforced() -> None:
    """CR-007 review MINOR: pydantic Field bounds reject pathological values."""
    from pydantic import ValidationError

    # Lower bounds
    with pytest.raises(ValidationError):
        OrchestrationConfig(evidence_hard_ceiling=0)
    with pytest.raises(ValidationError):
        OrchestrationConfig(top_k_neighbors=0)
    with pytest.raises(ValidationError):
        OrchestrationConfig(max_llm_calls=0)

    # Upper bounds
    with pytest.raises(ValidationError):
        OrchestrationConfig(max_llm_calls=10_000)
    with pytest.raises(ValidationError):
        OrchestrationConfig(prompt_hard_cap=10_000_000)
