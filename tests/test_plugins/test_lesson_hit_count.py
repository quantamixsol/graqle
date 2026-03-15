"""Tests for BUG-7 fix: lesson hit_count incremented when lessons are surfaced.

Verifies that _handle_lessons, _handle_preflight, and _find_lesson_nodes
properly increment hit_count on matched lesson nodes and persist via _save_graph.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_lesson_hit_count
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, dataclasses, typing, mock +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from graqle.plugins.mcp_dev_server import KogniDevServer

# ---------------------------------------------------------------------------
# Mock graph objects (same pattern as test_mcp_dev_server.py)
# ---------------------------------------------------------------------------

@dataclass
class MockNode:
    id: str
    label: str
    entity_type: str
    description: str
    properties: dict = field(default_factory=dict)
    degree: int = 2
    status: str = "ACTIVE"


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    weight: float = 1.0


@dataclass
class MockStats:
    total_nodes: int = 4
    total_edges: int = 2
    avg_degree: float = 1.0
    density: float = 0.5
    connected_components: int = 1
    hub_nodes: list = field(default_factory=lambda: ["auth-lambda"])


def _build_mock_graph() -> MagicMock:
    """Build a mock graph with lesson nodes that have hit_count tracking."""
    nodes = {
        "auth-lambda": MockNode(
            id="auth-lambda",
            label="Auth Lambda",
            entity_type="service",
            description="JWT verification and authentication.",
            properties={"runtime": "python3.11"},
        ),
        "lesson-cors": MockNode(
            id="lesson-cors",
            label="CORS Double-Header Bug",
            entity_type="LESSON",
            description="Duplicate CORS headers cause browser rejection.",
            properties={"severity": "CRITICAL", "hit_count": 0},
        ),
        "lesson-deploy": MockNode(
            id="lesson-deploy",
            label="Deploy verification required",
            entity_type="LESSON",
            description="Always verify deployment with curl after Lambda deploy.",
            properties={"severity": "HIGH", "hit_count": 0},
        ),
        "mistake-env": MockNode(
            id="mistake-env",
            label="Missing NEO4J_PASSWORD",
            entity_type="MISTAKE",
            description="Lambda failed because NEO4J_PASSWORD env var was not set.",
            properties={"severity": "CRITICAL", "hit_count": 0},
        ),
    }

    edges = {
        "e1": MockEdge(source_id="auth-lambda", target_id="lesson-cors", relationship="HAS_LESSON"),
        "e2": MockEdge(source_id="auth-lambda", target_id="mistake-env", relationship="HAS_MISTAKE"),
    }

    graph = MagicMock()
    graph.nodes = nodes
    graph.edges = edges
    graph.stats = MockStats()
    return graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graph():
    return _build_mock_graph()


@pytest.fixture
def server(mock_graph):
    """KogniDevServer with graph pre-injected."""
    srv = KogniDevServer.__new__(KogniDevServer)
    srv.config_path = "graqle.yaml"
    srv.read_only = False
    srv._graph = mock_graph
    srv._config = None
    srv._graph_file = "graqle.json"
    srv._graph_mtime = 9999999999.0
    return srv


# ---------------------------------------------------------------------------
# Tests: lesson nodes start with hits=0
# ---------------------------------------------------------------------------

class TestLessonHitCountInitial:
    def test_lesson_starts_with_zero_hits(self, mock_graph):
        """Lesson nodes should start with hit_count=0."""
        node = mock_graph.nodes["lesson-cors"]
        assert node.properties.get("hit_count", 0) == 0

    def test_lesson_without_hit_count_key(self):
        """A lesson node with no hit_count key defaults to 0."""
        node = MockNode(
            id="lesson-new",
            label="New lesson",
            entity_type="LESSON",
            description="A fresh lesson with no hit_count.",
            properties={"severity": "MEDIUM"},
        )
        assert node.properties.get("hit_count", 0) == 0


# ---------------------------------------------------------------------------
# Tests: _handle_lessons increments hit_count
# ---------------------------------------------------------------------------

class TestHandleLessonsIncrements:
    @pytest.mark.asyncio
    async def test_handle_lessons_increments_hit_count(self, server, mock_graph):
        """After _handle_lessons returns lessons, hit_count should be 1."""
        with patch.object(server, "_save_graph") as mock_save:
            result = await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "all"}
            )

        data = json.loads(result)
        assert data["count"] >= 1

        # The CORS lesson node should have been incremented
        cors_node = mock_graph.nodes["lesson-cors"]
        assert cors_node.properties["hit_count"] == 1

        # _save_graph should have been called
        mock_save.assert_called()

    @pytest.mark.asyncio
    async def test_handle_lessons_returns_updated_hit_count(self, server, mock_graph):
        """The returned lesson data should reflect the incremented hit_count."""
        with patch.object(server, "_save_graph"):
            result = await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "all"}
            )

        data = json.loads(result)
        cors_lessons = [l for l in data["lessons"] if l["id"] == "lesson-cors"]
        assert len(cors_lessons) == 1
        assert cors_lessons[0]["hit_count"] == 1


# ---------------------------------------------------------------------------
# Tests: _handle_preflight increments hit_count
# ---------------------------------------------------------------------------

class TestHandlePreflightIncrements:
    @pytest.mark.asyncio
    async def test_preflight_increments_hit_count(self, server, mock_graph):
        """After _handle_preflight surfaces lessons, hit_count should be incremented."""
        with patch.object(server, "_save_graph") as mock_save:
            result = await server.handle_tool(
                "graq_preflight", {"action": "deploy CORS Lambda", "files": []}
            )

        data = json.loads(result)
        # Preflight should find CORS-related lessons
        all_entries = data["lessons"] + data.get("safety_boundaries", [])
        assert len(all_entries) >= 1

        # The CORS lesson node should have been incremented
        cors_node = mock_graph.nodes["lesson-cors"]
        assert cors_node.properties["hit_count"] == 1

        mock_save.assert_called()


# ---------------------------------------------------------------------------
# Tests: cumulative increments
# ---------------------------------------------------------------------------

class TestCumulativeIncrements:
    @pytest.mark.asyncio
    async def test_multiple_calls_increment_cumulatively(self, server, mock_graph):
        """Calling _handle_lessons multiple times should increment hit_count each time."""
        with patch.object(server, "_save_graph"):
            # First call
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "all"}
            )
            # Second call
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS headers", "severity_filter": "all"}
            )
            # Third call
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS duplicate", "severity_filter": "all"}
            )

        cors_node = mock_graph.nodes["lesson-cors"]
        assert cors_node.properties["hit_count"] == 3

    @pytest.mark.asyncio
    async def test_preflight_and_lessons_both_increment(self, server, mock_graph):
        """Preflight + lessons calls should cumulatively increment the same node."""
        with patch.object(server, "_save_graph"):
            # Preflight call
            await server.handle_tool(
                "graq_preflight", {"action": "fix CORS", "files": []}
            )
            # Lessons call
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "all"}
            )

        cors_node = mock_graph.nodes["lesson-cors"]
        assert cors_node.properties["hit_count"] == 2

    @pytest.mark.asyncio
    async def test_unmatched_lessons_not_incremented(self, server, mock_graph):
        """Lesson nodes that don't match should NOT have hit_count incremented."""
        with patch.object(server, "_save_graph"):
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "critical"}
            )

        # deploy lesson (HIGH severity, no "CORS" in text) should be untouched
        deploy_node = mock_graph.nodes["lesson-deploy"]
        assert deploy_node.properties["hit_count"] == 0

    @pytest.mark.asyncio
    async def test_node_without_hit_count_gets_initialized(self, server, mock_graph):
        """A lesson node with no hit_count property should get it initialized to 1."""
        # Remove hit_count from the node to simulate missing key
        del mock_graph.nodes["lesson-cors"].properties["hit_count"]

        with patch.object(server, "_save_graph"):
            await server.handle_tool(
                "graq_lessons", {"operation": "CORS", "severity_filter": "all"}
            )

        cors_node = mock_graph.nodes["lesson-cors"]
        assert cors_node.properties["hit_count"] == 1
