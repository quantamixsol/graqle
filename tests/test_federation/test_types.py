"""Tests for R9 federation types."""

from __future__ import annotations

import json

import numpy as np
import pytest

from graqle.federation.types import (
    DomainAgent,
    FederatedQuery,
    FederatedReasoningRound,
    KGQueryResult,
    KGRegistration,
    KGStatus,
    ProvenanceNode,
    ProvenanceTag,
)


def _make_provenance(**overrides) -> ProvenanceTag:
    defaults = dict(
        home_kg_id="sdk", activation_score=0.9, activation_rank=0,
        query_timestamp="2026-03-31T00:00:00Z", response_ms=50.0,
        embedding_model="all-MiniLM-L6-v2",
    )
    defaults.update(overrides)
    return ProvenanceTag(**defaults)


def _make_node(**overrides) -> ProvenanceNode:
    defaults = dict(
        node_id="test_node", node_type="Function", language="python",
        description="test function", chunk_text="def test(): pass",
        embedding=np.array([1.0, 0.0, 0.0]), properties={},
        provenance=_make_provenance(),
    )
    defaults.update(overrides)
    return ProvenanceNode(**defaults)


class TestKGStatus:
    def test_all_statuses_defined(self):
        assert set(s.value for s in KGStatus) == {"active", "degraded", "offline", "draining"}


class TestProvenanceTag:
    def test_frozen(self):
        tag = _make_provenance()
        with pytest.raises(AttributeError):
            tag.home_kg_id = "modified"  # type: ignore

    def test_hashable(self):
        tag = _make_provenance()
        assert hash(tag)  # frozen=True makes it hashable


class TestKGRegistration:
    def test_to_dict(self):
        kg = KGRegistration(
            kg_id="sdk", display_name="SDK KG", language="python",
            node_count=100, edge_count=200, embedding_model="test",
            embedding_dim=384, endpoint="/path/to/kg",
        )
        d = kg.to_dict()
        assert d["kg_id"] == "sdk"
        assert d["status"] == "active"
        json.dumps(d)  # must be serializable


class TestProvenanceNode:
    def test_to_dict_serializable(self):
        node = _make_node()
        d = node.to_dict()
        json_str = json.dumps(d)
        assert "test_node" in json_str
        assert d["embedding"] == [1.0, 0.0, 0.0]

    def test_none_embedding(self):
        node = _make_node(embedding=None)
        d = node.to_dict()
        assert d["embedding"] is None


class TestKGQueryResult:
    def test_to_dict(self):
        result = KGQueryResult(
            kg_id="sdk", nodes=[_make_node()],
            response_ms=100.0, status="success",
        )
        d = result.to_dict()
        assert d["status"] == "success"
        assert len(d["nodes"]) == 1


class TestFederatedReasoningRound:
    def test_to_dict(self):
        agent = DomainAgent(
            agent_id="a1", home_kg_id="sdk", domain="code",
            expertise=["Function"], activated_nodes=[_make_node()],
            confidence=0.8,
        )
        rnd = FederatedReasoningRound(
            query="test", agents=[agent], round_number=1,
            contributions=[{"response": "answer"}],
            synthesis="merged answer", confidence=0.85,
            provenance_trail=[_make_provenance()],
        )
        d = rnd.to_dict()
        json.dumps(d)  # must be serializable
        assert d["round_number"] == 1


class TestActivationStrategyFederated:
    def test_federated_enum_value(self):
        from graqle.core.types import ActivationStrategy
        assert ActivationStrategy.FEDERATED.value == "federated"
