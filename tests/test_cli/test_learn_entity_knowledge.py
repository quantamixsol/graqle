"""Tests for graq learn entity/knowledge CLI subcommands (v0.16.0).

Updated for semantic auto-connect, entity extraction, and GDS intelligence.
"""

from __future__ import annotations

import json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.learn import learn_app, _extract_entities, _connect_extracted_entities

runner = CliRunner()


def _mock_graph():
    graph = MagicMock()
    graph.nodes = {"existing-node": MagicMock(id="existing-node")}
    graph.__len__ = MagicMock(return_value=10)
    graph.add_node_simple = MagicMock()
    graph.add_edge_simple = MagicMock()
    graph.auto_connect = MagicMock(return_value=3)
    graph.semantic_auto_connect = MagicMock(return_value=3)
    graph.get_edges_between = MagicMock(return_value=[])
    graph.get_neighbors = MagicMock(return_value=[])
    graph.to_json = MagicMock()
    graph.to_networkx = MagicMock()
    return graph


def _mock_graph_lock(graph):
    """Create a mock _graph_lock context manager that yields the given graph."""
    @contextmanager
    def mock_lock(graph_path="graqle.json"):
        yield graph, "test.json"
    return mock_lock


class TestLearnEntity:
    @patch("graqle.cli.commands.learn._load_graph")
    def test_entity_basic(self, mock_load):
        mock_load.return_value = (_mock_graph(), "test.json")

        result = runner.invoke(learn_app, [
            "entity", "CrawlQ",
            "--type", "PRODUCT",
            "--desc", "Content ERP for enterprise",
        ])
        assert result.exit_code == 0
        assert "Business entity added" in result.output
        assert "CrawlQ" in result.output

    @patch("graqle.cli.commands.learn._load_graph")
    def test_entity_with_connects(self, mock_load):
        graph = _mock_graph()
        mock_load.return_value = (graph, "test.json")

        result = runner.invoke(learn_app, [
            "entity", "MyProduct",
            "--type", "PRODUCT",
            "--connects", "existing-node",
            "--relation", "POWERS",
        ])
        assert result.exit_code == 0
        graph.add_edge_simple.assert_called_once()

    @patch("graqle.cli.commands.learn._load_graph")
    def test_entity_custom_type_warning(self, mock_load):
        mock_load.return_value = (_mock_graph(), "test.json")

        result = runner.invoke(learn_app, [
            "entity", "something",
            "--type", "WEIRD_TYPE",
        ])
        assert result.exit_code == 0
        assert "not a standard business type" in result.output

    @patch("graqle.cli.commands.learn._load_graph")
    def test_entity_uses_semantic_auto_connect(self, mock_load):
        graph = _mock_graph()
        mock_load.return_value = (graph, "test.json")

        runner.invoke(learn_app, [
            "entity", "TestEntity",
            "--type", "PRODUCT",
            "--desc", "A test product",
        ])
        graph.semantic_auto_connect.assert_called_once()


