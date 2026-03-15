"""Tests for graqle.intelligence.governance.audit — Immutable Audit Trail."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_audit
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, pytest, audit
# constraints: none
# ── /graqle:intelligence ──

from pathlib import Path

from graqle.intelligence.governance.audit import (
    AuditEntry,
    AuditSession,
    AuditTrail,
)

# ── AuditEntry ──────────────────────────────────────────────────────


class TestAuditEntry:
    def test_creates_with_defaults(self):
        entry = AuditEntry(action="reason", tool="graq_reason", module="core.graph")
        assert entry.action == "reason"
        assert entry.tool == "graq_reason"
        assert entry.module == "core.graph"
        assert entry.timestamp  # auto-generated
        assert entry.entry_hash == ""
        assert entry.prev_hash == ""

    def test_compute_hash_deterministic(self):
        entry = AuditEntry(
            timestamp="2026-01-01T00:00:00",
            action="gate",
            tool="graq_gate",
            module="auth.middleware",
            input_summary="Check auth module",
            output_summary="Risk: HIGH",
            prev_hash="",
        )
        h1 = entry.compute_hash()
        h2 = entry.compute_hash()
        assert h1 == h2
        assert len(h1) == 16  # SHA-256 truncated to 16 hex chars

    def test_compute_hash_changes_with_content(self):
        entry1 = AuditEntry(
            timestamp="2026-01-01T00:00:00",
            action="gate",
            tool="graq_gate",
            module="auth",
        )
        entry2 = AuditEntry(
            timestamp="2026-01-01T00:00:00",
            action="gate",
            tool="graq_gate",
            module="core",  # different module
        )
        assert entry1.compute_hash() != entry2.compute_hash()

    def test_metadata_default_empty(self):
        entry = AuditEntry(action="learn")
        assert entry.metadata == {}

    def test_full_entry_fields(self):
        entry = AuditEntry(
            action="impact",
            tool="graq_impact",
            module="graqle.core",
            input_summary="What depends on core?",
            output_summary="12 modules depend on core",
            evidence_count=3,
            nodes_consulted=15,
            duration_ms=45.2,
            caller="claude-code",
            metadata={"provider": "anthropic"},
        )
        assert entry.evidence_count == 3
        assert entry.nodes_consulted == 15
        assert entry.duration_ms == 45.2
        assert entry.caller == "claude-code"


# ── AuditSession ────────────────────────────────────────────────────


class TestAuditSession:
    def test_creates_empty_session(self):
        session = AuditSession(session_id="test-001", task="Modify auth")
        assert session.session_id == "test-001"
        assert session.task == "Modify auth"
        assert session.status == "active"
        assert session.entry_count == 0
        assert session.total_nodes_consulted == 0
        assert session.total_evidence == 0

    def test_add_entry_sets_hash(self):
        session = AuditSession(session_id="s1", task="Test")
        entry = AuditEntry(action="reason", tool="graq_reason")
        result = session.add_entry(entry)
        assert result.entry_hash != ""
        assert result.prev_hash == ""  # first entry has no prev

    def test_add_entry_chains_hashes(self):
        session = AuditSession(session_id="s1", task="Test")

        e1 = session.add_entry(AuditEntry(action="gate"))
        e2 = session.add_entry(AuditEntry(action="reason"))
        e3 = session.add_entry(AuditEntry(action="impact"))

        assert e1.prev_hash == ""
        assert e2.prev_hash == e1.entry_hash
        assert e3.prev_hash == e2.entry_hash

    def test_verify_chain_valid(self):
        session = AuditSession(session_id="s1", task="Test")
        session.add_entry(AuditEntry(action="gate", timestamp="2026-01-01T00:00:00"))
        session.add_entry(AuditEntry(action="reason", timestamp="2026-01-01T00:01:00"))
        session.add_entry(AuditEntry(action="impact", timestamp="2026-01-01T00:02:00"))
        assert session.verify_chain() is True

    def test_verify_chain_detects_tamper(self):
        session = AuditSession(session_id="s1", task="Test")
        session.add_entry(AuditEntry(action="gate", timestamp="2026-01-01T00:00:00"))
        session.add_entry(AuditEntry(action="reason", timestamp="2026-01-01T00:01:00"))

        # Tamper with first entry
        session.entries[0].output_summary = "TAMPERED"
        assert session.verify_chain() is False

    def test_verify_chain_detects_broken_link(self):
        session = AuditSession(session_id="s1", task="Test")
        session.add_entry(AuditEntry(action="gate", timestamp="2026-01-01T00:00:00"))
        session.add_entry(AuditEntry(action="reason", timestamp="2026-01-01T00:01:00"))

        # Break the chain link
        session.entries[1].prev_hash = "0000000000000000"
        assert session.verify_chain() is False

    def test_verify_empty_chain(self):
        session = AuditSession(session_id="s1", task="Test")
        assert session.verify_chain() is True

    def test_complete_session(self):
        session = AuditSession(session_id="s1", task="Test")
        session.complete(drace_score=0.85)
        assert session.status == "completed"
        assert session.drace_score == 0.85

    def test_entry_count_and_totals(self):
        session = AuditSession(session_id="s1", task="Test")
        session.add_entry(AuditEntry(action="gate", nodes_consulted=5, evidence_count=2))
        session.add_entry(AuditEntry(action="reason", nodes_consulted=10, evidence_count=3))
        assert session.entry_count == 2
        assert session.total_nodes_consulted == 15
        assert session.total_evidence == 5


# ── AuditTrail (persistence) ───────────────────────────────────────


class TestAuditTrail:
    def test_start_session(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        session = trail.start_session("Modify core.graph", session_id="s1")
        assert session.session_id == "s1"
        assert session.task == "Modify core.graph"
        # File should exist
        fpath = tmp_path / ".graqle" / "governance" / "audit" / "s1.json"
        assert fpath.exists()

    def test_log_entry_persists(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        session = trail.start_session("Test task", session_id="s2")
        trail.log_entry(session, AuditEntry(action="gate", module="auth"))
        # Reload from disk
        loaded = trail.load_session("s2")
        assert loaded is not None
        assert loaded.entry_count == 1
        assert loaded.entries[0].action == "gate"

    def test_complete_session_persists(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        session = trail.start_session("Test", session_id="s3")
        trail.log_entry(session, AuditEntry(action="reason"))
        trail.complete_session(session, drace_score=0.9)
        loaded = trail.load_session("s3")
        assert loaded.status == "completed"
        assert loaded.drace_score == 0.9

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        assert trail.load_session("nonexistent") is None

    def test_list_sessions(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        trail.start_session("Task A", session_id="a")
        trail.start_session("Task B", session_id="b")
        trail.start_session("Task C", session_id="c")
        listing = trail.list_sessions()
        assert len(listing) == 3
        assert all("session_id" in s for s in listing)
        assert all("task" in s for s in listing)

    def test_list_sessions_empty(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        assert trail.list_sessions() == []

    def test_auto_generated_session_id(self, tmp_path: Path):
        trail = AuditTrail(tmp_path)
        session = trail.start_session("Auto ID test")
        assert session.session_id  # should be timestamp-based
        assert len(session.session_id) > 0

    def test_chain_integrity_after_reload(self, tmp_path: Path):
        """Chain integrity survives serialization round-trip."""
        trail = AuditTrail(tmp_path)
        session = trail.start_session("Integrity test", session_id="integrity")
        trail.log_entry(session, AuditEntry(action="gate", timestamp="2026-01-01T00:00:00"))
        trail.log_entry(session, AuditEntry(action="reason", timestamp="2026-01-01T00:01:00"))
        trail.log_entry(session, AuditEntry(action="verify", timestamp="2026-01-01T00:02:00"))

        loaded = trail.load_session("integrity")
        assert loaded.verify_chain() is True
