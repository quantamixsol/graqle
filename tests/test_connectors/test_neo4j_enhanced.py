"""Tests for enhanced Neo4j connector — write, chunks, vector search, schema.

All tests mock the neo4j driver to avoid requiring a live database.
"""

from unittest.mock import MagicMock, patch, call

import pytest


def _make_connector(**kwargs):
    """Create a Neo4jConnector with a mocked driver."""
    with patch.dict("sys.modules", {"neo4j": MagicMock()}):
        from graqle.connectors.neo4j import Neo4jConnector
        connector = Neo4jConnector(**kwargs)
        # Inject mock driver
        mock_driver = MagicMock()
        connector._driver = mock_driver
        return connector, mock_driver


class TestNeo4jLoad:
    """Tests for load() and load_chunks()."""

    def test_load_nodes_and_edges(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        # Mock node query results
        node_record = MagicMock()
        node_record.__getitem__ = lambda s, k: {
            "id": "n1", "label": "Auth", "type": "SERVICE",
            "description": "Auth service", "properties": {"region": "eu"},
        }[k]
        node_record.get = lambda k, d=None: {
            "id": "n1", "label": "Auth", "type": "SERVICE",
            "description": "Auth service", "properties": {"region": "eu"},
        }.get(k, d)

        edge_record = MagicMock()
        edge_data = {
            "id": "e1", "source": "n1", "target": "n2",
            "relationship": "CALLS", "properties": {"weight": 0.8},
        }
        edge_record.__getitem__ = lambda s, k: edge_data[k]
        edge_record.get = lambda k, d=None: edge_data.get(k, d)

        # First run() call returns nodes, second returns edges
        session.run.side_effect = [[node_record], [edge_record]]

        nodes, edges = connector.load()
        assert "n1" in nodes
        assert nodes["n1"]["label"] == "Auth"
        assert len(edges) == 1

    def test_load_chunks(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        chunk_records = []
        for i in range(3):
            rec = MagicMock()
            data = {
                "node_id": "n1", "chunk_id": f"n1_chunk_{i}",
                "text": f"chunk text {i}", "type": "function", "idx": i,
            }
            rec.__getitem__ = lambda s, k, d=data: d[k]
            rec.get = lambda k, default=None, d=data: d.get(k, default)
            chunk_records.append(rec)

        session.run.return_value = chunk_records
        result = connector.load_chunks()
        assert "n1" in result
        assert len(result["n1"]) == 3


class TestNeo4jSave:
    """Tests for save() and save_chunks()."""

    def test_save_nodes_and_edges(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        nodes = {
            "n1": {"label": "Auth", "type": "SERVICE", "description": "Auth svc", "properties": {}},
            "n2": {"label": "DB", "type": "DATABASE", "description": "Database", "properties": {}},
        }
        edges = {
            "e1": {"source": "n1", "target": "n2", "relationship": "USES", "weight": 1.0},
        }

        connector.save(nodes, edges)
        # Should have 2 run calls: one for nodes UNWIND, one for edges UNWIND
        assert session.run.call_count == 2

    def test_save_chunks_with_embedding(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        chunks = {
            "n1": [
                {"text": "function auth() {}", "type": "function"},
                {"text": "class User {}", "type": "class"},
            ],
        }
        embed_fn = MagicMock(return_value=[0.1] * 1024)

        count = connector.save_chunks(chunks, embed_fn=embed_fn)
        assert count == 2
        assert embed_fn.call_count == 2
        # Should call session.run with UNWIND
        assert session.run.call_count == 1

    def test_save_chunks_without_embedding(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        chunks = {"n1": [{"text": "some code", "type": "text"}]}
        count = connector.save_chunks(chunks, embed_fn=None)
        assert count == 1
        assert session.run.call_count == 1

    def test_save_chunks_empty_text_skipped(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        chunks = {"n1": [{"text": "", "type": "text"}, {"text": "real", "type": "function"}]}
        count = connector.save_chunks(chunks, embed_fn=None)
        assert count == 1


class TestNeo4jSchema:
    """Tests for create_schema()."""

    def test_create_schema_runs_three_queries(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        connector.create_schema()
        # 2 constraints + 1 vector index = 3 calls
        assert session.run.call_count == 3


class TestNeo4jVectorSearch:
    """Tests for vector_search()."""

    def test_vector_search_returns_node_ids(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        # Mock vector search results
        records = []
        for nid, score in [("n1", 0.95), ("n2", 0.80), ("n3", 0.65)]:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, n=nid, sc=score: {"node_id": n, "relevance": sc}[k]
            records.append(rec)

        session.run.return_value = records
        hits = connector.vector_search([0.1] * 1024, k=10)

        assert len(hits) == 3
        assert hits[0] == ("n1", 0.95)
        assert hits[1] == ("n2", 0.80)

    def test_vector_search_empty_results(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()
        session.run.return_value = []

        hits = connector.vector_search([0.1] * 1024, k=10)
        assert hits == []


class TestNeo4jHealthCheck:
    """Tests for validate() and health_check()."""

    def test_validate_success(self):
        connector, driver = _make_connector()
        assert connector.validate() is True

    def test_validate_failure(self):
        connector, driver = _make_connector()
        driver.verify_connectivity.side_effect = Exception("Connection refused")
        assert connector.validate() is False

    def test_health_check_connected(self):
        connector, driver = _make_connector()
        session = driver.session().__enter__()

        # Mock count queries
        count_mock = MagicMock()
        count_mock.single.return_value = {"cnt": 100}

        index_mock = MagicMock()
        index_mock.single.return_value = {"state": "ONLINE"}

        session.run.side_effect = [count_mock, count_mock, index_mock]

        info = connector.health_check()
        assert info["connected"] is True

    def test_close(self):
        connector, driver = _make_connector()
        connector.close()
        driver.close.assert_called_once()
        assert connector._driver is None
