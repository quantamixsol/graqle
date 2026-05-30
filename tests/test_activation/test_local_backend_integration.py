"""Integration tests for v0.62.3 on LOCAL backend (graqle.json).

User-requested coverage gap: most v0.62.3 tests stub or use mocks. This file
exercises the FULL end-to-end path against the local-JSON backend with no
Neo4j and no Bedrock — proves the structural fix works equally well for
deployers who use `connector: networkx` (the default) instead of Neo4j.

What it tests:
  L_01  default config + tiny graph -> CypherActivation skipped (no neo4j),
        ChunkScorer via (local, semantic) factory dispatch returns sensible
        nodes that actually match the query
  L_02  explicit `ranking: degree` -> DegreeRanker via (local, degree) returns
        top-N by graph degree (no embeddings needed)
  L_03  explicit `ranking: none` -> FullActivator returns ALL node ids
  L_04  legacy `strategy: top_k` -> back-compat promotes to (local, degree),
        emits DeprecationWarning, returns top-N-by-degree (same as L_02)
  L_05  legacy `strategy: chunk` -> back-compat promotes to (local, semantic),
        NO warning (was the default), returns same result as L_01
  L_06  legacy `strategy: full` -> back-compat promotes to (local, none),
        emits warning, returns all node ids
  L_07  the EXACT Session-0 freeze condition replayed on LOCAL backend:
        `strategy: top_k` returns top-N-by-degree (preserves behaviour) +
        warning fires (loud), demonstrating the bug class is contained
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from graqle.config.settings import GraqleConfig
from graqle.core.graph import Graqle


# ─── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tiny_graph_json(tmp_path: Path) -> Path:
    """Build a 10-node toy graph JSON file in graqle.json format.

    Nodes have:
      - distinct labels + descriptions (so semantic ranking has signal)
      - varying degree (so degree ranking has signal and a clear winner)

    Schema must match what Graqle.from_json expects:
      {"nodes": [{"id": ..., "label": ..., "entity_type": ...,
                  "description": ..., "properties": {...}}],
       "edges": [{"source": ..., "target": ..., "type": ...}]}
    """
    nodes = [
        {
            "id": "user_service.py",
            "label": "UserService",
            "entity_type": "PythonModule",
            "description": "Authentication, login, password hashing, user signup.",
            "properties": {},
        },
        {
            "id": "payment_service.py",
            "label": "PaymentService",
            "entity_type": "PythonModule",
            "description": "Stripe integration, charge cards, invoice generation, refunds.",
            "properties": {},
        },
        {
            "id": "graph_engine.py",
            "label": "GraphEngine",
            "entity_type": "PythonModule",
            "description": "Knowledge graph traversal, BFS, semantic search, embeddings.",
            "properties": {},
        },
        {
            "id": "models.py",
            "label": "Models",
            "entity_type": "PythonModule",
            "description": "SQLAlchemy ORM models for users, payments, sessions.",
            "properties": {},
        },
        {
            "id": "utils.py",
            "label": "Utils",
            "entity_type": "PythonModule",
            "description": "Helper functions, string manipulation, date formatting.",
            "properties": {},
        },
        # 5 leaf nodes with low degree
        {"id": "constants.py", "label": "Constants", "entity_type": "PythonModule",
         "description": "Magic numbers, configuration constants.", "properties": {}},
        {"id": "errors.py", "label": "Errors", "entity_type": "PythonModule",
         "description": "Custom exception classes.", "properties": {}},
        {"id": "logging_setup.py", "label": "LoggingSetup", "entity_type": "PythonModule",
         "description": "Logging configuration.", "properties": {}},
        {"id": "types.py", "label": "Types", "entity_type": "PythonModule",
         "description": "Type aliases and protocols.", "properties": {}},
        {"id": "version.py", "label": "Version", "entity_type": "PythonModule",
         "description": "Package version string.", "properties": {}},
    ]
    # Edges chosen so that:
    #   models.py     has degree 5 (hub — referenced by user/payment/graph/utils + itself loop)
    #   utils.py      has degree 4
    #   user_service  has degree 2
    #   payment       has degree 2
    #   graph_engine  has degree 1
    #   others        degree 0 (leaves) -- low signal for degree ranking
    edges = [
        {"source": "user_service.py", "target": "models.py", "type": "IMPORTS"},
        {"source": "payment_service.py", "target": "models.py", "type": "IMPORTS"},
        {"source": "graph_engine.py", "target": "models.py", "type": "IMPORTS"},
        {"source": "utils.py", "target": "models.py", "type": "IMPORTS"},
        {"source": "user_service.py", "target": "utils.py", "type": "IMPORTS"},
        {"source": "payment_service.py", "target": "utils.py", "type": "IMPORTS"},
        {"source": "graph_engine.py", "target": "utils.py", "type": "IMPORTS"},
    ]
    p = tmp_path / "graqle.json"
    p.write_text(json.dumps({"nodes": nodes, "edges": edges}))
    return p


@pytest.fixture
def local_config(tmp_path: Path) -> GraqleConfig:
    """A GraqleConfig pointing at networkx (local-JSON) backend.

    Uses simple embedding engine so tests don't need Bedrock / network.
    """
    yaml_text = """\
