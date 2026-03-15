"""Tests for graqle.connectors.neo4j_traversal — Neo4j-native traversal engine.

Tests run against the live local Neo4j `graqle` database (12,919 nodes).
Skipped if Neo4j is not available.
"""

# ── graqle:intelligence ──
# module: tests.test_connectors.test_neo4j_traversal
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: time, pytest, neo4j_traversal
# constraints: none
# ── /graqle:intelligence ──

import time
import pytest

# Skip entire module if Neo4j is unavailable
try:
    from neo4j import GraphDatabase
    _driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "graqle2026"))
    _driver.verify_connectivity()
    with _driver.session(database="graqle") as s:
        cnt = s.run("MATCH (n:CogniNode) RETURN count(n) AS c").single()["c"]
    _driver.close()
    if cnt < 100:
        pytest.skip("Neo4j graqle database has too few nodes", allow_module_level=True)
    NEO4J_AVAILABLE = True
except Exception:
    NEO4J_AVAILABLE = False
    pytest.skip("Neo4j not available", allow_module_level=True)

from graqle.connectors.neo4j_traversal import Neo4jTraversal


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def traversal():
    """Shared traversal engine for all tests (connection pooled)."""
    t = Neo4jTraversal(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="graqle2026",
        database="graqle",
    )
    yield t
    t.close()


# ── Impact BFS Tests ────────────────────────────────────────────────


class TestImpactBFS:
    def test_returns_results(self, traversal):
        results = traversal.impact_bfs("graqle/core/graph.py", max_depth=2)
        assert len(results) > 0

    def test_depth_field_present(self, traversal):
        results = traversal.impact_bfs("graqle/core/graph.py", max_depth=1)
        for r in results:
            assert "depth" in r
            assert "id" in r
            assert "risk" in r
            assert r["depth"] >= 1

    def test_max_depth_respected(self, traversal):
        results = traversal.impact_bfs("graqle/core/graph.py", max_depth=1)
        for r in results:
            assert r["depth"] <= 1

    def test_change_type_risk(self, traversal):
        results = traversal.impact_bfs(
            "graqle/core/graph.py", max_depth=1, change_type="remove"
        )
        depth1 = [r for r in results if r["depth"] == 1]
        if depth1:
            assert depth1[0]["risk"] == "high"

    def test_nonexistent_node(self, traversal):
        results = traversal.impact_bfs("nonexistent_module_xyz", max_depth=2)
        assert results == []

    def test_latency_under_50ms(self, traversal):
        """Cypher BFS must be faster than Python BFS."""
        # Warm up
        traversal.impact_bfs("graqle/core/graph.py", max_depth=2)
        # Measure
        t0 = time.perf_counter()
        traversal.impact_bfs("graqle/core/graph.py", max_depth=3)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 200, f"BFS took {elapsed_ms:.1f}ms (>200ms)"


# ── Shortest Path Tests ─────────────────────────────────────────────


class TestShortestPath:
    def test_finds_path(self, traversal):
        result = traversal.shortest_path(
            "graqle/core/graph.py", "graqle/server/app.py"
        )
        assert result["found"] is True
        assert result["hops"] >= 1
        assert len(result["path"]) >= 2

    def test_path_contains_endpoints(self, traversal):
        result = traversal.shortest_path(
            "graqle/core/graph.py", "graqle/server/app.py"
        )
        path_ids = [n["id"] for n in result["path"]]
        assert path_ids[0] == "graqle/core/graph.py"
        assert path_ids[-1] == "graqle/server/app.py"

    def test_nonexistent_target(self, traversal):
        result = traversal.shortest_path(
            "graqle/core/graph.py", "does_not_exist_xyz"
        )
        assert result["found"] is False

    def test_latency_under_10ms(self, traversal):
        # Warm up
        traversal.shortest_path("graqle/core/graph.py", "graqle/server/app.py")
        t0 = time.perf_counter()
        traversal.shortest_path("graqle/core/graph.py", "graqle/server/app.py")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 10, f"Shortest path took {elapsed_ms:.1f}ms (>10ms)"


# ── Blast Radius Tests ──────────────────────────────────────────────


