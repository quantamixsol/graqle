"""R10 Correction Approach A — Orthogonal Procrustes Projection."""

# ── graqle:intelligence ──
# module: graqle.alignment.procrustes
# risk: MEDIUM (impact radius: 2 modules)
# consumers: alignment.pipeline
# dependencies: numpy, graqle.alignment.types, graqle.alignment.embedding_store
# constraints: closed-form solution, O(d^2*n), preserves norms
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any, List, Tuple

import numpy as np

from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.measurement import measure_alignment
from graqle.alignment.types import AlignmentPair, AlignmentReport

logger = logging.getLogger("graqle.alignment.procrustes")


def apply_procrustes_correction(
    pairs: List[AlignmentPair],
    embedding_store: EmbeddingStore,
    graph: Any,
    target_space: str = "python",
) -> Tuple[np.ndarray, AlignmentReport]:
    """Orthogonal Procrustes: find optimal rotation R minimizing ||source@R - target||^2.

    Closed-form solution via SVD. No training loop, no hyperparameters.
    Preserves embedding norms (orthogonal transformation).

    Parameters
    ----------
    pairs:
        Alignment pairs with ts_embedding and py_embedding.
    embedding_store:
        Store to read/write corrected embeddings.
    graph:
        Graqle instance for node language detection and re-measurement.
    target_space:
        "python" (default) rotates TS embeddings into PY space.
        "typescript" rotates PY embeddings into TS space.

    Returns
    -------
    Tuple of (rotation_matrix, post_correction_report).
    """
    ts_matrix = np.array([p.ts_embedding for p in pairs])  # (n, 384)
    py_matrix = np.array([p.py_embedding for p in pairs])  # (n, 384)

    if target_space == "python":
        source = ts_matrix
        target = py_matrix
        source_lang = "typescript"
    else:
        source = py_matrix
        target = ts_matrix
        source_lang = "python"

    # Orthogonal Procrustes: R = V @ U^T where U, S, V = svd(target^T @ source)
    M = target.T @ source  # (384, 384)
    U, _S, Vt = np.linalg.svd(M)
    R = U @ Vt  # optimal rotation matrix (384, 384)

    logger.info(
        "Procrustes rotation computed: target_space=%s, pairs=%d",
        target_space, len(pairs),
    )

    # Apply rotation to ALL embeddings of source language
    corrected_count = 0
    for node_id, embedding in embedding_store.items():
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        # Detect language from node properties
        node_lang = node.properties.get("language", "")
        if node_lang == source_lang:
            corrected = embedding @ R.T
            embedding_store.update(node_id, corrected)
            corrected_count += 1

    logger.info("Rotated %d %s embeddings", corrected_count, source_lang)

    # Re-measure alignment after correction
    post_report = measure_alignment(graph, embedding_store)
    post_report.correction_applied = "procrustes"

    return R, post_report
