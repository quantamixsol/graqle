"""Tests for P1 debate governance components.

Covers: ClearanceLevel, DebateCostBudget, DebateCostGate,
ClearanceFilter, CitationValidator, DebateAuditEvent.
"""
from __future__ import annotations

import pytest

from graqle.core.types import ClearanceLevel, DebateCostBudget
from graqle.intelligence.governance.debate_cost_gate import (
    BudgetExhaustedError,
    DebateCostGate,
)
from graqle.intelligence.governance.debate_clearance import (
    ClearanceFilter,
    ClearanceViolationError,
)
from graqle.intelligence.governance.debate_citation import (
    CitationError,
    CitationValidator,
)
from graqle.intelligence.governance.audit import AuditEntry, DebateAuditEvent


# ---------------------------------------------------------------------------
# 1. ClearanceLevel enum
# ---------------------------------------------------------------------------


class TestClearanceLevel:

    def test_public_value(self):
        assert ClearanceLevel.PUBLIC == "public"

    def test_internal_value(self):
        assert ClearanceLevel.INTERNAL == "internal"

    def test_confidential_value(self):
        assert ClearanceLevel.CONFIDENTIAL == "confidential"

    def test_str_membership(self):
        assert "PUBLIC" in ClearanceLevel.__members__
        assert "INTERNAL" in ClearanceLevel.__members__
        assert "CONFIDENTIAL" in ClearanceLevel.__members__

    def test_all_three_distinct(self):
        levels = {ClearanceLevel.PUBLIC, ClearanceLevel.INTERNAL, ClearanceLevel.CONFIDENTIAL}
        assert len(levels) == 3

    def test_is_str_subclass(self):
        assert isinstance(ClearanceLevel.PUBLIC, str)


# ---------------------------------------------------------------------------
# 2. DebateCostBudget
# ---------------------------------------------------------------------------


class TestDebateCostBudget:

    def test_initial_state(self):
        b = DebateCostBudget(initial_budget=5.0)
        assert b._remaining == pytest.approx(5.0)
        assert b._round == 0
        assert b.exhausted is False

    def test_exhausted_when_zero(self):
        b = DebateCostBudget(initial_budget=0.0, decay_factor=0.75)
        assert b.exhausted is True

    def test_authorize_round_passes(self):
        b = DebateCostBudget(initial_budget=1.0, decay_factor=0.75)
        assert b.authorize_round(0.5) is True

    def test_authorize_round_fails_over_budget(self):
        b = DebateCostBudget(initial_budget=0.1, decay_factor=0.75)
        assert b.authorize_round(0.5) is False

    def test_authorize_round_fails_when_exhausted(self):
        b = DebateCostBudget(initial_budget=0.0, decay_factor=0.75)
        assert b.authorize_round(0.01) is False

    def test_record_spend_with_decay(self):
        b = DebateCostBudget(initial_budget=1.0, decay_factor=0.75)
        remaining = b.record_spend(0.25)
        expected = (1.0 - 0.25) * 0.75
        assert remaining == pytest.approx(expected)
        assert b._round == 1

    def test_multi_round_compounding(self):
        b = DebateCostBudget(initial_budget=1.0, decay_factor=0.75)
        r1 = b.record_spend(0.1)
        assert r1 == pytest.approx((1.0 - 0.1) * 0.75)
        r2 = b.record_spend(0.1)
        assert r2 == pytest.approx((r1 - 0.1) * 0.75)
        r3 = b.record_spend(0.1)
        assert r3 == pytest.approx((r2 - 0.1) * 0.75)
        assert r3 < r2 < r1

    def test_custom_decay_factor(self):
        b = DebateCostBudget(initial_budget=1.0, decay_factor=0.5)
        r = b.record_spend(0.2)
        assert r == pytest.approx((1.0 - 0.2) * 0.5)


# ---------------------------------------------------------------------------
# 3. DebateCostGate
# ---------------------------------------------------------------------------


class TestDebateCostGate:

    def test_check_round_passes(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=1.0, decay_factor=0.75))
        gate.check_round(0.1)  # should not raise

    def test_check_round_raises_when_exhausted(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=0.0, decay_factor=0.75))
        with pytest.raises(BudgetExhaustedError):
            gate.check_round(0.1)

    def test_check_round_raises_when_over_budget(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=0.05, decay_factor=0.75))
        with pytest.raises(BudgetExhaustedError):
            gate.check_round(0.1)

    def test_record_and_decay_returns_remaining(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=1.0, decay_factor=0.75))
        remaining = gate.record_and_decay(0.2)
        assert remaining == pytest.approx((1.0 - 0.2) * 0.75)

    def test_remaining_property(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=2.0, decay_factor=0.75))
        assert gate.remaining == pytest.approx(2.0)

    def test_current_round_starts_zero(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=1.0, decay_factor=0.75))
        assert gate.current_round == 0

    def test_current_round_increments(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=10.0, decay_factor=0.75))
        gate.record_and_decay(0.1)
        assert gate.current_round == 1
        gate.record_and_decay(0.1)
        assert gate.current_round == 2

    def test_exhausted_property(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=0.0, decay_factor=0.75))
        assert gate.exhausted is True

    def test_budget_exhausted_error_fields(self):
        gate = DebateCostGate(DebateCostBudget(initial_budget=0.0, decay_factor=0.75))
        with pytest.raises(BudgetExhaustedError) as exc_info:
            gate.check_round(0.01)
        assert exc_info.value.remaining_budget == pytest.approx(0.0)
        assert exc_info.value.round_number == 0


# ---------------------------------------------------------------------------
# 4. ClearanceFilter
# ---------------------------------------------------------------------------


