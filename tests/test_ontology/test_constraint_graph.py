"""Tests for ConstraintGraph — shared constraint detection and propagation."""

import pytest
import numpy as np

from graqle.ontology.constraint_graph import ConstraintGraph, NodeConstraints
from graqle.core.node import CogniNode
from graqle.core.graph import Graqle
from graqle.core.edge import CogniEdge


def _make_graph_with_nodes():
    """Create a simple test graph with governance nodes."""
    nodes = {
        "gdpr_art22": CogniNode(
            id="gdpr_art22",
            label="GDPR Article 22 - Automated Decision Making",
            entity_type="GOV_REQUIREMENT",
            description="Right not to be subject to automated decision-making including profiling",
            properties={
                "framework": "GDPR",
                "articles": ["Art. 22"],
                "chunks": [{"type": "text", "text": "Human intervention required for automated decisions"}],
            },
        ),
        "ai_act_art14": CogniNode(
            id="ai_act_art14",
            label="AI Act Article 14 - Human Oversight",
            entity_type="GOV_REQUIREMENT",
            description="High-risk AI systems shall be designed to enable human oversight",
            properties={
                "framework": "AI Act",
                "articles": ["Art. 14"],
                "chunks": [{"type": "text", "text": "Human oversight measures for high-risk AI"}],
            },
        ),
        "dora_art28": CogniNode(
            id="dora_art28",
            label="DORA Article 28 - Third-Party ICT Risk",
            entity_type="GOV_REQUIREMENT",
            description="ICT third-party risk management requirements",
            properties={
                "framework": "DORA",
                "articles": ["Art. 28"],
            },
        ),
    }
    edges = {
        "e1": CogniEdge(
            id="e1", source_id="gdpr_art22", target_id="ai_act_art14",
            relationship="MAPS_TO", weight=0.8,
        ),
    }
    nodes["gdpr_art22"].outgoing_edges.append("e1")
    nodes["ai_act_art14"].incoming_edges.append("e1")
    return Graqle(nodes=nodes, edges=edges)


class TestConstraintGraph:
    def test_build_without_embeddings(self):
        graph = _make_graph_with_nodes()
        cg = ConstraintGraph()
        cg.build(graph)
        # Without embeddings, should still extract own constraints
        constraints = cg.get_constraints("gdpr_art22")
        assert constraints.node_id == "gdpr_art22"
        assert len(constraints.own_constraints) > 0
        assert any("GDPR" in c for c in constraints.own_constraints)

    def test_build_with_embeddings_finds_overlap(self):
        graph = _make_graph_with_nodes()

        # Mock embedding function that makes GDPR/AI Act similar
        def mock_embed(text):
            if "GDPR" in text or "human" in text.lower():
                return np.array([1.0, 0.0, 0.5, 0.3])
            if "AI Act" in text or "oversight" in text.lower():
                return np.array([0.9, 0.1, 0.5, 0.3])  # very similar
            return np.array([0.0, 1.0, 0.0, 0.0])  # different

        # Normalize
        def embed(text):
            v = mock_embed(text)
            return v / (np.linalg.norm(v) or 1.0)

        cg = ConstraintGraph(similarity_threshold=0.7, embedding_fn=embed)
        cg.build(graph)

        # GDPR Art 22 and AI Act Art 14 should share a constraint
        constraints_22 = cg.get_constraints("gdpr_art22")
        assert len(constraints_22.propagated_constraints) >= 1

    def test_prompt_text_format(self):
        nc = NodeConstraints(
            node_id="test",
            own_constraints=["Framework: GDPR", "Articles: Art. 22"],
        )
        text = nc.to_prompt_text()
        assert "GDPR" in text
        assert "Art. 22" in text

    def test_empty_constraints(self):
        nc = NodeConstraints(node_id="test")
        assert nc.to_prompt_text() == ""

    def test_reset(self):
        cg = ConstraintGraph()
        graph = _make_graph_with_nodes()
        cg.build(graph)
        cg.reset()
        assert len(cg.shared_constraints) == 0

    def test_stats(self):
        graph = _make_graph_with_nodes()
        cg = ConstraintGraph()
        cg.build(graph)
        stats = cg.stats
        assert "shared_constraints" in stats
        assert "propagations" in stats
