"""Tests for graqle.intelligence.governance.middleware — Governance Middleware."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_governance_middleware
# risk: HIGH (impact radius: 32 modules)
# consumers: sdk_self_audit, adaptive, reformulator, relevance, benchmark_runner +27 more
# dependencies: json, pathlib, pytest, middleware
# constraints: none
# ── /graqle:intelligence ──

import json
from pathlib import Path

from graqle.intelligence.governance.middleware import GovernanceMiddleware


class TestGovernanceMiddleware:
    def test_start_session(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Test task", session_id="test-001")
        assert session.session_id == "test-001"
        assert session.task == "Test task"
        assert session.status == "active"

    def test_get_or_start_session_reuses(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        s1 = gov.start_session("Task A", session_id="s1")
        s2 = gov.get_or_start_session("Task B")
        assert s1.session_id == s2.session_id  # reuses active session

    def test_get_or_start_session_creates_new_after_complete(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        s1 = gov.start_session("Task A", session_id="s1")
        gov.complete_session(s1)
        s2 = gov.get_or_start_session("Task B")
        assert s2.session_id != s1.session_id

    def test_log_tool_call(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Gate test", session_id="gate-001")

        result = {
            "module": "graqle.core.graph",
            "risk_level": "HIGH",
            "consumers": ["a", "b", "c"],
            "constraints": ["thread safe"],
            "incidents": [],
        }
        entry = gov.log_tool_call(
            session, "graq_gate",
            {"module": "core.graph", "action": "context"},
            result,
            duration_ms=15.5,
        )

        assert entry.action == "gate"
        assert entry.tool == "graq_gate"
        assert entry.module == "core.graph"
        assert entry.duration_ms == 15.5
        assert entry.evidence_count >= 4  # risk + 3 consumers + 1 constraint
        assert entry.entry_hash != ""

    def test_log_reason_call(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Reason test", session_id="reason-001")

        result = json.dumps({
            "answer": "The graph module manages the knowledge graph.",
            "confidence": 0.85,
            "nodes_used": 8,
        })
        entry = gov.log_tool_call(
            session, "graq_reason",
            {"question": "What does the graph module do?"},
            result,
            duration_ms=1200.0,
            nodes_consulted=8,
        )

        assert entry.action == "reason"
        assert entry.nodes_consulted == 8
        assert "Question:" in entry.input_summary

    def test_complete_session_with_drace(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("DRACE test", session_id="drace-001")

        # Log a complete entry
        gov.log_tool_call(
            session, "graq_gate",
            {"module": "auth"},
            {
                "risk_level": "HIGH",
                "consumers": ["login", "api"],
                "constraints": ["thread safe"],
                "incidents": [],
            },
            duration_ms=10.0,
        )

        drace_score = gov.complete_session(session)
        assert drace_score is not None
        assert 0.0 <= drace_score <= 1.0
        assert session.status == "completed"

    def test_complete_empty_session(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Empty", session_id="empty-001")
        drace = gov.complete_session(session)
        assert drace is None

    def test_chain_integrity_maintained(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Chain test", session_id="chain-001")

        for i in range(5):
            gov.log_tool_call(
                session, "graq_gate",
                {"module": f"module_{i}"},
                {"risk_level": "LOW"},
                duration_ms=5.0,
            )

        assert session.verify_chain() is True
        assert session.entry_count == 5

    def test_kogni_alias_mapping(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Alias test", session_id="alias-001")

        entry = gov.log_tool_call(
            session, "kogni_reason",
            {"question": "test"},
            {"answer": "ok"},
        )
        assert entry.action == "reason"  # kogni_ stripped

    def test_persistence_round_trip(self, tmp_path: Path):
        gov = GovernanceMiddleware(tmp_path)
        session = gov.start_session("Persist test", session_id="persist-001")
        gov.log_tool_call(
            session, "graq_gate",
            {"module": "core"},
            {"risk_level": "LOW"},
        )
        gov.complete_session(session)

        # Reload from disk
        from graqle.intelligence.governance.audit import AuditTrail
        trail = AuditTrail(tmp_path)
        loaded = trail.load_session("persist-001")
        assert loaded is not None
        assert loaded.status == "completed"
        assert loaded.entry_count == 1
        assert loaded.drace_score is not None
