"""Tests for graqle.studio.routes.health — Health Streaks & Engagement API."""

# ── graqle:intelligence ──
# module: tests.test_studio.test_health_routes
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: json, dataclasses, datetime, pathlib, mock +4 more
# constraints: none
# ── /graqle:intelligence ──

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.health import router


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float = 1.0


def _build_mock_graph() -> MagicMock:
    nodes = {
        "auth": MockNode("auth", "Auth Service", "SERVICE", "Handles auth"),
        "db": MockNode("db", "Database", "DATABASE", "Main DB"),
        "api": MockNode("api", "API Gateway", "SERVICE", "Gateway"),
        "cache": MockNode("cache", "Redis Cache", "SERVICE", "Caching layer"),
    }
    edges = {
        "e1": MockEdge("auth", "db", "READS_FROM"),
        "e2": MockEdge("api", "auth", "CALLS"),
        "e3": MockEdge("api", "cache", "CALLS"),
        "e4": MockEdge("cache", "db", "READS_FROM"),
    }
    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    return graph


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def app_with_health(tmp_path: Path):
    """Create FastAPI app with health router and test data."""
    app = FastAPI()

    graqle_dir = tmp_path / ".graqle"
    audit_dir = graqle_dir / "governance" / "audit"
    intel_dir = graqle_dir / "intelligence"
    audit_dir.mkdir(parents=True)
    intel_dir.mkdir(parents=True)

    # Create audit sessions for streak data (spread over multiple days)
    today = datetime.now(timezone.utc)
    for i in range(5):
        d = today - timedelta(days=i)
        session = {
            "session_id": f"session-{i}",
            "started": d.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "task": f"Test session {i}",
            "status": "completed",
            "entries": [],
            "drace_score": 0.8,
        }
        fname = d.strftime("%Y%m%d_%H%M%S") + ".json"
        (audit_dir / fname).write_text(json.dumps(session), encoding="utf-8")

    # Create scorecard
    scorecard = {
        "health": "HEALTHY",
        "nodes": 100,
        "chunk_coverage": 85.0,
        "description_coverage": 90.0,
    }
    (graqle_dir / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")

    # Create module index with HIGH risk modules
    module_index = [
        {"module": "core.graph", "risk": "HIGH", "impact_radius": 26},
        {"module": "core.auth", "risk": "CRITICAL", "impact_radius": 15},
        {"module": "utils.helpers", "risk": "LOW", "impact_radius": 1},
    ]
    (intel_dir / "module_index.json").write_text(json.dumps(module_index), encoding="utf-8")

    app.state.studio_state = {"root": str(tmp_path), "graph": _build_mock_graph()}
    app.include_router(router, prefix="/health")

    return TestClient(app)


@pytest.fixture
def app_empty(tmp_path: Path):
    """App with empty .graqle dir."""
    app = FastAPI()
    (tmp_path / ".graqle").mkdir()
    app.state.studio_state = {"root": str(tmp_path)}
    app.include_router(router, prefix="/health")
    return TestClient(app)


# ── Streak Tests ────────────────────────────────────────────────────


class TestStreakEndpoint:
    def test_returns_calendar(self, app_with_health):
        r = app_with_health.get("/health/streak?days=30")
        assert r.status_code == 200
        data = r.json()
        assert "calendar" in data
        assert len(data["calendar"]) == 30
        assert data["period_days"] == 30

    def test_streak_count(self, app_with_health):
        r = app_with_health.get("/health/streak?days=30")
        data = r.json()
        # We created 5 consecutive days of sessions
        assert data["streak"] >= 1
        assert data["active_days"] >= 1
        assert data["total_sessions"] >= 1

    def test_calendar_day_format(self, app_with_health):
        r = app_with_health.get("/health/streak?days=7")
        data = r.json()
        for day in data["calendar"]:
            assert "date" in day
            assert "count" in day
            assert "level" in day
            assert 0 <= day["level"] <= 4

    def test_empty_audit_dir(self, app_empty):
        r = app_empty.get("/health/streak?days=7")
        data = r.json()
        assert data["streak"] == 0
        assert data["active_days"] == 0
        assert data["total_sessions"] == 0

    def test_days_validation(self, app_with_health):
        r = app_with_health.get("/health/streak?days=3")
        assert r.status_code == 422  # Below minimum of 7


# ── Suggestions Tests ───────────────────────────────────────────────


class TestSuggestionsEndpoint:
    def test_returns_suggestions(self, app_with_health):
        r = app_with_health.get("/health/suggestions")
        assert r.status_code == 200
        data = r.json()
        assert "suggestions" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_high_risk_modules_appear(self, app_with_health):
        r = app_with_health.get("/health/suggestions")
        suggestions = r.json()["suggestions"]
        ids = [s["id"] for s in suggestions]
        assert "risk-core.graph" in ids
        assert "risk-core.auth" in ids
        # LOW risk should not appear
        assert "risk-utils.helpers" not in ids

    def test_critical_before_high(self, app_with_health):
        r = app_with_health.get("/health/suggestions")
        suggestions = r.json()["suggestions"]
        # Find risk suggestions
        risk_suggestions = [s for s in suggestions if s["category"] == "risk"]
        if len(risk_suggestions) >= 2:
            critical_idx = next(
                (i for i, s in enumerate(risk_suggestions) if s["severity"] == "CRITICAL"), None
            )
            high_idx = next(
                (i for i, s in enumerate(risk_suggestions) if s["severity"] == "HIGH"), None
            )
            if critical_idx is not None and high_idx is not None:
                assert critical_idx < high_idx

    def test_coverage_suggestions(self, app_with_health):
        r = app_with_health.get("/health/suggestions")
        suggestions = r.json()["suggestions"]
        coverage_ids = [s["id"] for s in suggestions if s["category"] == "coverage"]
        # Chunk coverage is 85% (< 95%), should suggest improvement
        assert "coverage-chunks" in coverage_ids

    def test_limit_parameter(self, app_with_health):
        r = app_with_health.get("/health/suggestions?limit=1")
        data = r.json()
        assert len(data["suggestions"]) <= 1

    def test_empty_intelligence(self, app_empty):
        r = app_empty.get("/health/suggestions")
        data = r.json()
        assert data["suggestions"] == []
        assert data["total"] == 0

    def test_suggestion_fields(self, app_with_health):
        r = app_with_health.get("/health/suggestions")
        for s in r.json()["suggestions"]:
            assert "id" in s
            assert "category" in s
            assert "severity" in s
            assert "title" in s
            assert "description" in s
            assert "command" in s
            assert "priority" in s


# ── Impact Blast Radius Tests ───────────────────────────────────────


class TestImpactBlastRadius:
    def test_single_hop(self, app_with_health):
        r = app_with_health.get("/health/impact/api?hops=1")
        assert r.status_code == 200
        data = r.json()
        assert data["center"]["id"] == "api"
        assert data["hops"] == 1
        assert len(data["rings"]) == 1
        # api connects to auth and cache at hop 1
        hop1_ids = [n["id"] for n in data["rings"][0]]
        assert "auth" in hop1_ids
        assert "cache" in hop1_ids

    def test_two_hops(self, app_with_health):
        r = app_with_health.get("/health/impact/api?hops=2")
        data = r.json()
        assert len(data["rings"]) == 2
        # At hop 2, db should appear (through auth→db and cache→db)
        hop2_ids = [n["id"] for n in data["rings"][1]]
        assert "db" in hop2_ids

    def test_total_affected(self, app_with_health):
        r = app_with_health.get("/health/impact/api?hops=2")
        data = r.json()
        assert data["total_affected"] >= 3  # auth, cache, db

    def test_node_not_found(self, app_with_health):
        r = app_with_health.get("/health/impact/nonexistent?hops=1")
        data = r.json()
        assert "error" in data

    def test_leaf_node(self, app_with_health):
        # db has no outgoing connections beyond what we already traversed
        r = app_with_health.get("/health/impact/db?hops=1")
        data = r.json()
        assert data["center"]["id"] == "db"
        # db has incoming from auth and cache
        hop1_ids = [n["id"] for n in data["rings"][0]]
        assert len(hop1_ids) >= 1


# ── Edge Cases ──────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_governance_data(self, tmp_path: Path):
        """Empty .graqle dir with no governance data returns zeroed streak."""
        app = FastAPI()
        (tmp_path / ".graqle").mkdir()
        app.state.studio_state = {"root": str(tmp_path)}
        app.include_router(router, prefix="/health")
        client = TestClient(app)

        r = client.get("/health/streak?days=7")
        data = r.json()
        assert data["streak"] == 0
        assert data["active_days"] == 0
        assert data["total_sessions"] == 0

    def test_no_graph_for_impact(self, tmp_path: Path):
        app = FastAPI()
        (tmp_path / ".graqle").mkdir()
        app.state.studio_state = {"root": str(tmp_path)}
        app.include_router(router, prefix="/health")
        client = TestClient(app)

        r = client.get("/health/impact/some-node?hops=1")
        assert "error" in r.json()
