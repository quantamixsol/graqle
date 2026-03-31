"""Tests for R9 FederationCoordinator merge algorithm."""

from __future__ import annotations

import numpy as np

from graqle.alignment.r9_config import FederatedActivationConfig
from graqle.federation.merger import FederationCoordinator
from graqle.federation.types import ProvenanceNode, ProvenanceTag


def _make_node(
    kg_id: str = "sdk",
    score: float = 0.8,
    rank: int = 0,
    node_type: str = "Function",
    description: str = "test",
    embedding: list[float] | None = None,
) -> ProvenanceNode:
    prov = ProvenanceTag(
        home_kg_id=kg_id, activation_score=score, activation_rank=rank,
        query_timestamp="2026-03-31T00:00:00Z", response_ms=50.0,
        embedding_model="all-MiniLM-L6-v2",
    )
    emb = np.array(embedding) if embedding else np.random.default_rng(hash((kg_id, rank)) % (2**31)).standard_normal(10)
    return ProvenanceNode(
        node_id=f"{kg_id}_node_{rank}", node_type=node_type, language="python",
        description=description, chunk_text="", embedding=emb,
        properties={}, provenance=prov, normalized_score=score,
    )


class TestFederationCoordinator:
    def test_empty_nodes(self):
        config = FederatedActivationConfig()
        coordinator = FederationCoordinator(config)
        assert coordinator.merge([], config) == []

    def test_merge_assigns_ranks(self):
        config = FederatedActivationConfig()
        coordinator = FederationCoordinator(config)
        nodes = [
            _make_node("sdk", 0.9, 0),
            _make_node("ext", 0.7, 0),
            _make_node("sdk", 0.5, 1),
        ]
        merged = coordinator.merge(nodes, config)
        assert merged[0].federation_rank == 0
        assert merged[-1].federation_rank == len(merged) - 1

    def test_results_from_both_kgs(self):
        config = FederatedActivationConfig()
        coordinator = FederationCoordinator(config)
        nodes = [
            _make_node("sdk", 0.9, 0),
            _make_node("ext", 0.8, 0),
        ]
        merged = coordinator.merge(nodes, config)
        kg_ids = {n.provenance.home_kg_id for n in merged}
        assert "sdk" in kg_ids
        assert "ext" in kg_ids

    def test_semantic_dedup_removes_cross_kg_duplicates(self):
        config = FederatedActivationConfig(dedup_threshold=0.90)
        coordinator = FederationCoordinator(config)
        # Same embedding in different KGs → should be deduped
        emb = [1.0, 0.0, 0.0, 0.0, 0.0]
        nodes = [
            _make_node("sdk", 0.9, 0, embedding=emb),
            _make_node("ext", 0.7, 0, embedding=emb),  # identical
        ]
        merged = coordinator.merge(nodes, config)
        non_dup = [n for n in merged if not n.is_duplicate]
        assert len(non_dup) == 1

    def test_semantic_dedup_preserves_within_kg(self):
        config = FederatedActivationConfig(dedup_threshold=0.90)
        coordinator = FederationCoordinator(config)
        emb = [1.0, 0.0, 0.0]
        nodes = [
            _make_node("sdk", 0.9, 0, embedding=emb),
            _make_node("sdk", 0.7, 1, embedding=emb),  # same KG, not deduped
        ]
        merged = coordinator.merge(nodes, config)
        assert len(merged) == 2  # both kept

    def test_conflict_detection(self):
        config = FederatedActivationConfig(conflict_detection=True)
        coordinator = FederationCoordinator(config)
        # Same type + same description prefix from different KGs
        nodes = [
            _make_node("sdk", 0.9, 0, node_type="Function", description="handle_auth validates tokens"),
            _make_node("ext", 0.8, 0, node_type="Function", description="handle_auth validates tokens"),
        ]
        merged = coordinator.merge(nodes, config)
        conflicts = [n for n in merged if n.conflict_flag]
        assert len(conflicts) >= 1

    def test_diversity_enforcement(self):
        config = FederatedActivationConfig(
            diversity_enforcement=True, min_diversity_ratio=0.3,
        )
        coordinator = FederationCoordinator(config)
        # SDK dominates with 4 nodes, ext has 1
        nodes = [_make_node("sdk", 0.9 - i * 0.1, i) for i in range(4)]
        nodes.append(_make_node("ext", 0.5, 0))
        merged = coordinator.merge(nodes, config)
        # Ext node should have been boosted
        ext_nodes = [n for n in merged if n.provenance.home_kg_id == "ext"]
        assert len(ext_nodes) >= 1

    def test_authority_weighting(self):
        config = FederatedActivationConfig(
            authority_weights={"sdk": 2.0, "ext": 0.5},
        )
        coordinator = FederationCoordinator(config)
        nodes = [
            _make_node("sdk", 0.5, 0),
            _make_node("ext", 0.5, 0),
        ]
        merged = coordinator.merge(nodes, config)
        sdk_node = next(n for n in merged if n.provenance.home_kg_id == "sdk")
        ext_node = next(n for n in merged if n.provenance.home_kg_id == "ext")
        # SDK should score higher due to 2x authority
        assert sdk_node.normalized_score > ext_node.normalized_score
