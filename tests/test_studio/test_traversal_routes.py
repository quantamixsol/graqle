"""Tests for graqle.studio.routes.traversal — Neo4j Traversal API.

Tests against mock traversal engine (no Neo4j required).
"""

# ── graqle:intelligence ──
# module: tests.test_studio.test_traversal_routes
# risk: LOW (impact radius: 0 modules)
# dependencies: dataclasses, mock, pytest, fastapi, testclient +1 more
# constraints: none
# ── /graqle:intelligence ──

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.traversal import router

# ── Mock Traversal Engine ────────────────────────────────────────────


def _mock_traversal():
    t = MagicMock()

    t.shortest_path.return_value = {
        "found": True,
        "source": "a",
        "target": "b",
        "hops": 2,
        "path": [
            {"id": "a", "label": "A", "type": "SERVICE"},
            {"id": "mid", "label": "Mid", "type": "SERVICE"},
            {"id": "b", "label": "B", "type": "SERVICE"},
        ],
        "edge_types": ["RELATED_TO", "RELATED_TO"],
    }

    t.hub_nodes.return_value = [
        {"id": "hub1", "label": "Hub 1", "type": "SERVICE", "degree": 50},
        {"id": "hub2", "label": "Hub 2", "type": "MODULE", "degree": 30},
    ]

    t.node_context.return_value = {
        "found": True,
        "id": "n1",
        "label": "Node 1",
        "type": "SERVICE",
        "description": "Test node",
        "properties": {},
        "neighbors": [{"id": "n2", "label": "Node 2", "type": "MODULE", "relationship": "RELATED_TO"}],
    }

    t.impact_bfs.return_value = [
        {"id": "affected1", "label": "Affected", "type": "MODULE", "depth": 1, "risk": "medium"},
    ]

    t.materialize_neighborhoods.return_value = 100

    return t


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def app_with_traversal():
    app = FastAPI()
    app.state.studio_state = {"neo4j_traversal": _mock_traversal()}
    app.include_router(router, prefix="/traversal")
    return TestClient(app)


@pytest.fixture
def app_without_traversal():
    app = FastAPI()
    app.state.studio_state = {}
    app.include_router(router, prefix="/traversal")
    return TestClient(app)


# ── Shortest Path Tests ─────────────────────────────────────────────


class TestShortestPathRoute:
    def test_finds_path(self, app_with_traversal):
        r = app_with_traversal.get("/traversal/shortest-path?source=a&target=b")
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True
        assert data["hops"] == 2

    def test_no_traversal_engine(self, app_without_traversal):
        r = app_without_traversal.get("/traversal/shortest-path?source=a&target=b")
        data = r.json()
        assert "error" in data


# ── Hub Nodes Tests ──────────────────────────────────────────────────


class TestHubNodesRoute:
    def test_returns_hubs(self, app_with_traversal):
        r = app_with_traversal.get("/traversal/hubs?top_k=10")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        assert data[0]["degree"] == 50

    def test_no_engine(self, app_without_traversal):
        r = app_without_traversal.get("/traversal/hubs")
        assert "error" in r.json()


# ── Node Context Tests ───────────────────────────────────────────────


class TestNodeContextRoute:
    def test_returns_context(self, app_with_traversal):
        r = app_with_traversal.get("/traversal/context/n1")
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True
        assert data["id"] == "n1"

    def test_no_engine(self, app_without_traversal):
        r = app_without_traversal.get("/traversal/context/n1")
        assert "error" in r.json()


# ── Impact Analysis Tests ────────────────────────────────────────────


class TestImpactRoute:
    def test_returns_impact(self, app_with_traversal):
        r = app_with_traversal.get("/traversal/impact/n1?max_depth=2&change_type=modify")
        assert r.status_code == 200
        data = r.json()
        assert data["affected_count"] == 1
        assert data["overall_risk"] == "low"

    def test_no_engine(self, app_without_traversal):
        r = app_without_traversal.get("/traversal/impact/n1")
        assert "error" in r.json()


# ── Materialize Tests ────────────────────────────────────────────────


class TestMaterializeRoute:
    def test_materialize(self, app_with_traversal):
        r = app_with_traversal.post("/traversal/materialize?max_hops=2")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "materialized"
        assert data["nodes_with_neighborhoods"] == 100
