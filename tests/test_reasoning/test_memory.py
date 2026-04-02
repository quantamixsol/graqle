"""Tests for reasoning memory subsystem — S2-15 through S2-19 (ADR-146).

Covers: TRACEScores, ProvenanceEntry decay/reverification/redaction,
ReasoningMemory store/decay_all/summary/MVCC/redundancy.
"""
from __future__ import annotations

import pytest

from graqle.core.memory_types import TRACEScores, ProvenanceEntry
from graqle.core.results import ToolResult
from graqle.core.types import ClearanceLevel
from graqle.reasoning.memory import ReasoningMemory


# ---------------------------------------------------------------------------
# Shared config (non-proprietary test values — TS-2 compliant)
# ---------------------------------------------------------------------------

_TEST_CONFIG: dict = {
    "EPISTEMIC_DECAY_LAMBDA": 0.9,
    "CONTRADICTION_PENALTY": 0.9,
    "REVERIFICATION_THRESHOLD": 0.5,
    "MEMORY_SUMMARY_MAX_CHARS": 100,
    "MEMORY_MIN_CONFIDENCE": 0.1,
}


def _make_entry(
    *,
    value: str = "test-value",
    confidence: float = 0.9,
    source_agent_id: str = "agent_a",
    round_stored: int = 0,
    round_verified: int = 0,
    node_id: str = "node_1",
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC,
    contradiction_count: int = 0,
    trace_scores: TRACEScores | None = None,
) -> ProvenanceEntry:
    return ProvenanceEntry(
        value=value,
        confidence=confidence,
        confidence_initial=confidence,
        source_agent_id=source_agent_id,
        round_stored=round_stored,
        round_verified=round_verified,
        node_id=node_id,
        clearance=clearance,
        contradiction_count=contradiction_count,
        trace_scores=trace_scores or TRACEScores(),
    )


def _make_memory(**overrides) -> ReasoningMemory:
    cfg = {**_TEST_CONFIG, **overrides}
    return ReasoningMemory(config=cfg)


# ===================================================================
# 1. TestTRACEScores
# ===================================================================


class TestTRACEScores:

    def test_default_zero(self):
        ts = TRACEScores()
        assert ts.total_gap == pytest.approx(0.0)
        assert ts.trace_score == pytest.approx(1.0)

    def test_total_gap(self):
        ts = TRACEScores(scg=0.1, pkc=0.2, dlt=0.05, adg=0.15, fsc=0.1)
        assert ts.total_gap == pytest.approx(0.6)

    def test_trace_score(self):
        ts = TRACEScores(scg=0.1, pkc=0.1, dlt=0.1, adg=0.1, fsc=0.1)
        assert ts.trace_score == pytest.approx(0.5)


# ===================================================================
# 2. TestProvenanceEntryDecay (S2-15)
# ===================================================================


class TestProvenanceEntryDecay:

    def test_no_decay_same_round(self):
        entry = _make_entry(confidence=0.95, round_verified=3)
        decayed = entry.decay(current_round=3, lambda_=0.9, contradiction_penalty=0.9)
        assert decayed == pytest.approx(0.95)

    def test_decay_over_rounds(self):
        c0 = 0.95
        entry = _make_entry(confidence=c0, round_verified=0)
        decayed = entry.decay(current_round=5, lambda_=0.9, contradiction_penalty=0.9)
        expected = c0 * (0.9 ** 5)
        assert decayed == pytest.approx(expected, rel=1e-6)

    def test_contradiction_penalty(self):
        c0 = 0.95
        entry = _make_entry(confidence=c0, round_verified=0, contradiction_count=2)
        decayed = entry.decay(current_round=3, lambda_=0.9, contradiction_penalty=0.8)
        expected = c0 * (0.9 ** 3) * (0.8 ** 2)
        assert decayed == pytest.approx(expected, rel=1e-6)

    def test_dlt_increases_on_decay(self):
        entry = _make_entry(confidence=0.95, round_verified=0)
        dlt_before = entry.trace_scores.dlt
        entry.decay(current_round=5, lambda_=0.9, contradiction_penalty=0.9)
        assert entry.trace_scores.dlt >= dlt_before

    def test_adg_increases_on_decay(self):
        entry = _make_entry(confidence=0.95, round_verified=0)
        adg_before = entry.trace_scores.adg
        entry.decay(current_round=5, lambda_=0.9, contradiction_penalty=0.9)
        assert entry.trace_scores.adg >= adg_before

    def test_dlt_capped_at_one(self):
        entry = _make_entry(confidence=0.95, round_verified=0)
        entry.decay(current_round=200, lambda_=0.5, contradiction_penalty=0.9)
        assert entry.trace_scores.dlt <= 1.0


