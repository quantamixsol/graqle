"""Tests for graqle.studio.routes.governance — Governance Dashboard API Routes."""

# ── graqle:intelligence ──
# module: tests.test_studio.test_governance_routes
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: hashlib, json, pathlib, pytest, fastapi +2 more
# constraints: none
# ── /graqle:intelligence ──

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.governance import router


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def app_with_governance(tmp_path: Path):
    """Create a FastAPI app with governance router and test data."""
    app = FastAPI()

    # Set up .graqle directory with test governance data
    graqle_dir = tmp_path / ".graqle"
    audit_dir = graqle_dir / "governance" / "audit"
    evidence_dir = graqle_dir / "governance" / "evidence"
    audit_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)

    # Create a completed audit session with hash chain
    entries = _build_chain_entries([
        {"action": "gate", "tool": "graq_gate", "module": "core.graph",
         "input_summary": "Module: core.graph", "output_summary": "Risk: HIGH",
         "evidence_count": 4, "nodes_consulted": 3, "duration_ms": 12.5},
        {"action": "reason", "tool": "graq_reason", "module": "core.graph",
         "input_summary": "Question: What does graph do?", "output_summary": "The graph module manages the knowledge graph with 51 functions.",
         "evidence_count": 2, "nodes_consulted": 8, "duration_ms": 1200.0},
        {"action": "gate", "tool": "graq_gate", "module": "auth.middleware",
         "input_summary": "Module: auth.middleware", "output_summary": "Risk: MEDIUM, thread safe",
         "evidence_count": 3, "nodes_consulted": 2, "duration_ms": 8.0},
    ])

    session_data = {
        "session_id": "test-session-001",
        "started": "2026-03-15T10:00:00+00:00",
        "task": "Test governance session",
        "status": "completed",
        "entries": entries,
        "drace_score": 0.82,
    }
    (audit_dir / "test-session-001.json").write_text(json.dumps(session_data), encoding="utf-8")

    # Create an active (incomplete) session
    active_session = {
        "session_id": "test-session-002",
        "started": "2026-03-15T11:00:00+00:00",
        "task": "Active session",
        "status": "active",
        "entries": [entries[0]],
        "drace_score": None,
    }
    (audit_dir / "test-session-002.json").write_text(json.dumps(active_session), encoding="utf-8")

    # Create an evidence chain
    evidence_chain = {
        "chain_id": "test-chain-001",
        "task": "Build governance layer",
        "started": "2026-03-15T09:00:00+00:00",
        "decisions": [
            {
                "decision_id": "d1",
                "timestamp": "2026-03-15T09:00:00+00:00",
                "action": "create",
                "target": "governance.audit",
                "reasoning": "Need audit trail for compliance",
                "agent": "claude",
                "evidence": [
                    {"type": "module_packet", "source": "audit", "content": "Risk: LOW", "confidence": 1.0, "metadata": {}},
                    {"type": "constraint", "source": "audit", "content": "immutable entries", "confidence": 1.0, "metadata": {}},
                ],
                "outcome": "approved",
                "risk_level": "LOW",
                "drace_score": None,
            },
            {
                "decision_id": "d2",
                "timestamp": "2026-03-15T09:05:00+00:00",
                "action": "create",
                "target": "governance.drace",
                "reasoning": "Need DRACE scoring",
                "agent": "claude",
                "evidence": [
                    {"type": "module_packet", "source": "drace", "content": "Risk: LOW", "confidence": 1.0, "metadata": {}},
                ],
                "outcome": "approved",
                "risk_level": "LOW",
                "drace_score": None,
            },
        ],
        "status": "completed",
        "final_outcome": "Governance layer built successfully",
        "final_drace_score": 0.9,
    }
    (evidence_dir / "test-chain-001.json").write_text(json.dumps(evidence_chain), encoding="utf-8")

    # Mount router
    app.state.studio_state = {"root": str(tmp_path)}
    app.include_router(router, prefix="/studio/api/governance")

    return TestClient(app)


