"""CR-003 PR-003a — round-trip property tests for Graqle JSON persistence.

For every fixture, ``Graqle.from_json(p).to_json(p2)`` must preserve node count,
edge count, and entity-type counts exactly. This is the regression guard
against the silent edge-loss observed between v0.46 and v0.53 where
``graq grow`` started persisting nodes without edges to ``graqle.json``.

See: .gsm/external/Change Requests/CR-003-kg-persistence-schema-parity.md
"""

# -- graqle:intelligence --
# module: tests.test_core.test_persistence_round_trip
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, networkx, graph
# constraints: none
# -- /graqle:intelligence --

from __future__ import annotations

import json
import os
from pathlib import Path

import networkx as nx
import pytest

from graqle.core.graph import Graqle


# -------- fixture helpers --------


def _make_graph(num_nodes: int, num_edges: int) -> nx.DiGraph:
    """Build a deterministic NetworkX DiGraph with described nodes and edges."""
    G = nx.DiGraph()
    for i in range(num_nodes):
        G.add_node(
            f"n{i}",
            label=f"Node{i}",
            type="TestNode",
            description=f"Test node number {i}",
        )
    edges_added = 0
    # Deterministic chain + chord pattern so edge_count is exact even when
    # num_edges < num_nodes - 1.
    for i in range(min(num_edges, num_nodes - 1)):
        G.add_edge(f"n{i}", f"n{i+1}", relationship="RELATED_TO")
        edges_added += 1
    # If we still need more edges, add chords (n0 -> n_k for k > 1)
    k = 2
    while edges_added < num_edges and k < num_nodes:
        if not G.has_edge("n0", f"n{k}"):
            G.add_edge("n0", f"n{k}", relationship="RELATED_TO")
            edges_added += 1
        k += 1
    return G


# -------- round-trip property tests --------


@pytest.mark.parametrize(
    "num_nodes,num_edges",
    [
        (5, 4),       # tiny
        (50, 49),     # small chain
        (100, 200),   # small with chords
        (500, 1000),  # medium dense
        (1000, 100),  # large sparse — this is the shape that caught the regression
    ],
)
def test_round_trip_preserves_counts(tmp_path, num_nodes, num_edges):
    """from_json -> to_json -> from_json must preserve node and edge counts."""
    src = _make_graph(num_nodes, num_edges)

    p1 = tmp_path / "src.json"
    p2 = tmp_path / "round_trip.json"

    g1 = Graqle.from_networkx(src)
    g1.to_json(str(p1))

    g2 = Graqle.from_json(str(p1))
    g2.to_json(str(p2))

    g3 = Graqle.from_json(str(p2))

    # Node count preserved
    assert len(g1.nodes) == len(g2.nodes) == len(g3.nodes), (
        f"node_count drift: g1={len(g1.nodes)} g2={len(g2.nodes)} g3={len(g3.nodes)}"
    )
    # Edge count preserved (this is the CR-003 regression guard)
    assert len(g1.edges) == len(g2.edges) == len(g3.edges), (
        f"edge_count drift: g1={len(g1.edges)} g2={len(g2.edges)} g3={len(g3.edges)}"
    )


def test_round_trip_preserves_entity_types(tmp_path):
    """Node and edge types must round-trip without loss."""
    G = nx.DiGraph()
    G.add_node("svc", label="AuthService", type="SERVICE", description="auth")
    G.add_node("db", label="UserDB", type="DATABASE", description="users")
    G.add_node("api", label="LoginAPI", type="ENDPOINT", description="login")
    G.add_edge("api", "svc", relationship="CALLS")
    G.add_edge("svc", "db", relationship="QUERIES")

    p = tmp_path / "typed.json"
    g1 = Graqle.from_networkx(G)
    g1.to_json(str(p))

    g2 = Graqle.from_json(str(p))
    assert len(g2.nodes) == 3
    assert len(g2.edges) == 2

    # Entity-type distribution preserved
    types_g1 = sorted(n.entity_type for n in g1.nodes.values())
    types_g2 = sorted(n.entity_type for n in g2.nodes.values())
    assert types_g1 == types_g2, f"entity_type drift: {types_g1} vs {types_g2}"


def test_empty_graph_round_trip(tmp_path):
    """A graph with one node and no edges should round-trip cleanly.

    Single-node graphs have edge_count == 0 legitimately, and the new
    edge-shrink guard must not fire on them.
    """
    G = nx.DiGraph()
    G.add_node("solo", label="Solo", type="TestNode", description="alone")
    p = tmp_path / "solo.json"
    g1 = Graqle.from_networkx(G)
    g1.to_json(str(p))

    g2 = Graqle.from_json(str(p))
    assert len(g2.nodes) == 1
    assert len(g2.edges) == 0


def test_links_key_is_present_after_to_json(tmp_path):
    """to_json must always emit a 'links' array, even when there are no edges.

    The previous _validate_graph_data ignored 'links' entirely; CR-003 PR-003a
    makes 'links' validation symmetric with 'nodes', so this asserts the
    on-disk shape is well-formed.
    """
    G = nx.DiGraph()
    G.add_node("a", label="A", type="T", description="a")
    G.add_node("b", label="B", type="T", description="b")
    G.add_edge("a", "b", relationship="RELATED_TO")

    p = tmp_path / "two.json"
    g = Graqle.from_networkx(G)
    g.to_json(str(p))

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "nodes" in raw
    assert "links" in raw
    assert isinstance(raw["links"], list)
    assert len(raw["nodes"]) == 2
    assert len(raw["links"]) == 1