# ===================================================================
# 3. TestProvenanceEntryReverification (S2-16)
# ===================================================================


class TestProvenanceEntryReverification:

    def test_above_threshold(self):
        entry = _make_entry(confidence=0.8)
        assert entry.needs_reverification(threshold=0.5) is False

    def test_below_threshold(self):
        entry = _make_entry(confidence=0.3)
        assert entry.needs_reverification(threshold=0.5) is True

    def test_at_threshold(self):
        entry = _make_entry(confidence=0.5)
        assert entry.needs_reverification(threshold=0.5) is False


# ===================================================================
# 4. TestProvenanceEntryRedaction (S2-17)
# ===================================================================


class TestProvenanceEntryRedaction:

    def test_public_sees_all(self):
        entry = _make_entry(value="open-data", clearance=ClearanceLevel.PUBLIC)
        redacted = entry.redacted_for(ClearanceLevel.PUBLIC)
        assert redacted.value == "open-data"

    def test_insufficient_clearance_redacted(self):
        entry = _make_entry(value="secret-info", clearance=ClearanceLevel.CONFIDENTIAL)
        redacted = entry.redacted_for(ClearanceLevel.PUBLIC)
        assert "REDACTED" in str(redacted.value).upper()

    def test_trace_visible_on_redaction(self):
        ts = TRACEScores(dlt=0.2)
        entry = _make_entry(
            value="secret", clearance=ClearanceLevel.CONFIDENTIAL, trace_scores=ts,
        )
        redacted = entry.redacted_for(ClearanceLevel.PUBLIC)
        assert redacted.trace_scores.dlt == pytest.approx(0.2)

    def test_restricted_entry_at_internal(self):
        entry = _make_entry(value="restricted-data", clearance=ClearanceLevel.RESTRICTED)
        redacted = entry.redacted_for(ClearanceLevel.INTERNAL)
        assert "REDACTED" in str(redacted.value).upper()


# ===================================================================
# 5. TestReasoningMemoryStore
# ===================================================================


class TestReasoningMemoryStore:

    def test_store_returns_key(self):
        mem = _make_memory()
        result = ToolResult.success(data="data", clearance=ClearanceLevel.PUBLIC)
        key = mem.store(
            round_num=1, node_id="node_x", result=result,
            confidence=0.9, source_agent_id="agent_a",
        )
        assert key == "agent_a:1/node_x"

    def test_contradiction_detection(self):
        mem = _make_memory()
        r1 = ToolResult.success(data="val-1", clearance=ClearanceLevel.PUBLIC)
        r2 = ToolResult.success(data="val-2", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=1, node_id="node_x", result=r1, confidence=0.9, source_agent_id="agent_a")
        mem.store(round_num=1, node_id="node_x", result=r2, confidence=0.8, source_agent_id="agent_b")
        # First agent's entry should have contradiction_count incremented
        entries = mem.get_weighted()
        node_x_entries = [e for e in entries if e.node_id == "node_x"]
        assert any(e.contradiction_count > 0 for e in node_x_entries)

    def test_clearance_inherited(self):
        mem = _make_memory()
        result = ToolResult.success(data="secret", clearance=ClearanceLevel.CONFIDENTIAL)
        key = mem.store(
            round_num=1, node_id="node_y", result=result,
            confidence=0.9, source_agent_id="agent_a",
        )
        entry = mem.get_weighted()[0]
        assert entry.clearance == ClearanceLevel.CONFIDENTIAL


# ===================================================================
# 6. TestReasoningMemoryDecayAll (S2-16)
# ===================================================================


class TestReasoningMemoryDecayAll:

    def test_decay_returns_reverification_keys(self):
        mem = _make_memory()
        result = ToolResult.success(data="old-data", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=0, node_id="node_s", result=result, confidence=0.6, source_agent_id="agent_a")
        stale_keys = mem.decay_all(current_round=50)
        assert any("node_s" in k for k in stale_keys)

    def test_fresh_entries_not_flagged(self):
        mem = _make_memory()
        result = ToolResult.success(data="fresh", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=5, node_id="node_f", result=result, confidence=0.9, source_agent_id="agent_a")
        stale_keys = mem.decay_all(current_round=5)
        assert not any("node_f" in k for k in stale_keys)


# ===================================================================
# 7. TestReasoningMemorySummary
# ===================================================================


