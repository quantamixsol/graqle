"""Tests for backend upgrade advisor."""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_upgrade
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, upgrade
# constraints: none
# ── /graqle:intelligence ──


import json
from unittest.mock import MagicMock, patch

import pytest

from graqle.connectors.upgrade import (
    NODE_THRESHOLD,
    _sanitise_for_neo4j_props,
    assess_upgrade,
    check_neo4j_available,
    generate_migration_cypher,
    migrate_json_to_neo4j,
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


class TestSanitiseForNeo4jProps:
    """Hot-fix 2026-04-16: nested maps must be JSON-stringified or Neo4j rejects.

    Reason: previously the migrator passed Map values straight to UNWIND ... SET
    n += node.properties, which raised CypherTypeError("Property values can only
    be of primitive types or arrays thereof") on any real scanned KG.
    """

    def test_primitive_values_pass_through(self):
        out = _sanitise_for_neo4j_props(
            {"name": "x", "score": 0.5, "tags": ["a", "b"]},
            owner_id="n1",
            owner_kind="node",
        )
        assert out == {"name": "x", "score": 0.5, "tags": ["a", "b"]}

    def test_dict_value_is_json_stringified(self):
        out = _sanitise_for_neo4j_props(
            {"meta": {"k": "v", "n": 1}},
            owner_id="n1",
            owner_kind="node",
        )
        assert isinstance(out["meta"], str)
        assert json.loads(out["meta"]) == {"k": "v", "n": 1}

    def test_list_of_dicts_is_json_stringified(self):
        out = _sanitise_for_neo4j_props(
            {"items": [{"x": 1}, {"y": 2}]},
            owner_id="e1",
            owner_kind="edge",
        )
        assert isinstance(out["items"], str)
        assert json.loads(out["items"]) == [{"x": 1}, {"y": 2}]

    def test_list_of_primitives_pass_through(self):
        out = _sanitise_for_neo4j_props(
            {"versions": ["1.0", "2.0"]},
            owner_id="n1",
            owner_kind="node",
        )
        assert out["versions"] == ["1.0", "2.0"]


class TestMigrateJsonToNeo4j:
    """Hot-fix 2026-04-16: chunks must become :Chunk nodes, not scalar props.

    Reason: previously the migrator dumped the `chunks` list of dicts into
    CogniNode.chunks as a property. Neo4j rejects nested maps, so
    migrate_json_to_neo4j crashed on any KG that came from `graq scan`.
    Even when sanitised to a JSON string, it broke Neo4jConnector queries
    that expect (CogniNode)-[:HAS_CHUNK]->(:Chunk) graph structure.
    """

    @pytest.fixture()
    def kg_with_chunks(self, tmp_path):
        kg = {
            "nodes": [
                {
                    "id": "module/auth.py",
                    "label": "auth.py",
                    "entity_type": "PythonModule",
                    "description": "Auth module",
                    "chunks": [
                        {"text": "def login(): ...", "type": "function"},
                        {"text": "def logout(): ...", "type": "function"},
                    ],
                    "scalar_prop": "ok",
                    "nested_prop": {"a": 1},
                },
                {"id": "module/empty.py", "label": "empty.py", "entity_type": "PythonModule"},
            ],
            "edges": [
                {"id": "e1", "source": "module/auth.py", "target": "module/empty.py", "relationship": "IMPORTS"}
            ],
        }
        path = tmp_path / "test_kg.json"
        path.write_text(json.dumps(kg), encoding="utf-8")
        return path

    def test_migration_extracts_chunks_to_save_chunks(self, kg_with_chunks):
        # Mock both the bare driver AND the Neo4jConnector so the test runs
        # without a live Neo4j instance. Patching at the upgrade.py module level
        # via the lazy `import graqle.connectors.neo4j as _neo4j_conn_mod`
        # access pattern.
        import graqle.connectors.neo4j as neo4j_mod

        original_cls = neo4j_mod.Neo4jConnector
        mock_connector = MagicMock()
        mock_connector.save_chunks.return_value = 2
        mock_connector_cls = MagicMock(return_value=mock_connector)

        with patch("neo4j.GraphDatabase.driver") as mock_driver:
            mock_session = MagicMock()
            mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
            try:
                neo4j_mod.Neo4jConnector = mock_connector_cls
                result = migrate_json_to_neo4j(
                    json_path=str(kg_with_chunks),
                    neo4j_uri="bolt://x:7687",
                    neo4j_user="neo4j",
                    neo4j_password="pw",
                    neo4j_database="testdb",
                )
            finally:
                neo4j_mod.Neo4jConnector = original_cls

        assert result["status"] == "migrated"
        assert result["nodes_migrated"] == 2
        assert result["edges_migrated"] == 1
        assert result["chunks_migrated"] == 2

        # save_chunks was called with the chunks-keyed-by-node dict
        mock_connector.save_chunks.assert_called_once()
        chunks_arg = mock_connector.save_chunks.call_args[0][0]
        assert "module/auth.py" in chunks_arg
        assert len(chunks_arg["module/auth.py"]) == 2
        assert "module/empty.py" not in chunks_arg  # no chunks → not included

    def test_chunks_property_not_passed_into_node_props(self, kg_with_chunks):
        import graqle.connectors.neo4j as neo4j_mod

        original_cls = neo4j_mod.Neo4jConnector
        mock_connector_cls = MagicMock(
            return_value=MagicMock(save_chunks=MagicMock(return_value=0))
        )
        with patch("neo4j.GraphDatabase.driver") as mock_driver:
            mock_session = MagicMock()
            mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
            try:
                neo4j_mod.Neo4jConnector = mock_connector_cls
                migrate_json_to_neo4j(
                    json_path=str(kg_with_chunks),
                    neo4j_uri="bolt://x:7687",
                    neo4j_user="neo4j",
                    neo4j_password="pw",
                    neo4j_database="testdb",
                )
            finally:
                neo4j_mod.Neo4jConnector = original_cls

        # Find the node-batch UNWIND call and verify chunks isn't in any node's properties
        node_call = next(
            c for c in mock_session.run.call_args_list
            if c.args and "UNWIND $nodes" in c.args[0]
        )
        for node in node_call.kwargs["nodes"]:
            assert "chunks" not in node["properties"], \
                f"chunks leaked into node {node['id']} properties: {node['properties']}"

    def test_nested_map_props_are_sanitised_not_crashed(self, kg_with_chunks):
        # The `nested_prop = {"a": 1}` on module/auth.py must be JSON-stringified,
        # not passed through (which would crash Neo4j) and not silently dropped.
        import graqle.connectors.neo4j as neo4j_mod

        original_cls = neo4j_mod.Neo4jConnector
        mock_connector_cls = MagicMock(
            return_value=MagicMock(save_chunks=MagicMock(return_value=0))
        )
        with patch("neo4j.GraphDatabase.driver") as mock_driver:
            mock_session = MagicMock()
            mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
            try:
                neo4j_mod.Neo4jConnector = mock_connector_cls
                migrate_json_to_neo4j(
                    json_path=str(kg_with_chunks),
                    neo4j_uri="bolt://x:7687",
                    neo4j_user="neo4j",
                    neo4j_password="pw",
                    neo4j_database="testdb",
                )
            finally:
                neo4j_mod.Neo4jConnector = original_cls

        node_call = next(
            c for c in mock_session.run.call_args_list
            if c.args and "UNWIND $nodes" in c.args[0]
        )
        auth_node = next(n for n in node_call.kwargs["nodes"] if n["id"] == "module/auth.py")
        # Sanitised to JSON string, not the raw dict
        assert isinstance(auth_node["properties"]["nested_prop"], str)
        assert json.loads(auth_node["properties"]["nested_prop"]) == {"a": 1}
        # Primitive props untouched
        assert auth_node["properties"]["scalar_prop"] == "ok"

    def test_kg_without_chunks_does_not_call_neo4j_connector(self, tmp_path):
        # When no node has chunks, we should NOT lazily import + instantiate the connector.
        kg = {"nodes": [{"id": "n1", "label": "n1"}], "edges": []}
        path = tmp_path / "no_chunks.json"
        path.write_text(json.dumps(kg), encoding="utf-8")

        import graqle.connectors.neo4j as neo4j_mod

        original_cls = neo4j_mod.Neo4jConnector
        mock_connector_cls = MagicMock()
        with patch("neo4j.GraphDatabase.driver") as mock_driver:
            mock_session = MagicMock()
            mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
            try:
                neo4j_mod.Neo4jConnector = mock_connector_cls
                result = migrate_json_to_neo4j(
                    json_path=str(path),
                    neo4j_uri="bolt://x:7687",
                    neo4j_user="neo4j",
                    neo4j_password="pw",
                    neo4j_database="testdb",
                )
            finally:
                neo4j_mod.Neo4jConnector = original_cls

        assert result["chunks_migrated"] == 0
        mock_connector_cls.assert_not_called()
