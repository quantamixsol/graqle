"""Tests for graqle.activation.embeddings — EmbeddingEngine, SimpleEngine, TitanV2Engine.

Added in v0.35.0: coverage gaps flagged by graq_predict deployment gate (2026-03-25).
"""

# ── graqle:intelligence ──
# module: tests.test_activation.test_embeddings
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, numpy, embeddings
# constraints: none
# ── /graqle:intelligence ──

import numpy as np
import pytest

from graqle.activation.embeddings import (
    CachedEmbeddingEngine,
    EmbeddingEngine,
    TitanV2Engine,
)


class TestEmbeddingEngineModelName:
    """model_name property must be accessible and return a non-empty string."""

    def test_embedding_engine_model_name_property(self):
        engine = EmbeddingEngine(model_name="sentence-transformers/all-MiniLM-L6-v2")
        assert engine.model_name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_embedding_engine_model_name_custom(self):
        engine = EmbeddingEngine(model_name="my-custom-model/v1")
        assert engine.model_name == "my-custom-model/v1"

    def test_embedding_engine_model_name_is_string(self):
        engine = EmbeddingEngine(model_name="test-model")
        assert isinstance(engine.model_name, str)
        assert len(engine.model_name) > 0


class TestSimpleEngine:
    """EmbeddingEngine._simple_embed (hash-based fallback, 128-dim, zero deps)."""

    def test_simple_engine_model_name(self):
        """SimpleEngine (EmbeddingEngine in _use_simple mode) still exposes model_name."""
        engine = EmbeddingEngine(model_name="sentence-transformers/all-MiniLM-L6-v2")
        # Force simple mode without needing sentence-transformers installed
        engine._use_simple = True
        assert engine.model_name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_simple_embed_returns_unit_vector(self):
        vec = EmbeddingEngine._simple_embed("hello world")
        assert vec.shape == (128,)
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-6 or norm == pytest.approx(1.0, abs=1e-5)

    def test_simple_embed_empty_string(self):
        """Empty string should return zero vector without raising."""
        vec = EmbeddingEngine._simple_embed("")
        assert vec.shape == (128,)
        assert np.all(vec == 0.0)

    def test_simple_embed_different_texts_differ(self):
        v1 = EmbeddingEngine._simple_embed("authentication module")
        v2 = EmbeddingEngine._simple_embed("database connector")
        assert not np.allclose(v1, v2), "Different texts must produce different embeddings"

    def test_simple_embed_same_text_is_deterministic(self):
        v1 = EmbeddingEngine._simple_embed("deterministic test string")
        v2 = EmbeddingEngine._simple_embed("deterministic test string")
        assert np.allclose(v1, v2)

    def test_simple_embed_custom_dim(self):
        vec = EmbeddingEngine._simple_embed("test", dim=64)
        assert vec.shape == (64,)

    def test_embed_batch_via_simple(self):
        engine = EmbeddingEngine(model_name="test-model")
        engine._use_simple = True
        batch = engine.embed_batch(["hello", "world", "graqle"])
        assert batch.shape == (3, 128)


class TestTitanV2EngineModelName:
    """TitanV2Engine.model_name must return the model_id string."""

    def test_titan_engine_model_name(self):
        """TitanV2Engine.model_name returns the configured model_id."""
        # We can't instantiate without a region, so test via a subclass mock
        # that bypasses __init__ but exposes model_name logic.
        engine = object.__new__(TitanV2Engine)
        engine._model_id = "amazon.titan-embed-text-v2:0"
        engine._dimension = 1024
        engine._region = "eu-central-1"
        engine._client = None
        engine._cache = {}
        assert engine.model_name == "amazon.titan-embed-text-v2:0"

    def test_titan_engine_custom_model_id(self):
        engine = object.__new__(TitanV2Engine)
        engine._model_id = "custom.titan-v3:0"
        assert engine.model_name == "custom.titan-v3:0"


class TestCachedEmbeddingEngine:
    """CachedEmbeddingEngine wraps any engine and caches results by content hash."""

    def test_cached_engine_returns_same_vector(self):
        inner = EmbeddingEngine(model_name="test-model")
        inner._use_simple = True
        cached = CachedEmbeddingEngine(inner)
        v1 = cached.embed("graqle test")
        v2 = cached.embed("graqle test")
        assert np.allclose(v1, v2)

    def test_cached_engine_invalidate(self):
        inner = EmbeddingEngine(model_name="test-model")
        inner._use_simple = True
        cached = CachedEmbeddingEngine(inner)
        cached.embed("test string")
        assert len(cached._cache) == 1
        cached.invalidate("test string")
        assert len(cached._cache) == 0

    def test_cached_engine_clear_cache(self):
        inner = EmbeddingEngine(model_name="test-model")
        inner._use_simple = True
        cached = CachedEmbeddingEngine(inner)
        cached.embed("a")
        cached.embed("b")
        cached.embed("c")
        assert len(cached._cache) == 3
        cached.clear_cache()
        assert len(cached._cache) == 0