class TestReasoningMemorySummary:

    def test_summary_is_markdown(self):
        mem = _make_memory()
        result = ToolResult.success(data="data", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=1, node_id="node_m", result=result, confidence=0.9, source_agent_id="agent_a")
        summary = mem.get_summary(viewer_clearance=ClearanceLevel.PUBLIC, current_round=1)
        assert summary.startswith("##")

    def test_summary_clearance_filtered(self):
        mem = _make_memory()
        result = ToolResult.success(data="classified", clearance=ClearanceLevel.CONFIDENTIAL)
        mem.store(round_num=1, node_id="node_c", result=result, confidence=0.9, source_agent_id="agent_a")
        summary = mem.get_summary(viewer_clearance=ClearanceLevel.PUBLIC, current_round=1)
        assert "REDACTED" in summary.upper()
        assert "classified" not in summary


# ===================================================================
# 8. TestReasoningMemoryMVCC (S2-18)
# ===================================================================


class TestReasoningMemoryMVCC:

    def test_snapshot_and_rollback(self):
        mem = _make_memory()
        r1 = ToolResult.success(data="first", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=1, node_id="n1", result=r1, confidence=0.9, source_agent_id="a")
        epoch = mem.snapshot()
        r2 = ToolResult.success(data="second", clearance=ClearanceLevel.PUBLIC)
        mem.store(round_num=2, node_id="n2", result=r2, confidence=0.8, source_agent_id="a")
        assert mem.entry_count == 2
        mem.rollback(epoch)
        assert mem.entry_count == 1

    def test_snapshot_cap(self):
        mem = _make_memory()
        for i in range(15):
            mem.snapshot()
        # Should be capped at 10
        assert len(mem._epochs) <= 10

    def test_merge_trace_wins(self):
        mem = _make_memory()
        key = "agent_a:1/node_x"
        existing = _make_entry(
            value="low-quality", trace_scores=TRACEScores(dlt=0.5, adg=0.3),
        )
        winner = _make_entry(
            value="high-quality", trace_scores=TRACEScores(),  # trace_score=1.0
        )
        mem._store[key] = existing
        mem.merge_concurrent([{key: winner}])
        assert mem._store[key].value == "high-quality"
        assert f"DISSENT:{key}" in mem._store


# ===================================================================
# 9. TestReasoningMemoryRedundancy (S2-19)
# ===================================================================


class TestReasoningMemoryRedundancy:

    def test_zero_redundancy(self):
        mem = _make_memory()
        assert mem.redundancy_rate({"a", "b", "c"}) == 0.0

    def test_full_redundancy(self):
        mem = _make_memory()
        for nid in ["a", "b", "c"]:
            r = ToolResult.success(data="x", clearance=ClearanceLevel.PUBLIC)
            mem.store(round_num=1, node_id=nid, result=r, confidence=0.9, source_agent_id="ag")
        assert mem.redundancy_rate({"a", "b", "c"}) == pytest.approx(1.0)

    def test_partial_redundancy(self):
        mem = _make_memory()
        for nid in ["a", "b"]:
            r = ToolResult.success(data="x", clearance=ClearanceLevel.PUBLIC)
            mem.store(round_num=1, node_id=nid, result=r, confidence=0.9, source_agent_id="ag")
        assert mem.redundancy_rate({"a", "b", "c", "d"}) == pytest.approx(0.5)


# ===================================================================
# 10. TestTS2ConfigEnforcement
# ===================================================================


class TestTS2ConfigEnforcement:
    """Verify ReasoningMemory enforces all 5 required config keys (TS-2)."""

    VALID_CONFIG = {
        "MEMORY_SUMMARY_MAX_CHARS": 500,
        "MEMORY_MIN_CONFIDENCE": 0.5,
        "EPISTEMIC_DECAY_LAMBDA": 0.1,
        "CONTRADICTION_PENALTY": 0.2,
        "REVERIFICATION_THRESHOLD": 0.8,
    }

    def test_missing_all_keys_raises(self):
        with pytest.raises(ValueError, match="requires config keys"):
            ReasoningMemory(config={})

    @pytest.mark.parametrize("missing_key", [
        "MEMORY_SUMMARY_MAX_CHARS",
        "MEMORY_MIN_CONFIDENCE",
        "EPISTEMIC_DECAY_LAMBDA",
        "CONTRADICTION_PENALTY",
        "REVERIFICATION_THRESHOLD",
    ])
    def test_missing_one_key_raises(self, missing_key):
        incomplete = {k: v for k, v in self.VALID_CONFIG.items() if k != missing_key}
        assert len(incomplete) == 4
        with pytest.raises(ValueError, match="requires config keys"):
            ReasoningMemory(config=incomplete)

    def test_all_keys_present_succeeds(self):
        memory = ReasoningMemory(config=self.VALID_CONFIG)
        assert memory is not None
