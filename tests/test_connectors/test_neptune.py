"""Tests for graqle.connectors.neptune — Neptune production client.

Tests the openCypher query client with mocked HTTP responses.
Does NOT require a live Neptune cluster.
"""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_neptune
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, unittest.mock, neptune
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from graqle.connectors.neptune import (
    check_neptune_available,
    check_neptune_connection,
    execute_query,
    get_nodes,
    get_edges,
    get_graph_stats,
    get_visualization,
    get_node_neighbors,
    upsert_nodes,
    upsert_edges,
    neptune_health,
    reset_availability,
    _sanitize_cypher,
)


class TestSanitize:
    def test_sanitize_cypher_quotes(self):
        assert _sanitize_cypher("it's a test") == "it\\'s a test"

    def test_sanitize_cypher_double_quotes(self):
        assert _sanitize_cypher('say "hello"') == 'say \\"hello\\"'

    def test_sanitize_cypher_backslash(self):
        assert _sanitize_cypher("path\\to") == "path\\\\to"


class TestCheckAvailability:
    def test_check_available(self):
        # OT-068: check_neptune_available() returns False without gremlinpython
        # installed. Skip cleanly when the optional driver is absent.
        pytest.importorskip("gremlin_python")
        available, msg = check_neptune_available()
        assert available
        assert "production" in msg

    def test_check_connection_success(self):
        with patch("graqle.connectors.neptune.neptune_health") as mock_health:
            mock_health.return_value = {"status": "connected", "endpoint": "test"}
            ok, msg = check_neptune_connection()
            assert ok

    def test_check_connection_failure(self):
        with patch("graqle.connectors.neptune.neptune_health") as mock_health:
            mock_health.return_value = {"status": "error", "error": "timeout"}
            ok, msg = check_neptune_connection()
            assert not ok


class TestExecuteQuery:
    def setup_method(self):
        # OT-068: skip entire class without gremlinpython (optional extra).
        pytest.importorskip("gremlin_python")
        reset_availability()

    @patch("graqle.connectors.neptune._execute_with_iam")
    def test_execute_query_success(self, mock_iam):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"id": "n1", "label": "test"}]}
        mock_iam.return_value = mock_resp

        results = execute_query("MATCH (n) RETURN n.id AS id")
        assert len(results) == 1
        assert results[0]["id"] == "n1"

    @patch("graqle.connectors.neptune._execute_with_iam")
    def test_execute_query_error(self, mock_iam):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Invalid query"
        mock_iam.return_value = mock_resp

        with pytest.raises(RuntimeError, match="query failed"):
            execute_query("INVALID QUERY")

    @patch("graqle.connectors.neptune._execute_with_iam")
    def test_execute_query_with_parameters(self, mock_iam):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_iam.return_value = mock_resp

        execute_query("MATCH (n {id: $nid}) RETURN n", {"nid": "test"})
        call_args = mock_iam.call_args[0][0]
        assert "parameters" in call_args


class TestGraphQueries:
    @patch("graqle.connectors.neptune.execute_query")
    def test_get_nodes(self, mock_eq):
        mock_eq.return_value = [
            {"id": "n1", "label": "auth.py", "type": "Module"},
        ]
        nodes = get_nodes("graqle-sdk")
        assert len(nodes) == 1
        assert nodes[0]["type"] == "Module"

    @patch("graqle.connectors.neptune.execute_query")
    def test_get_edges(self, mock_eq):
        mock_eq.return_value = [
            {"id": "e1", "source": "n1", "target": "n2", "relationship": "IMPORTS"},
        ]
        edges = get_edges("graqle-sdk")
        assert len(edges) == 1

    @patch("graqle.connectors.neptune.execute_query")
    def test_get_graph_stats(self, mock_eq):
        mock_eq.side_effect = [
            [{"type": "Module", "cnt": 10}, {"type": "Function", "cnt": 20}],
            [{"edge_count": 30}],
        ]
        stats = get_graph_stats("graqle-sdk")
        assert stats["node_count"] == 30
        assert stats["edge_count"] == 30
        assert stats["type_counts"]["Module"] == 10

    @patch("graqle.connectors.neptune.execute_query")
    def test_get_visualization(self, mock_eq):
        mock_eq.side_effect = [
            [{"id": "n1", "label": "test", "type": "Module", "description": "desc",
              "size": 12, "degree": 3, "color": "#abc"}],
            [{"id": "e1", "source": "n1", "target": "n2", "relationship": "CALLS", "weight": 1.0}],
        ]
        viz = get_visualization("graqle-sdk")
        assert len(viz["nodes"]) == 1
        assert len(viz["links"]) == 1
        assert viz["nodes"][0]["label"] == "test"

    @patch("graqle.connectors.neptune.execute_query")
    def test_get_node_neighbors(self, mock_eq):
        mock_eq.return_value = [
            {"id": "n2", "label": "dep", "type": "Module", "hops": 1, "score": 1.0},
        ]
        neighbors = get_node_neighbors("graqle-sdk", "n1", max_hops=2)
        assert len(neighbors) == 1
        assert neighbors[0]["score"] == 1.0


class TestWriteFunctions:
    @patch("graqle.connectors.neptune.execute_query")
    def test_upsert_nodes(self, mock_eq):
        mock_eq.return_value = []
        count = upsert_nodes("graqle-sdk", [
            {"id": "n1", "label": "test", "type": "Module"},
            {"id": "n2", "label": "test2", "type": "Function"},
        ])
        assert count == 2
        assert mock_eq.call_count == 2

    @patch("graqle.connectors.neptune.execute_query")
    def test_upsert_nodes_empty(self, mock_eq):
        count = upsert_nodes("graqle-sdk", [])
        assert count == 0
        mock_eq.assert_not_called()

    @patch("graqle.connectors.neptune.execute_query")
    def test_upsert_edges(self, mock_eq):
        mock_eq.return_value = []
        count = upsert_edges("graqle-sdk", [
            {"source": "n1", "target": "n2", "relationship": "CALLS"},
        ])
        assert count == 1

    @patch("graqle.connectors.neptune.execute_query")
    def test_upsert_edges_skip_invalid(self, mock_eq):
        count = upsert_edges("graqle-sdk", [
            {"source": "", "target": "n2"},  # invalid: no source
        ])
        assert count == 0


class TestHealth:
    @patch("graqle.connectors.neptune.execute_query")
    def test_neptune_health_connected(self, mock_eq):
        mock_eq.return_value = [{"status": "ok", "connected": 1}]
        result = neptune_health()
        assert result["status"] == "connected"

    @patch("graqle.connectors.neptune.execute_query")
    def test_neptune_health_error(self, mock_eq):
        mock_eq.side_effect = RuntimeError("timeout")
        result = neptune_health()
        assert result["status"] == "error"
