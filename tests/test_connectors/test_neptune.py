"""Tests for graqle.connectors.neptune — Neptune adapter."""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_neptune
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pytest, neptune
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.connectors.neptune import (
    NeptuneAdapter,
    NeptuneConfig,
    check_neptune_available,
    check_neptune_connection,
)


class TestNeptuneConfig:
    def test_default_not_configured(self):
        config = NeptuneConfig()
        assert not config.is_configured

    def test_configured(self):
        config = NeptuneConfig(endpoint="my-cluster.neptune.amazonaws.com", region="eu-central-1")
        assert config.is_configured

    def test_websocket_url(self):
        config = NeptuneConfig(endpoint="cluster.neptune.amazonaws.com", port=8182)
        assert config.websocket_url == "wss://cluster.neptune.amazonaws.com:8182/gremlin"

    def test_http_url(self):
        config = NeptuneConfig(endpoint="cluster.neptune.amazonaws.com")
        assert "openCypher" in config.http_url


class TestNeptuneAdapter:
    def setup_method(self):
        self.adapter = NeptuneAdapter(NeptuneConfig(
            endpoint="test.neptune.amazonaws.com",
            region="eu-central-1",
        ))

    def test_generate_upsert_node(self):
        query = self.adapter.generate_upsert_node({
            "id": "fn::auth.py::verify_token",
            "label": "verify_token",
            "entity_type": "Function",
            "source_type": "code",
        })
        assert "fn::auth.py::verify_token" in query
        assert "addV('Function')" in query
        assert "property('label', 'verify_token')" in query

    def test_generate_upsert_edge(self):
        query = self.adapter.generate_upsert_edge({
            "id": "e1",
            "source": "n1",
            "target": "n2",
            "relationship": "CALLS",
        })
        assert "CALLS" in query
        assert "'n1'" in query
        assert "'n2'" in query

    def test_generate_delete_node(self):
        query = self.adapter.generate_delete_node("fn::test")
        assert "drop()" in query
        assert "fn::test" in query

    def test_generate_delete_edge(self):
        query = self.adapter.generate_delete_edge("e1")
        assert "drop()" in query

    def test_generate_team_query(self):
        query = self.adapter.generate_team_query("team-test")
        assert "team-test" in query
        assert "valueMap" in query

    def test_generate_team_query_with_type(self):
        query = self.adapter.generate_team_query("team-test", "Function")
        assert "Function" in query

    def test_generate_cross_repo_edges(self):
        query = self.adapter.generate_cross_repo_edges("team-test")
        assert "cross_repo" in query
        assert "team-test" in query

    def test_sync_push_queries(self):
        delta = {
            "nodes_added": [{"id": "n1", "entity_type": "Function"}],
            "nodes_modified": [{"id": "n2", "entity_type": "Class"}],
            "nodes_deleted": ["n3"],
            "edges_added": [{"id": "e1", "source": "n1", "target": "n2", "relationship": "CALLS"}],
            "edges_modified": [],
            "edges_deleted": ["e2"],
        }
        queries = self.adapter.generate_sync_push_queries(delta, "team-test", "dev-alice")
        assert len(queries) == 5  # 2 upserts + 1 delete + 1 edge + 1 edge delete

        # Check team_id is injected
        assert any("team-test" in q for q in queries)
        # Check developer_id is injected
        assert any("dev-alice" in q for q in queries)

    def test_generate_cypher_upsert(self):
        query = self.adapter.generate_cypher_upsert_node({
            "id": "fn::test",
            "entity_type": "Function",
            "label": "test_func",
        })
        assert "MERGE" in query
        assert "Function" in query

    def test_generate_cypher_stats(self):
        query = self.adapter.generate_cypher_stats("team-test")
        assert "team-test" in query
        assert "count" in query

    def test_connect_not_configured_raises(self):
        adapter = NeptuneAdapter(NeptuneConfig())
        with pytest.raises(ConnectionError, match="not configured"):
            adapter.connect()

    def test_connect_configured(self):
        # Should not raise in foundation mode
        self.adapter.connect()


class TestNeptuneAvailability:
    def test_check_available(self):
        available, msg = check_neptune_available()
        assert available
        assert "foundation" in msg

    def test_check_connection_no_endpoint(self):
        ok, msg = check_neptune_connection(NeptuneConfig())
        assert not ok

    def test_check_connection_no_region(self):
        ok, msg = check_neptune_connection(NeptuneConfig(endpoint="test"))
        assert not ok

    def test_check_connection_valid(self):
        ok, msg = check_neptune_connection(NeptuneConfig(
            endpoint="cluster.neptune.amazonaws.com",
            region="eu-central-1",
        ))
        assert ok
