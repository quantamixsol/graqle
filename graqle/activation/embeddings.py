"""Embedding computation for query-node relevance scoring.

Supports multiple backends:
- TitanV2Engine: Amazon Bedrock Titan V2 (1024-dim, production)
- SentenceTransformerEngine: sentence-transformers (384-dim, local)
- SimpleEngine: hash-based fallback (128-dim, zero dependencies)
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

logger = logging.getLogger("graqle.embeddings")


class EmbeddingEngine:
    """Computes embeddings for queries and node descriptions.

    Uses sentence-transformers if available, falls back to
    simple TF-IDF bag-of-words for zero-dependency operation.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None
        self._use_simple = False

    @staticmethod
    def _patch_stderr_flush() -> None:
        """Patch sys.stderr.flush to handle [Errno 22] on Windows pipes."""
        import sys
        _orig = getattr(sys.stderr, "_orig_flush", None)
        if _orig is not None:
            return  # Already patched
        _orig_flush = sys.stderr.flush
        def _safe_flush():
            try:
                _orig_flush()
            except OSError:
                pass
        sys.stderr._orig_flush = _orig_flush  # type: ignore[attr-defined]
        sys.stderr.flush = _safe_flush  # type: ignore[method-assign]

    def _load(self) -> None:
        if self._model is not None or self._use_simple:
            return
        try:
            import os
            # Disable tqdm progress bars to prevent [Errno 22] on Windows
            # when stderr is not a real TTY (piped/subagent environments).
            os.environ["TQDM_DISABLE"] = "1"
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            self._patch_stderr_flush()
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            logger.info(f"Loaded embedding model: {self._model_name}")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed, using bag-of-words fallback. "
                "Install with: pip install 'graqle[embeddings]'"
            )
            self._use_simple = True

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string."""
        self._load()
        if self._use_simple:
            return self._simple_embed(text)
        return self._model.encode(text, normalize_embeddings=True, show_progress_bar=False)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of text strings."""
        self._load()
        if self._use_simple:
            return np.array([self._simple_embed(t) for t in texts])
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    @staticmethod
    def _simple_embed(text: str, dim: int = 128) -> np.ndarray:
        """Simple hash-based embedding fallback (no ML dependencies)."""
        words = text.lower().split()
        vec = np.zeros(dim)
        for i, word in enumerate(words):
            h = hash(word) % dim
            vec[h] += 1.0 / (i + 1)  # position-weighted
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec


class TitanV2Engine:
    """Amazon Bedrock Titan Text Embeddings V2 (1024-dim).

    Production-grade embeddings. Requires AWS credentials with
    Bedrock access in the configured region.
    """

    def __init__(
        self,
        region: str = "eu-central-1",
        model_id: str = "amazon.titan-embed-text-v2:0",
        dimension: int = 1024,
    ) -> None:
        self._region = region
        self._model_id = model_id
        self._dimension = dimension
        self._client = None
        self._cache: dict[str, np.ndarray] = {}

    def _load(self) -> None:
        if self._client is not None:
            return
        try:
            import boto3
            self._client = boto3.client(
                "bedrock-runtime", region_name=self._region
            )
            logger.info(f"Loaded Titan V2 embedding engine: {self._region}")
        except ImportError:
            raise ImportError(
                "boto3 required for Titan V2 embeddings. "
                "Install with: pip install boto3"
            )

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string via Bedrock."""
        # Check cache
        cache_key = self._cache_key(text)
        if cache_key in self._cache:
            return self._cache[cache_key]

        self._load()
        import json
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps({
                "inputText": text[:8192],  # Titan V2 limit
                "dimensions": self._dimension,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())
        embedding = np.array(result["embedding"], dtype=np.float32)

        self._cache[cache_key] = embedding
        return embedding

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of texts (sequential — Titan V2 has no batch API)."""
        return np.array([self.embed(t) for t in texts])

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def clear_cache(self) -> None:
        self._cache.clear()


class CachedEmbeddingEngine:
    """Wraps any embedding engine with content-hash-based caching.

    If node content changes (description + chunks), the embedding
    is recomputed. Otherwise, the cached version is used.
    """

    def __init__(self, engine: EmbeddingEngine | TitanV2Engine) -> None:
        self._engine = engine
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, text: str) -> np.ndarray:
        key = hashlib.md5(text.encode()).hexdigest()
        if key not in self._cache:
            self._cache[key] = self._engine.embed(text)
        return self._cache[key]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.array([self.embed(t) for t in texts])

    def invalidate(self, text: str) -> None:
        key = hashlib.md5(text.encode()).hexdigest()
        self._cache.pop(key, None)

    def clear_cache(self) -> None:
        self._cache.clear()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
