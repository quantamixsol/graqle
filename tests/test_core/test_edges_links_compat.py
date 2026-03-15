"""Tests for P0-1 fix: edges/links JSON key normalization.

graq scan writes graqle.json with "links" key, but some tools or older
versions may write "edges". The from_json loader must accept both.
"""

# ── graqle:intelligence ──
# module: tests.test_core.test_edges_links_compat
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, tempfile, pathlib, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json

from graqle.core.graph import Graqle


def _minimal_graph_data(edge_key: str = "links") -> dict:
    """Build minimal valid node_link_data with configurable edge key."""
    return {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "a", "label": "A", "entity_type": "SERVICE",
             "description": "Service A", "properties": {}},
            {"id": "b", "label": "B", "entity_type": "SERVICE",
             "description": "Service B", "properties": {}},
        ],
        edge_key: [
            {"source": "a", "target": "b", "relationship": "CALLS", "weight": 1.0},
        ],
    }


class TestEdgesLinksCompat:
    def test_loads_with_links_key(self, tmp_path):
        """Standard 'links' key should work."""
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_minimal_graph_data("links")), encoding="utf-8")
        g = Graqle.from_json(str(p))
        assert len(g.nodes) == 2
        assert len(g.edges) >= 1

    def test_loads_with_edges_key(self, tmp_path):
        """Scanner's 'edges' key should also work (normalized to 'links')."""
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_minimal_graph_data("edges")), encoding="utf-8")
        g = Graqle.from_json(str(p))
        assert len(g.nodes) == 2
        assert len(g.edges) >= 1

    def test_saves_with_links_key(self, tmp_path):
        """to_json must always write 'links' key for consistency."""
        # Load with 'edges' key
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_minimal_graph_data("edges")), encoding="utf-8")
        g = Graqle.from_json(str(p))

        # Save back
        out = tmp_path / "out.json"
        g.to_json(str(out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert "links" in data
        assert "edges" not in data

    def test_roundtrip_preserves_edges(self, tmp_path):
        """Load with 'edges' key, save, reload — edges preserved."""
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_minimal_graph_data("edges")), encoding="utf-8")
        g1 = Graqle.from_json(str(p))

        out = tmp_path / "out.json"
        g1.to_json(str(out))

        g2 = Graqle.from_json(str(out))
        assert len(g2.nodes) == len(g1.nodes)
        assert len(g2.edges) == len(g1.edges)

    def test_scan_learn_cycle_no_crash(self, tmp_path):
        """Simulates the scan→learn→save→learn cycle that was crashing."""
        # Start with scanner output (uses "links" key)
        p = tmp_path / "graqle.json"
        p.write_text(json.dumps(_minimal_graph_data("links")), encoding="utf-8")

        # Load, add a node, save, reload, add another — should not crash
        g = Graqle.from_json(str(p))
        g.add_node_simple("c", label="C", entity_type="KNOWLEDGE",
                          description="Test knowledge")
        g.to_json(str(p))

        g2 = Graqle.from_json(str(p))
        assert "c" in g2.nodes
        g2.add_node_simple("d", label="D", entity_type="KNOWLEDGE",
                           description="More knowledge")
        g2.to_json(str(p))

        g3 = Graqle.from_json(str(p))
        assert "d" in g3.nodes
        assert len(g3.nodes) == 4
