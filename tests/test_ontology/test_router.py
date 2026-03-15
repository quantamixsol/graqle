"""Tests for OntologyRouter — ontology-based message routing."""

# ── graqle:intelligence ──
# module: tests.test_ontology.test_router
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, router, domain_registry, governance, node +2 more
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.ontology.router import OntologyRouter
from graqle.ontology.domain_registry import DomainRegistry
from graqle.ontology.domains.governance import register_governance_domain
from graqle.core.node import CogniNode
from graqle.core.graph import Graqle
from graqle.core.edge import CogniEdge


def _make_governance_graph():
    """Create a test graph with governance nodes and edges."""
    nodes = {
        "req_1": CogniNode(id="req_1", label="GDPR Art 22", entity_type="GOV_REQUIREMENT"),
        "ctrl_1": CogniNode(id="ctrl_1", label="DPIA Control", entity_type="GOV_CONTROL"),
        "enf_1": CogniNode(id="enf_1", label="GDPR Penalty", entity_type="GOV_ENFORCEMENT"),
        "risk_1": CogniNode(id="risk_1", label="High Risk AI", entity_type="GOV_RISK_CATEGORY"),
        "person_1": CogniNode(id="person_1", label="Data Officer", entity_type="PERSON"),
    }
    edges = {
        "e1": CogniEdge(id="e1", source_id="req_1", target_id="ctrl_1",
                        relationship="PART_OF"),
        "e2": CogniEdge(id="e2", source_id="req_1", target_id="enf_1",
                        relationship="NON_COMPLIANCE_LEADS_TO"),
        "e3": CogniEdge(id="e3", source_id="risk_1", target_id="enf_1",
                        relationship="TRIGGERS_ENFORCEMENT"),
        "e4": CogniEdge(id="e4", source_id="req_1", target_id="person_1",
                        relationship="RELATED_TO"),
    }
    # Wire edges
    nodes["req_1"].outgoing_edges = ["e1", "e2", "e4"]
    nodes["ctrl_1"].incoming_edges = ["e1"]
    nodes["enf_1"].incoming_edges = ["e2", "e3"]
    nodes["risk_1"].outgoing_edges = ["e3"]
    nodes["person_1"].incoming_edges = ["e4"]

    return Graqle(nodes=nodes, edges=edges)


class TestOntologyRouter:
    def test_fallback_without_registry(self):
        graph = _make_governance_graph()
        router = OntologyRouter()
        recipients = router.get_valid_recipients(graph, "req_1")
        # Without registry, returns all neighbors
        assert len(recipients) >= 3
        assert router.stats["fallback"] >= 1

    def test_routing_with_governance_ontology(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        graph = _make_governance_graph()
        router = OntologyRouter(registry=registry)

        recipients = router.get_valid_recipients(graph, "req_1")
        # req_1 (GOV_REQUIREMENT) should reach ctrl_1 and enf_1
        assert "ctrl_1" in recipients  # PART_OF has domain=None
        assert "enf_1" in recipients  # NON_COMPLIANCE_LEADS_TO valid

    def test_filters_active_nodes(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        graph = _make_governance_graph()
        router = OntologyRouter(registry=registry)

        active = ["req_1", "enf_1"]
        recipients = router.get_valid_recipients(graph, "req_1", active_node_ids=active)
        # Only active nodes should be in recipients
        for r in recipients:
            assert r in active

    def test_risk_to_enforcement_valid(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        graph = _make_governance_graph()
        router = OntologyRouter(registry=registry)

        recipients = router.get_valid_recipients(graph, "risk_1")
        assert "enf_1" in recipients  # TRIGGERS_ENFORCEMENT valid

    def test_stats_tracking(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        graph = _make_governance_graph()
        router = OntologyRouter(registry=registry)

        router.get_valid_recipients(graph, "req_1")
        stats = router.stats
        assert stats["routed"] > 0 or stats["filtered"] > 0

    def test_reset_stats(self):
        router = OntologyRouter()
        router._stats["routed"] = 5
        router.reset_stats()
        assert router.stats["routed"] == 0
