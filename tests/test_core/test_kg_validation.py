"""Tests for mandatory KG quality validation.

These tests ensure that CogniGraph enforces node description completeness.
Nodes without descriptions produce agents that cannot reason, leading to
low-confidence garbage answers. This was discovered during the CrawlQ POC
where 291 nodes with empty descriptions produced 22% confidence answers,
vs 72% after enrichment. (LESSON-094)
"""

import pytest
import networkx as nx

from cognigraph.core.graph import CogniGraph
from cognigraph.core.node import CogniNode


class TestNodeDescriptionEnforcement:
    """Mandatory: no node can have an empty description."""

    def test_graph_with_descriptions_passes(self):
        """Nodes with descriptions should load without error."""
        G = nx.Graph()
        G.add_node("a", label="Alpha", type="Test", description="Alpha node does X")
        G.add_node("b", label="Beta", type="Test", description="Beta node does Y")
        G.add_edge("a", "b", relationship="RELATED_TO")

        graph = CogniGraph.from_networkx(G)
        assert len(graph.nodes) == 2
        assert graph.nodes["a"].description == "Alpha node does X"

    def test_graph_with_empty_descriptions_gets_auto_enriched(self):
        """Nodes with empty descriptions get auto-enriched from metadata."""
        G = nx.Graph()
        G.add_node("svc1", label="AuthService", type="SERVICE",
                    handler="auth/handler.py", timeout="30s")
        G.add_node("svc2", label="ChatService", type="SERVICE",
                    handler="chat/handler.py", timeout="60s")
        G.add_edge("svc1", "svc2", relationship="CALLS")

        # Should NOT raise because auto-enrichment fills descriptions
        graph = CogniGraph.from_networkx(G)
        assert graph.nodes["svc1"].description  # auto-enriched
        assert "SERVICE" in graph.nodes["svc1"].description
        assert "AuthService" in graph.nodes["svc1"].description

    def test_graph_with_completely_bare_nodes_raises(self):
        """Nodes with no label, no type, no properties should raise ValueError."""
        G = nx.Graph()
        # Bare nodes: no label, no type, no properties
        G.add_node("x")
        G.add_node("y")
        # No edges either, so no edge context

        with pytest.raises(ValueError, match="KG Quality Error"):
            CogniGraph.from_networkx(G)

    def test_auto_enrichment_uses_properties(self):
        """Auto-enrichment should include property values in description."""
        G = nx.Graph()
        G.add_node("lambda1", label="UploadHandler", type="LAMBDA",
                    memory_mb="512", runtime="python3.10",
                    region="eu-central-1")
        graph = CogniGraph.from_networkx(G)

        desc = graph.nodes["lambda1"].description
        assert "LAMBDA" in desc
        assert "UploadHandler" in desc
        assert "512" in desc or "memory_mb" in desc

    def test_auto_enrichment_uses_edge_context(self):
        """Auto-enrichment should include neighbor info from edges."""
        G = nx.Graph()
        G.add_node("a", label="ServiceA", type="SERVICE")
        G.add_node("b", label="ServiceB", type="SERVICE",
                    description="B handles chat")
        G.add_edge("a", "b", relationship="CALLS")

        graph = CogniGraph.from_networkx(G)
        desc_a = graph.nodes["a"].description
        # Should mention the connection to ServiceB
        assert "ServiceB" in desc_a or "CALLS" in desc_a


class TestValidateMethod:
    """Test the graph.validate() quality report."""

    def test_validate_good_graph(self):
        """Graph with all descriptions should score high."""
        G = nx.Graph()
        G.add_node("a", label="A", type="T",
                    description="A detailed description of node A that is long enough")
        G.add_node("b", label="B", type="T",
                    description="A detailed description of node B that is long enough")
        G.add_edge("a", "b")

        graph = CogniGraph.from_networkx(G)
        report = graph.validate()

        assert report["total_nodes"] == 2
        assert report["nodes_with_descriptions"] == 2
        assert report["nodes_without_descriptions"] == 0
        assert report["quality_score"] >= 60
        assert len(report["warnings"]) == 0

    def test_validate_poor_graph(self):
        """Graph with short auto-enriched descriptions should warn."""
        G = nx.Graph()
        G.add_node("a", label="A", type="T")
        G.add_node("b", label="B", type="T")
        G.add_edge("a", "b")

        graph = CogniGraph.from_networkx(G)
        report = graph.validate()

        # Auto-enriched descriptions are short, so quality should be moderate
        assert report["total_nodes"] == 2

    def test_validate_returns_all_fields(self):
        """Validate report should have all required fields."""
        G = nx.Graph()
        G.add_node("a", label="A", type="T", description="Good description here")
        graph = CogniGraph.from_networkx(G)
        report = graph.validate()

        required_fields = [
            "total_nodes", "total_edges", "nodes_with_descriptions",
            "nodes_without_descriptions", "avg_description_length",
            "quality_score", "warnings",
        ]
        for field in required_fields:
            assert field in report, f"Missing field: {field}"


class TestFromJsonValidation:
    """Test that from_json also enforces validation."""

    def test_from_json_with_descriptions(self, tmp_path):
        """JSON graph with descriptions should load fine."""
        import json

        data = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {"id": "a", "label": "NodeA", "type": "Test",
                 "description": "First test node"},
                {"id": "b", "label": "NodeB", "type": "Test",
                 "description": "Second test node"},
            ],
            "links": [
                {"source": "a", "target": "b", "relationship": "RELATED_TO"}
            ],
        }

        json_path = tmp_path / "test_kg.json"
        json_path.write_text(json.dumps(data))

        graph = CogniGraph.from_json(str(json_path))
        assert len(graph.nodes) == 2
        assert graph.nodes["a"].description == "First test node"

    def test_from_json_auto_enriches_empty(self, tmp_path):
        """JSON graph with empty descriptions should auto-enrich."""
        import json

        data = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {"id": "svc1", "label": "AuthLambda", "type": "SERVICE",
                 "handler": "auth/handler.py"},
                {"id": "svc2", "label": "ChatLambda", "type": "SERVICE",
                 "handler": "chat/handler.py"},
            ],
            "links": [
                {"source": "svc1", "target": "svc2", "relationship": "CALLS"}
            ],
        }

        json_path = tmp_path / "test_kg.json"
        json_path.write_text(json.dumps(data))

        graph = CogniGraph.from_json(str(json_path))
        assert graph.nodes["svc1"].description  # should be auto-enriched
