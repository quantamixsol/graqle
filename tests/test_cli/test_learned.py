"""Tests for P2-11: graq learned command."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_learned
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, tempfile, pathlib, mock +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from graqle.cli.main import app

runner = CliRunner()


def _make_graph_json(nodes: list[dict]) -> str:
    """Create a minimal graqle.json with the given nodes and return its path."""
    graph_data = {
        "nodes": [],
        "edges": [],
    }
    for n in nodes:
        graph_data["nodes"].append({
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "entity_type": n.get("entity_type", "CONCEPT"),
            "description": n.get("description", ""),
            "properties": n.get("properties", {}),
        })
    return json.dumps(graph_data)


@pytest.fixture
def graph_file(tmp_path):
    """Create a temp graph file with KNOWLEDGE, LESSON, and regular nodes."""
    nodes = [
        {
            "id": "knowledge_brand_20260101T000000",
            "label": "Target audience is C-suite",
            "entity_type": "KNOWLEDGE",
            "description": "Target audience is C-suite in regulated industries",
            "properties": {
                "domain": "brand",
                "manual": True,
                "created": "20260101T000000",
                "hit_count": 5,
                "source": "graq_learn_knowledge",
            },
        },
        {
            "id": "knowledge_product_20260102T000000",
            "label": "Free tier: 500 nodes",
            "entity_type": "KNOWLEDGE",
            "description": "Free tier: 500 nodes, 3 queries/month",
            "properties": {
                "domain": "product",
                "manual": True,
                "created": "20260102T000000",
                "hit_count": 2,
                "source": "graq_learn_knowledge",
            },
        },
        {
            "id": "lesson_cors",
            "label": "CORS duplicate headers",
            "entity_type": "LESSON",
            "description": "Duplicate CORS headers cause browser rejection",
            "properties": {
                "domain": "technical",
                "manual": True,
                "hit_count": 10,
            },
        },
        {
            "id": "auth-service",
            "label": "Auth Service",
            "entity_type": "SERVICE",
            "description": "Handles JWT authentication",
            "properties": {},
        },
        {
            "id": "manual-concept",
            "label": "My Concept",
            "entity_type": "CONCEPT",
            "description": "A manually added concept",
            "properties": {"manual": True},
        },
    ]
    gpath = tmp_path / "graqle.json"
    gpath.write_text(_make_graph_json(nodes))
    return str(gpath)


class TestLearnedCommand:
    def test_learned_lists_knowledge_and_lessons(self, graph_file):
        result = runner.invoke(app, ["learned", "--graph", graph_file])
        assert result.exit_code == 0
        assert "Learned Nodes (4)" in result.output
        # Check node types appear (Rich table may truncate IDs)
        assert "KNOWLEDGE" in result.output
        assert "LESSON" in result.output
        assert "Total: 4 learned nodes" in result.output
        # Regular non-manual service node should NOT appear
        assert "auth-service" not in result.output

    def test_learned_domain_filter(self, graph_file):
        result = runner.invoke(app, ["learned", "--graph", graph_file, "--domain", "brand"])
        assert result.exit_code == 0
        assert "Learned Nodes (1)" in result.output
        assert "brand" in result.output
        assert "Total: 1 learned nodes" in result.output

    def test_learned_empty_graph(self, tmp_path):
        gpath = tmp_path / "empty.json"
        gpath.write_text(_make_graph_json([{
            "id": "svc",
            "entity_type": "SERVICE",
            "description": "regular service",
        }]))
        result = runner.invoke(app, ["learned", "--graph", str(gpath)])
        assert result.exit_code == 0
        assert "No learned nodes found" in result.output

    def test_learned_missing_graph_file(self):
        result = runner.invoke(app, ["learned", "--graph", "/nonexistent/graph.json"])
        assert result.exit_code == 1

    def test_learned_shows_hit_count(self, graph_file):
        result = runner.invoke(app, ["learned", "--graph", graph_file])
        assert result.exit_code == 0
        # Should show hit counts in the table
        assert "5" in result.output
        assert "10" in result.output
