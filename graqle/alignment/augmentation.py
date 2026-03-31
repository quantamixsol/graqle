"""R10 Correction Approach B — Description Augmentation for domain drift."""

# ── graqle:intelligence ──
# module: graqle.alignment.augmentation
# risk: MEDIUM (impact radius: 2 modules)
# consumers: alignment.pipeline
# dependencies: numpy, graqle.alignment.types, graqle.alignment.embedding_store
# constraints: modifies node descriptions — adds cross-domain context
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from typing import Any, List, Set

import numpy as np

from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.measurement import measure_alignment
from graqle.alignment.types import AlignmentPair, AlignmentReport

logger = logging.getLogger("graqle.alignment.augmentation")


def extract_key_terms(description: str) -> Set[str]:
    """Extract key terms from a description for cross-domain augmentation.

    Uses simple word tokenization — no NLP dependencies.
    Filters out common stop words and short tokens.
    """
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "and", "but", "or", "nor",
        "not", "so", "yet", "both", "either", "neither", "each", "every", "all",
        "any", "few", "more", "most", "other", "some", "such", "no", "only",
        "same", "than", "too", "very", "this", "that", "these", "those", "it",
    }
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", description.lower())
    return {w for w in words if len(w) > 2 and w not in stop_words}


def apply_description_augmentation(
    pairs: List[AlignmentPair],
    graph: Any,
    embedding_store: EmbeddingStore,
    embedding_model: Any = None,
) -> AlignmentReport:
    """Fix domain drift by augmenting node descriptions with cross-domain terms.

    For each misaligned pair (YELLOW or worse), extracts key terms from
    both descriptions and augments each with terms unique to the other side.

    Parameters
    ----------
    pairs:
        Alignment pairs to correct.
    graph:
        Graqle instance with node descriptions.
    embedding_store:
        Store to read/write corrected embeddings.
    embedding_model:
        Embedding model with ``.encode(text)`` method. If None, uses
        ``create_embedding_engine`` from the activation module.
    """
    if embedding_model is None:
        try:
            from graqle.activation.embeddings import create_embedding_engine
            embedding_model = create_embedding_engine(graph.config)
        except Exception as exc:
            logger.error("Cannot create embedding engine: %s", exc)
            return measure_alignment(graph, embedding_store)

    augmented_count = 0

    for pair in pairs:
        if pair.tier in ("GREEN", "BLUE"):
            continue  # already aligned, don't touch

        ts_node = graph.nodes.get(pair.ts_node_id)
        py_node = graph.nodes.get(pair.py_node_id)
        if ts_node is None or py_node is None:
            continue

        ts_desc = ts_node.properties.get("description", "")
        py_desc = py_node.properties.get("description", "")
        if not ts_desc or not py_desc:
            continue

        # Extract key terms from each description
        ts_terms = extract_key_terms(ts_desc)
        py_terms = extract_key_terms(py_desc)

        # Find terms unique to each side
        ts_only = ts_terms - py_terms
        py_only = py_terms - ts_terms

        if not ts_only and not py_only:
            continue

        # Augment: add cross-domain context to each description
        ts_augmented = ts_desc
        if py_only:
            ts_augmented += f" [Cross-domain: implements {', '.join(list(py_only)[:5])}]"
        py_augmented = py_desc
        if ts_only:
            py_augmented += f" [Cross-domain: called via {', '.join(list(ts_only)[:5])}]"

        # Re-embed augmented descriptions
        try:
            ts_new_emb = embedding_model.embed(ts_augmented)
            py_new_emb = embedding_model.embed(py_augmented)

            if isinstance(ts_new_emb, np.ndarray) and isinstance(py_new_emb, np.ndarray):
                embedding_store.update(pair.ts_node_id, ts_new_emb)
                embedding_store.update(pair.py_node_id, py_new_emb)

                # Store augmented descriptions for transparency
                ts_node.properties["description_augmented"] = ts_augmented
                py_node.properties["description_augmented"] = py_augmented

                augmented_count += 1
        except Exception as exc:
            logger.warning(
                "Augmentation failed for pair %s<->%s: %s",
                pair.ts_node_id, pair.py_node_id, exc,
            )

    logger.info("Augmented %d pairs", augmented_count)

    # Re-measure alignment
    post_report = measure_alignment(graph, embedding_store)
    post_report.correction_applied = "augmentation"
    return post_report
