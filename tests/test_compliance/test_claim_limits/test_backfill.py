"""Tests for graqle.compliance.claim_limits.backfill (PR-010c)."""

from __future__ import annotations

import pytest

from graqle.compliance.claim_limits.backfill import (
    BACKFILL_SOURCE_KEY,
    BACKFILL_SOURCE_VALUE,
    BACKFILLED_AT_KEY,
    BackfillStats,
    backfill_graph,
    backfill_node,
)
from graqle.compliance.claim_limits.taxonomy import LEGACY_BACKFILL_VALUE


class FakeNode:
    """Minimal node shim matching the protocol backfill_node expects."""

    def __init__(self, entity_type: str, properties: dict | None = None, nid: str = "n1"):
        self.entity_type = entity_type
        self.properties = properties if properties is not None else {}
        self.id = nid


class FakeGraph:
    """Minimal graph shim with a .nodes dict-view."""

    def __init__(self, nodes: list[FakeNode]):
        self._nodes = {n.id: n for n in nodes}

    @property
    def nodes(self):
        return self._nodes


class TestBackfillNode:
    def test_wrong_entity_type_returns_none(self):
        n = FakeNode("RandomNode")
        assert backfill_node(n, dry_run=True) is None

    def test_already_compliant_left_untouched(self):
        n = FakeNode(
            "ResponseSnapshot",
            properties={"claim_limits": ["not_legal_advice"]},
        )
        result = backfill_node(n, dry_run=False)
        assert result == "already_compliant"
        # Properties unchanged
        assert n.properties["claim_limits"] == ["not_legal_advice"]
        assert BACKFILL_SOURCE_KEY not in n.properties

    def test_missing_claim_limits_backfilled_dry_run(self):
        n = FakeNode("ResponseSnapshot")
        result = backfill_node(n, dry_run=True)
        assert result == "backfilled"
        # Dry-run: properties NOT mutated
        assert "claim_limits" not in n.properties

    def test_missing_claim_limits_backfilled_live(self):
        n = FakeNode("ResponseSnapshot")
        result = backfill_node(n, dry_run=False)
        assert result == "backfilled"
        assert n.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]
        assert n.properties[BACKFILL_SOURCE_KEY] == BACKFILL_SOURCE_VALUE
        assert BACKFILLED_AT_KEY in n.properties

    def test_empty_claim_limits_backfilled(self):
        n = FakeNode("ResponseSnapshot", properties={"claim_limits": []})
        result = backfill_node(n, dry_run=False)
        assert result == "backfilled"
        assert n.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]

    def test_malformed_claim_limits_backfilled(self):
        # Non-string entries → treated as not yet compliant
        n = FakeNode("ResponseSnapshot", properties={"claim_limits": [1, 2, 3]})
        result = backfill_node(n, dry_run=False)
        assert result == "backfilled"
        assert n.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]

    def test_evidence_state_snapshot_eligible(self):
        n = FakeNode("EvidenceStateSnapshot")
        result = backfill_node(n, dry_run=False)
        assert result == "backfilled"

    def test_governance_bypass_eligible(self):
        n = FakeNode("GOVERNANCE_BYPASS")
        result = backfill_node(n, dry_run=False)
        assert result == "backfilled"

    def test_idempotent(self):
        # Running backfill twice on the same node leaves it stable.
        n = FakeNode("ResponseSnapshot")
        first = backfill_node(n, dry_run=False)
        second = backfill_node(n, dry_run=False)
        assert first == "backfilled"
        assert second == "already_compliant"
        # Audit markers from first pass survived.
        assert n.properties[BACKFILL_SOURCE_KEY] == BACKFILL_SOURCE_VALUE


class TestBackfillGraph:
    def test_mixed_graph_dry_run(self):
        graph = FakeGraph([
            FakeNode("ResponseSnapshot", nid="r1"),
            FakeNode("ResponseSnapshot", properties={"claim_limits": ["x-foo"]}, nid="r2"),
            FakeNode("RandomNode", nid="r3"),
            FakeNode("EvidenceStateSnapshot", nid="r4"),
        ])
        stats = backfill_graph(graph, dry_run=True)
        assert stats.total_scanned == 4
        assert stats.backfilled == 2  # r1, r4
        assert stats.already_compliant == 1  # r2
        assert stats.skipped_wrong_type == 1  # r3
        assert stats.errors == []

    def test_live_backfill_mutates_properties(self):
        n = FakeNode("ResponseSnapshot", nid="r1")
        graph = FakeGraph([n])
        backfill_graph(graph, dry_run=False)
        assert n.properties["claim_limits"] == [LEGACY_BACKFILL_VALUE]

    def test_graph_without_nodes_attr_raises(self):
        class BadGraph:
            pass
        with pytest.raises(ValueError, match="no .nodes attribute"):
            backfill_graph(BadGraph(), dry_run=True)

    def test_stats_as_dict(self):
        stats = BackfillStats(
            total_scanned=10,
            already_compliant=3,
            backfilled=5,
            skipped_wrong_type=2,
            errors=["x: oops"],
        )
        d = stats.as_dict()
        assert d == {
            "total_scanned": 10,
            "already_compliant": 3,
            "backfilled": 5,
            "skipped_wrong_type": 2,
            "errors": ["x: oops"],
        }

    def test_empty_graph_returns_zero_stats(self):
        graph = FakeGraph([])
        stats = backfill_graph(graph, dry_run=True)
        assert stats.total_scanned == 0
        assert stats.backfilled == 0
