"""Tests for graqle.learning.graph_learner module."""

# ── graqle:intelligence ──
# module: tests.test_learning.test_graph_learner
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, dataclasses, pathlib, typing +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from graqle.learning.graph_learner import EdgeUpdate, GraphLearner, LearningConfig


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class MockEdge:
    id: str
    source_id: str
    target_id: str
    weight: float


@dataclass
class MockGraph:
    edges: dict[str, MockEdge] = field(default_factory=dict)


@dataclass
class MockMessage:
    source: str
    content: str


@dataclass
class MockResult:
    message_trace: list[MockMessage] = field(default_factory=list)


def _make_graph(*edge_tuples: tuple[str, str, str, float]) -> MockGraph:
    """Build a MockGraph from (id, src, tgt, weight) tuples."""
    edges = {eid: MockEdge(eid, src, tgt, w) for eid, src, tgt, w in edge_tuples}
    return MockGraph(edges=edges)


def _make_result(messages: dict[str, str]) -> MockResult:
    """Build a MockResult from {node_id: text} dict."""
    trace = [MockMessage(source=src, content=txt) for src, txt in messages.items()]
    return MockResult(message_trace=trace)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgreementMatrixJaccard:
    """test_agreement_matrix_jaccard — 3 nodes, verify similarity scores."""

    def test_identical_messages_have_similarity_one(self):
        learner = GraphLearner()
        messages = {
            "a": "the cat sat on the mat",
            "b": "the cat sat on the mat",
            "c": "dogs run in the park quickly",
        }
        pairs = learner.compute_agreement_matrix(messages)
        # a and b are identical → Jaccard = 1.0
        assert pairs[("a", "b")] == pytest.approx(1.0)
        # a and c share only "the" → low similarity
        assert pairs[("a", "c")] < 0.3

    def test_single_node_returns_empty(self):
        learner = GraphLearner()
        assert learner.compute_agreement_matrix({"a": "hello"}) == {}

    def test_three_distinct_nodes(self):
        learner = GraphLearner()
        messages = {
            "x": "alpha beta gamma",
            "y": "alpha beta delta",
            "z": "epsilon zeta eta",
        }
        pairs = learner.compute_agreement_matrix(messages)
        # x-y share 2/4 tokens → Jaccard = 0.5
        assert pairs[("x", "y")] == pytest.approx(0.5)
        # x-z share 0 tokens
        assert pairs[("x", "z")] == pytest.approx(0.0)


