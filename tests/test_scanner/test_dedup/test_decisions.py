"""Tests for user decision persistence."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_decisions
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, decisions
# constraints: none
# ── /graqle:intelligence ──

import json
from pathlib import Path

from graqle.scanner.dedup.decisions import DecisionStore, UserDecision


class TestDecisionStore:
    """Tests for DecisionStore."""

    def test_record_and_retrieve(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("node_a", "node_b", accepted=True, reason="confirmed match")

        assert store.has_decision("node_a", "node_b")
        decision = store.get_decision("node_a", "node_b")
        assert decision is not None
        assert decision.accepted is True
        assert decision.reason == "confirmed match"
        assert decision.timestamp != ""

    def test_symmetric_key(self, tmp_path):
        """Order of node_a/node_b doesn't matter."""
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("alpha", "beta", accepted=False)

        assert store.has_decision("beta", "alpha")
        decision = store.get_decision("beta", "alpha")
        assert decision is not None
        assert decision.accepted is False

    def test_persistence_across_instances(self, tmp_path):
        path = tmp_path / "decisions.json"
        store1 = DecisionStore(path)
        store1.record("a", "b", accepted=True, reason="same entity")

        # New instance loads from file
        store2 = DecisionStore(path)
        assert store2.has_decision("a", "b")
        decision = store2.get_decision("a", "b")
        assert decision.accepted is True
        assert decision.reason == "same entity"

    def test_all_decisions(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("a", "b", accepted=True)
        store.record("c", "d", accepted=False)

        all_dec = store.all_decisions()
        assert len(all_dec) == 2

    def test_clear(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("a", "b", accepted=True)
        store.clear()
        assert not store.has_decision("a", "b")
        assert store.all_decisions() == []

    def test_no_decision_returns_none(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        assert store.get_decision("x", "y") is None
        assert not store.has_decision("x", "y")

    def test_overwrite_decision(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("a", "b", accepted=True)
        store.record("a", "b", accepted=False, reason="changed mind")

        decision = store.get_decision("a", "b")
        assert decision.accepted is False
        assert decision.reason == "changed mind"

    def test_missing_file_no_error(self, tmp_path):
        path = tmp_path / "nonexistent" / "decisions.json"
        store = DecisionStore(path)
        assert store.all_decisions() == []

    def test_corrupt_file_handled(self, tmp_path):
        path = tmp_path / "decisions.json"
        path.write_text("not valid json", encoding="utf-8")
        store = DecisionStore(path)
        assert store.all_decisions() == []

    def test_json_format(self, tmp_path):
        path = tmp_path / "decisions.json"
        store = DecisionStore(path)
        store.record("node_x", "node_y", accepted=True, reason="test")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        key = list(data.keys())[0]
        assert data[key]["accepted"] is True
        assert data[key]["reason"] == "test"
