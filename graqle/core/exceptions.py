"""Core exceptions for the Graqle SDK."""


class GraqleError(Exception):
    """Base exception for all Graqle errors."""


class EmbeddingDimensionMismatchError(GraqleError):
    """Raised when a loaded graph was built with a different embedding model/dimension
    than the currently active engine.

    This happens when:
    - The user pip-upgrades graqle and the default model changes
    - sentence-transformers is missing, causing fallback to SimpleEmbeddingEngine (128-dim)
      on a graph built with all-MiniLM-L6-v2 (384-dim)
    - The user changes embeddings.model in graqle.yaml without rebuilding the graph

    Recovery:
        graq rebuild --re-embed
    """

    def __init__(
        self,
        stored_model: str,
        stored_dim: int,
        active_model: str,
        active_dim: int,
    ) -> None:
        super().__init__(
            f"Embedding dimension mismatch: graph was built with "
            f"model='{stored_model}' (dim={stored_dim}), but current engine uses "
            f"model='{active_model}' (dim={active_dim}). "
            f"Run: graq rebuild --re-embed"
        )
        self.stored_model = stored_model
        self.stored_dim = stored_dim
        self.active_model = active_model
        self.active_dim = active_dim
