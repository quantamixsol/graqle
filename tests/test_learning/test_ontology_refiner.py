"""Tests for P3-13: Ontology refinement from usage patterns."""

# ── graqle:intelligence ──
# module: tests.test_learning.test_ontology_refiner
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, dataclasses, mock, pytest, ontology_refiner
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from graqle.learning.ontology_refiner import OntologyRefiner


@dataclass
class MockNodeRecord:
    activations: int = 0
    useful_activations: int = 0
    avg_confidence: float = 0.0
    query_patterns: list = field(default_factory=list)


def _make_mock_graph(nodes_by_type: dict[str, list[str]]) -> MagicMock:
    """Create a mock graph with nodes grouped by entity type."""
    graph = MagicMock()
    nodes = {}
    for etype, nids in nodes_by_type.items():
        for nid in nids:
            node = MagicMock()
            node.entity_type = etype
            nodes[nid] = node
    graph.nodes = nodes
    return graph


def _make_mock_memory(
    total_queries: int,
    records: dict[str, MockNodeRecord],
) -> MagicMock:
    """Create a mock activation memory."""
    memory = MagicMock()
    memory._total_queries = total_queries
    memory._records = records
    return memory


class TestOntologyRefiner:
    def test_insufficient_queries_returns_empty(self):
        """Refiner should return empty if too few queries."""
        memory = _make_mock_memory(5, {})
        graph = _make_mock_graph({"SERVICE": ["s1"]})
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        assert refiner.analyze() == []

    def test_underused_type_detected(self):
        """Types with many nodes but few activations should be flagged."""
        records = {
            "s1": MockNodeRecord(activations=50, useful_activations=40, query_patterns=["auth", "api"]),
            "s2": MockNodeRecord(activations=45, useful_activations=30, query_patterns=["deploy"]),
            "m1": MockNodeRecord(activations=1, useful_activations=0, query_patterns=[]),
            "m2": MockNodeRecord(activations=0, useful_activations=0, query_patterns=[]),
            "m3": MockNodeRecord(activations=1, useful_activations=0, query_patterns=[]),
        }
        memory = _make_mock_memory(20, records)
        graph = _make_mock_graph({
            "SERVICE": ["s1", "s2"],
            "MOAT_MODULE": ["m1", "m2", "m3"],
        })
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()

        underused = [s for s in suggestions if s.action == "review"]
        assert len(underused) >= 1
        assert any("MOAT_MODULE" in s.entity_types for s in underused)

    def test_coactivation_detected(self):
        """Types with high pattern overlap should be flagged."""
        shared = ["auth", "security", "jwt", "token", "verify"]
        records = {
            "s1": MockNodeRecord(activations=20, useful_activations=15,
                                 query_patterns=shared + ["deploy"]),
            "e1": MockNodeRecord(activations=18, useful_activations=12,
                                 query_patterns=shared + ["env"]),
        }
        memory = _make_mock_memory(25, records)
        graph = _make_mock_graph({
            "SERVICE": ["s1"],
            "ENVVAR": ["e1"],
        })
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()

        coactive = [s for s in suggestions if s.action == "add_relationship"]
        assert len(coactive) >= 1

    def test_high_value_type_promoted(self):
        """Types with high usefulness should get promote suggestion."""
        records = {
            "s1": MockNodeRecord(activations=20, useful_activations=18,
                                 avg_confidence=0.85, query_patterns=["deploy"]),
            "s2": MockNodeRecord(activations=15, useful_activations=14,
                                 avg_confidence=0.80, query_patterns=["api"]),
        }
        memory = _make_mock_memory(30, records)
        graph = _make_mock_graph({"SERVICE": ["s1", "s2"]})
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()

        promoted = [s for s in suggestions if s.action == "promote"]
        assert len(promoted) >= 1
        assert "SERVICE" in promoted[0].entity_types

    def test_type_usage_report(self):
        """get_type_usage_report should return structured report."""
        records = {
            "s1": MockNodeRecord(activations=10, useful_activations=8, query_patterns=["test"]),
        }
        memory = _make_mock_memory(15, records)
        graph = _make_mock_graph({"SERVICE": ["s1"], "MODULE": ["m1"]})
        refiner = OntologyRefiner(memory, graph)
        report = refiner.get_type_usage_report()

        assert report["total_queries"] == 15
        assert "SERVICE" in report["types"]
        assert "MODULE" in report["types"]
        assert report["types"]["SERVICE"]["activations"] == 10

    def test_suggestions_sorted_by_confidence(self):
        """Suggestions should be sorted by confidence descending."""
        records = {
            "s1": MockNodeRecord(activations=50, useful_activations=48,
                                 avg_confidence=0.9, query_patterns=["auth", "jwt"]),
            "s2": MockNodeRecord(activations=45, useful_activations=40,
                                 avg_confidence=0.8, query_patterns=["auth", "jwt"]),
            "m1": MockNodeRecord(activations=1, useful_activations=0, query_patterns=[]),
            "m2": MockNodeRecord(activations=0, useful_activations=0, query_patterns=[]),
            "m3": MockNodeRecord(activations=1, useful_activations=0, query_patterns=[]),
        }
        memory = _make_mock_memory(30, records)
        graph = _make_mock_graph({
            "SERVICE": ["s1", "s2"],
            "MOAT_MODULE": ["m1", "m2", "m3"],
        })
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()

        if len(suggestions) >= 2:
            for i in range(len(suggestions) - 1):
                assert suggestions[i].confidence >= suggestions[i + 1].confidence

    def test_meta_types_excluded_from_underuse(self):
        """KNOWLEDGE and LESSON types should not be flagged as underused."""
        records = {
            "k1": MockNodeRecord(activations=0, useful_activations=0, query_patterns=[]),
            "k2": MockNodeRecord(activations=0, useful_activations=0, query_patterns=[]),
            "s1": MockNodeRecord(activations=50, useful_activations=40, query_patterns=["test"]),
        }
        memory = _make_mock_memory(20, records)
        graph = _make_mock_graph({
            "KNOWLEDGE": ["k1", "k2"],
            "SERVICE": ["s1"],
        })
        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()

        underused = [s for s in suggestions if s.action == "review"]
        assert not any("KNOWLEDGE" in s.entity_types for s in underused)
