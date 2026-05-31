"""Tests for ChunkScorer.update_cache_incremental — v0.63.0 BLOCKER-1 fix.

The full build_cache re-embeds the entire graph (64K+ nodes); per-commit grow
must embed ONLY the changed nodes. These tests pin that behaviour, the npz
boolean-mask drop, edge cases (first grow, deleted node, empty delta),
drift self-heal, atomic write, and R-SEC-1 redaction.

V-CR-V063-WRITE-NATIVE-001: new test file in graqle-sdk/ — graq_write/generate
hit the S-010 "path escapes project root" gate; native Write fallback per
SENTINEL-v0623 + feedback_s010_write_path_only_and_graq_edit_gcc.
"""

# ── graqle:intelligence ──
# module: tests.test_activation.test_incremental_embed
# risk: LOW (impact radius: 0 modules)
# dependencies: numpy, pytest, chunk_scorer
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from graqle.activation.chunk_scorer import ChunkScorer


# ── deterministic stub engine (no Bedrock / no sentence-transformers) ──
class _StubEngine:
    """Returns a deterministic unit-ish vector per text; counts calls."""

    def __init__(self):
        self.calls: list[str] = []

    def embed(self, text: str) -> np.ndarray:
        self.calls.append(text)
        # Deterministic 3-dim vector derived from the text hash.
        h = abs(hash(text)) % 1000
        return np.array([h / 1000.0, (h % 7) / 7.0, 1.0], dtype=float)


def _make_node(nid, label, entity_type, description, chunks=None):
    node = MagicMock()
    node.id = nid
    node.label = label
    node.entity_type = entity_type
    node.description = description
    node.properties = {"chunks": chunks or []}
    return node


def _make_graph(nodes_dict):
    graph = MagicMock()
    graph.nodes = nodes_dict
    return graph


def _scorer():
    s = ChunkScorer(embedding_engine=_StubEngine())
    return s


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run inside tmp_path so .graqle/chunk_embeddings.npz is isolated."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _read_npz(path):
    data = np.load(str(path), allow_pickle=True)
    return {
        "chunk_keys": list(data["chunk_keys"]),
        "chunk_node_ids": list(data["chunk_node_ids"]),
        "desc_keys": list(data["desc_keys"]),
    }


