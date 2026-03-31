"""Core alignment measurement — R10 using CALLS_VIA_MCP edges."""

# ── graqle:intelligence ──
# module: graqle.alignment.measurement
# risk: HIGH (impact radius: alignment pipeline)
# consumers: alignment runner, reports, diagnostics
# dependencies: numpy, graqle.alignment.types, graqle.alignment.tiers, graqle.alignment.embedding_store
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import numpy as np

from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.tiers import classify_alignment_tier
from graqle.alignment.types import AlignmentPair, AlignmentReport, cosine_similarity

logger = logging.getLogger("graqle.alignment.measurement")


def measure_alignment(
    graph: Any,
    embedding_store: EmbeddingStore,
) -> AlignmentReport:
    """Measure semantic alignment across all CALLS_VIA_MCP edges.

    For each MCP call edge, computes cosine similarity between the source
    (TypeScript caller) and target (Python callee) node embeddings, classifies
    the pair into an alignment tier, and returns an aggregate report.

    Args:
        graph: A Graqle instance with ``.edges`` and ``.nodes`` dicts.
        embedding_store: Store providing cached embeddings via ``.get(node_id)``.

    Returns:
        AlignmentReport with per-pair scores and aggregate statistics.
    """
    # 1. Collect all CALLS_VIA_MCP edges
    mcp_edges = [
        e for e in graph.edges.values() if e.relationship == "CALLS_VIA_MCP"
    ]
    logger.info("Found %d CALLS_VIA_MCP edges", len(mcp_edges))

    # 2. Build alignment pairs
    pairs: list[AlignmentPair] = []

    for edge in mcp_edges:
        ts_node = graph.nodes.get(edge.source_id)
        py_node = graph.nodes.get(edge.target_id)
        if ts_node is None or py_node is None:
            logger.debug(
                "Skipping edge %s->%s: missing node(s)",
                edge.source_id, edge.target_id,
            )
            continue

        ts_emb = embedding_store.get(ts_node.id)
        py_emb = embedding_store.get(py_node.id)
        if ts_emb is None or py_emb is None:
            logger.debug(
                "Skipping edge %s->%s: missing embedding(s)",
                ts_node.id, py_node.id,
            )
            continue

        sim = cosine_similarity(ts_emb, py_emb)
        tier = classify_alignment_tier(sim)
        tool_name = (
            edge.properties.get("tool_name", "unknown")
            if edge.properties else "unknown"
        )

        pairs.append(AlignmentPair(
            ts_node_id=ts_node.id,
            py_node_id=py_node.id,
            ts_embedding=ts_emb,
            py_embedding=py_emb,
            tool_name=tool_name,
            cosine_sim=float(sim),
            tier=tier,
        ))

    # 3. Early return when no pairs found
    if not pairs:
        logger.warning("No valid alignment pairs found")
        return AlignmentReport(pairs=[], diagnosis="no_pairs_found")

    # 4. Compute aggregate statistics
    sims = np.array([p.cosine_sim for p in pairs])

    # 5. Build tier distribution
    tier_distribution: dict[str, int] = dict(Counter(p.tier for p in pairs))

    # 6. Return full report
    return AlignmentReport(
        pairs=pairs,
        mean_cosine=float(np.mean(sims)),
        median_cosine=float(np.median(sims)),
        std_cosine=float(np.std(sims)),
        tier_distribution=tier_distribution,
    )
