"""Tests for graq learn entity/knowledge CLI subcommands (v0.15.0)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.learn import learn_app

runner = CliRunner()


def _mock_graph():
    graph = MagicMock()
    graph.nodes = {"existing-node": MagicMock(id="existing-node")}
    graph.__len__ = MagicMock(return_value=10)
    graph.add_node_simple = MagicMock()
    graph.add_edge_simple = MagicMock()
    graph.auto_connect = MagicMock(return_value=3)
    graph.to_json = MagicMock()
    return graph


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


class TestLearnKnowledge:
    @patch("graqle.cli.commands.learn._load_graph")
    def test_knowledge_basic(self, mock_load):
        graph = _mock_graph()
        mock_load.return_value = (graph, "test.json")

        result = runner.invoke(learn_app, [
            "knowledge",
            "Target audience is C-suite in regulated industries",
            "--domain", "brand",
        ])
        assert result.exit_code == 0
        assert "Knowledge taught" in result.output
        assert "brand" in result.output
        graph.add_node_simple.assert_called_once()

    @patch("graqle.cli.commands.learn._load_graph")
    def test_knowledge_with_tags(self, mock_load):
        graph = _mock_graph()
        mock_load.return_value = (graph, "test.json")

        result = runner.invoke(learn_app, [
            "knowledge",
            "Free tier is 500 nodes",
            "--tags", "pricing,freemium",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        assert "tags" in call_kwargs["properties"]

    @patch("graqle.cli.commands.learn._load_graph")
    def test_knowledge_default_domain(self, mock_load):
        graph = _mock_graph()
        mock_load.return_value = (graph, "test.json")

        result = runner.invoke(learn_app, [
            "knowledge", "Some fact",
        ])
        assert result.exit_code == 0
        call_kwargs = graph.add_node_simple.call_args[1]
        assert call_kwargs["properties"]["domain"] == "general"