class TestIncrementalEmbed:
    def test_EG16a_first_grow_no_cache_builds_full(self, in_tmp):
        """No .npz yet → defers to full build_cache; rebuilt_full=1."""
        g = _make_graph({
            "a.py": _make_node("a.py", "a", "PythonModule", "module a",
                               chunks=[{"type": "function", "text": "def foo(): return 1  # foo body"}]),
        })
        s = _scorer()
        stats = s.update_cache_incremental(g, {"a.py"})
        assert stats["rebuilt_full"] == 1
        assert (in_tmp / ".graqle" / "chunk_embeddings.npz").exists()

    def test_EG16b_empty_delta_is_noop(self, in_tmp):
        """Empty changed set after a cache exists → no embedding work."""
        g = _make_graph({
            "a.py": _make_node("a.py", "a", "PythonModule", "module a",
                               chunks=[{"type": "function", "text": "def foo(): return 1  # foo body"}]),
        })
        s = _scorer()
        s.update_cache_incremental(g, {"a.py"})   # seed cache
        s2 = _scorer()
        stats = s2.update_cache_incremental(g, set())
        assert stats == {"reembedded_nodes": 0, "reembedded_chunks": 0,
                         "reembedded_descs": 0, "rebuilt_full": 0}
        assert s2.embedding_engine.calls == []  # nothing embedded

    def test_EG16_cost_scales_with_delta_not_graph(self, in_tmp):
        """The core BLOCKER-1 guard: re-embedding ONE node of a 50-node graph
        embeds ~1 node's chunks, not all 50."""
        nodes = {
            f"n{i}.py": _make_node(
                f"n{i}.py", f"n{i}", "PythonModule", f"module {i}",
                chunks=[{"type": "function", "text": f"def fn{i}(): return {i}  # body {i}"}],
            )
            for i in range(50)
        }
        g = _make_graph(nodes)
        # Seed full cache (this embeds all 50 — expected, one-time).
        ChunkScorer(embedding_engine=_StubEngine()).update_cache_incremental(g, set(nodes))
        # Now change ONE node and incrementally update.
        nodes["n7.py"].properties["chunks"] = [
            {"type": "function", "text": "def fn7_v2(): return 777  # changed body"}
        ]
        s = _scorer()
        s.update_cache_incremental(g, {"n7.py"})
        # Only n7's single chunk should have been embedded — NOT 50.
        assert len(s.embedding_engine.calls) == 1, s.embedding_engine.calls

    def test_EG_boolean_mask_drops_only_changed(self, in_tmp):
        nodes = {
            "a.py": _make_node("a.py", "a", "PythonModule", "a",
                               chunks=[{"type": "function", "text": "def a(): pass  # a body here"}]),
            "b.py": _make_node("b.py", "b", "PythonModule", "b",
                               chunks=[{"type": "function", "text": "def b(): pass  # b body here"}]),
        }
        g = _make_graph(nodes)
        ChunkScorer(embedding_engine=_StubEngine()).update_cache_incremental(g, set(nodes))
        # change only a.py
        nodes["a.py"].properties["chunks"] = [
            {"type": "function", "text": "def a_v2(): pass  # a changed body"}
        ]
        s = _scorer()
        s.update_cache_incremental(g, {"a.py"})
        npz = _read_npz(in_tmp / ".graqle" / "chunk_embeddings.npz")
        # both nodes still present, no duplicates
        assert set(npz["chunk_node_ids"]) == {"a.py", "b.py"}
        assert len(npz["chunk_keys"]) == len(set(npz["chunk_keys"]))

    def test_EG_deleted_node_drops_rows(self, in_tmp):
        nodes = {
            "a.py": _make_node("a.py", "a", "PythonModule", "a",
                               chunks=[{"type": "function", "text": "def a(): pass  # a body here"}]),
            "b.py": _make_node("b.py", "b", "PythonModule", "b",
                               chunks=[{"type": "function", "text": "def b(): pass  # b body here"}]),
        }
        g = _make_graph(dict(nodes))
        ChunkScorer(embedding_engine=_StubEngine()).update_cache_incremental(g, set(nodes))
        # delete b.py from the graph, mark it changed
        del g.nodes["b.py"]
        s = _scorer()
        s.update_cache_incremental(g, {"b.py"})
        npz = _read_npz(in_tmp / ".graqle" / "chunk_embeddings.npz")
        assert "b.py" not in npz["chunk_node_ids"]
        assert "a.py" in npz["chunk_node_ids"]
        assert s.embedding_engine.calls == []  # deleted node embeds nothing

    def test_EG_desc_only_node_uses_desc_arrays(self, in_tmp):
        """A node with no chunks is embedded into the desc_* arrays."""
        nodes = {
            "dir1": _make_node("dir1", "dir1", "Directory", "Directory: dir1", chunks=[]),
        }
        g = _make_graph(nodes)
        s = _scorer()
        s.update_cache_incremental(g, {"dir1"})  # first grow → full build
        npz = _read_npz(in_tmp / ".graqle" / "chunk_embeddings.npz")
        assert "dir1" in npz["desc_keys"]

    def test_EG17_drift_self_heals(self, in_tmp):
        """If the post-update key-set diverges from the graph, full rebuild fires."""
        nodes = {
            "a.py": _make_node("a.py", "a", "PythonModule", "a",
                               chunks=[{"type": "function", "text": "def a(): pass  # a body here"}]),
        }
        g = _make_graph(nodes)
        ChunkScorer(embedding_engine=_StubEngine()).update_cache_incremental(g, set(nodes))
        s = _scorer()
        # Force drift: make _drift_detected return True once.
        calls = {"n": 0}
        real = ChunkScorer.build_cache

        def spy_build(self, graph):
            calls["n"] += 1
            return real(self, graph)

        with patch.object(ChunkScorer, "_drift_detected", return_value=True), \
             patch.object(ChunkScorer, "build_cache", spy_build):
            stats = s.update_cache_incremental(g, {"a.py"})
        assert stats["rebuilt_full"] == 1
        assert calls["n"] == 1  # full rebuild was invoked

    def test_EG10_rsec1_redacts_secret_chunks(self, in_tmp):
        """R-SEC-1: SECRET+ chunk text never reaches the embedding engine."""
        secret = "AWS_SECRET_ACCESS_KEY=" + "A" * 40
        nodes = {
            "s.py": _make_node("s.py", "s", "PythonModule", "s",
                               chunks=[{"type": "code", "text": f"config = '{secret}'  # loaded at boot"}]),
        }
        g = _make_graph(nodes)
        s = _scorer()
        s.update_cache_incremental(g, {"s.py"})
        # The raw 40-char secret must not appear verbatim in anything embedded.
        assert all(secret not in t for t in s.embedding_engine.calls), \
            "raw secret reached the embedding engine — R-SEC-1 violated"

    def test_EG_atomic_write_no_tmp_leftover(self, in_tmp):
        nodes = {
            "a.py": _make_node("a.py", "a", "PythonModule", "a",
                               chunks=[{"type": "function", "text": "def a(): pass  # a body here"}]),
            "b.py": _make_node("b.py", "b", "PythonModule", "b",
                               chunks=[{"type": "function", "text": "def b(): pass  # b body here"}]),
        }
        g = _make_graph(nodes)
        ChunkScorer(embedding_engine=_StubEngine()).update_cache_incremental(g, set(nodes))
        nodes["a.py"].properties["chunks"] = [
            {"type": "function", "text": "def a_v2(): pass  # changed a body"}
        ]
        _scorer().update_cache_incremental(g, {"a.py"})
        leftovers = list((in_tmp / ".graqle").glob("*.tmp*"))
        assert leftovers == [], f"temp files left behind: {leftovers}"
