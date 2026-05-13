"""CR-006b regression tests — Neo4j writer preserves typed relationship labels.

Background: pre-CR-006b, Neo4jConnector.save() and migrate_json_to_neo4j() both
hardcoded ``MERGE (a)-[r:RELATED_TO]->(b)`` (and RELATES_TO respectively),
collapsing every typed edge (CALLS, DEFINES, IMPORTS, ...) into a single
``:RELATED_TO`` rel type at write time. After PR-006a fixed the read path,
the live DB still had its 216,577 typed edges from past writes, but every NEW
edge written via ``g.save()``, ``graq learn``, ``graq grow``, or
``graq_predict(fold_back=true)`` would collapse on the way back to Neo4j.

PR-006b groups edge rows by sanitised relationship type and runs one UNWIND
per type with native Cypher rel-type interpolation, mirroring the Neptune
connector pattern. The new ``_sanitise_rel_type`` helper enforces alphanumeric
+ underscore identifier safety with a ``RELATED_TO`` fallback, making Cypher
injection impossible by construction.

These tests are unit-level (no live Neo4j required): they verify the
sanitiser contract directly, plus the generate_migration_cypher emits the
correct shape of statements for typed edges.
"""

from __future__ import annotations

import pytest

from graqle.connectors.neo4j import _sanitise_rel_type
from graqle.connectors.upgrade import generate_migration_cypher


# --- _sanitise_rel_type contract ---------------------------------------------


class TestSanitiseRelType:
    """The sanitiser is the security boundary for native rel-type interpolation."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("CALLS", "CALLS"),
            ("DEFINES", "DEFINES"),
            ("IMPORTS", "IMPORTS"),
            ("calls", "CALLS"),
            ("Calls", "CALLS"),
            ("USES_ENVVAR", "USES_ENVVAR"),
            ("uses envvar", "USES_ENVVAR"),
            ("uses-envvar", "USES_ENVVAR"),
            ("RELATED_TO", "RELATED_TO"),
            ("SEMANTICALLY_RELATED", "SEMANTICALLY_RELATED"),
        ],
    )
    def test_valid_inputs_normalised(self, raw, expected):
        assert _sanitise_rel_type(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "  ",
            "123_starts_with_digit",
            "rel;DROP CONSTRAINT",
            "rel\nMATCH (n) DETACH DELETE n",
            "rel`backticks`",
            "rel{braces}",
            "rel(parens)",
            "rel.dot",
            "rel/slash",
            "rel|pipe",
            42,  # non-string
            ["list"],  # non-string
            {"dict": True},  # non-string
        ],
    )
    def test_invalid_inputs_fall_back_to_related_to(self, raw):
        assert _sanitise_rel_type(raw) == "RELATED_TO"


# --- generate_migration_cypher emits one stmt per relationship type ----------


class TestMigrationCypherTyped:
    """CR-006b: the upgrade migrator must emit one UNWIND per rel type so
    parallel typed edges land as distinct native Neo4j relationships."""

    def test_single_typed_edge_emits_typed_statement(self):
        nodes = {"a": {"id": "a"}, "b": {"id": "b"}}
        edges = {
            "e1": {
                "id": "e1",
                "source": "a",
                "target": "b",
                "relationship": "CALLS",
            },
        }
        stmts = generate_migration_cypher(nodes, edges)
        # constraint + index + nodes + one edges-per-rtype statement
        assert len(stmts) == 4
        edge_stmt = stmts[3]
        assert "MERGE (a)-[r:CALLS" in edge_stmt
        assert "UNWIND $edges_CALLS" in edge_stmt

    def test_three_typed_edges_emit_three_statements(self):
        nodes = {"a": {"id": "a"}, "b": {"id": "b"}}
        edges = {
            "e_calls":   {"id": "e_calls",   "source": "a", "target": "b", "relationship": "CALLS"},
            "e_defines": {"id": "e_defines", "source": "a", "target": "b", "relationship": "DEFINES"},
            "e_imports": {"id": "e_imports", "source": "a", "target": "b", "relationship": "IMPORTS"},
        }
        stmts = generate_migration_cypher(nodes, edges)
        # constraint + index + nodes + 3 typed edge statements
        assert len(stmts) == 6
        edge_stmts = stmts[3:]
        labels_in_stmts = set()
        for s in edge_stmts:
            for lbl in ("CALLS", "DEFINES", "IMPORTS"):
                if f"MERGE (a)-[r:{lbl}" in s:
                    labels_in_stmts.add(lbl)
        assert labels_in_stmts == {"CALLS", "DEFINES", "IMPORTS"}

    def test_caller_regex_extracts_param_name_from_every_generated_statement(self):
        """CR-006b producer/consumer contract: the regex in migrate_json_to_neo4j
        (UNWIND \\$(edges_([A-Z_][A-Z0-9_]*))) MUST match every statement that
        generate_migration_cypher emits. If the producer's format ever changes,
        this test catches the consumer breakage at unit-level (no live Neo4j
        needed) before it hits production.
        """
        import re as _re

        nodes = {"a": {"id": "a"}, "b": {"id": "b"}}
        edges = {
            "e1": {"id": "e1", "source": "a", "target": "b", "relationship": "CALLS"},
            "e2": {"id": "e2", "source": "a", "target": "b", "relationship": "USES_ENVVAR"},
            "e3": {"id": "e3", "source": "a", "target": "b", "relationship": "rel; DROP"},
        }
        stmts = generate_migration_cypher(nodes, edges)

        # Same regex literal as in upgrade.py's migrate_json_to_neo4j caller.
        param_re = _re.compile(r"UNWIND \$(edges_([A-Z_][A-Z0-9_]*))")
        extracted_rtypes = set()
        for stmt in stmts[3:]:  # edge stmts start at index 3
            m = param_re.search(stmt)
            assert m is not None, (
                f"producer/consumer mismatch — caller regex did not match "
                f"generated statement: {stmt!r}"
            )
            param_name, rtype = m.group(1), m.group(2)
            assert param_name == f"edges_{rtype}"
            extracted_rtypes.add(rtype)
        # CALLS and USES_ENVVAR pass through; "rel; DROP" sinks to RELATED_TO.
        assert extracted_rtypes == {"CALLS", "USES_ENVVAR", "RELATED_TO"}

    def test_adversarial_relationship_sanitised_to_related_to(self):
        """A relationship name that's not a valid Cypher identifier must fall
        back to RELATED_TO — never appear in the interpolated Cypher string."""
        nodes = {"a": {"id": "a"}, "b": {"id": "b"}}
        edges = {
            "e_bad": {
                "id": "e_bad",
                "source": "a",
                "target": "b",
                "relationship": "rel; DROP CONSTRAINT cogni_node_id;",
            },
        }
        stmts = generate_migration_cypher(nodes, edges)
        edge_stmt = stmts[3]
        # Sanitised to RELATED_TO; the adversarial payload must NOT appear in
        # the Cypher string.
        assert "MERGE (a)-[r:RELATED_TO" in edge_stmt
        assert "DROP" not in edge_stmt
        assert ";" not in edge_stmt.split("MERGE")[1].split("]")[0]
