"""Embedding computation for query-node relevance scoring.

Supports multiple backends:
- TitanV2Engine: Amazon Bedrock Titan V2 (1024-dim, production)
- SentenceTransformerEngine: sentence-transformers (384-dim, local)
- SimpleEngine: hash-based fallback (128-dim, zero dependencies)
"""

# ── graqle:intelligence ──
# module: graqle.activation.embeddings
# risk: MEDIUM (impact radius: 4 modules)
# consumers: chunk_scorer, relevance, __init__, test_pcst
# dependencies: __future__, hashlib, logging, typing, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import logging

import numpy as np

logger = logging.getLogger("graqle.embeddings")


class EmbeddingEngine:
    """Computes embeddings for queries and node descriptions.

    Uses sentence-transformers if available, falls back to
    simple TF-IDF bag-of-words for zero-dependency operation.
    """

    def __init__(self, model_name: str | None = None) -> None:
        if model_name is None:
            model_name = self._load_configured_model()
        self._model_name = model_name
        self._model = None
        self._use_simple = False

    @property
    def model_name(self) -> str:
        return self._model_name

    @staticmethod
    def _load_configured_model() -> str:
        """Read embedding model from graqle.yaml config, with fallback.

        Checks embeddings.model first (new v0.29.3+ config), then
        activation.embedding_model (legacy), then default MiniLM.
        """
        try:
            from pathlib import Path
            from graqle.config.settings import GraqleConfig
            # Search for graqle.yaml in cwd and ancestors
            cwd = Path.cwd()
            for parent in [cwd, *cwd.parents]:
                cfg_path = parent / "graqle.yaml"
                if cfg_path.exists():
                    config = GraqleConfig.from_yaml(cfg_path)
                    # New config: embeddings.model takes priority
                    emb_model = config.embeddings.model
                    if emb_model and emb_model != "sentence-transformers/all-MiniLM-L6-v2":
                        return emb_model
                    # Legacy: activation.embedding_model
                    return config.activation.embedding_model
        except Exception:
            pass
        return "sentence-transformers/all-MiniLM-L6-v2"

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
        region: str | None = None,
        model_id: str = "amazon.titan-embed-text-v2:0",
        dimension: int = 1024,
    ) -> None:
        import os as _os
        self._region = (
            region
            or _os.environ.get("AWS_DEFAULT_REGION")
            or _os.environ.get("AWS_REGION")
        )
        if not self._region:
            # Try reading from graqle.yaml config
            try:
                from pathlib import Path

                import yaml
                cfg_path = Path("graqle.yaml")
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    self._region = cfg.get("model", {}).get("region")
            except Exception:
                pass
        if not self._region:
            raise ValueError(
                "No AWS region configured for Titan V2 embeddings. "
                "Set AWS_DEFAULT_REGION env var or add 'region' to "
                "model config in graqle.yaml."
            )
        self._model_id = model_id
        self._dimension = dimension
        self._client = None
        self._cache: dict[str, np.ndarray] = {}

    @property
    def model_name(self) -> str:
        return self._model_id

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


class SimpleEmbeddingEngine:
    """Hash-based embedding engine (zero ML dependencies).

    128-dim, position-weighted hash vectors. Lowest quality but
    works everywhere with no setup.
    """

    def __init__(self, dim: int = 128) -> None:
        self._dim = dim

    @property
    def model_name(self) -> str:
        return f"simple-hash-{self._dim}d"

    def embed(self, text: str) -> np.ndarray:
        return EmbeddingEngine._simple_embed(text, dim=self._dim)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.array([self.embed(t) for t in texts])


def create_embedding_engine(
    config: object | None = None,
) -> EmbeddingEngine | TitanV2Engine | SimpleEmbeddingEngine:
    """Factory: create the right embedding engine from GraqleConfig.

    Resolution order:
    1. If config has embeddings.backend explicitly set → use that
    2. If config.activation.embedding_engine == "simple" → SimpleEmbeddingEngine
    3. If config.model.backend == "bedrock" and no explicit embeddings → use Titan V2
    4. Default → EmbeddingEngine (sentence-transformers / MiniLM)

    Returns an engine with .embed() and .embed_batch() methods.
    """
    if config is None:
        return EmbeddingEngine()

    # Read embeddings config section
    embeddings_cfg = getattr(config, "embeddings", None)
    activation_cfg = getattr(config, "activation", None)
    model_cfg = getattr(config, "model", None)

    # Determine backend
    backend = "local"  # default
    model_name = None
    region = None

    if embeddings_cfg is not None:
        backend = getattr(embeddings_cfg, "backend", "local")
        model_name = getattr(embeddings_cfg, "model", None)
        region = getattr(embeddings_cfg, "region", None)

    # Legacy: activation.embedding_engine = "simple"
    if backend == "local" and activation_cfg is not None:
        legacy_engine = getattr(activation_cfg, "embedding_engine", "")
        if legacy_engine == "simple":
            backend = "simple"

    # Auto-detect: if model backend is bedrock and embeddings not explicitly set,
    # inherit bedrock for embeddings too (user likely wants cloud embeddings)
    if backend == "local" and model_cfg is not None:
        model_backend = getattr(model_cfg, "backend", "local")
        if model_backend == "bedrock" and (embeddings_cfg is None or getattr(embeddings_cfg, "backend", "local") == "local"):
            # Don't auto-upgrade — keep local unless user explicitly sets embeddings.backend
            pass

    # Resolve region from model config if not set on embeddings
    if region is None and model_cfg is not None:
        region = getattr(model_cfg, "region", None)

    if backend == "simple":
        logger.info("Using SimpleEmbeddingEngine (hash-based, 128-dim)")
        return SimpleEmbeddingEngine()

    if backend == "bedrock":
        effective_model = model_name or "amazon.titan-embed-text-v2:0"
        effective_region = region or "eu-central-1"
        logger.info(
            "Using TitanV2Engine (%s, %s, 1024-dim)",
            effective_model, effective_region,
        )
        return TitanV2Engine(
            region=effective_region,
            model_id=effective_model,
        )

    # Default: local sentence-transformers
    effective_model = model_name or "sentence-transformers/all-MiniLM-L6-v2"
    if activation_cfg is not None:
        # Backward compat: activation.embedding_model overrides if set
        act_model = getattr(activation_cfg, "embedding_model", "")
        if act_model and act_model != "sentence-transformers/all-MiniLM-L6-v2":
            effective_model = act_model
    logger.info("Using EmbeddingEngine (local, %s)", effective_model)
    return EmbeddingEngine(model_name=effective_model)


def get_engine_info(engine: object) -> dict[str, str]:
    """Return human-readable info about an embedding engine."""
    if isinstance(engine, TitanV2Engine):
        return {
            "backend": "bedrock",
            "model": engine._model_id,
            "dimension": str(engine._dimension),
            "region": engine._region or "unknown",
        }
    if isinstance(engine, SimpleEmbeddingEngine):
        return {
            "backend": "simple",
            "model": "hash-based",
            "dimension": str(engine._dim),
            "region": "local",
        }
    if isinstance(engine, EmbeddingEngine):
        return {
            "backend": "local",
            "model": engine._model_name,
            "dimension": "384",
            "region": "local",
        }
    return {"backend": "unknown", "model": "unknown", "dimension": "?", "region": "?"}


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
