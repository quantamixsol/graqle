"""Tests for GDS Intelligence — link prediction, community detection, node similarity.

Tests both the NetworkX fallback mode (no Neo4j required) and the data structures.
Neo4j GDS tests are skipped unless a live Neo4j instance with GDS plugin is available.
"""

# ── graqle:intelligence ──
# module: tests.test_learning.test_gds_intelligence
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pytest, graph, node, gds_intelligence
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from graqle.learning.gds_intelligence import (
    Community,
    GDSIntelligence,
    GDSReport,
    LinkPrediction,
    SimilarityPair,
)


def _build_test_graph() -> Graqle:
    """Build a small test graph with known structure for predictable results.

    Structure:
        A -- B -- C
        |         |
        D -- E -- F
        |
        G -- H

    Nodes A-F form a cycle-ish structure. G-H are a pendant off D.
    Common neighbors of A and C: B (via A-B, B-C).
    Common neighbors of A and F: D (via A-D, D-E-F? no, need direct).
    """
    graph = Graqle()
    nodes = {
        "A": ("auth-service", "SERVICE", "Handles JWT authentication and session management"),
        "B": ("user-db", "DATABASE", "PostgreSQL database storing user profiles and credentials"),
        "C": ("api-gateway", "SERVICE", "Routes API requests and handles rate limiting"),
        "D": ("payment-service", "SERVICE", "Processes payments via Stripe and PayPal"),
        "E": ("notification-service", "SERVICE", "Sends email and push notifications to users"),
        "F": ("analytics-engine", "SERVICE", "Tracks user behavior and generates reports"),
        "G": ("billing-module", "MODULE", "Generates invoices and handles billing cycles"),
        "H": ("tax-calculator", "MODULE", "Calculates tax rates for different jurisdictions"),
    }
    for nid, (label, etype, desc) in nodes.items():
        graph.add_node_simple(nid, label=label, entity_type=etype, description=desc)

    edges = [
        ("A", "B", "DEPENDS_ON"),
        ("B", "C", "FEEDS"),
        ("A", "D", "CALLS"),
        ("D", "E", "TRIGGERS"),
        ("E", "F", "FEEDS"),
        ("C", "F", "MONITORS"),
        ("D", "G", "CONTAINS"),
        ("G", "H", "USES"),
    ]
    for src, tgt, rel in edges:
        graph.add_edge_simple(src, tgt, relation=rel)

    return graph


