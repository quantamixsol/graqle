"""Tests for R9 federated activator — async query routing."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from graqle.alignment.r9_config import FederatedActivationConfig
from graqle.federation.activator import query_single_kg, route_federated_query
from graqle.federation.registry import KGRegistry
from graqle.federation.types import FederatedQuery, KGRegistration, KGStatus


def _make_kg(kg_id: str = "sdk") -> KGRegistration:
    return KGRegistration(
        kg_id=kg_id, display_name=f"{kg_id} KG", language="python",
        node_count=100, edge_count=200, embedding_model="all-MiniLM-L6-v2",
        embedding_dim=384, endpoint=f"/path/{kg_id}",
    )


def _make_query(**overrides) -> FederatedQuery:
    defaults = dict(
        query_text="test query",
        query_embedding=np.random.default_rng(42).standard_normal(10),
        top_k_per_kg=5, timeout_ms=5000, min_quorum=1,
        unaligned_penalty=1.0,
    )
    defaults.update(overrides)
    return FederatedQuery(**defaults)


class TestQuerySingleKG:
    @pytest.mark.asyncio
    async def test_no_activation_fn_returns_empty(self):
        kg = _make_kg()
        query = _make_query()
        result = await query_single_kg(kg, query, activation_fn=None)
        assert result.status == "success"
        assert len(result.nodes) == 0

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self):
        async def slow_fn(kg_id, emb, top_k):
            await asyncio.sleep(10)
            return []

        kg = _make_kg()
        query = _make_query(timeout_ms=100)  # 100ms timeout
        result = await query_single_kg(kg, query, activation_fn=slow_fn)
        assert result.status == "timeout"

    @pytest.mark.asyncio
    async def test_error_returns_error_status(self):
        async def broken_fn(kg_id, emb, top_k):
            raise RuntimeError("test error")

        kg = _make_kg()
        query = _make_query()
        result = await query_single_kg(kg, query, activation_fn=broken_fn)
        assert result.status == "error"
        assert "test error" in result.error_message

    @pytest.mark.asyncio
    async def test_successful_activation_returns_nodes(self):
        async def mock_fn(kg_id, emb, top_k):
            return [
                ({"id": "n1", "type": "Function", "description": "test"}, 0.9),
                ({"id": "n2", "type": "Class", "description": "test2"}, 0.7),
            ]

        kg = _make_kg()
        query = _make_query()
        result = await query_single_kg(kg, query, activation_fn=mock_fn)
        assert result.status == "success"
        assert len(result.nodes) == 2
        assert result.nodes[0].provenance.home_kg_id == "sdk"
        assert result.nodes[0].provenance.activation_rank == 0


class TestRouteFederatedQuery:
    @pytest.mark.asyncio
    async def test_no_active_kgs(self):
        registry = KGRegistry()
        config = FederatedActivationConfig()
        query = _make_query()
        nodes, metadata = await route_federated_query(query, registry, config)
        assert len(nodes) == 0
        assert "error" in metadata

    @pytest.mark.asyncio
    async def test_quorum_not_met(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        config = FederatedActivationConfig()
        query = _make_query(min_quorum=5)  # need 5, have 1

        async def mock_fn(kg_id, emb, top_k):
            return []

        nodes, metadata = await route_federated_query(
            query, registry, config, activation_fn=mock_fn,
        )
        # 1 KG responds successfully but quorum needs 5
        assert len(nodes) == 0
        assert "Quorum not met" in metadata.get("error", "")

    @pytest.mark.asyncio
    async def test_successful_federation(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.register(_make_kg("ext"))
        config = FederatedActivationConfig()

        async def mock_fn(kg_id, emb, top_k):
            return [
                ({"id": f"{kg_id}_n1", "type": "Function", "description": "test"}, 0.8),
            ]

        query = _make_query()
        nodes, metadata = await route_federated_query(
            query, registry, config, activation_fn=mock_fn,
        )
        assert metadata["quorum_met"] is True
        assert metadata["kgs_responded"] == 2

    @pytest.mark.asyncio
    async def test_timeout_marks_degraded(self):
        registry = KGRegistry()
        registry.register(_make_kg("slow_kg"))

        async def slow_fn(kg_id, emb, top_k):
            await asyncio.sleep(10)
            return []

        config = FederatedActivationConfig()
        query = _make_query(timeout_ms=100, min_quorum=0)
        await route_federated_query(query, registry, config, activation_fn=slow_fn)
        kg = registry.get("slow_kg")
        assert kg.status == KGStatus.DEGRADED
