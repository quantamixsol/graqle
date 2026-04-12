"""R9 Federation Coordinator — 6-stage merge algorithm."""

# ── graqle:intelligence ──
# module: graqle.federation.merger
# risk: HIGH (impact radius: federation results)
# consumers: federation.activator, federation.reasoning
# dependencies: numpy, graqle.federation.types, graqle.alignment.types
# constraints: internal-pattern-B — all thresholds from FederatedActivationConfig
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

from graqle.alignment.r9_config import FederatedActivationConfig
from graqle.alignment.types import cosine_similarity
from graqle.federation.types import ProvenanceNode

logger = logging.getLogger("graqle.federation.merger")


class FederationCoordinator:
    """Merges activation results from multiple KGs into a single ranked list.

    6-stage pipeline:
        1. Z-score normalization (per-KG score distributions)
        2. Reciprocal Rank Fusion (RRF, rank-based merging)
        3. Authority weighting (per-KG domain expertise)
        4. Semantic deduplication (cross-KG near-duplicates)
        5. Conflict detection (contradictory results)
        6. Diversity enforcement (minority KG representation)
    """

    def __init__(self, config: FederatedActivationConfig) -> None:
        self.config = config

    def merge(
        self,
        all_nodes: List[ProvenanceNode],
        config: FederatedActivationConfig,
    ) -> List[ProvenanceNode]:
        """Full merge pipeline."""
        if not all_nodes:
            return []

        # Stage 1: Z-score normalization
        all_nodes = self._zscore_normalize(all_nodes)

        # Stage 2: RRF scoring
        all_nodes = self._rrf_score(all_nodes, config.rrf_k)

        # Stage 3: Authority weighting
        all_nodes = self._apply_authority_weights(all_nodes, config)

        # Stage 4: Semantic dedup
        all_nodes = self._semantic_dedup(all_nodes, config.dedup_threshold)

        # Stage 5: Conflict detection
        if config.conflict_detection:
            all_nodes = self._detect_conflicts(all_nodes)

        # Stage 6: Diversity enforcement
        if config.diversity_enforcement:
            all_nodes = self._enforce_diversity(all_nodes, config.min_diversity_ratio)

        # Sort by final score descending
        all_nodes.sort(key=lambda n: n.normalized_score, reverse=True)

        # Assign federation ranks
        for rank, node in enumerate(all_nodes):
            node.federation_rank = rank

        return all_nodes

    def _zscore_normalize(self, nodes: List[ProvenanceNode]) -> List[ProvenanceNode]:
        """Z-score normalization per KG for score comparability."""
        by_kg: Dict[str, List[ProvenanceNode]] = {}
        for node in nodes:
            kg_id = node.provenance.home_kg_id
            by_kg.setdefault(kg_id, []).append(node)

        for kg_id, kg_nodes in by_kg.items():
            scores = np.array([n.normalized_score for n in kg_nodes])
            mean = float(np.mean(scores))
            std = float(np.std(scores))
            if std < 1e-8:
                std = 1.0

            for node in kg_nodes:
                node.normalized_score = (node.normalized_score - mean) / std

        return nodes

    def _rrf_score(
        self, nodes: List[ProvenanceNode], k: int = 60,
    ) -> List[ProvenanceNode]:
        """Reciprocal Rank Fusion (Cormack et al., 2009).

        RRF score = 1 / (K + rank_in_kg). K=60 is standard.
        """
        by_kg: Dict[str, List[ProvenanceNode]] = {}
        for node in nodes:
            kg_id = node.provenance.home_kg_id
            by_kg.setdefault(kg_id, []).append(node)

        for kg_id, kg_nodes in by_kg.items():
            kg_nodes.sort(key=lambda n: n.normalized_score, reverse=True)
            for rank, node in enumerate(kg_nodes):
                rrf_contribution = 1.0 / (k + rank)
                node.normalized_score += rrf_contribution

        return nodes

    def _apply_authority_weights(
        self,
        nodes: List[ProvenanceNode],
        config: FederatedActivationConfig,
    ) -> List[ProvenanceNode]:
        """Apply per-KG authority weights."""
        for node in nodes:
            kg_id = node.provenance.home_kg_id
            weight = config.authority_weights.get(kg_id, 1.0)
            node.normalized_score *= weight
        return nodes

    def _semantic_dedup(
        self,
        nodes: List[ProvenanceNode],
        threshold: float,
    ) -> List[ProvenanceNode]:
        """Semantic dedup: remove cross-KG near-duplicates.

        Only deduplicates across KGs (not within same KG).
        Higher-scoring nodes survive.
        """
        if not nodes:
            return nodes

        nodes.sort(key=lambda n: n.normalized_score, reverse=True)

        survivors: list[ProvenanceNode] = []
        for candidate in nodes:
            if candidate.embedding is None:
                survivors.append(candidate)
                continue

            is_dup = False
            for survivor in survivors:
                if survivor.embedding is None:
                    continue
                # Only dedup across KGs
                if candidate.provenance.home_kg_id == survivor.provenance.home_kg_id:
                    continue
                sim = cosine_similarity(candidate.embedding, survivor.embedding)
                if sim >= threshold:
                    candidate.is_duplicate = True
                    is_dup = True
                    break

            if not is_dup:
                survivors.append(candidate)

        return survivors

    def _detect_conflicts(
        self, nodes: List[ProvenanceNode],
    ) -> List[ProvenanceNode]:
        """Flag results from different KGs that may contradict.

        Conflicts are FLAGGED, not resolved. Both kept for graq_reason.
        """
        identity_groups: Dict[str, List[ProvenanceNode]] = {}
        for node in nodes:
            if node.is_duplicate:
                continue
            identity_key = f"{node.node_type}:{node.description[:50]}"
            identity_groups.setdefault(identity_key, []).append(node)

        for key, group in identity_groups.items():
            kg_ids = set(n.provenance.home_kg_id for n in group)
            if len(kg_ids) > 1:
                for node in group:
                    node.conflict_flag = True

        return nodes

    def _enforce_diversity(
        self,
        nodes: List[ProvenanceNode],
        min_ratio: float,
    ) -> List[ProvenanceNode]:
        """Ensure minority KGs are represented in results.

        Boosts minority KG nodes' scores if below min_ratio.
        """
        if not nodes:
            return nodes

        kg_counts: Dict[str, int] = {}
        for node in nodes:
            if not node.is_duplicate:
                kg_id = node.provenance.home_kg_id
                kg_counts[kg_id] = kg_counts.get(kg_id, 0) + 1

        total = sum(kg_counts.values())
        if total == 0:
            return nodes

        for kg_id, count in kg_counts.items():
            ratio = count / total
            if ratio < min_ratio:
                boost_factor = min(min_ratio / (ratio + 1e-8), 2.0)
                for node in nodes:
                    if node.provenance.home_kg_id == kg_id and not node.is_duplicate:
                        node.normalized_score *= boost_factor

        return nodes
