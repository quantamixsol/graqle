"""Tests for R9 KG Registry."""

from __future__ import annotations

from graqle.federation.registry import KGRegistry
from graqle.federation.types import KGRegistration, KGStatus


def _make_kg(kg_id: str = "sdk", **overrides) -> KGRegistration:
    defaults = dict(
        kg_id=kg_id, display_name=f"{kg_id} KG", language="python",
        node_count=100, edge_count=200, embedding_model="all-MiniLM-L6-v2",
        embedding_dim=384, endpoint=f"/path/{kg_id}",
    )
    defaults.update(overrides)
    return KGRegistration(**defaults)


class TestKGRegistry:
    def test_register_and_get_active(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.register(_make_kg("ext", language="typescript"))
        active = registry.get_active()
        assert len(active) == 2

    def test_idempotent_register(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.register(_make_kg("sdk", node_count=999))
        assert len(registry) == 1
        assert registry.get("sdk").node_count == 999

    def test_deregister_graceful(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.deregister("sdk", graceful=True)
        assert registry.get("sdk").status == KGStatus.DRAINING
        assert len(registry.get_active()) == 0

    def test_deregister_immediate(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.deregister("sdk", graceful=False)
        assert registry.get("sdk") is None
        assert len(registry) == 0

    def test_heartbeat_updates_avg(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.heartbeat("sdk", response_ms=100.0)
        kg = registry.get("sdk")
        assert kg.avg_response_ms > 0

    def test_heartbeat_auto_recover(self):
        registry = KGRegistry()
        kg = _make_kg("sdk")
        registry.register(kg)
        registry.mark_degraded("sdk", "slow")
        assert registry.get("sdk").status == KGStatus.DEGRADED
        registry.heartbeat("sdk", response_ms=500)  # fast enough
        assert registry.get("sdk").status == KGStatus.ACTIVE

    def test_mark_degraded(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.mark_degraded("sdk", "test reason")
        assert registry.get("sdk").status == KGStatus.DEGRADED
        # Still returned by get_active (degraded is queryable)
        assert len(registry.get_active()) == 1

    def test_list_all(self):
        registry = KGRegistry()
        registry.register(_make_kg("sdk"))
        registry.register(_make_kg("ext"))
        registry.deregister("ext", graceful=True)
        assert len(registry.list_all()) == 2

    def test_deregister_nonexistent(self):
        registry = KGRegistry()
        registry.deregister("nonexistent")  # should not raise
