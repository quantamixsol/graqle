"""Tests for CypherActivation — Neo4j vector search activation strategy."""

# ── graqle:intelligence ──
# module: tests.test_activation.test_cypher_activation
# risk: LOW (impact radius: 0 modules)
# dependencies: mock, pytest, cypher_activation
# constraints: none
# ── /graqle:intelligence ──

from unittest.mock import MagicMock

from graqle.activation.cypher_activation import CypherActivation


def _make_graph(node_ids):
    """Create a mock graph with given node IDs."""
    graph = MagicMock()
    graph.nodes = {nid: MagicMock(id=nid) for nid in node_ids}
    return graph


class TestCypherActivation:
    """Tests for CypherActivation.activate()."""

    def test_basic_activation(self):
        """Vector search results map to activated nodes."""
        connector = MagicMock()
        connector.vector_search.return_value = [
            ("n1", 0.95), ("n2", 0.80), ("n3", 0.65),
        ]
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["n1", "n2", "n3", "n4"])
        act = CypherActivation(connector, engine, max_nodes=50)
        result = act.activate(graph, "What does auth do?")

        assert result == ["n1", "n2", "n3"]
        assert act.last_relevance == {"n1": 0.95, "n2": 0.80, "n3": 0.65}
        engine.embed.assert_called_once_with("What does auth do?")

    def test_filters_to_existing_graph_nodes(self):
        """Only nodes present in the graph are returned."""
        connector = MagicMock()
        connector.vector_search.return_value = [
            ("n1", 0.95), ("n_missing", 0.80), ("n2", 0.65),
        ]
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["n1", "n2"])
        act = CypherActivation(connector, engine)
        result = act.activate(graph, "query")

        assert "n1" in result
        assert "n2" in result
        assert "n_missing" not in result

    def test_embedding_failure_falls_back_to_full(self):
        """If embedding fails, return all graph nodes."""
        connector = MagicMock()
        engine = MagicMock()
        engine.embed.side_effect = RuntimeError("model not loaded")

        graph = _make_graph(["n1", "n2", "n3"])
        act = CypherActivation(connector, engine, max_nodes=10)
        result = act.activate(graph, "query")

        assert len(result) <= 10
        # All nodes should have relevance 1.0 (fallback)
        for nid in result:
            assert act.last_relevance[nid] == 1.0

    def test_vector_search_failure_falls_back(self):
        """If vector search fails, fall back to full graph."""
        connector = MagicMock()
        connector.vector_search.side_effect = Exception("DB connection lost")
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["n1", "n2"])
        act = CypherActivation(connector, engine)
        result = act.activate(graph, "query")

        assert set(result) == {"n1", "n2"}

    def test_empty_vector_results_falls_back(self):
        """If vector search returns empty, fall back to full graph."""
        connector = MagicMock()
        connector.vector_search.return_value = []
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["n1", "n2"])
        act = CypherActivation(connector, engine)
        result = act.activate(graph, "query")

        assert set(result) == {"n1", "n2"}

    def test_max_nodes_respected(self):
        """max_nodes is passed to vector_search."""
        connector = MagicMock()
        connector.vector_search.return_value = [("n1", 0.9)]
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["n1"])
        act = CypherActivation(connector, engine, max_nodes=5, k_chunks=50)
        act.activate(graph, "query")

        connector.vector_search.assert_called_once_with(
            query_embedding=[0.1] * 1024,
            k=50,
            max_nodes=5,
        )

    def test_relevance_scores_stored(self):
        """last_relevance stores the correct scores."""
        connector = MagicMock()
        connector.vector_search.return_value = [("a", 0.9), ("b", 0.7)]
        engine = MagicMock()
        engine.embed.return_value = [0.1] * 1024

        graph = _make_graph(["a", "b"])
        act = CypherActivation(connector, engine)
        act.activate(graph, "query")

        assert act.last_relevance["a"] == 0.9
        assert act.last_relevance["b"] == 0.7
