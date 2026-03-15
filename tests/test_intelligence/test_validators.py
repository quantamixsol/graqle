"""Tests for the 6 validation gates.

Each gate has tests for: pass, fail+autorepair, fail+degrade.
"""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_validators
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, validators, models
# constraints: none
# ── /graqle:intelligence ──

import pytest
from graqle.intelligence.validators import (
    gate_1_parse_integrity,
    gate_2_node_completeness,
    gate_3_chunk_quality,
    gate_4_edge_integrity,
    gate_5_relationship_completeness,
    gate_6_intelligence_compilation,
    run_all_gates,
)
from graqle.intelligence.models import ValidatedNode, ValidatedEdge


# ─── Gate 1: Parse Integrity ───────────────────────────────────────────

class TestGate1ParseIntegrity:
    def test_pass_with_nodes(self):
        nodes = [{"id": "mod.py", "label": "mod.py", "type": "PythonModule"}]
        result = gate_1_parse_integrity(nodes, "mod.py")
        assert result.passed
        assert result.auto_repaired == 0

    def test_autorepair_empty_nodes_with_content(self):
        nodes = []
        content = "def hello():\n    return 'world'\n\ndef foo():\n    pass\n"
        result = gate_1_parse_integrity(nodes, "mod.py", file_content=content)
        assert result.passed  # repaired
        assert result.auto_repaired == 1
        assert len(nodes) == 1  # raw node created
        assert nodes[0]["chunks"]  # has raw chunks

    def test_degrade_empty_nodes_no_content(self):
        nodes = []
        result = gate_1_parse_integrity(nodes, "mod.py", file_content=None)
        assert not result.passed
        assert result.degraded == 1


# ─── Gate 2: Node Completeness ────────────────────────────────────────

class TestGate2NodeCompleteness:
    def test_pass_complete_nodes(self):
        nodes = [{
            "id": "mod.py::hello",
            "label": "hello",
            "type": "Function",
            "description": "A function that returns a greeting string to the caller.",
            "chunks": [{"text": "def hello(): return 'world'", "type": "function"}],
            "properties": {},
        }]
        result, validated = gate_2_node_completeness(nodes, "mod.py")
        assert result.passed
        assert len(validated) == 1
        assert validated[0].description == nodes[0]["description"]

    def test_autorepair_missing_description(self):
        nodes = [{
            "id": "mod.py::foo",
            "label": "foo",
            "type": "Function",
            "description": "",  # empty
            "chunks": [{"text": "def foo(x, y): return x + y", "type": "function"}],
            "properties": {"params": ["x", "y"]},
        }]
        result, validated = gate_2_node_completeness(nodes, "mod.py")
        assert result.auto_repaired >= 1
        assert len(validated) == 1
        assert len(validated[0].description) >= 30  # synthesized

    def test_autorepair_missing_chunks(self):
        nodes = [{
            "id": "mod.py::bar",
            "label": "bar",
            "type": "Function",
            "description": "A function that does bar operations with baz inputs.",
            "chunks": [],  # empty
            "properties": {"file_path": "mod.py"},
        }]
        result, validated = gate_2_node_completeness(nodes, "mod.py")
        assert result.auto_repaired >= 1
        assert len(validated) == 1
        assert len(validated[0].chunks) >= 1  # synthesized

    def test_autorepair_missing_label(self):
        nodes = [{
            "id": "mod.py::some_func",
            "label": "",
            "type": "Function",
            "description": "A function with a missing label that needs repair.",
            "chunks": [{"text": "def some_func(): pass", "type": "function"}],
            "properties": {},
        }]
        result, validated = gate_2_node_completeness(nodes, "mod.py")
        assert result.auto_repaired >= 1
        assert validated[0].label == "some_func"  # derived from id


# ─── Gate 3: Chunk Quality ────────────────────────────────────────────

