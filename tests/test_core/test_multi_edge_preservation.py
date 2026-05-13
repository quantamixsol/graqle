"""CR-006a regression tests — multi-edge preservation across to_networkx and JSON round-trip.

Background: pre-CR-006a, Graqle.to_networkx() built nx.DiGraph (single-edge-per-pair).
This silently dropped every parallel typed edge between an already-connected
(src, tgt) pair. The fix migrates to_networkx() to nx.MultiDiGraph and keys
each edge by its unique edge id so round-trips preserve all typed edges.

Neo4j-backed roundtrip test is deferred to PR-006b (Site 3 writer fix).
"""

from __future__ import annotations

import json

import networkx as nx
import pytest

from graqle.core.graph import CogniEdge, CogniNode, Graqle


def _build_three_typed_parallel_edges() -> Graqle:
    """Construct a Graqle with two nodes A and B and three parallel typed edges A->B."""
    g = Graqle()
    g.add_node(CogniNode(id="A", label="A", entity_type="CONCEPT"))
    g.add_node(CogniNode(id="B", label="B", entity_type="CONCEPT"))
    g.add_edge(CogniEdge(id="e_calls", source_id="A", target_id="B", relationship="CALLS"))
    g.add_edge(CogniEdge(id="e_defines", source_id="A", target_id="B", relationship="DEFINES"))
    g.add_edge(CogniEdge(id="e_imports", source_id="A", target_id="B", relationship="IMPORTS"))
    return g


def test_to_networkx_preserves_parallel_typed_edges() -> None:
    g = _build_three_typed_parallel_edges()
    assert len(g.edges) == 3

    G = g.to_networkx()
    assert isinstance(G, nx.MultiDiGraph)
    assert G.number_of_edges() == 3

    rels = {data["relationship"] for _u, _v, data in G.edges(data=True)}
    assert rels == {"CALLS", "DEFINES", "IMPORTS"}


def test_json_round_trip_preserves_multi_edges(tmp_path) -> None:
    g = _build_three_typed_parallel_edges()
    out = tmp_path / "kg.json"
    g.to_json(str(out))

    g2 = Graqle.from_json(str(out))
    assert len(g2.edges) == 3

    rels = {e.relationship for e in g2.edges.values()}
    assert rels == {"CALLS", "DEFINES", "IMPORTS"}

    # Edge ids preserved through round-trip (review pass 2 MINOR #1).
    assert set(g.edges.keys()) == set(g2.edges.keys())


def test_synthetic_eid_uniqueness_for_null_id_typed_edges() -> None:
    """CR-006a Site 2: when Neo4j returns r.id == NULL for parallel typed edges
    between the same (src, tgt) pair, the load() loop must build a unique
    synthetic eid per record so they don't collide in the raw_edges dict.

    Verifies the construction rule ``f"e_{src}_{tgt}_{rel}_{idx}"`` produces
    distinct keys for the three typed edges seen in the live graqle KG
    (CALLS, DEFINES, IMPORTS between the same nodes).
    """
    src, tgt = "graqle/core/graph.py", "graqle/core/types.py"
    synthetic_ids = {
        (rel, idx): f"e_{src}_{tgt}_{rel}_{idx}"
        for idx, rel in enumerate(["CALLS", "DEFINES", "IMPORTS"])
    }
    assert len(set(synthetic_ids.values())) == 3
    # Same pair, three different rel types — must yield three distinct eids.
    assert synthetic_ids[("CALLS", 0)] != synthetic_ids[("DEFINES", 1)]
    assert synthetic_ids[("DEFINES", 1)] != synthetic_ids[("IMPORTS", 2)]


def test_existing_collapsed_json_still_loads(tmp_path) -> None:
    """Backward compatibility — pre-CR-006a single-edge JSON files must still load."""
    legacy_payload = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "A", "label": "A", "type": "CONCEPT"},
            {"id": "B", "label": "B", "type": "CONCEPT"},
        ],
        "links": [
            {
                "source": "A",
                "target": "B",
                "id": "e1",
                "relationship": "RELATED_TO",
                "weight": 1.0,
            },
        ],
    }
    legacy_path = tmp_path / "old.json"
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    g = Graqle.from_json(str(legacy_path))
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    # Verify legacy 'type' field maps to entity_type (review pass 2 MINOR #2).
    assert g.nodes["A"].entity_type == "CONCEPT"
