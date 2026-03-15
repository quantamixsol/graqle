"""Tests for graq link CLI subcommands (v0.15.0 — multi-project support)."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_link
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, mock, pytest +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.commands.link import link_app

runner = CliRunner()


@pytest.fixture
def sample_graphs(tmp_path):
    """Create two small graph JSON files for merge testing."""
    g1 = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "auth-lambda", "label": "Auth", "entity_type": "SERVICE",
             "description": "Auth service", "properties": {}},
            {"id": "users-db", "label": "Users DB", "entity_type": "DATABASE",
             "description": "User store", "properties": {}},
        ],
        "links": [
            {"source": "auth-lambda", "target": "users-db", "relationship": "READS_FROM"},
        ],
    }
    g2 = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "retrieval", "label": "Retrieval", "entity_type": "MODULE",
             "description": "Document retrieval", "properties": {}},
        ],
        "links": [],
    }

    p1 = tmp_path / "project1"
    p1.mkdir()
    (p1 / "graqle.json").write_text(json.dumps(g1))

    p2 = tmp_path / "project2"
    p2.mkdir()
    (p2 / "graqle.json").write_text(json.dumps(g2))

    return p1 / "graqle.json", p2 / "graqle.json", tmp_path


class TestLinkMerge:
    def test_merge_two_graphs(self, sample_graphs):
        g1, g2, tmp = sample_graphs
        output = tmp / "merged.json"

        result = runner.invoke(link_app, [
            "merge", str(g1), str(g2), "--output", str(output),
        ])
        assert result.exit_code == 0
        assert "Merged 2 projects" in result.output

        merged = json.loads(output.read_text())
        assert len(merged["nodes"]) == 3  # 2 + 1
        assert len(merged["links"]) == 1

        # Check prefixing
        node_ids = {n["id"] for n in merged["nodes"]}
        assert "project1/auth-lambda" in node_ids
        assert "project2/retrieval" in node_ids

    def test_merge_no_prefix(self, sample_graphs):
        g1, g2, tmp = sample_graphs
        output = tmp / "merged_noprefix.json"

        result = runner.invoke(link_app, [
            "merge", str(g1), str(g2), "--output", str(output), "--no-prefix",
        ])
        assert result.exit_code == 0

        merged = json.loads(output.read_text())
        node_ids = {n["id"] for n in merged["nodes"]}
        assert "auth-lambda" in node_ids  # No prefix

    def test_merge_needs_two_files(self, sample_graphs):
        g1, _, _ = sample_graphs
        result = runner.invoke(link_app, ["merge", str(g1)])
        assert result.exit_code != 0

    def test_merge_skips_missing(self, sample_graphs):
        g1, _, tmp = sample_graphs
        output = tmp / "merged.json"
        result = runner.invoke(link_app, [
            "merge", str(g1), "/nonexistent/graph.json", "--output", str(output),
        ])
        # Should still succeed but skip missing file
        assert "Skipping" in result.output


class TestLinkStats:
    def test_stats_basic(self, sample_graphs):
        g1, g2, tmp = sample_graphs
        output = tmp / "merged.json"

        # First merge
        runner.invoke(link_app, [
            "merge", str(g1), str(g2), "--output", str(output),
        ])

        result = runner.invoke(link_app, ["stats", str(output)])
        assert result.exit_code == 0
        assert "Multi-Project Graph Stats" in result.output
        assert "3" in result.output  # 3 nodes

    def test_stats_missing_file(self):
        result = runner.invoke(link_app, ["stats", "/no/such/file.json"])
        assert result.exit_code != 0