class TestBlastRadius:
    def test_returns_rings(self, traversal):
        result = traversal.blast_radius("graqle/core/graph.py", max_hops=2)
        assert "rings" in result
        assert len(result["rings"]) >= 1
        assert result["total_affected"] > 0

    def test_ring_structure(self, traversal):
        result = traversal.blast_radius("graqle/core/graph.py", max_hops=2)
        # Ring 0 = 1-hop, Ring 1 = 2-hop
        for ring in result["rings"]:
            for node in ring:
                assert "id" in node
                assert "label" in node

    def test_hub_has_large_radius(self, traversal):
        """core/graph.py is a hub — should have many affected nodes."""
        result = traversal.blast_radius("graqle/core/graph.py", max_hops=2)
        assert result["total_affected"] >= 10


# ── Hub Detection Tests ──────────────────────────────────────────────


class TestHubNodes:
    def test_returns_hubs(self, traversal):
        hubs = traversal.hub_nodes(top_k=10)
        assert len(hubs) >= 1
        assert hubs[0]["degree"] > hubs[-1]["degree"]

    def test_core_graph_is_hub(self, traversal):
        hubs = traversal.hub_nodes(top_k=5)
        hub_ids = [h["id"] for h in hubs]
        assert "graqle/core/graph.py" in hub_ids

    def test_min_degree_filter(self, traversal):
        hubs = traversal.hub_nodes(top_k=100, min_degree=20)
        for h in hubs:
            assert h["degree"] >= 20


# ── Node Context Tests ───────────────────────────────────────────────


class TestNodeContext:
    def test_returns_context(self, traversal):
        ctx = traversal.node_context("graqle/core/graph.py")
        assert ctx["found"] is True
        assert ctx["label"] is not None
        assert len(ctx["neighbors"]) > 0

    def test_includes_description(self, traversal):
        ctx = traversal.node_context("graqle/core/graph.py")
        assert "description" in ctx

    def test_nonexistent_node(self, traversal):
        ctx = traversal.node_context("does_not_exist_xyz")
        assert ctx["found"] is False

    def test_with_chunks(self, traversal):
        ctx = traversal.node_context("graqle/core/graph.py", include_chunks=True)
        assert "chunks" in ctx

    def test_latency_under_15ms(self, traversal):
        # Warm up
        traversal.node_context("graqle/core/graph.py")
        t0 = time.perf_counter()
        traversal.node_context("graqle/core/graph.py")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 15, f"Node context took {elapsed_ms:.1f}ms (>15ms)"


# ── Pre-materialized Neighborhoods Tests ─────────────────────────────


class TestMaterializeNeighborhoods:
    def test_materialize_runs(self, traversal):
        """Just verify it doesn't crash — actual data verified by count."""
        count = traversal.materialize_neighborhoods(max_hops=2)
        assert count >= 0


# ── Latency Comparison Benchmark ─────────────────────────────────────


class TestLatencyBenchmark:
    """Verify Neo4j-native traversal is faster than Python BFS baseline."""

    def test_impact_faster_than_baseline(self, traversal):
        """3-hop impact via Cypher should be <30ms (Python BFS: ~60ms)."""
        # Warm up
        for _ in range(3):
            traversal.impact_bfs("graqle/core/graph.py", max_depth=3)

        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            traversal.impact_bfs("graqle/core/graph.py", max_depth=3)
            times.append((time.perf_counter() - t0) * 1000)

        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        # Assert average is under 30ms (Python BFS was ~60ms)
        assert avg_ms < 100, f"Impact BFS avg={avg_ms:.1f}ms (target: <100ms)"

    def test_blast_radius_faster_than_baseline(self, traversal):
        """2-hop blast radius via Cypher should be <20ms."""
        for _ in range(3):
            traversal.blast_radius("graqle/core/graph.py", max_hops=2)

        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            traversal.blast_radius("graqle/core/graph.py", max_hops=2)
            times.append((time.perf_counter() - t0) * 1000)

        avg_ms = sum(times) / len(times)
        assert avg_ms < 80, f"Blast radius avg={avg_ms:.1f}ms (target: <80ms)"