class TestClearanceFilter:

    @pytest.fixture()
    def nodes(self):
        return [
            {"id": "n1", "clearance": "public", "data": "public info"},
            {"id": "n2", "clearance": "internal", "data": "internal info"},
            {"id": "n3", "clearance": "confidential", "data": "secret info"},
        ]

    def test_public_keeps_only_public(self, nodes):
        f = ClearanceFilter()
        result = f.filter_nodes(nodes, ClearanceLevel.PUBLIC)
        ids = [n["id"] for n in result]
        assert ids == ["n1"]

    def test_internal_keeps_public_and_internal(self, nodes):
        f = ClearanceFilter()
        result = f.filter_nodes(nodes, ClearanceLevel.INTERNAL)
        ids = [n["id"] for n in result]
        assert ids == ["n1", "n2"]

    def test_confidential_keeps_all(self, nodes):
        f = ClearanceFilter()
        result = f.filter_nodes(nodes, ClearanceLevel.CONFIDENTIAL)
        ids = [n["id"] for n in result]
        assert ids == ["n1", "n2", "n3"]

    def test_no_clearance_key_defaults_to_public(self):
        f = ClearanceFilter()
        nodes = [{"id": "x1", "data": "no clearance key"}]
        result = f.filter_nodes(nodes, ClearanceLevel.PUBLIC)
        assert len(result) == 1

    def test_get_effective_clearance_unknown_panelist(self):
        f = ClearanceFilter()
        level = f.get_effective_clearance("unknown", {})
        assert level is ClearanceLevel.PUBLIC

    def test_get_effective_clearance_known_panelist(self):
        f = ClearanceFilter()
        levels = {"admin": "confidential"}
        level = f.get_effective_clearance("admin", levels)
        assert level is ClearanceLevel.CONFIDENTIAL


# ---------------------------------------------------------------------------
# 5. CitationValidator
# ---------------------------------------------------------------------------


class TestCitationValidator:

    def test_valid_refs_pass(self):
        v = CitationValidator({"ref1", "ref2", "ref3"})
        assert v.validate(["ref1", "ref2"]) is True

    def test_invalid_refs_raise(self):
        v = CitationValidator({"ref1"})
        with pytest.raises(CitationError) as exc_info:
            v.validate(["ref1", "ref_unknown"])
        assert "ref_unknown" in exc_info.value.invalid_refs

    def test_empty_refs_required_raises(self):
        v = CitationValidator({"ref1"})
        with pytest.raises(CitationError, match="no evidence_refs"):
            v.validate([], require_citation=True)

    def test_empty_refs_not_required_passes(self):
        v = CitationValidator(set())
        assert v.validate([], require_citation=False) is True

    def test_node_count_property(self):
        v = CitationValidator({"a", "b", "c"})
        assert v.node_count == 3

    def test_citation_error_fields(self):
        v = CitationValidator({"ref1"})
        with pytest.raises(CitationError) as exc_info:
            v.validate(["ref1", "bad1", "bad2"])
        assert len(exc_info.value.invalid_refs) == 2
        assert exc_info.value.valid_count == 1


# ---------------------------------------------------------------------------
# 6. DebateAuditEvent
# ---------------------------------------------------------------------------


class TestDebateAuditEvent:

    def test_default_action(self):
        event = DebateAuditEvent()
        assert event.action == "debate"

    def test_inherits_audit_entry(self):
        assert issubclass(DebateAuditEvent, AuditEntry)

    def test_gate_decisions_default_empty(self):
        event = DebateAuditEvent()
        assert event.gate_decisions == {}

    def test_compute_hash_works(self):
        event = DebateAuditEvent()
        h = event.compute_hash()
        assert isinstance(h, str)
        assert len(h) > 0

    def test_debate_specific_fields(self):
        event = DebateAuditEvent(
            round_number=2,
            panelist="gpt-5.4",
            position="challenge",
            cost_usd=0.05,
            clearance_level="internal",
            branch_parent_id="parent-abc",
        )
        assert event.round_number == 2
        assert event.panelist == "gpt-5.4"
        assert event.position == "challenge"
        assert event.cost_usd == pytest.approx(0.05)
        assert event.clearance_level == "internal"
        assert event.branch_parent_id == "parent-abc"


# ---------------------------------------------------------------------------
# 7. ClearanceFilter — output clamping (R3 remediation)
# ---------------------------------------------------------------------------


class TestClearanceOutputClamping:
    """Prevent clearance laundering: CONFIDENTIAL -> PUBLIC."""

    def test_same_level_passes(self):
        f = ClearanceFilter()
        f.check_output_clearance(ClearanceLevel.PUBLIC, ClearanceLevel.PUBLIC)

    def test_lower_seen_passes(self):
        f = ClearanceFilter()
        f.check_output_clearance(ClearanceLevel.PUBLIC, ClearanceLevel.CONFIDENTIAL)

    def test_higher_seen_raises(self):
        f = ClearanceFilter()
        with pytest.raises(ClearanceViolationError):
            f.check_output_clearance(
                ClearanceLevel.CONFIDENTIAL, ClearanceLevel.PUBLIC,
            )

    def test_violation_error_fields(self):
        f = ClearanceFilter()
        with pytest.raises(ClearanceViolationError) as exc_info:
            f.check_output_clearance(
                ClearanceLevel.CONFIDENTIAL, ClearanceLevel.PUBLIC,
            )
        assert exc_info.value.max_seen is ClearanceLevel.CONFIDENTIAL
        assert exc_info.value.output_level is ClearanceLevel.PUBLIC

    def test_internal_to_public_raises(self):
        f = ClearanceFilter()
        with pytest.raises(ClearanceViolationError):
            f.check_output_clearance(
                ClearanceLevel.INTERNAL, ClearanceLevel.PUBLIC,
            )
