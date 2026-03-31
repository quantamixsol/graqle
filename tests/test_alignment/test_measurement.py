"""Tests for R10 measure_alignment using CALLS_VIA_MCP edges."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import numpy as np

from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.measurement import measure_alignment


# ---------------------------------------------------------------------------
# Mock graph infrastructure
# ---------------------------------------------------------------------------


@dataclass
class MockNode:
    id: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockEdge:
    source_id: str
    target_id: str
    relationship: str
    properties: Dict[str, Any] = field(default_factory=dict)


class MockGraph:
    def __init__(self):
        self.nodes: dict[str, MockNode] = {}
        self.edges: dict[str, MockEdge] = {}

    def add_node(self, nid: str, embedding: list[float] | None = None, **props):
        node = MockNode(id=nid, properties=props)
        if embedding is not None:
            node.properties["_embedding_cache"] = {
                "hash": "test:mock",
                "vector": embedding,
            }
        self.nodes[nid] = node

    def add_edge(self, eid: str, src: str, tgt: str, rel: str, **props):
        self.edges[eid] = MockEdge(
            source_id=src, target_id=tgt, relationship=rel, properties=props,
        )


def _build_aligned_graph(n_pairs: int = 5, cosine_target: float = 0.9):
    """Build a mock graph with CALLS_VIA_MCP edges and embeddings."""
    graph = MockGraph()
    rng = np.random.default_rng(42)

    for i in range(n_pairs):
        # Python node with random embedding
        py_emb = rng.standard_normal(10).tolist()
        graph.add_node(f"py_{i}", embedding=py_emb, language="python")

        # TS node with similar embedding (high cosine)
        py_vec = np.array(py_emb)
        noise = rng.standard_normal(10) * (1.0 - cosine_target)
        ts_emb = (py_vec + noise).tolist()
        graph.add_node(f"ts_{i}", embedding=ts_emb, language="typescript")

        # CALLS_VIA_MCP edge
        graph.add_edge(
            f"edge_{i}", f"ts_{i}", f"py_{i}", "CALLS_VIA_MCP",
            tool_name=f"graq_tool_{i}",
        )

    return graph


class TestMeasureAlignment:
    def test_returns_report_with_pairs(self):
        graph = _build_aligned_graph(n_pairs=5)
        store = EmbeddingStore(graph)
        report = measure_alignment(graph, store)
        assert len(report.pairs) == 5
        assert report.mean_cosine > 0.0

    def test_no_mcp_edges_returns_empty(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0, 0.0])
        store = EmbeddingStore(graph)
        report = measure_alignment(graph, store)
        assert len(report.pairs) == 0
        assert report.diagnosis == "no_pairs_found"

    def test_missing_embedding_skipped(self):
        graph = MockGraph()
        graph.add_node("ts1")  # no embedding
        graph.add_node("py1", embedding=[1.0, 0.0])
        graph.add_edge("e1", "ts1", "py1", "CALLS_VIA_MCP")
        store = EmbeddingStore(graph)
        report = measure_alignment(graph, store)
        assert len(report.pairs) == 0

    def test_tier_distribution_populated(self):
        graph = _build_aligned_graph(n_pairs=5)
        store = EmbeddingStore(graph)
        report = measure_alignment(graph, store)
        assert sum(report.tier_distribution.values()) == 5

    def test_non_mcp_edges_ignored(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0, 0.0])
        graph.add_node("n2", embedding=[0.0, 1.0])
        graph.add_edge("e1", "n1", "n2", "IMPORTS")  # not CALLS_VIA_MCP
        store = EmbeddingStore(graph)
        report = measure_alignment(graph, store)
        assert len(report.pairs) == 0


class TestEmbeddingStore:
    def test_get_returns_cached_embedding(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0, 2.0, 3.0])
        store = EmbeddingStore(graph)
        vec = store.get("n1")
        assert vec is not None
        assert len(vec) == 3
        assert vec[0] == 1.0

    def test_get_missing_node_returns_none(self):
        graph = MockGraph()
        store = EmbeddingStore(graph)
        assert store.get("missing") is None

    def test_update_stores_aligned_embedding(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0, 2.0])
        store = EmbeddingStore(graph)
        store.update("n1", np.array([3.0, 4.0]))
        vec = store.get("n1")
        assert vec is not None
        assert list(vec) == [3.0, 4.0]

    def test_update_preserves_raw_cache(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0, 2.0])
        store = EmbeddingStore(graph)
        store.update("n1", np.array([9.0, 9.0]))
        # Raw cache should still exist
        raw = graph.nodes["n1"].properties["_embedding_cache"]["vector"]
        assert raw == [1.0, 2.0]

    def test_has_embedding(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0])
        graph.add_node("n2")
        store = EmbeddingStore(graph)
        assert store.has_embedding("n1") is True
        assert store.has_embedding("n2") is False

    def test_items(self):
        graph = MockGraph()
        graph.add_node("n1", embedding=[1.0])
        graph.add_node("n2", embedding=[2.0])
        graph.add_node("n3")
        store = EmbeddingStore(graph)
        items = store.items()
        assert len(items) == 2