class TestGate3ChunkQuality:
    def test_pass_good_chunks(self):
        node = ValidatedNode(
            id="test", label="test", entity_type="Function",
            description="A test function for validating chunk quality checks.",
            chunks=[{"text": "def test(): return True", "type": "function"}],
        )
        result = gate_3_chunk_quality([node])
        assert result.passed

    def test_autorepair_import_only_chunk(self):
        node = ValidatedNode(
            id="test", label="test", entity_type="PythonModule",
            description="A module that only contains import statements for dependencies.",
            chunks=[{"text": "import os\nimport sys\nfrom pathlib import Path\n", "type": "file"}],
        )
        result = gate_3_chunk_quality([node])
        assert result.auto_repaired >= 1
        assert node.chunks[0]["type"] == "imports"  # reclassified

    def test_autorepair_missing_chunk_type(self):
        node = ValidatedNode(
            id="test", label="test", entity_type="Function",
            description="A function node with a chunk missing its type annotation.",
            chunks=[{"text": "def process(data): return data.strip()"}],
        )
        result = gate_3_chunk_quality([node])
        assert result.auto_repaired >= 1
        assert node.chunks[0].get("type")  # type inferred

    def test_autorepair_all_boilerplate(self):
        node = ValidatedNode(
            id="test", label="test", entity_type="Function",
            description="A function whose chunks are all too short to be useful.",
            chunks=[{"text": "x", "type": "raw"}, {"text": "y", "type": "raw"}],
        )
        result = gate_3_chunk_quality([node])
        assert result.auto_repaired >= 1
        # Should have synthesized replacement
        assert len(node.chunks) >= 1


# ─── Gate 4: Edge Integrity ───────────────────────────────────────────

class TestGate4EdgeIntegrity:
    def test_pass_valid_edges(self):
        edges = [{"source": "a", "target": "b", "relationship": "IMPORTS"}]
        result, valid, pending = gate_4_edge_integrity(edges, {"a", "b"})
        assert result.passed
        assert len(valid) == 1
        assert len(pending) == 0

    def test_removes_self_loops(self):
        edges = [{"source": "a", "target": "a", "relationship": "CALLS"}]
        result, valid, pending = gate_4_edge_integrity(edges, {"a"})
        assert result.auto_repaired == 1
        assert len(valid) == 0

    def test_deduplicates(self):
        edges = [
            {"source": "a", "target": "b", "relationship": "IMPORTS"},
            {"source": "a", "target": "b", "relationship": "IMPORTS"},  # dup
        ]
        result, valid, pending = gate_4_edge_integrity(edges, {"a", "b"})
        assert result.auto_repaired == 1
        assert len(valid) == 1

    def test_defers_missing_target(self):
        edges = [{"source": "a", "target": "unknown", "relationship": "IMPORTS"}]
        result, valid, pending = gate_4_edge_integrity(edges, {"a"})
        assert len(valid) == 0
        assert len(pending) == 1

    def test_autorepair_edge_type(self):
        edges = [{"source": "a", "target": "b", "relationship": "IMPORT"}]  # missing S
        result, valid, pending = gate_4_edge_integrity(edges, {"a", "b"})
        assert result.auto_repaired == 1
        assert valid[0].relationship == "IMPORTS"


# ─── Gate 5: Relationship Completeness ────────────────────────────────

