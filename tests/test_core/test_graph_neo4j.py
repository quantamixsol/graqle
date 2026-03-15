"""Tests for Graqle.from_neo4j() and to_neo4j()."""

# ── graqle:intelligence ──
# module: tests.test_core.test_graph_neo4j
# risk: LOW (impact radius: 0 modules)
# dependencies: mock, pytest, graph, settings
# constraints: none
# ── /graqle:intelligence ──

from unittest.mock import MagicMock, patch

from graqle.core.graph import Graqle


def _mock_neo4j_module():
    """Create a mock neo4j module."""
    mock_module = MagicMock()
    mock_driver = MagicMock()
    mock_module.GraphDatabase.driver.return_value = mock_driver
    return mock_module, mock_driver


class TestFromNeo4j:
    """Tests for Graqle.from_neo4j()."""

    def test_from_neo4j_creates_graph(self):
        """from_neo4j loads nodes and edges from Neo4j."""
        mock_module, mock_driver = _mock_neo4j_module()
        session = mock_driver.session().__enter__()

        # Mock node records
        node_data = [
            {"id": "n1", "label": "Auth", "type": "SERVICE", "description": "Auth service", "properties": {}},
            {"id": "n2", "label": "DB", "type": "DATABASE", "description": "Database", "properties": {}},
        ]
        edge_data = [
            {"id": "e1", "source": "n1", "target": "n2", "relationship": "USES", "properties": {"weight": 1.0}},
        ]
        chunk_data = [
            {"node_id": "n1", "chunk_id": "n1_c0", "text": "function auth()", "type": "function", "idx": 0},
        ]

        node_records = []
        for d in node_data:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, dd=d: dd[k]
            rec.get = lambda k, default=None, dd=d: dd.get(k, default)
            node_records.append(rec)

        edge_records = []
        for d in edge_data:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, dd=d: dd[k]
            rec.get = lambda k, default=None, dd=d: dd.get(k, default)
            edge_records.append(rec)

        chunk_records = []
        for d in chunk_data:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, dd=d: dd[k]
            rec.get = lambda k, default=None, dd=d: dd.get(k, default)
            chunk_records.append(rec)

        # Three session.run calls: nodes, edges, chunks
        session.run.side_effect = [node_records, edge_records, chunk_records]

        with patch.dict("sys.modules", {"neo4j": mock_module}):
            graph = Graqle.from_neo4j(
                uri="bolt://localhost:7687",
                username="neo4j",
                password="test",
            )

        assert len(graph.nodes) == 2
        assert "n1" in graph.nodes
        assert "n2" in graph.nodes
        assert graph.nodes["n1"].label == "Auth"
        assert graph._neo4j_connector is not None

    def test_from_neo4j_attaches_chunks(self):
        """Chunks should be attached to node properties."""
        mock_module, mock_driver = _mock_neo4j_module()
        session = mock_driver.session().__enter__()

        node_data = [{"id": "n1", "label": "File", "type": "FILE", "description": "A file", "properties": {}}]
        chunk_data = [
            {"node_id": "n1", "chunk_id": "n1_c0", "text": "chunk0", "type": "function", "idx": 0},
            {"node_id": "n1", "chunk_id": "n1_c1", "text": "chunk1", "type": "class", "idx": 1},
        ]

        node_records = []
        for d in node_data:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, dd=d: dd[k]
            rec.get = lambda k, default=None, dd=d: dd.get(k, default)
            node_records.append(rec)

        chunk_records = []
        for d in chunk_data:
            rec = MagicMock()
            rec.__getitem__ = lambda s, k, dd=d: dd[k]
            rec.get = lambda k, default=None, dd=d: dd.get(k, default)
            chunk_records.append(rec)

        session.run.side_effect = [node_records, [], chunk_records]

        with patch.dict("sys.modules", {"neo4j": mock_module}):
            graph = Graqle.from_neo4j()

        chunks = graph.nodes["n1"].properties.get("chunks", [])
        assert len(chunks) == 2
        assert chunks[0]["text"] == "chunk0"


class TestToNeo4j:
    """Tests for Graqle.to_neo4j()."""

    def test_to_neo4j_writes_graph(self):
        """to_neo4j should call save and save_chunks on connector."""
        mock_module, mock_driver = _mock_neo4j_module()
        session = mock_driver.session().__enter__()

        # Create a simple in-memory graph
        from graqle.core.edge import CogniEdge
        from graqle.core.node import CogniNode

        nodes = {
            "a": CogniNode(id="a", label="A", entity_type="T", description="Node A"),
            "b": CogniNode(id="b", label="B", entity_type="T", description="Node B"),
        }
        nodes["a"].properties["chunks"] = [{"text": "code", "type": "function"}]
        edges = {
            "e1": CogniEdge(id="e1", source_id="a", target_id="b", relationship="REL"),
        }
        graph = Graqle(nodes=nodes, edges=edges)

        with patch.dict("sys.modules", {"neo4j": mock_module}):
            graph.to_neo4j(uri="bolt://localhost:7687", password="test")

        # Should have called session.run multiple times (schema + save + chunks)
        assert session.run.call_count > 0
        assert graph._neo4j_connector is not None

    def test_to_neo4j_with_embed_fn(self):
        """to_neo4j should pass embed_fn to save_chunks."""
        mock_module, mock_driver = _mock_neo4j_module()
        session = mock_driver.session().__enter__()

        from graqle.core.node import CogniNode
        nodes = {
            "a": CogniNode(id="a", label="A", entity_type="T", description="desc"),
        }
        nodes["a"].properties["chunks"] = [{"text": "code", "type": "function"}]
        graph = Graqle(nodes=nodes)

        embed_fn = MagicMock(return_value=[0.1] * 1024)

        with patch.dict("sys.modules", {"neo4j": mock_module}):
            graph.to_neo4j(embed_fn=embed_fn)

        # embed_fn should have been called for the chunk
        assert embed_fn.call_count >= 1
