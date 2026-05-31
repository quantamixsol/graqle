"""v0.63.1 — graq_learn persists to Neo4j; SAVE_FAILED URI-guard; embed-engine.

Three bugs fixed:
- Fix A: _save_graph treated a `neo4j://`/`bolt://` _graph_file URI as a JSON
  path → tried to write a file named after the URI → SAVE_FAILED on every learn.
- Fix B: learn handlers never wrote the new node/edges through to the Neo4j
  connector (add_node is in-memory only) → lessons lost on restart.
- Fix C: grow embed helpers used bare EmbeddingEngine() not create_embedding_engine.

V-CR-V0631-WRITE-NATIVE-001: new test file — graq_write S-010 gate; native Write.
"""

# ── graqle:intelligence ──
# module: tests.test_plugins.test_learn_neo4j_persist_v0631
# risk: LOW (impact radius: 0 modules)
# dependencies: asyncio, json, pytest, mcp_dev_server
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import json

import pytest

from graqle.core.edge import CogniEdge
from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from graqle.plugins.mcp_dev_server import (
    KogniDevServer,
    SaveStatus,
    _is_backend_only_graph_file,
)


# ── Fix A: URI guard ──────────────────────────────────────────────────
class TestBackendOnlyGraphFileGuard:
    @pytest.mark.parametrize("uri", [
        "neo4j://bolt://localhost:7687", "bolt://localhost:7687",
        "neptune://x", "memgraph://y",
    ])
    def test_uris_are_backend_only(self, uri):
        assert _is_backend_only_graph_file(uri) is True

    @pytest.mark.parametrize("path", [
        "C:/Users/x/graqle.json", "graqle.json", "./g.json", "",
    ])
    def test_paths_are_not_backend_only(self, path):
        assert _is_backend_only_graph_file(path) is False

    def test_none_is_not_backend_only(self):
        assert _is_backend_only_graph_file(None) is False

    def test_save_graph_returns_no_graph_file_for_uri(self):
        """The core SAVE_FAILED fix: a neo4j URI _graph_file → NO_GRAPH_FILE,
        not a crash from trying to write a file named after the URI."""
        s = KogniDevServer.__new__(KogniDevServer)
        s._graph_file = "neo4j://bolt://localhost:7687"
        g = Graqle(nodes={}, edges={})
        result = s._save_graph(g)
        assert result.status is SaveStatus.NO_GRAPH_FILE
        assert result.recorded is True  # folds into success


# ── Fix B: learn write-through to Neo4j ───────────────────────────────
class _SpyConnector:
    """Captures connector.save(nodes, edges) calls."""
    def __init__(self):
        self.saved_nodes = {}
        self.saved_edges = {}
        self.calls = 0

    def save(self, nodes, edges):
        self.calls += 1
        self.saved_nodes.update(nodes)
        self.saved_edges.update(edges)


def _server_with_neo4j_graph():
    """A server whose loaded graph is Neo4j-backed (spy connector)."""
    s = KogniDevServer.__new__(KogniDevServer)
    s._graph_file = "neo4j://bolt://localhost:7687"
    # two real code nodes + an edge so outcome-mode has something to reweight
    g = Graqle(
        nodes={
            "a.py": CogniNode(id="a.py", label="a", entity_type="PythonModule",
                              description="module a"),
            "b.py": CogniNode(id="b.py", label="b", entity_type="PythonModule",
                              description="module b"),
        },
        edges={
            "e1": CogniEdge(id="e1", source_id="a.py", target_id="b.py",
                            relationship="IMPORTS", weight=1.0),
        },
    )
    spy = _SpyConnector()
    g._neo4j_connector = spy
    s._graph = g
    s._kg_load_state = "LOADED"
    # _load_graph fast-path returns the cached graph
    s._load_graph = lambda: g  # type: ignore[method-assign]
    return s, g, spy


class TestLearnPersistsToNeo4j:
    def test_persist_helper_writes_scoped_nodes_edges(self):
        s, g, spy = _server_with_neo4j_graph()
        ok = s._persist_learn_to_backend(g, node_ids=["a.py"], edge_ids=["e1"])
        assert ok is True
        assert spy.calls == 1
        assert "a.py" in spy.saved_nodes
        assert "e1" in spy.saved_edges

    def test_persist_helper_returns_false_without_connector(self):
        s = KogniDevServer.__new__(KogniDevServer)
        g = Graqle(nodes={}, edges={})  # no _neo4j_connector
        assert s._persist_learn_to_backend(g) is False

    def test_learn_outcome_persists_lesson_to_neo4j(self):
        """End-to-end: graq_learn outcome on a Neo4j session writes the LESSON
        node through to the connector AND reports recorded=True (no SAVE_FAILED)."""
        s, g, spy = _server_with_neo4j_graph()
        raw = asyncio.run(s._handle_learn_outcome({
            "action": "fixed the connector alias bug",
            "outcome": "success",
            "components": ["a.py", "b.py"],
            "lesson": "neo4j URI graph_file must be treated like None in _save_graph",
        }))
        resp = json.loads(raw)
        assert resp.get("recorded") is True, resp
        assert resp.get("error_code") != "SAVE_FAILED"
        # the lesson node reached the connector
        assert spy.calls >= 1
        lesson_ids = [nid for nid in spy.saved_nodes if nid.startswith("lesson_")]
        assert lesson_ids, f"no lesson node persisted to neo4j: {list(spy.saved_nodes)}"
        assert resp.get("persistence") == "neo4j"

    def test_learn_entity_persists_to_neo4j(self):
        s, g, spy = _server_with_neo4j_graph()
        raw = asyncio.run(s._handle_learn_entity({
            "entity_id": "the regulatory product",
            "entity_type": "PRODUCT",
            "description": "TraceGov regulatory product",
            "connects_to": ["a.py"],
        }))
        resp = json.loads(raw)
        assert resp.get("recorded") is True, resp
        assert "the regulatory product" in spy.saved_nodes

    def test_learn_knowledge_persists_to_neo4j(self):
        s, g, spy = _server_with_neo4j_graph()
        raw = asyncio.run(s._handle_learn_knowledge({
            "description": "Free tier allows 1000 anchors/month per ADR-BIZ-001",
            "domain": "product",
            "tags": ["pricing"],
        }))
        resp = json.loads(raw)
        assert resp.get("recorded") is True, resp
        kn = [n for n in spy.saved_nodes if n.startswith("knowledge_")]
        assert kn, f"no knowledge node persisted: {list(spy.saved_nodes)}"

    def test_learn_outcome_surfaces_backend_failure(self):
        """If the connector.save raises, learn reports SAVE_FAILED (loud),
        not a false success."""
        s, g, spy = _server_with_neo4j_graph()

        def boom(nodes, edges):
            raise RuntimeError("neo4j down")
        spy.save = boom  # type: ignore[method-assign]

        raw = asyncio.run(s._handle_learn_outcome({
            "action": "x", "outcome": "success", "components": ["a.py", "b.py"],
            "lesson": "this should fail to persist",
        }))
        resp = json.loads(raw)
        assert resp.get("recorded") is False
        assert resp.get("error_code") == "SAVE_FAILED"