class TestLinkPrediction:
    """Test link prediction algorithms (NetworkX mode)."""

    def test_predict_links_returns_results(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=10)
        assert isinstance(predictions, list)
        # Should find at least some predictions in this connected graph
        assert len(predictions) > 0

    def test_predict_links_structure(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=5)
        for pred in predictions:
            assert isinstance(pred, LinkPrediction)
            assert pred.source in graph.nodes
            assert pred.target in graph.nodes
            assert pred.source != pred.target
            assert pred.score > 0
            assert pred.algorithm in (
                "adamic_adar", "common_neighbors", "preferential_attachment"
            )

    def test_predict_links_no_existing_edges(self):
        """Predictions should not include already-existing edges."""
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=50)

        existing_pairs = set()
        for edge in graph.edges.values():
            existing_pairs.add((edge.source_id, edge.target_id))
            existing_pairs.add((edge.target_id, edge.source_id))

        for pred in predictions:
            pair = (pred.source, pred.target)
            assert pair not in existing_pairs, (
                f"Prediction {pred.source}->{pred.target} is already an existing edge"
            )

    def test_predict_links_focus_nodes(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=10, focus_nodes=["A"])
        for pred in predictions:
            assert pred.source == "A" or pred.target == "A"

    def test_predict_links_single_algorithm(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(
            top_k=5, algorithms=["adamic_adar"]
        )
        for pred in predictions:
            assert pred.algorithm == "adamic_adar"

    def test_predict_links_respects_top_k(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=3)
        assert len(predictions) <= 3

    def test_predict_links_sorted_by_score(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links(top_k=10)
        if len(predictions) > 1:
            scores = [p.score for p in predictions]
            assert scores == sorted(scores, reverse=True)

    def test_predict_links_empty_graph(self):
        graph = Graqle()
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links()
        assert predictions == []

    def test_predict_links_single_node(self):
        graph = Graqle()
        graph.add_node_simple("only", label="only", description="lonely node")
        gds = GDSIntelligence(graph)
        predictions = gds.predict_links()
        assert predictions == []


class TestCommunityDetection:
    """Test Louvain community detection (NetworkX mode)."""

    def test_detect_communities_returns_results(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities()
        assert isinstance(communities, list)
        # 8 nodes should form at least 1 community
        assert len(communities) >= 1

    def test_community_structure(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities()
        for comm in communities:
            assert isinstance(comm, Community)
            assert comm.size == len(comm.members)
            assert comm.size >= 2  # min_community_size default
            assert all(m in graph.nodes for m in comm.members)
            assert comm.label  # Auto-generated label

    def test_communities_sorted_by_size(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities()
        if len(communities) > 1:
            sizes = [c.size for c in communities]
            assert sizes == sorted(sizes, reverse=True)

    def test_communities_no_overlap(self):
        """Each node should belong to exactly one community (Louvain property)."""
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities(min_community_size=1)
        all_members = []
        for comm in communities:
            all_members.extend(comm.members)
        # No duplicates
        assert len(all_members) == len(set(all_members))

    def test_communities_min_size(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities(min_community_size=4)
        for comm in communities:
            assert comm.size >= 4

    def test_communities_auto_labels_entity_type(self):
        """Labels should reflect dominant entity type in the community."""
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities(min_community_size=2)
        for comm in communities:
            assert "cluster" in comm.label.lower()
            assert "nodes" in comm.label.lower()

    def test_communities_empty_graph(self):
        graph = Graqle()
        gds = GDSIntelligence(graph)
        communities = gds.detect_communities()
        assert communities == []


class TestNodeSimilarity:
    """Test node similarity (Jaccard/Overlap) via NetworkX mode."""

    def test_find_similar_nodes_returns_results(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        # A and F should have some similarity (both connect to multiple services)
        similarities = gds.find_similar_nodes(top_k=10, min_score=0.01)
        assert isinstance(similarities, list)

    def test_similarity_structure(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        similarities = gds.find_similar_nodes(top_k=10, min_score=0.01)
        for sim in similarities:
            assert isinstance(sim, SimilarityPair)
            assert sim.node_a in graph.nodes
            assert sim.node_b in graph.nodes
            assert sim.node_a != sim.node_b
            assert 0 <= sim.score <= 1.0

    def test_similarity_focus_node(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        similarities = gds.find_similar_nodes("A", top_k=5, min_score=0.01)
        for sim in similarities:
            assert sim.node_a == "A" or sim.node_b == "A"

    def test_similarity_sorted_by_score(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        similarities = gds.find_similar_nodes(top_k=10, min_score=0.01)
        if len(similarities) > 1:
            scores = [s.score for s in similarities]
            assert scores == sorted(scores, reverse=True)

    def test_similarity_jaccard_vs_overlap(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        jaccard = gds.find_similar_nodes(top_k=10, min_score=0.01, metric="jaccard")
        overlap = gds.find_similar_nodes(top_k=10, min_score=0.01, metric="overlap")
        # Overlap scores are >= Jaccard scores for same pairs
        # Just verify both return results
        assert isinstance(jaccard, list)
        assert isinstance(overlap, list)

    def test_similarity_shared_neighbors_populated(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        similarities = gds.find_similar_nodes(top_k=10, min_score=0.01)
        for sim in similarities:
            if sim.score > 0:
                assert len(sim.shared_neighbors) > 0

    def test_similarity_nonexistent_node(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        similarities = gds.find_similar_nodes("NONEXISTENT")
        assert similarities == []


class TestGDSReport:
    """Test the full intelligence report."""

    def test_discover_missing_links(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        report = gds.discover_missing_links(top_k=10)
        assert isinstance(report, GDSReport)
        assert report.method == "networkx"
        assert isinstance(report.link_predictions, list)
        assert isinstance(report.communities, list)
        assert isinstance(report.similarities, list)
        assert "total_nodes" in report.stats
        assert report.stats["total_nodes"] == 8

    def test_discover_with_focus(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        report = gds.discover_missing_links(focus_nodes=["A"], top_k=5)
        # All link predictions should involve A
        for pred in report.link_predictions:
            assert pred.source == "A" or pred.target == "A"

    def test_discover_without_communities(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        report = gds.discover_missing_links(include_communities=False)
        assert report.communities == []


class TestMethodProperty:
    """Test engine detection."""

    def test_default_method_is_networkx(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph)
        assert gds.method == "networkx"

    def test_neo4j_detection_without_connector(self):
        graph = _build_test_graph()
        gds = GDSIntelligence(graph, neo4j_connector=None)
        assert gds.method == "networkx"
        assert not gds._gds_available


class TestDataclasses:
    """Test dataclass constructors and fields."""

    def test_link_prediction_fields(self):
        pred = LinkPrediction(
            source="A", target="B", score=0.85,
            algorithm="adamic_adar", reason="test"
        )
        assert pred.source == "A"
        assert pred.target == "B"
        assert pred.score == 0.85
        assert pred.algorithm == "adamic_adar"

    def test_community_fields(self):
        comm = Community(id=0, members=["A", "B", "C"], size=3, label="test")
        assert comm.id == 0
        assert len(comm.members) == 3
        assert comm.size == 3

    def test_similarity_pair_fields(self):
        pair = SimilarityPair(
            node_a="A", node_b="B", score=0.5, shared_neighbors=["C"]
        )
        assert pair.node_a == "A"
        assert pair.shared_neighbors == ["C"]

    def test_gds_report_fields(self):
        report = GDSReport(
            link_predictions=[], communities=[], similarities=[],
            method="networkx", stats={"total_nodes": 0},
        )
        assert report.method == "networkx"
        assert report.stats["total_nodes"] == 0
