"""Tests for BUG 4 fix: impact analysis filters structural edges (CONTAINS, DEFINES).

The old BFS followed ALL edges including CONTAINS, which caused
`graq_impact component=Expertise.tsx` to return the entire components/ directory.
The fix: _bfs_impact skips CONTAINS and DEFINES edges, only following dependency
edges (IMPORTS, CALLS, DEPENDS_ON, etc.).
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_impact_filtering
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, dataclasses, mock, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer


@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str = ""
    properties: dict = field(default_factory=dict)
    degree: int = 2


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float = 1.0


def _build_graph_with_structural_edges():
    """Graph where components/ CONTAINS multiple files, but only some IMPORT each other."""
    nodes = {
        "components": MockNode("components", "components/", "DIRECTORY"),
        "Hero.tsx": MockNode("Hero.tsx", "Hero", "JavaScriptModule"),
        "Contact.tsx": MockNode("Contact.tsx", "Contact", "JavaScriptModule"),
        "Expertise.tsx": MockNode("Expertise.tsx", "Expertise", "JavaScriptModule"),
        "ScrollReveal.tsx": MockNode("ScrollReveal.tsx", "ScrollReveal", "JavaScriptModule"),
        "utils.ts": MockNode("utils.ts", "Utils", "JavaScriptModule"),
    }
    edges = {
        # Structural: directory contains files (should NOT propagate impact)
        "e1": MockEdge("components", "Hero.tsx", "CONTAINS"),
        "e2": MockEdge("components", "Contact.tsx", "CONTAINS"),
        "e3": MockEdge("components", "Expertise.tsx", "CONTAINS"),
        "e4": MockEdge("components", "ScrollReveal.tsx", "CONTAINS"),
        "e5": MockEdge("components", "utils.ts", "CONTAINS"),
        # Dependency: real imports (SHOULD propagate impact)
        "e6": MockEdge("Hero.tsx", "ScrollReveal.tsx", "IMPORTS"),
        "e7": MockEdge("Expertise.tsx", "ScrollReveal.tsx", "IMPORTS"),
        "e8": MockEdge("Contact.tsx", "utils.ts", "IMPORTS"),
    }
    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    return graph


@pytest.fixture
def server():
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = _build_graph_with_structural_edges()
    srv._config = None
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


class TestImpactFiltering:
    @pytest.mark.asyncio
    async def test_impact_skips_contains_edges(self, server):
        """Changing ScrollReveal should NOT affect Contact or components/ dir."""
        result = await server._handle_impact({"component": "ScrollReveal.tsx"})
        data = json.loads(result)
        affected_ids = {item["id"] for item in data["impact_tree"]}

        # Hero and Expertise IMPORT ScrollReveal — they should be affected
        assert "Hero.tsx" in affected_ids
        assert "Expertise.tsx" in affected_ids

        # Contact and components/ dir are NOT dependency-connected — should NOT appear
        assert "Contact.tsx" not in affected_ids
        assert "components" not in affected_ids

    @pytest.mark.asyncio
    async def test_impact_follows_imports(self, server):
        """Changing utils.ts should affect Contact (which IMPORTS it)."""
        result = await server._handle_impact({"component": "utils.ts"})
        data = json.loads(result)
        affected_ids = {item["id"] for item in data["impact_tree"]}

        assert "Contact.tsx" in affected_ids
        # Others don't import utils
        assert "Hero.tsx" not in affected_ids

    @pytest.mark.asyncio
    async def test_old_behavior_would_include_siblings(self, server):
        """Verify the count is small — old behavior returned 17 components."""
        result = await server._handle_impact({"component": "Expertise.tsx"})
        data = json.loads(result)

        # Expertise imports ScrollReveal. ScrollReveal is imported by Hero.
        # So affected = ScrollReveal + Hero = 2 (not all 5 siblings)
        assert data["affected_count"] <= 3

    @pytest.mark.asyncio
    async def test_structural_edges_constant(self, server):
        """_STRUCTURAL_EDGES should contain CONTAINS and DEFINES."""
        assert "CONTAINS" in KogniDevServer._STRUCTURAL_EDGES
        assert "DEFINES" in KogniDevServer._STRUCTURAL_EDGES