def _build_chain_entries(raw_entries: list[dict]) -> list[dict]:
    """Build entries with proper SHA-256 hash chain."""
    entries = []
    prev_hash = ""
    for raw in raw_entries:
        entry = {
            "timestamp": raw.get("timestamp", "2026-03-15T10:00:00+00:00"),
            "action": raw["action"],
            "tool": raw.get("tool", ""),
            "module": raw.get("module", ""),
            "input_summary": raw.get("input_summary", ""),
            "output_summary": raw.get("output_summary", ""),
            "evidence_count": raw.get("evidence_count", 0),
            "nodes_consulted": raw.get("nodes_consulted", 0),
            "duration_ms": raw.get("duration_ms", 0.0),
            "caller": "",
            "metadata": {},
            "prev_hash": prev_hash,
            "entry_hash": "",
        }
        # Compute hash
        content = json.dumps({
            "timestamp": entry["timestamp"],
            "action": entry["action"],
            "tool": entry["tool"],
            "module": entry["module"],
            "input_summary": entry["input_summary"],
            "output_summary": entry["output_summary"],
            "prev_hash": entry["prev_hash"],
        }, sort_keys=True)
        entry["entry_hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        prev_hash = entry["entry_hash"]
        entries.append(entry)
    return entries


# ── DRACE Endpoints ──────────────────────────────────────────────────


class TestDRACECurrent:
    def test_returns_current_drace(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/drace/current")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == "test-session-001"
        assert data["drace_score"] == 0.82
        assert data["grade"] == "GOOD"
        assert "pillars" in data
        assert set(data["pillars"].keys()) == {"D", "R", "A", "C", "E"}

    def test_pillars_are_floats(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/drace/current")
        pillars = r.json()["pillars"]
        for key in "DRACE":
            assert isinstance(pillars[key], (int, float))
            assert 0.0 <= pillars[key] <= 1.0


class TestDRACEHistory:
    def test_returns_history(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/drace/history")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 2
        # Both sessions present, sorted by filename (reverse)
        ids = [s["session_id"] for s in sessions]
        assert "test-session-001" in ids
        assert "test-session-002" in ids

    def test_limit_parameter(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/drace/history?limit=1")
        assert len(r.json()["sessions"]) == 1


# ── Audit Endpoints ──────────────────────────────────────────────────


class TestAuditSessions:
    def test_list_sessions(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/audit/sessions")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 2
        # Check fields
        for s in sessions:
            assert "session_id" in s
            assert "task" in s
            assert "status" in s
            assert "entry_count" in s

    def test_session_detail(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/audit/session/test-session-001")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == "test-session-001"
        assert len(data["entries"]) == 3
        assert data["status"] == "completed"

    def test_session_not_found(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/audit/session/nonexistent")
        assert r.status_code == 404


class TestChainVerification:
    def test_valid_chain(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/audit/verify/test-session-001")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_valid"] is True
        assert data["entry_count"] == 3
        for entry in data["entries"]:
            assert entry["hash_valid"] is True
            assert entry["chain_valid"] is True

    def test_tampered_chain_detected(self, app_with_governance, tmp_path: Path):
        """Tamper with a session and verify detection."""
        audit_path = tmp_path / ".graqle" / "governance" / "audit" / "test-session-001.json"
        data = json.loads(audit_path.read_text())
        # Tamper: change output_summary of entry 1
        data["entries"][1]["output_summary"] = "TAMPERED DATA"
        audit_path.write_text(json.dumps(data))

        r = app_with_governance.get("/studio/api/governance/audit/verify/test-session-001")
        result = r.json()
        assert result["chain_valid"] is False
        # Entry 1 should have invalid hash
        assert result["entries"][1]["hash_valid"] is False

    def test_verify_not_found(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/audit/verify/nonexistent")
        assert r.status_code == 404


# ── Evidence Chain Endpoints ─────────────────────────────────────────


class TestEvidenceChains:
    def test_list_chains(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/evidence/chains")
        assert r.status_code == 200
        chains = r.json()["chains"]
        assert len(chains) == 1
        chain = chains[0]
        assert chain["chain_id"] == "test-chain-001"
        assert chain["decision_count"] == 2
        assert chain["total_evidence"] == 3
        assert chain["evidence_ratio"] == 0.5  # 1 of 2 decisions has >= 2 evidence

    def test_chain_detail(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/evidence/chain/test-chain-001")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_id"] == "test-chain-001"
        assert len(data["decisions"]) == 2
        assert data["final_drace_score"] == 0.9
        # First decision has 2 evidence items
        assert len(data["decisions"][0]["evidence"]) == 2
        # Second decision has 1
        assert len(data["decisions"][1]["evidence"]) == 1

    def test_chain_not_found(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/evidence/chain/nonexistent")
        assert r.status_code == 404


# ── Badge Endpoint ───────────────────────────────────────────────────


class TestBadge:
    def test_badge_svg(self, app_with_governance):
        r = app_with_governance.get("/studio/api/governance/badge.svg")
        assert r.status_code == 200
        assert "image/svg+xml" in r.headers["content-type"]
        assert "<svg" in r.text
        assert "DRACE" in r.text
        assert "0.82" in r.text
        assert "GOOD" in r.text

    def test_badge_without_data(self, tmp_path: Path):
        """Badge renders even without governance data."""
        app = FastAPI()
        # Create an empty .graqle dir so fallback doesn't find the real one
        (tmp_path / ".graqle").mkdir()
        app.state.studio_state = {"root": str(tmp_path)}
        app.include_router(router, prefix="/studio/api/governance")
        client = TestClient(app)

        r = client.get("/studio/api/governance/badge.svg")
        assert r.status_code == 200
        assert "0.00" in r.text
        assert "N/A" in r.text


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_governance_data(self, tmp_path: Path):
        """Endpoints gracefully handle .graqle dir with no governance data."""
        app = FastAPI()
        (tmp_path / ".graqle").mkdir()
        app.state.studio_state = {"root": str(tmp_path)}
        app.include_router(router, prefix="/gov")
        client = TestClient(app)

        assert "error" in client.get("/gov/drace/current").json()
        assert client.get("/gov/audit/sessions").json()["sessions"] == []
        assert client.get("/gov/evidence/chains").json()["chains"] == []

    def test_empty_audit_dir(self, tmp_path: Path):
        """Empty audit directory returns empty lists."""
        app = FastAPI()
        (tmp_path / ".graqle" / "governance" / "audit").mkdir(parents=True)
        app.state.studio_state = {"root": str(tmp_path)}
        app.include_router(router, prefix="/gov")
        client = TestClient(app)

        assert client.get("/gov/drace/current").json().get("error") is not None
        assert client.get("/gov/drace/history").json()["sessions"] == []
        assert client.get("/gov/audit/sessions").json()["sessions"] == []
