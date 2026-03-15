"""Chain tests — end-to-end workflows that simulate real user operations.

These tests verify that multi-step operations work correctly together,
not just in isolation. Each test simulates a real user workflow.
"""

# ── graqle:intelligence ──
# module: tests.test_integration.test_chain
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, tempfile, pathlib, mock +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestScanLearnQueryChain:
    """Test: scan repo -> learn knowledge -> query context -> verify."""

    def test_scan_learn_context_roundtrip(self, tmp_path):
        """Full chain: create graph, learn knowledge, query context."""
        from graqle.core.graph import Graqle
        from graqle.config.settings import GraqleConfig

        # Step 1: Create a minimal graph (simulating scan output)
        graph_data = {
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [
                {"id": "auth-service", "label": "Auth Service",
                 "entity_type": "SERVICE", "description": "JWT authentication",
                 "properties": {}},
                {"id": "api-gateway", "label": "API Gateway",
                 "entity_type": "SERVICE", "description": "HTTP routing",
                 "properties": {}},
            ],
            "links": [
                {"source": "api-gateway", "target": "auth-service",
                 "relationship": "CALLS", "weight": 1.0},
            ],
        }
        graph_file = tmp_path / "graqle.json"
        graph_file.write_text(json.dumps(graph_data), encoding="utf-8")

        # Step 2: Load graph
        g = Graqle.from_json(str(graph_file))
        assert len(g.nodes) == 2
        assert len(g.edges) >= 1

        # Step 3: Learn knowledge (add a node)
        g.add_node_simple("k1", label="Auth uses RSA-256",
                          entity_type="KNOWLEDGE",
                          description="Auth service uses RSA-256 for JWT signing")
        assert "k1" in g.nodes

        # Step 4: Save
        g.to_json(str(graph_file))

        # Step 5: Reload (simulates next session)
        g2 = Graqle.from_json(str(graph_file))
        assert "k1" in g2.nodes
        assert g2.nodes["k1"].entity_type == "KNOWLEDGE"
        assert len(g2.nodes) == 3

    def test_edges_key_survives_multiple_saves(self, tmp_path):
        """Graph saved with 'links' key should survive multiple save/load cycles."""
        from graqle.core.graph import Graqle

        graph_data = {
            "directed": True, "multigraph": False, "graph": {},
            "nodes": [
                {"id": "a", "label": "A", "entity_type": "SERVICE",
                 "description": "A", "properties": {}},
                {"id": "b", "label": "B", "entity_type": "SERVICE",
                 "description": "B", "properties": {}},
            ],
            "edges": [  # Note: "edges" not "links"
                {"source": "a", "target": "b", "relationship": "CALLS", "weight": 1.0},
            ],
        }
        p = tmp_path / "g.json"
        p.write_text(json.dumps(graph_data), encoding="utf-8")

        for i in range(5):
            g = Graqle.from_json(str(p))
            g.add_node_simple(f"n{i}", label=f"Node{i}",
                              entity_type="KNOWLEDGE", description=f"Test {i}")
            g.to_json(str(p))

        # Final load should have all nodes
        final = Graqle.from_json(str(p))
        assert len(final.nodes) == 7  # 2 original + 5 added
        assert len(final.edges) >= 1

        # Verify JSON uses "links" key
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "links" in data
        assert "edges" not in data


class TestCredentialsChain:
    """Test: login -> check status -> logout -> verify clean."""

    def test_login_status_logout_chain(self, tmp_path, monkeypatch):
        """Full chain: login, check status, logout, verify clean."""
        from graqle.cloud.credentials import (
            CloudCredentials, save_credentials, load_credentials,
            clear_credentials, get_cloud_status,
        )

        monkeypatch.setattr("graqle.cloud.credentials.CREDENTIALS_FILE",
                            tmp_path / "creds.json")
        monkeypatch.setattr("graqle.cloud.credentials.CREDENTIALS_DIR", tmp_path)

        # Step 1: Not connected
        assert not load_credentials().is_authenticated

        # Step 2: Login
        save_credentials(CloudCredentials(
            api_key="grq_test123", email="user@test.com",
            plan="pro", connected=True,
        ))

        # Step 3: Check status
        status = get_cloud_status()
        assert status["connected"] is True
        assert status["email"] == "user@test.com"
        assert status["plan"] == "pro"

        # Step 4: Logout
        clear_credentials()

        # Step 5: Verify clean
        assert not load_credentials().is_authenticated
        status2 = get_cloud_status()
        assert status2["connected"] is False