graph:
  connector: networkx
embeddings:
  backend: simple
activation:
  ranking: semantic
  max_nodes: 5
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    return GraqleConfig.from_yaml(str(p))


@pytest.fixture
def graph_local_semantic(tiny_graph_json: Path, local_config: GraqleConfig) -> Graqle:
    """Load the toy graph with default (local, semantic) config."""
    return Graqle.from_json(str(tiny_graph_json), config=local_config)


# ─── L_01: default = semantic ranking on local backend ──────────────────────


def test_L_01_local_semantic_matches_query_topic(graph_local_semantic: Graqle):
    """ChunkScorer via (local, semantic) returns nodes RELATED to the query."""
    nodes = graph_local_semantic._activate_subgraph(
        "stripe payment processing", strategy=None,
    )
    assert len(nodes) > 0, "Should activate at least one node"
    # The payment_service node should be in the top results — its description
    # mentions stripe + payments + invoices. We don't assert it's first
    # (embeddings can be noisy) but it must appear in the activated set.
    # If semantic ranking is broken and falls back to top-by-degree, this
    # would return [models.py, utils.py, ...] which doesn't contain payment_service.
    activated_ids = set(nodes)
    # Either it's in the activated set, OR direct_file_lookup matched (also OK)
    has_payment = "payment_service.py" in activated_ids
    has_relevant = any(
        any(token in nid.lower() for token in ["payment", "stripe", "invoice"])
        for nid in activated_ids
    )
    assert has_payment or has_relevant, (
        f"Query 'stripe payment processing' should activate payment-related node. "
        f"Got: {activated_ids}"
    )


# ─── L_02: explicit ranking=degree on local ────────────────────────────────


def test_L_02_local_degree_returns_highest_degree_first(graph_local_semantic: Graqle):
    """DegreeRanker via (local, degree) returns top-N by graph degree."""
    # Switch config to degree
    graph_local_semantic.config.activation.ranking = "degree"
    nodes = graph_local_semantic._activate_subgraph("anything", strategy=None)
    assert len(nodes) > 0
    # models.py is the hub with the highest in-degree (4 IMPORTS to it)
    # Should be in the top-3
    assert "models.py" in nodes[:3], (
        f"models.py (degree-5 hub) should be in top-3 for ranking=degree. "
        f"Got: {nodes}"
    )


# ─── L_03: explicit ranking=none on local ──────────────────────────────────


def test_L_03_local_none_returns_all_nodes(graph_local_semantic: Graqle):
    """FullActivator via (local, none) returns ALL node ids."""
    graph_local_semantic.config.activation.ranking = "none"
    nodes = graph_local_semantic._activate_subgraph("anything", strategy=None)
    assert set(nodes) == set(graph_local_semantic.nodes.keys())
    assert len(nodes) == 10  # all 10 nodes in the toy graph


# ─── L_04: legacy strategy=top_k via back-compat alias ─────────────────────


