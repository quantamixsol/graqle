"""Tests for PCST activation."""

# ── graqle:intelligence ──
# module: tests.test_activation.test_pcst
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, graph, pcst, relevance, embeddings +1 more
# constraints: none
# ── /graqle:intelligence ──

import numpy as np
import pytest

from graqle.activation.embeddings import EmbeddingEngine, cosine_similarity
from graqle.activation.pcst import PCSTActivation
from graqle.activation.relevance import RelevanceScorer


def test_cosine_similarity():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)

    c = np.array([0.0, 1.0, 0.0])
    assert cosine_similarity(a, c) == pytest.approx(0.0)


def test_embedding_engine_simple():
    engine = EmbeddingEngine()
    engine._use_simple = True  # force simple mode
    emb = engine.embed("test query about regulations")
    assert isinstance(emb, np.ndarray)
    assert np.linalg.norm(emb) == pytest.approx(1.0, abs=0.01)


def test_relevance_scorer(sample_graph):
    scorer = RelevanceScorer()
    scores = scorer.score(sample_graph, "concept hub")
    assert len(scores) == 5
    # v3: scores can exceed 1.0 due to content multiplier + property boosts
    assert all(v >= 0.0 for v in scores.values())
    # n5 has "hub" in description, should score higher
    assert scores["n5"] > 0


def test_pcst_topk_fallback(sample_graph):
    activator = PCSTActivation(max_nodes=3)
    selected = activator._topk_select({"n1": 0.9, "n2": 0.1, "n3": 0.5, "n4": 0.3, "n5": 0.7})
    assert len(selected) == 3
    assert selected[0] == "n1"  # highest relevance


def test_pcst_activate_fallback(sample_graph):
    """Test activation with top-k fallback (pcst_fast may not be installed)."""
    activator = PCSTActivation(max_nodes=3)
    selected = activator.activate(sample_graph, "concept hub related")
    assert len(selected) <= 3
    assert all(nid in sample_graph.nodes for nid in selected)
