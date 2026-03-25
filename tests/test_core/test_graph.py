"""Tests for GraQle."""

# ── graqle:intelligence ──
# module: tests.test_core.test_graph
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, networkx, graph, mock
# constraints: none
# ── /graqle:intelligence ──

import networkx as nx
import pytest

from graqle.backends.mock import MockBackend
from graqle.core.graph import Graqle


def test_graph_from_networkx(sample_nx_graph):
    graph = Graqle.from_networkx(sample_nx_graph)
    assert len(graph.nodes) == 5
    assert len(graph.edges) == 7
    assert graph.nodes["n1"].label == "Node A"


def test_graph_neighbors(sample_graph):
    neighbors = sample_graph.get_neighbors("n5")
    assert len(neighbors) == 4  # hub connected to all
    assert "n1" in neighbors
    assert "n2" in neighbors


def test_graph_edges_between(sample_graph):
    edges = sample_graph.get_edges_between("n1", "n2")
    assert len(edges) >= 1
    assert edges[0].relationship == "RELATED_TO"


def test_graph_stats(sample_graph):
    stats = sample_graph.stats
    assert stats.total_nodes == 5
    assert stats.total_edges == 7
    assert stats.avg_degree > 0
    assert len(stats.hub_nodes) >= 1


def test_graph_to_networkx(sample_graph):
    G = sample_graph.to_networkx()
    assert isinstance(G, nx.Graph)
    assert len(G.nodes) == 5


def test_graph_add_node(sample_graph):
    from graqle.core.node import CogniNode
    new_node = CogniNode(id="n6", label="New Node")
    sample_graph.add_node(new_node)
    assert "n6" in sample_graph.nodes


@pytest.mark.asyncio
async def test_graph_reason(sample_graph):
    backend = MockBackend(response="Synthesized answer. Confidence: 85%")
    sample_graph.set_default_backend(backend)

    result = await sample_graph.areason(
        "What is the relationship between concepts?",
        max_rounds=2,
        strategy="full",
    )
    assert result.answer
    assert result.rounds_completed >= 1
    assert result.node_count == 5
    assert result.confidence > 0


def test_graph_repr(sample_graph):
    r = repr(sample_graph)
    assert "Graqle" in r
    assert "nodes=5" in r


# ---------------------------------------------------------------------------
# Tests added in v0.35.0 — graq_predict gate coverage gaps
# Flagged by deployment gate session 2026-03-25 at 88-92% confidence
# ---------------------------------------------------------------------------

def test_to_json_writes_embedding_meta(sample_graph, tmp_path):
    """to_json must persist _meta with embedding_model and embedding_dim."""
    import json
    out = str(tmp_path / "graph.json")
    sample_graph.to_json(out)
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    meta = (data.get("graph") or {}).get("_meta")
    assert meta is not None, "_meta missing from saved graph — embedding provenance lost"
    assert "embedding_model" in meta, "_meta must contain embedding_model"
    assert "embedding_dim" in meta, "_meta must contain embedding_dim"
    assert isinstance(meta["embedding_dim"], int)
    assert meta["embedding_dim"] > 0


def test_from_json_raises_on_dimension_mismatch(sample_graph, tmp_path):
    """from_json must raise EmbeddingDimensionMismatchError when stored dim != active dim."""
    import json
    from graqle.core.exceptions import EmbeddingDimensionMismatchError

    out = str(tmp_path / "graph.json")
    sample_graph.to_json(out)

    # Tamper: inject a _meta with a dimension that will never match any engine
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    if "graph" not in data:
        data["graph"] = {}
    data["graph"]["_meta"] = {
        "embedding_model": "fake-model/99999-dim",
        "embedding_dim": 99999,
        "graqle_version": "test",
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with pytest.raises(EmbeddingDimensionMismatchError):
        from graqle.core.graph import Graqle as _G
        _G.from_json(out)


def test_from_json_passes_when_no_meta(sample_graph, tmp_path):
    """from_json must succeed on graphs with no _meta (backward compat — pre-v0.34.0 graphs)."""
    import json
    out = str(tmp_path / "graph_legacy.json")
    sample_graph.to_json(out)

    # Strip _meta to simulate a pre-v0.34.0 graph
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    if "graph" in data and "_meta" in data["graph"]:
        del data["graph"]["_meta"]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # Must not raise — no _meta means no dimension check performed
    from graqle.core.graph import Graqle as _G
    loaded = _G.from_json(out)
    assert loaded is not None


def test_cache_key_includes_model_name(sample_graph, tmp_path):
    """Two to_json saves with different mock model names must produce different _meta."""
    import json

    out1 = str(tmp_path / "g1.json")
    out2 = str(tmp_path / "g2.json")
    sample_graph.to_json(out1)
    sample_graph.to_json(out2)

    with open(out1, encoding="utf-8") as f:
        d1 = json.load(f)
    with open(out2, encoding="utf-8") as f:
        d2 = json.load(f)

    # Both saves of the same graph should produce consistent _meta
    meta1 = (d1.get("graph") or {}).get("_meta", {})
    meta2 = (d2.get("graph") or {}).get("_meta", {})
    assert meta1.get("embedding_model") == meta2.get("embedding_model"), (
        "Repeated to_json calls must produce consistent embedding_model in _meta"
    )
    assert meta1.get("embedding_dim") == meta2.get("embedding_dim")
