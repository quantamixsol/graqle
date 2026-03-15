"""Tests for intelligence data models."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_models
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, models
# constraints: none
# ── /graqle:intelligence ──

import pytest
from graqle.intelligence.models import (
    CoverageReport,
    CuriosityInsight,
    FileIntelligenceUnit,
    InsightCategory,
    ModulePacket,
    PublicInterface,
    ValidationGateResult,
    ValidationStatus,
    ValidatedEdge,
    ValidatedNode,
)


class TestValidatedNode:
    def test_valid_node(self):
        node = ValidatedNode(
            id="graqle/core/graph.py::Graqle",
            label="Graqle",
            entity_type="Class",
            description="Core graph class that manages the knowledge graph.",
            chunks=[{"text": "class Graqle:\n    def __init__(self):", "type": "class"}],
        )
        assert node.chunk_count == 1
        assert not node.has_source

    def test_node_with_source(self):
        node = ValidatedNode(
            id="test",
            label="test_func",
            entity_type="Function",
            description="A test function that validates input data.",
            chunks=[{"text": "def test(): pass", "type": "function"}],
            file_path="tests/test_core.py",
        )
        assert node.has_source

    def test_node_rejects_short_description(self):
        with pytest.raises(Exception):
            ValidatedNode(
                id="x", label="x", entity_type="Function",
                description="too short",
                chunks=[{"text": "content here"}],
            )

    def test_node_rejects_empty_chunks(self):
        with pytest.raises(Exception):
            ValidatedNode(
                id="x", label="x", entity_type="Function",
                description="A sufficiently long description for this node.",
                chunks=[],
            )


class TestValidatedEdge:
    def test_valid_edge(self):
        edge = ValidatedEdge(
            source="mod_a", target="mod_b", relationship="IMPORTS"
        )
        assert edge.source == "mod_a"

    def test_edge_with_properties(self):
        edge = ValidatedEdge(
            source="a", target="b", relationship="CALLS",
            properties={"line": 42},
        )
        assert edge.properties["line"] == 42


class TestCoverageReport:
    def test_perfect_coverage(self):
        report = CoverageReport(
            total_nodes=10, nodes_with_chunks=10, nodes_with_descriptions=10,
            total_edges=20, valid_edges=20,
        )
        assert report.chunk_coverage == 100.0
        assert report.description_coverage == 100.0
        assert report.edge_integrity == 100.0
        assert report.health == "HEALTHY"

    def test_warning_coverage(self):
        report = CoverageReport(
            total_nodes=10, nodes_with_chunks=8, nodes_with_descriptions=9,
            total_edges=20, valid_edges=19,
        )
        assert report.chunk_coverage == 80.0
        assert report.health == "WARNING"

    def test_critical_coverage(self):
        report = CoverageReport(
            total_nodes=10, nodes_with_chunks=5, nodes_with_descriptions=5,
            total_edges=20, valid_edges=10,
        )
        assert report.chunk_coverage == 50.0
        assert report.health == "CRITICAL"

    def test_empty_report(self):
        report = CoverageReport()
        assert report.chunk_coverage == 100.0
        assert report.health == "HEALTHY"


class TestModulePacket:
    def test_basic_packet(self):
        pkt = ModulePacket(
            module="graqle.core.graph",
            files=["graqle/core/graph.py"],
            node_count=42,
            function_count=35,
            class_count=3,
        )
        assert pkt.consumer_count == 0
        assert pkt.dependency_count == 0
        assert pkt.risk_level == "LOW"

    def test_packet_with_consumers(self):
        from graqle.intelligence.models import ModuleConsumer
        pkt = ModulePacket(
            module="graqle.core.graph",
            files=["graqle/core/graph.py"],
            consumers=[
                ModuleConsumer(module="graqle.cli.commands.scan"),
                ModuleConsumer(module="graqle.activation.pcst"),
            ],
        )
        assert pkt.consumer_count == 2


class TestFileIntelligenceUnit:
    def test_healthy_unit(self):
        node = ValidatedNode(
            id="test_mod",
            label="test_mod.py",
            entity_type="PythonModule",
            description="A test module for validating intelligence pipeline.",
            chunks=[{"text": "def main(): print('hello')", "type": "function"}],
        )
        unit = FileIntelligenceUnit(
            file_path="test_mod.py",
            nodes=[node],
            edges=[],
            module_packet=ModulePacket(module="test_mod", files=["test_mod.py"]),
            coverage=CoverageReport(total_nodes=1, nodes_with_chunks=1, nodes_with_descriptions=1),
            validation_status=ValidationStatus.PASS,
        )
        assert unit.is_healthy
        assert unit.node_count == 1

    def test_degraded_unit(self):
        node = ValidatedNode(
            id="broken",
            label="broken.py",
            entity_type="PythonModule",
            description="A broken module that failed full validation.",
            chunks=[{"text": "raw fallback content here", "type": "raw"}],
        )
        unit = FileIntelligenceUnit(
            file_path="broken.py",
            nodes=[node],
            edges=[],
            module_packet=ModulePacket(module="broken", files=["broken.py"]),
            coverage=CoverageReport(total_nodes=1, degraded_nodes=1),
            validation_status=ValidationStatus.DEGRADED,
        )
        assert not unit.is_healthy


class TestCuriosityInsight:
    def test_superlative_insight(self):
        insight = CuriosityInsight(
            category=InsightCategory.SUPERLATIVE,
            module="graqle.core.graph",
            message="THE MOST IMPORTED MODULE — 49 consumers.",
            metric="49 consumers",
            severity="critical",
        )
        assert insight.category == InsightCategory.SUPERLATIVE
        assert "49" in insight.message
