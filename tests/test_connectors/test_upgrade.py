"""Tests for backend upgrade advisor."""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_upgrade
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, upgrade
# constraints: none
# ── /graqle:intelligence ──

import json
from pathlib import Path

from graqle.connectors.upgrade import (
    assess_upgrade,
    check_neo4j_available,
    generate_migration_cypher,
    UpgradeAssessment,
    NODE_THRESHOLD,
)


class TestAssessUpgrade:

    def test_below_threshold_no_upgrade(self):
        result = assess_upgrade(100, 50, "networkx")
        assert result.should_upgrade is False
        assert result.current_backend == "networkx"

    def test_at_threshold_upgrade(self):
        result = assess_upgrade(5000, 2000, "networkx")
        assert result.should_upgrade is True
        assert result.recommended_backend == "neo4j"
        assert "5,000" in result.reason

    def test_above_threshold_upgrade(self):
        result = assess_upgrade(10000, 5000, "json")
        assert result.should_upgrade is True
        assert result.recommended_backend == "neo4j"

    def test_already_neo4j_no_upgrade(self):
        result = assess_upgrade(10000, 5000, "neo4j")
        assert result.should_upgrade is False

    def test_already_neptune_no_upgrade(self):
        result = assess_upgrade(50000, 20000, "neptune")
        assert result.should_upgrade is False

    def test_latency_triggers_upgrade(self):
        result = assess_upgrade(1000, 500, "networkx", load_time_seconds=6.0)
        assert result.should_upgrade is True
        assert "6.0s" in result.reason

    def test_custom_threshold(self):
        result = assess_upgrade(100, 50, "networkx", node_threshold=50)
        assert result.should_upgrade is True

    def test_summary_property(self):
        result = assess_upgrade(100, 50, "networkx")
        assert "adequate" in result.summary

        result2 = assess_upgrade(6000, 3000, "networkx")
        assert "upgrade" in result2.summary.lower()

    def test_default_threshold_is_5000(self):
        assert NODE_THRESHOLD == 5000


class TestCheckNeo4jAvailable:

    def test_returns_tuple(self):
        available, msg = check_neo4j_available()
        assert isinstance(available, bool)
        assert isinstance(msg, str)


class TestGenerateMigrationCypher:

    def test_empty_graph(self):
        stmts = generate_migration_cypher({}, {})
        assert len(stmts) == 2  # Just schema statements

    def test_with_nodes(self):
        nodes = {"a": {"id": "a", "label": "Auth"}}
        stmts = generate_migration_cypher(nodes, {})
        assert len(stmts) == 3  # schema + nodes
        assert "UNWIND" in stmts[2]
        assert "MERGE" in stmts[2]

    def test_with_edges(self):
        nodes = {"a": {"id": "a"}}
        edges = {"e1": {"source": "a", "target": "b"}}
        stmts = generate_migration_cypher(nodes, edges)
        assert len(stmts) == 4  # schema + nodes + edges
        assert "MATCH" in stmts[3]

    def test_schema_statements(self):
        stmts = generate_migration_cypher({"a": {}}, {})
        assert "CONSTRAINT" in stmts[0]
        assert "INDEX" in stmts[1]

    def test_cypher_uses_unwind_pattern(self):
        """Verifies TAMR+ pipeline pattern: UNWIND batch insert."""
        nodes = {"n1": {"id": "n1"}, "n2": {"id": "n2"}}
        stmts = generate_migration_cypher(nodes, {})
        node_stmt = stmts[2]
        assert "UNWIND $nodes" in node_stmt
        assert "MERGE (n:CogniNode" in node_stmt