class TestLearnKnowledge:
    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_basic(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        result = runner.invoke(learn_app, [
            "knowledge",
            "Target audience is C-suite in regulated industries",
            "--domain", "brand",
        ])
        assert result.exit_code == 0
        assert "Knowledge taught" in result.output
        assert "brand" in result.output
        graph.add_node_simple.assert_called_once()

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_with_tags(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        result = runner.invoke(learn_app, [
            "knowledge",
            "Free tier is 500 nodes",
            "--tags", "pricing,freemium",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        assert "tags" in call_kwargs["properties"]

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_default_domain(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        result = runner.invoke(learn_app, [
            "knowledge", "Some fact",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        assert call_kwargs["properties"]["domain"] == "general"

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_uses_semantic_auto_connect(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        runner.invoke(learn_app, [
            "knowledge",
            "TAMR+ uses intelligent retrieval",
            "--domain", "copy",
        ])
        graph.semantic_auto_connect.assert_called_once()

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_extracts_entities(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        result = runner.invoke(learn_app, [
            "knowledge",
            'CrawlQ uses "TAMR+" for intelligent document retrieval',
            "--domain", "product",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        entities = call_kwargs["properties"].get("extracted_entities", [])
        assert isinstance(entities, list)
        assert len(entities) > 0

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_no_extract(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        result = runner.invoke(learn_app, [
            "knowledge",
            "CrawlQ is the best product",
            "--no-extract",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        entities = call_kwargs["properties"].get("extracted_entities", [])
        assert entities == []

    @patch("graqle.cli.commands.learn._graph_lock")
    def test_knowledge_no_semantic(self, mock_lock_cls):
        graph = _mock_graph()
        mock_lock_cls.side_effect = _mock_graph_lock(graph)

        runner.invoke(learn_app, [
            "knowledge",
            "some fact about things",
            "--no-semantic",
        ])
        # Should call semantic_auto_connect with method="keyword"
        call_args = graph.semantic_auto_connect.call_args
        assert call_args[1]["method"] == "keyword"


class TestEntityExtraction:
    """Test the _extract_entities helper function."""

    def test_extract_quoted_terms(self):
        entities = _extract_entities('The "TAMR+" engine uses "CrawlQ" technology')
        assert "TAMR+" in entities
        assert "CrawlQ" in entities

    def test_extract_single_quoted(self):
        entities = _extract_entities("The 'GraphLearner' module is important")
        assert "GraphLearner" in entities

    def test_extract_acronyms(self):
        entities = _extract_entities("JWT authentication via API gateway with CORS")
        assert "JWT" in entities
        assert "API" in entities
        assert "CORS" in entities

    def test_extract_capitalized_phrases(self):
        entities = _extract_entities("Neo4j Graph Database and Apache Kafka are used")
        # Should capture capitalized multi-word phrases
        found = [e for e in entities if "Neo4j" in e or "Apache" in e]
        assert len(found) > 0

    def test_extract_camel_case(self):
        entities = _extract_entities("The GraphLearner and NodeState classes")
        assert "GraphLearner" in entities
        assert "NodeState" in entities

    def test_no_common_stopwords(self):
        entities = _extract_entities("The quick brown fox jumps over the lazy dog")
        # "The" should not appear as an entity
        assert "THE" not in entities

    def test_empty_string(self):
        entities = _extract_entities("")
        assert entities == []

    def test_deduplication(self):
        entities = _extract_entities('JWT JWT JWT "JWT"')
        assert entities.count("JWT") == 1

    def test_returns_sorted(self):
        entities = _extract_entities("CrawlQ and TAMR+ and API")
        assert entities == sorted(entities)

    def test_real_world_knowledge(self):
        """Test with a realistic knowledge fact."""
        entities = _extract_entities(
            "CrawlQ Content ERP serves C-suite executives in regulated "
            "industries like Philips and Siemens using TAMR+ technology"
        )
        entity_str = " ".join(entities)
        # Should find at least some of these
        assert any(e in entities for e in ["CrawlQ", "Philips", "Siemens"])


class TestEntityConnection:
    """Test the _connect_extracted_entities helper function."""

    def test_connect_exact_match(self):
        graph = _mock_graph()
        # Make the mock nodes dict iterable with proper node objects
        node_mock = MagicMock()
        node_mock.label = "CrawlQ Product"
        node_mock.entity_type = "PRODUCT"
        node_mock.description = "Content ERP"
        graph.nodes = {"CrawlQ": node_mock, "knowledge_brand_123": MagicMock()}
        graph.get_edges_between = MagicMock(return_value=[])

        edges = _connect_extracted_entities(
            graph, "knowledge_brand_123", ["CrawlQ"], "brand"
        )
        assert edges == 1
        graph.add_edge_simple.assert_called_once()

    def test_connect_respects_cap(self):
        """Should not create more than 10 entity connections."""
        graph = _mock_graph()
        # Create 15 matching nodes
        nodes = {}
        for i in range(15):
            node_mock = MagicMock()
            node_mock.label = f"Node{i}"
            node_mock.entity_type = "SERVICE"
            node_mock.description = f"Service number {i}"
            nodes[f"Node{i}"] = node_mock
        nodes["knowledge_test_123"] = MagicMock()
        graph.nodes = nodes
        graph.get_edges_between = MagicMock(return_value=[])

        entities = [f"Node{i}" for i in range(15)]
        edges = _connect_extracted_entities(
            graph, "knowledge_test_123", entities, "technical"
        )
        assert edges <= 10

    def test_connect_domain_aware_relation(self):
        graph = _mock_graph()
        node_mock = MagicMock()
        node_mock.label = "CrawlQ"
        node_mock.entity_type = "PRODUCT"
        node_mock.description = "Content platform"
        graph.nodes = {"CrawlQ": node_mock, "knowledge_brand_123": MagicMock()}
        graph.get_edges_between = MagicMock(return_value=[])

        _connect_extracted_entities(
            graph, "knowledge_brand_123", ["CrawlQ"], "brand"
        )
        call_args = graph.add_edge_simple.call_args
        assert call_args[1]["relation"] == "INFORMS"

    def test_connect_technical_domain_relation(self):
        graph = _mock_graph()
        node_mock = MagicMock()
        node_mock.label = "auth-service"
        node_mock.entity_type = "SERVICE"
        node_mock.description = "Authentication"
        graph.nodes = {"auth-service": node_mock, "knowledge_tech_123": MagicMock()}
        graph.get_edges_between = MagicMock(return_value=[])

        _connect_extracted_entities(
            graph, "knowledge_tech_123", ["auth-service"], "technical"
        )
        call_args = graph.add_edge_simple.call_args
        assert call_args[1]["relation"] == "RELATED_TO"