def test_L_04_legacy_strategy_top_k_via_config_promotes_to_degree(
    tiny_graph_json: Path, tmp_path: Path,
):
    """yaml: `strategy: top_k` -> ranking=degree, warning fires, returns top-by-degree."""
    yaml_text = """\
graph:
  connector: networkx
embeddings:
  backend: simple
activation:
  strategy: top_k
  top_k: 5
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("GRAQLE_LEGACY_ACTIVATION_SCHEMA" in str(w.message) for w in deps), (
        f"Legacy strategy=top_k must emit consolidated migration warning; got: "
        f"{[str(w.message) for w in deps]}"
    )
    assert cfg.activation.ranking == "degree"
    assert cfg.activation.max_nodes == 5

    g = Graqle.from_json(str(tiny_graph_json), config=cfg)
    nodes = g._activate_subgraph("anything", strategy=None)
    # Same behaviour as L_02 — degree ranker picks the hub
    assert "models.py" in nodes[:3]


# ─── L_05: legacy strategy=chunk via back-compat (no warning) ──────────────


def test_L_05_legacy_strategy_chunk_no_warning(tiny_graph_json: Path, tmp_path: Path):
    """yaml: `strategy: chunk` -> ranking=semantic, NO warning (chunk was the default)."""
    yaml_text = """\
graph:
  connector: networkx
embeddings:
  backend: simple
activation:
  strategy: chunk
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)
            and "ACTIVATION" in str(w.message)]
    assert deps == [], (
        f"strategy=chunk should NOT warn (was the v0.62.2 default); got: "
        f"{[str(w.message) for w in deps]}"
    )
    assert cfg.activation.ranking == "semantic"


# ─── L_06: legacy strategy=full via back-compat ─────────────────────────────


def test_L_06_legacy_strategy_full_returns_all_nodes(tiny_graph_json: Path, tmp_path: Path):
    """yaml: `strategy: full` -> ranking=none -> returns ALL nodes + warning fires."""
    yaml_text = """\
graph:
  connector: networkx
embeddings:
  backend: simple
activation:
  strategy: full
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)
            and "GRAQLE_LEGACY_ACTIVATION_SCHEMA" in str(w.message)]
    assert len(deps) >= 1

    g = Graqle.from_json(str(tiny_graph_json), config=cfg)
    nodes = g._activate_subgraph("anything", strategy=None)
    assert set(nodes) == set(g.nodes.keys())


# ─── L_07: Session-0 replay scenario adapted to LOCAL backend ──────────────


def test_L_07_session0_pattern_on_local_warns_and_preserves_behaviour(
    tiny_graph_json: Path, tmp_path: Path,
):
    """The EXACT Session-0 yaml pattern adapted to local backend.

    On Neo4j (Session-0 case), strategy=top_k bypassed the vector index
    silently. On local backend, top_k WAS the documented way to get
    degree-ranking — that contract is preserved (behaviour) but the
    deprecation warning fires (loud), making future misconfigurations on
    Neo4j impossible to hit silently.

    This proves the v0.62.3 fix preserves the legitimate use case on local
    AND makes the bad-on-neo4j case loud.
    """
    yaml_text = """\
graph:
  connector: networkx
embeddings:
  backend: simple
activation:
  strategy: top_k
  top_k: 5
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = GraqleConfig.from_yaml(str(p))

    # 1. Loud warning fires — exactly the "0% recurrence" guarantee
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)
            and "GRAQLE_LEGACY_ACTIVATION_SCHEMA" in str(w.message)]
    assert len(deps) >= 1, (
        "Session-0 yaml pattern must emit GRAQLE_LEGACY_ACTIVATION_SCHEMA warning"
    )

    # 2. Behaviour preserved on local — top-by-degree is the documented intent
    g = Graqle.from_json(str(tiny_graph_json), config=cfg)
    nodes = g._activate_subgraph("anything", strategy=None)
    assert "models.py" in nodes[:3], (
        "Top-by-degree behaviour must be preserved on local backend (was always valid there)"
    )

    # 3. Backend inference returns 'local' (no neo4j connector)
    assert g._infer_backend() == "local"

    # 4. The (local, degree) pair does NOT log the "ignores vector index"
    #    warning — that's only for neo4j/neptune backends
    from graqle.activation import factory_helpers as fh
    from graqle.activation.registry import ActivatorRegistry
    factory = ActivatorRegistry.resolve("local", "degree")
    activator = factory(g)
    assert activator.warn_on_neo4j is False, (
        "DegreeRanker on local backend must NOT warn (degree is a valid choice on local)"
    )
