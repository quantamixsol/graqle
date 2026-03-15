"""Tests for graqle.intelligence.governance.evidence — Evidence Chains."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_evidence
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, pytest, evidence
# constraints: none
# ── /graqle:intelligence ──

from pathlib import Path

from graqle.intelligence.governance.evidence import (
    DecisionRecord,
    EvidenceChain,
    EvidenceItem,
    EvidenceStore,
)

# ── EvidenceItem ────────────────────────────────────────────────────


class TestEvidenceItem:
    def test_creates_item(self):
        item = EvidenceItem(
            type="module_packet",
            source="graqle.core.graph",
            content="Risk: HIGH, Impact: 12 modules",
        )
        assert item.type == "module_packet"
        assert item.confidence == 1.0

    def test_custom_confidence(self):
        item = EvidenceItem(
            type="incident",
            source="auth",
            content="Past failure",
            confidence=0.7,
        )
        assert item.confidence == 0.7

    def test_metadata(self):
        item = EvidenceItem(
            type="kg_node",
            source="node-123",
            content="Graph node data",
            metadata={"node_type": "module"},
        )
        assert item.metadata["node_type"] == "module"


# ── DecisionRecord ──────────────────────────────────────────────────


class TestDecisionRecord:
    def test_creates_decision(self):
        d = DecisionRecord(
            decision_id="d1",
            action="modify",
            target="graqle.core.graph",
            reasoning="Graph module needs new edge type",
        )
        assert d.decision_id == "d1"
        assert d.outcome == "pending"
        assert d.risk_level == "LOW"
        assert d.evidence_count == 0
        assert d.is_evidenced is False

    def test_add_evidence(self):
        d = DecisionRecord(
            decision_id="d1",
            action="modify",
            target="auth",
            reasoning="Test",
        )
        d.add_evidence(EvidenceItem(type="module_packet", source="auth", content="Risk: LOW"))
        assert d.evidence_count == 1
        assert d.is_evidenced is False  # needs >= 2

        d.add_evidence(EvidenceItem(type="constraint", source="auth", content="Thread safe"))
        assert d.evidence_count == 2
        assert d.is_evidenced is True

    def test_decision_with_drace(self):
        d = DecisionRecord(
            decision_id="d1",
            action="approve",
            target="core",
            reasoning="Safe change",
            drace_score=0.85,
        )
        assert d.drace_score == 0.85


# ── EvidenceChain ───────────────────────────────────────────────────


class TestEvidenceChain:
    def test_creates_chain(self):
        chain = EvidenceChain(chain_id="c1", task="Modify auth middleware")
        assert chain.status == "active"
        assert chain.decision_count == 0
        assert chain.total_evidence == 0
        assert chain.evidence_ratio == 0.0

    def test_add_decisions(self):
        chain = EvidenceChain(chain_id="c1", task="Test")

        d1 = DecisionRecord(decision_id="d1", action="modify", target="auth", reasoning="Change needed")
        d1.add_evidence(EvidenceItem(type="module_packet", source="auth", content="Risk: LOW"))
        d1.add_evidence(EvidenceItem(type="constraint", source="auth", content="Thread safe"))

        d2 = DecisionRecord(decision_id="d2", action="approve", target="auth", reasoning="Approved")

        chain.add_decision(d1)
        chain.add_decision(d2)

        assert chain.decision_count == 2
        assert chain.total_evidence == 2
        assert chain.evidence_ratio == 0.5  # 1 of 2 decisions evidenced

    def test_complete_chain(self):
        chain = EvidenceChain(chain_id="c1", task="Test")
        chain.complete("Successfully modified auth module", drace_score=0.9)
        assert chain.status == "completed"
        assert chain.final_outcome == "Successfully modified auth module"
        assert chain.final_drace_score == 0.9

    def test_evidence_ratio_all_evidenced(self):
        chain = EvidenceChain(chain_id="c1", task="Test")
        for i in range(3):
            d = DecisionRecord(decision_id=f"d{i}", action="modify", target="x", reasoning="y")
            d.add_evidence(EvidenceItem(type="module_packet", source="x", content="a" * 20))
            d.add_evidence(EvidenceItem(type="constraint", source="x", content="b" * 20))
            chain.add_decision(d)
        assert chain.evidence_ratio == 1.0


# ── EvidenceStore (persistence) ─────────────────────────────────────


class TestEvidenceStore:
    def test_save_and_load(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        chain = EvidenceChain(chain_id="test-chain", task="Test persistence")
        d = DecisionRecord(decision_id="d1", action="create", target="new_module", reasoning="Needed")
        d.add_evidence(EvidenceItem(type="source_code", source="file.py", content="New module code"))
        chain.add_decision(d)

        store.save_chain(chain)
        loaded = store.load_chain("test-chain")

        assert loaded is not None
        assert loaded.chain_id == "test-chain"
        assert loaded.decision_count == 1
        assert loaded.decisions[0].evidence_count == 1

    def test_load_nonexistent(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        assert store.load_chain("nonexistent") is None

    def test_list_chains(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        for i in range(3):
            chain = EvidenceChain(chain_id=f"chain-{i}", task=f"Task {i}")
            store.save_chain(chain)

        listing = store.list_chains()
        assert len(listing) == 3
        assert all("chain_id" in c for c in listing)
        assert all("task" in c for c in listing)

    def test_list_chains_empty(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        assert store.list_chains() == []

    def test_build_evidence_from_gate(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        gate_result = {
            "module": "graqle.core.graph",
            "risk_level": "HIGH",
            "impact_radius": 12,
            "function_count": 8,
            "constraints": ["Thread safe", "No breaking changes"],
            "incidents": ["Graph corruption in v0.15"],
            "consumers": [
                {"module": "graqle.intelligence.pipeline"},
                {"module": "graqle.cli.main"},
                {"module": "graqle.plugins.mcp_dev_server"},
            ],
        }
        items = store.build_evidence_from_gate("core.graph", gate_result)
        assert len(items) >= 4  # packet + 2 constraints + 1 incident + consumers
        types = [i.type for i in items]
        assert "module_packet" in types
        assert "constraint" in types
        assert "incident" in types
        assert "impact_analysis" in types

    def test_build_evidence_from_gate_error(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        items = store.build_evidence_from_gate("x", {"error": "Not found"})
        assert items == []

    def test_build_evidence_from_gate_no_consumers(self, tmp_path: Path):
        store = EvidenceStore(tmp_path)
        gate_result = {
            "module": "leaf",
            "risk_level": "LOW",
            "impact_radius": 0,
            "function_count": 2,
            "constraints": [],
            "incidents": [],
            "consumers": [],
        }
        items = store.build_evidence_from_gate("leaf", gate_result)
        assert len(items) == 1  # just the module packet
        assert items[0].type == "module_packet"