class TestAgreementMatrixWithEmbedder:
    """test_agreement_matrix_with_embedder — mock embedder, verify cosine sim used."""

    def test_cosine_similarity_used(self):
        learner = GraphLearner()
        # Two identical vectors, one orthogonal
        vecs = np.array([
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        embedder = MagicMock()
        embedder.embed_batch.return_value = vecs

        messages = {"a": "foo", "b": "bar", "c": "baz"}
        pairs = learner.compute_agreement_matrix(messages, embedder=embedder)

        assert pairs[("a", "b")] == pytest.approx(1.0)
        assert pairs[("a", "c")] == pytest.approx(0.0)
        embedder.embed_batch.assert_called_once()

    def test_fallback_to_jaccard_on_embedder_error(self):
        learner = GraphLearner()
        embedder = MagicMock()
        embedder.embed_batch.side_effect = RuntimeError("boom")

        messages = {"a": "cat dog", "b": "cat dog"}
        pairs = learner.compute_agreement_matrix(messages, embedder=embedder)
        # Falls back to Jaccard: identical → 1.0
        assert pairs[("a", "b")] == pytest.approx(1.0)


class TestStrengthenOnConvergence:
    """test_strengthen_on_convergence — similar messages → edge weight increases."""

    def test_converged_edge_strengthened(self):
        graph = _make_graph(("e1", "a", "b", 1.0))
        result = _make_result({"a": "the cat sat on the mat", "b": "the cat sat on the mat"})
        cfg = LearningConfig(learning_rate=0.5, agreement_threshold=0.7, decay_factor=1.0)
        learner = GraphLearner(config=cfg)

        updates = learner.update_from_reasoning(graph, result)
        converged = [u for u in updates if u.reason == "converged"]
        assert len(converged) == 1
        assert converged[0].new_weight > converged[0].old_weight


class TestWeakenOnDivergence:
    """test_weaken_on_divergence — dissimilar messages → edge weight decreases."""

    def test_diverged_edge_weakened(self):
        graph = _make_graph(("e1", "a", "b", 1.0))
        result = _make_result({
            "a": "alpha beta gamma delta",
            "b": "epsilon zeta eta theta",
        })
        cfg = LearningConfig(
            learning_rate=0.5,
            disagreement_threshold=0.3,
            decay_factor=1.0,
        )
        learner = GraphLearner(config=cfg)

        updates = learner.update_from_reasoning(graph, result)
        diverged = [u for u in updates if u.reason == "diverged"]
        assert len(diverged) == 1
        assert diverged[0].new_weight < diverged[0].old_weight


class TestTemporalDecay:
    """test_temporal_decay — verify all edges get decayed."""

    def test_edges_decayed(self):
        graph = _make_graph(
            ("e1", "a", "b", 2.0),
            ("e2", "b", "c", 3.0),
        )
        result = _make_result({"a": "hello world", "b": "hello world"})
        cfg = LearningConfig(decay_factor=0.5, learning_rate=0.0)
        learner = GraphLearner(config=cfg)

        updates = learner.update_from_reasoning(graph, result)
        decayed = [u for u in updates if u.reason == "decayed"]
        assert len(decayed) == 2
        # e1: 2.0 * 0.5 = 1.0
        e1_update = [u for u in decayed if u.edge_id == "e1"][0]
        assert e1_update.new_weight == pytest.approx(1.0)
        # e2: 3.0 * 0.5 = 1.5
        e2_update = [u for u in decayed if u.edge_id == "e2"][0]
        assert e2_update.new_weight == pytest.approx(1.5)


class TestMinMaxWeightBounds:
    """test_min_max_weight_bounds — weight never goes below min or above max."""

    def test_weight_does_not_go_below_min(self):
        graph = _make_graph(("e1", "a", "b", 0.15))
        result = _make_result({
            "a": "alpha beta gamma delta",
            "b": "epsilon zeta eta theta",
        })
        cfg = LearningConfig(
            learning_rate=10.0,
            min_weight=0.1,
            disagreement_threshold=0.3,
            decay_factor=1.0,
        )
        learner = GraphLearner(config=cfg)
        learner.update_from_reasoning(graph, result)
        assert graph.edges["e1"].weight >= cfg.min_weight

    def test_weight_does_not_go_above_max(self):
        graph = _make_graph(("e1", "a", "b", 4.9))
        result = _make_result({"a": "the cat sat on the mat", "b": "the cat sat on the mat"})
        cfg = LearningConfig(
            learning_rate=10.0,
            max_weight=5.0,
            agreement_threshold=0.7,
            decay_factor=1.0,
        )
        learner = GraphLearner(config=cfg)
        learner.update_from_reasoning(graph, result)
        assert graph.edges["e1"].weight <= cfg.max_weight


class TestStatsTracking:
    """test_stats_tracking — verify update_count, strengthened, weakened counts."""

    def test_stats_after_updates(self):
        learner = GraphLearner(config=LearningConfig(decay_factor=1.0, learning_rate=0.5))

        # Round 1: convergence
        graph = _make_graph(("e1", "a", "b", 1.0))
        result = _make_result({"a": "the cat sat on the mat", "b": "the cat sat on the mat"})
        learner.update_from_reasoning(graph, result)

        # Round 2: divergence
        graph2 = _make_graph(("e2", "x", "y", 1.0))
        result2 = _make_result({"x": "alpha beta gamma", "y": "delta epsilon zeta"})
        learner.update_from_reasoning(graph2, result2)

        stats = learner.stats
        assert stats["update_rounds"] == 2
        assert stats["total_strengthened"] >= 1
        assert stats["total_weakened"] >= 1
        assert stats["history_length"] == 2


class TestPersistAndLoad:
    """test_persist_and_load — save weights, reload, verify."""

    def test_round_trip(self, tmp_path: Path):
        persist_file = tmp_path / "weights.json"
        cfg = LearningConfig(
            persist=True,
            persist_path=str(persist_file),
            decay_factor=1.0,
            learning_rate=0.5,
        )
        graph = _make_graph(("e1", "a", "b", 1.0))
        result = _make_result({"a": "the cat sat on the mat", "b": "the cat sat on the mat"})

        learner = GraphLearner(config=cfg)
        learner.update_from_reasoning(graph, result)
        saved_weight = graph.edges["e1"].weight

        # Verify file written
        assert persist_file.exists()
        data = json.loads(persist_file.read_text())
        assert "e1" in data

        # Load into fresh graph with original weight
        graph2 = _make_graph(("e1", "a", "b", 0.5))
        loaded = learner.load_weights(graph2)
        assert loaded == 1
        assert graph2.edges["e1"].weight == pytest.approx(saved_weight)

    def test_load_missing_file_returns_zero(self):
        cfg = LearningConfig(persist_path="/nonexistent/weights.json")
        learner = GraphLearner(config=cfg)
        graph = _make_graph(("e1", "a", "b", 1.0))
        assert learner.load_weights(graph) == 0


class TestReset:
    """test_reset — verify reset clears state."""

    def test_reset_clears_all(self):
        learner = GraphLearner(config=LearningConfig(decay_factor=1.0, learning_rate=0.5))
        graph = _make_graph(("e1", "a", "b", 1.0))
        result = _make_result({"a": "the cat sat on the mat", "b": "the cat sat on the mat"})
        learner.update_from_reasoning(graph, result)

        assert learner.stats["update_rounds"] > 0

        learner.reset()
        stats = learner.stats
        assert stats["update_rounds"] == 0
        assert stats["total_strengthened"] == 0
        assert stats["total_weakened"] == 0
        assert stats["total_decayed"] == 0
        assert stats["history_length"] == 0
