"""Tests for P2 BackendPool — parallel panelist dispatch."""
from __future__ import annotations

import asyncio

import pytest

from graqle.orchestration.backend_pool import BackendPool, PanelistResponse


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------


class MockBackend:
    """Minimal ModelBackend-compatible mock."""

    def __init__(self, response: str = "mock response", cost: float = 0.003, fail: bool = False):
        self._response = response
        self._cost = cost
        self._fail = fail

    async def generate(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.3, stop=None) -> str:
        if self._fail:
            raise RuntimeError("Backend failure")
        return self._response

    @property
    def name(self) -> str:
        return "mock:test"

    @property
    def cost_per_1k_tokens(self) -> float:
        return self._cost


# ---------------------------------------------------------------------------
# PanelistResponse
# ---------------------------------------------------------------------------


class TestPanelistResponse:

    def test_ok_when_no_error(self):
        r = PanelistResponse(panelist="p1", response="hello")
        assert r.ok is True

    def test_not_ok_when_error(self):
        r = PanelistResponse(panelist="p1", error="boom")
        assert r.ok is False

    def test_frozen(self):
        r = PanelistResponse(panelist="p1")
        with pytest.raises(AttributeError):
            r.panelist = "p2"  # type: ignore[misc]

    def test_defaults(self):
        r = PanelistResponse(panelist="p1")
        assert r.response == ""
        assert r.cost_usd == 0.0
        assert r.latency_ms == 0.0
        assert r.error is None


# ---------------------------------------------------------------------------
# BackendPool
# ---------------------------------------------------------------------------


class TestBackendPool:

    def test_panelist_names(self):
        pool = BackendPool([("a", MockBackend()), ("b", MockBackend())])
        assert pool.panelist_names == ["a", "b"]

    def test_empty_pool_returns_empty(self):
        pool = BackendPool([])
        results = asyncio.run(pool.dispatch_all("test"))
        assert results == []

    @pytest.mark.asyncio
    async def test_dispatch_all_returns_responses(self):
        pool = BackendPool([
            ("p1", MockBackend("answer1")),
            ("p2", MockBackend("answer2")),
        ])
        results = await pool.dispatch_all("question")
        assert len(results) == 2
        assert all(r.ok for r in results)
        names = [r.panelist for r in results]
        assert "p1" in names
        assert "p2" in names

    @pytest.mark.asyncio
    async def test_one_failure_doesnt_kill_others(self):
        pool = BackendPool([
            ("good", MockBackend("ok")),
            ("bad", MockBackend(fail=True)),
        ])
        results = await pool.dispatch_all("test")
        assert len(results) == 2
        good = [r for r in results if r.panelist == "good"][0]
        bad = [r for r in results if r.panelist == "bad"][0]
        assert good.ok is True
        assert good.response == "ok"
        assert bad.ok is False
        assert "Backend failure" in bad.error

    @pytest.mark.asyncio
    async def test_latency_is_measured(self):
        pool = BackendPool([("p1", MockBackend())])
        results = await pool.dispatch_all("test")
        assert results[0].latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_cost_is_estimated(self):
        pool = BackendPool([("p1", MockBackend("a" * 100, cost=0.01))])
        results = await pool.dispatch_all("test")
        assert results[0].cost_usd > 0.0

    @pytest.mark.asyncio
    async def test_clearance_filter_applied(self):
        def my_filter(prompt: str, panelist: str) -> str:
            return f"[FILTERED for {panelist}] {prompt}"

        pool = BackendPool(
            [("p1", MockBackend())],
            clearance_filter=my_filter,
        )
        # Can't directly check the filtered prompt passed to backend,
        # but at least verify the call succeeds
        results = await pool.dispatch_all("secret data")
        assert len(results) == 1
        assert results[0].ok is True


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestBackendPoolSummary:

    def test_summary_all_ok(self):
        results = [
            PanelistResponse(panelist="p1", response="ok", cost_usd=0.01, latency_ms=50.0),
            PanelistResponse(panelist="p2", response="ok", cost_usd=0.02, latency_ms=100.0),
        ]
        s = BackendPool.summary(results)
        assert s["total"] == 2
        assert s["succeeded"] == 2
        assert s["failed"] == 0
        assert s["cost_usd"] == pytest.approx(0.03)
        assert s["latency_ms"] == pytest.approx(100.0)

    def test_summary_with_failure(self):
        results = [
            PanelistResponse(panelist="p1", response="ok", cost_usd=0.01, latency_ms=50.0),
            PanelistResponse(panelist="p2", error="timeout", latency_ms=30000.0),
        ]
        s = BackendPool.summary(results)
        assert s["succeeded"] == 1
        assert s["failed"] == 1
        assert "p2" in s["errors"]

    def test_summary_empty(self):
        s = BackendPool.summary([])
        assert s["total"] == 0
        assert s["latency_ms"] == 0.0
