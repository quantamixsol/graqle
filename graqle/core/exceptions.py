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


class GovernanceViolation(GraqleError):
    """Policy violation (clearance laundering, taint escalation, redaction bypass).

    Stores optional ``input_state`` dict for audit logging at rejection time.
    """

    def __init__(self, message: str, input_state: dict | None = None) -> None:
        super().__init__(message)
        self.input_state: dict | None = input_state


# CR-003 PR-003a — KG persistence defensive guards (BAU phase, 2026-05-09)
# See .gsm/external/Change Requests/CR-003-kg-persistence-schema-parity.md


class EdgeShrinkError(GraqleError):
    """Raised when ``Graqle.to_json`` would persist a graph whose edge count has
    shrunk by more than the configured threshold versus the existing on-disk file.

    This guards against the silent edge-loss regression observed between v0.46
    and v0.53 (CR-003), where ``graq grow`` started persisting nodes without
    edges to ``graqle.json``.

    Override the guard with the ``--allow-edge-shrink`` CLI flag or
    ``GRAQLE_ALLOW_EDGE_SHRINK=1`` environment variable. Both trigger an
    audit log entry recording user, pid, old/new counts, and target path.
    """

    def __init__(
        self,
        old_edges: int,
        new_edges: int,
        threshold: float,
        allow_flag: str = "--allow-edge-shrink",
    ) -> None:
        self.old_edges = old_edges
        self.new_edges = new_edges
        self.threshold = threshold
        self.allow_flag = allow_flag
        # Defensive guard against division-by-zero — old_edges should be > 100
        # to reach here per the call site, but bulletproof the message anyway.
        old_safe = max(1, old_edges)
        loss_pct = max(0.0, 1.0 - (new_edges / old_safe))
        super().__init__(
            f"Edge count would shrink {old_edges} -> {new_edges} "
            f"({loss_pct:.1%} loss; threshold {threshold:.0%}). "
            f"Pass {allow_flag} to override after audit."
        )


class GraphSchemaError(GraqleError):
    """Raised when graph payload schema is invalid (malformed nodes/links shape).

    Examples: ``nodes`` is neither dict nor list; a list element is not a dict;
    a dict key is non-string. Used by ``cli/commands/neo4j_import._as_items``
    and ``_validate_graph_data`` to give callers a precise schema error rather
    than an opaque ``AttributeError``.
    """


class GraphFileTooLargeError(GraqleError):
    """Raised when an on-disk graph file exceeds the streaming-safe size cap.

    Used by edge-shrink guard's pre-write read of the existing file. Cap is
    50 MB by default; override via ``GRAQLE_GRAPH_FILE_MAX_BYTES``.
    """