class TestOntologyRefinerChain:
    """Test: build graph -> simulate queries -> run refiner -> get suggestions."""

    def test_refiner_with_activation_data(self):
        """Refiner should produce suggestions from activation data."""
        from graqle.learning.ontology_refiner import OntologyRefiner
        from collections import defaultdict
        from dataclasses import dataclass, field
        from unittest.mock import MagicMock

        @dataclass
        class MockRecord:
            activations: int = 0
            useful_activations: int = 0
            avg_confidence: float = 0.0
            query_patterns: list = field(default_factory=list)

        # Build mock graph with diverse types
        graph = MagicMock()
        nodes = {}
        for i in range(10):
            node = MagicMock()
            node.entity_type = "SERVICE"
            nodes[f"svc{i}"] = node
        for i in range(5):
            node = MagicMock()
            node.entity_type = "MODULE"
            nodes[f"mod{i}"] = node
        for i in range(3):
            node = MagicMock()
            node.entity_type = "ENVVAR"
            nodes[f"env{i}"] = node
        graph.nodes = nodes

        # Build mock activation memory with usage patterns
        memory = MagicMock()
        memory._total_queries = 50
        records = {}
        # SERVICE nodes highly active
        for i in range(10):
            records[f"svc{i}"] = MockRecord(
                activations=30, useful_activations=25,
                avg_confidence=0.85,
                query_patterns=["auth", "deploy", "api"],
            )
        # MODULE nodes somewhat active
        for i in range(5):
            records[f"mod{i}"] = MockRecord(
                activations=5, useful_activations=2,
                avg_confidence=0.4,
                query_patterns=["import", "util"],
            )
        # ENVVAR nodes barely used
        for i in range(3):
            records[f"env{i}"] = MockRecord(
                activations=1, useful_activations=0,
                avg_confidence=0.1,
                query_patterns=[],
            )
        memory._records = records

        refiner = OntologyRefiner(memory, graph, min_queries=10)
        suggestions = refiner.analyze()
        assert len(suggestions) > 0

        # Should find SERVICE as high-value
        promoted = [s for s in suggestions if s.action == "promote"]
        assert any("SERVICE" in s.entity_types for s in promoted)

        # Usage report should work
        report = refiner.get_type_usage_report()
        assert report["total_queries"] == 50
        assert "SERVICE" in report["types"]


class TestEntityExtractionChain:
    """Test: entity extraction handles multiple delimiter formats."""

    def test_comma_separated(self):
        """Comma-separated entities should be split correctly."""
        import re
        connects = "React, TypeScript, Zustand, React-Query"
        raw = re.split(r'[,;]\s*|\s+and\s+|\s*\+\s*', connects)
        targets = [t.strip() for t in raw if t.strip()]
        assert len(targets) == 4
        assert "React" in targets
        assert "TypeScript" in targets

    def test_and_separated(self):
        """'and' separated entities should be split."""
        import re
        connects = "React and TypeScript and Zustand"
        raw = re.split(r'[,;]\s*|\s+and\s+|\s*\+\s*', connects)
        targets = [t.strip() for t in raw if t.strip()]
        assert len(targets) == 3

    def test_plus_separated(self):
        """'+' separated entities should be split."""
        import re
        connects = "React + TypeScript + Zustand"
        raw = re.split(r'[,;]\s*|\s+and\s+|\s*\+\s*', connects)
        targets = [t.strip() for t in raw if t.strip()]
        assert len(targets) == 3

    def test_mixed_delimiters(self):
        """Mixed delimiters should all work."""
        import re
        connects = "React, TypeScript; Zustand and React-Query + TailwindCSS"
        raw = re.split(r'[,;]\s*|\s+and\s+|\s*\+\s*', connects)
        targets = [t.strip() for t in raw if t.strip()]
        assert len(targets) == 5
