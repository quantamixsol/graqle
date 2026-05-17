"""Tests for graqle.studio.routes.api::graph_visualization — SF-05 size guard.

Module: graqle.studio.routes.api
Risk: LOW (test-only module, no consumers)

Covers CR-011 SF-05 fix: response-size guard preventing AWS Lambda
6 MB synchronous-response cap from triggering HTTP 502 on large KGs.
"""

# ── graqle:intelligence ──
# module: tests.test_studio.test_graph_visualization_routes
# risk: LOW (impact radius: 0 modules)
# constraints: none
# ── /graqle:intelligence ──

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graqle.studio.routes.api import router


# ── Mocks ────────────────────────────────────────────────────────────


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


def _make_app(graph) -> FastAPI:
    """Build a FastAPI app with studio_state containing the given graph."""
    app = FastAPI()
    app.include_router(router, prefix="/studio/api")
    # The handler reads request.app.state.studio_state["graph"]
    app.state.studio_state = {"graph": graph}
    return app


def _make_graph(nodes_dict: dict, edges_dict: dict):
    """Build a mock graph object exposing .nodes (dict) and .edges (dict)."""
    g = MagicMock()
    g.nodes = nodes_dict
    g.edges = edges_dict
    return g


# ── Empty graph ──────────────────────────────────────────────────────


class TestGraphVisualizationEmpty:
    def test_no_graph_state_returns_empty_envelope(self):
        """No graph in studio_state → empty envelope with metadata."""
        app = FastAPI()
        app.include_router(router, prefix="/studio/api")
        app.state.studio_state = {"graph": None}
        client = TestClient(app)

        response = client.get("/studio/api/graph/visualization")

        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["links"] == []
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
        assert data["truncated"] is False
        assert data["limit"] == 2000


# ── Small graph (under limit) ────────────────────────────────────────


class TestGraphVisualizationSmallGraph:
    def test_under_limit_returns_all_nodes_not_truncated(self):
        nodes = {
            "n1": MockNode("n1", "Node 1", "Service", "desc1"),
            "n2": MockNode("n2", "Node 2", "Service", "desc2"),
            "n3": MockNode("n3", "Node 3", "Service", "desc3"),
        }
        edges = {
            "e1": MockEdge("n1", "n2", "CALLS"),
            "e2": MockEdge("n2", "n3", "CALLS"),
        }
        client = TestClient(_make_app(_make_graph(nodes, edges)))

        response = client.get("/studio/api/graph/visualization")

        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 3
        assert len(data["links"]) == 2
        assert data["total_nodes"] == 3
        assert data["total_edges"] == 2
        assert data["truncated"] is False
        assert data["limit"] == 2000


# ── Large graph (over limit) ─────────────────────────────────────────


class TestGraphVisualizationLargeGraph:
    def test_over_limit_truncates_to_top_n_by_degree(self):
        """50 nodes, limit=10 → top-10 by degree returned, truncated=True."""
        # Build 50 nodes
        nodes = {
            f"n{i}": MockNode(f"n{i}", f"Node {i}", "Service", "")
            for i in range(50)
        }
        # n0 has degree 20 (hub), n1 has degree 15, n2 has degree 10
        # n3..n49 mostly have 0 or 1 degree
        edges = {}
        for i in range(1, 21):
            edges[f"e0_{i}"] = MockEdge("n0", f"n{i}", "REL")
        for i in range(20, 35):
            edges[f"e1_{i}"] = MockEdge("n1", f"n{i}", "REL")
        for i in range(35, 45):
            edges[f"e2_{i}"] = MockEdge("n2", f"n{i}", "REL")
        client = TestClient(_make_app(_make_graph(nodes, edges)))

        response = client.get("/studio/api/graph/visualization?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 10
        assert data["total_nodes"] == 50
        assert data["total_edges"] == len(edges)
        assert data["truncated"] is True
        assert data["limit"] == 10
        # Verify top-degree nodes are included
        selected = {n["id"] for n in data["nodes"]}
        assert "n0" in selected  # highest degree (21 — source + 20 targets)
        assert "n1" in selected  # second-highest (16)
        assert "n2" in selected  # third-highest (11)


# ── Link filtering ───────────────────────────────────────────────────


class TestGraphVisualizationLinkFiltering:
    def test_only_links_with_both_endpoints_in_selected_are_returned(self):
        """SF-05 invariant: no dangling source/target refs in response."""
        nodes = {
            f"n{i}": MockNode(f"n{i}", f"Node {i}", "Entity", "")
            for i in range(50)
        }
        edges = {}
        # Edges within top-3 hub set (n0/n1/n2 all high degree)
        for i in range(1, 21):
            edges[f"e0_{i}"] = MockEdge("n0", f"n{i}", "REL")
        # Dangling: n0 -> n45 (n45 won't be in top-10)
        edges["dangle_1"] = MockEdge("n0", "n45", "REL")
        edges["dangle_2"] = MockEdge("n1", "n48", "REL")
        client = TestClient(_make_app(_make_graph(nodes, edges)))

        response = client.get("/studio/api/graph/visualization?limit=10")

        assert response.status_code == 200
        data = response.json()
        selected = {n["id"] for n in data["nodes"]}

        # Every returned link must have BOTH endpoints in selected
        for link in data["links"]:
            assert link["source"] in selected, (
                f"Dangling source: {link['source']} not in {selected}"
            )
            assert link["target"] in selected, (
                f"Dangling target: {link['target']} not in {selected}"
            )


# ── Limit query-parameter validation ─────────────────────────────────


class TestGraphVisualizationLimitValidation:
    @pytest.mark.parametrize("invalid_limit", [5, 9, 10001, 15000, -1, 0])
    def test_limit_out_of_range_returns_422(self, invalid_limit):
        """FastAPI Query(ge=10, le=10000) rejects out-of-range values."""
        client = TestClient(_make_app(_make_graph({}, {})))
        response = client.get(
            f"/studio/api/graph/visualization?limit={invalid_limit}"
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("valid_limit", [10, 100, 500, 2000, 10000])
    def test_limit_in_range_returns_200_and_echoes_limit(self, valid_limit):
        """Valid limits are accepted and echoed in the response envelope."""
        client = TestClient(_make_app(_make_graph({}, {})))
        response = client.get(
            f"/studio/api/graph/visualization?limit={valid_limit}"
        )
        assert response.status_code == 200
        assert response.json()["limit"] == valid_limit


# ── Response shape invariants ────────────────────────────────────────


class TestGraphVisualizationResponseShape:
    def test_response_includes_metadata_fields(self):
        """Every response includes total_nodes, total_edges, truncated, limit."""
        nodes = {"n1": MockNode("n1", "N1", "Service", "")}
        client = TestClient(_make_app(_make_graph(nodes, {})))
        response = client.get("/studio/api/graph/visualization")
        data = response.json()
        for field_name in ("nodes", "links", "total_nodes",
                           "total_edges", "truncated", "limit"):
            assert field_name in data, f"Missing field: {field_name}"

    def test_node_shape(self):
        """Each node has id, label, type, description, chunks, degree, size, color."""
        nodes = {"n1": MockNode("n1", "Hub", "Service", "x" * 500)}
        edges = {}
        client = TestClient(_make_app(_make_graph(nodes, edges)))
        response = client.get("/studio/api/graph/visualization")
        node = response.json()["nodes"][0]
        for field_name in ("id", "label", "type", "description",
                           "chunks", "degree", "size", "color"):
            assert field_name in node, f"Missing field: {field_name}"
        # Description is truncated to 200 chars per existing behavior
        assert len(node["description"]) <= 200