class TestGate5RelationshipCompleteness:
    def test_adds_missing_defines(self):
        mod = ValidatedNode(
            id="graqle/core/graph.py", label="graph.py",
            entity_type="PythonModule",
            description="Core graph module that manages the knowledge graph.",
            chunks=[{"text": "from __future__ import annotations", "type": "file"}],
            file_path="graqle/core/graph.py",
        )
        func = ValidatedNode(
            id="graqle/core/graph.py::validate", label="validate",
            entity_type="Function",
            description="Validates the knowledge graph for quality and completeness.",
            chunks=[{"text": "def validate(): pass", "type": "function"}],
            file_path="graqle/core/graph.py",
        )
        result, edges = gate_5_relationship_completeness([mod, func], [], "graqle/core/graph.py")
        assert result.auto_repaired >= 1
        assert any(e.relationship == "DEFINES" for e in edges)

    def test_no_duplicate_defines(self):
        mod = ValidatedNode(
            id="mod.py", label="mod.py", entity_type="PythonModule",
            description="A Python module with one function definition inside.",
            chunks=[{"text": "module content here for testing", "type": "file"}],
            file_path="mod.py",
        )
        func = ValidatedNode(
            id="mod.py::fn", label="fn", entity_type="Function",
            description="A function already linked with a DEFINES edge from module.",
            chunks=[{"text": "def fn(): pass", "type": "function"}],
            file_path="mod.py",
        )
        existing = [ValidatedEdge(source="mod.py", target="mod.py::fn", relationship="DEFINES")]
        result, edges = gate_5_relationship_completeness([mod, func], existing, "mod.py")
        defines = [e for e in edges if e.relationship == "DEFINES"]
        assert len(defines) == 1  # no duplicate


# ─── Gate 6: Intelligence Compilation ─────────────────────────────────

class TestGate6IntelligenceCompilation:
    def test_pass_with_nodes(self):
        node = ValidatedNode(
            id="test", label="test", entity_type="Function",
            description="A function that tests the intelligence compilation gate.",
            chunks=[{"text": "def test(): pass", "type": "function"}],
        )
        edge = ValidatedEdge(source="mod", target="test", relationship="DEFINES")
        result = gate_6_intelligence_compilation([node], [edge], "test.py")
        assert result.passed

    def test_fail_no_nodes(self):
        result = gate_6_intelligence_compilation([], [], "empty.py")
        assert not result.passed
        assert result.degraded == 1

    def test_warn_no_edges(self):
        node = ValidatedNode(
            id="isolated", label="isolated", entity_type="Function",
            description="An isolated function with no edges to other nodes.",
            chunks=[{"text": "def isolated(): pass", "type": "function"}],
        )
        result = gate_6_intelligence_compilation([node], [], "isolated.py")
        assert result.passed  # still passes
        assert len(result.warnings) > 0  # but with warning


# ─── Full Pipeline ────────────────────────────────────────────────────

class TestRunAllGates:
    def test_complete_pipeline(self):
        nodes = [{
            "id": "mod.py",
            "label": "mod.py",
            "type": "PythonModule",
            "description": "A Python module serving as the main entry point for the application.",
            "chunks": [{"text": "import os\nimport sys\n\ndef main():\n    print('hello')", "type": "file"}],
            "properties": {"file_path": "mod.py"},
        }, {
            "id": "mod.py::main",
            "label": "main",
            "type": "Function",
            "description": "The main entry point function that initializes the application.",
            "chunks": [{"text": "def main():\n    print('hello')", "type": "function"}],
            "properties": {"file_path": "mod.py"},
        }]
        edges = [
            {"source": "mod.py", "target": "mod.py::main", "relationship": "DEFINES"},
        ]

        results, v_nodes, v_edges, pending = run_all_gates(
            nodes, edges, "mod.py",
            known_node_ids={"mod.py", "mod.py::main"},
        )

        assert len(results) == 6
        assert all(r.passed for r in results)
        assert len(v_nodes) == 2
        assert len(v_edges) >= 1
        assert len(pending) == 0

    def test_pipeline_autorepairs_hollow_node(self):
        """The critical test: hollow node (description but no chunks) gets repaired."""
        nodes = [{
            "id": "hollow.py::MyClass",
            "label": "MyClass",
            "type": "Class",
            "description": "",  # empty
            "chunks": [],       # hollow!
            "properties": {},
        }]
        edges = []

        results, v_nodes, v_edges, pending = run_all_gates(
            nodes, edges, "hollow.py",
        )

        # Node should be repaired, not dropped
        assert len(v_nodes) == 1
        assert len(v_nodes[0].chunks) >= 1  # chunks synthesized
        assert len(v_nodes[0].description) >= 30  # description synthesized
