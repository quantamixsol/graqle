"""
ADR-240 D1+D2: BackendRaceChain (first-to-finish / best-of-N) + CostAwareRouter
(auto cost/latency selection). Deterministic tests via MockBackend.
"""
from __future__ import annotations

import asyncio

import pytest

from graqle.backends import BackendRaceChain
from graqle.backends.base import GenerateResult
from graqle.backends.mock import MockBackend
from graqle.routing import CostAwareRouter, Difficulty


# ── fakes ─────────────────────────────────────────────────────────────────────

class _TimedMock(MockBackend):
    def __init__(self, name: str, delay: float, text: str, *, fail: bool = False):
        super().__init__()
        self._n, self._d, self._t, self._fail = name, delay, text, fail

    @property
    def name(self) -> str:
        return self._n

    async def generate(self, prompt, **kw) -> GenerateResult:
        await asyncio.sleep(self._d)
        if self._fail:
            raise RuntimeError(f"{self._n} failed")
        return GenerateResult(text=self._t, model=self._n)


class _CostMock(MockBackend):
    def __init__(self, name: str, cost: float):
        super().__init__()
        self._n, self._c = name, cost

    @property
    def name(self) -> str:
        return self._n

    @property
    def cost_per_1k_tokens(self) -> float:
        return self._c


# ── D1: BackendRaceChain ──────────────────────────────────────────────────────

def test_race_requires_at_least_one_backend():
    with pytest.raises(ValueError):
        BackendRaceChain([])


def test_race_first_to_finish_returns_fastest():
    fast = _TimedMock("fast", 0.02, "FAST")
    slow = _TimedMock("slow", 0.50, "SLOW")
    r = asyncio.run(BackendRaceChain([slow, fast]).generate("hi"))
    assert r.text == "FAST"


def test_race_first_to_finish_skips_a_failing_backend():
    boom = _TimedMock("boom", 0.01, "-", fail=True)
    ok = _TimedMock("ok", 0.05, "OK")
    r = asyncio.run(BackendRaceChain([boom, ok]).generate("hi"))
    assert r.text == "OK"


def test_race_all_fail_raises_runtimeerror():
    a = _TimedMock("a", 0.01, "-", fail=True)
    b = _TimedMock("b", 0.02, "-", fail=True)
    with pytest.raises(RuntimeError, match="All 2 backends failed"):
        asyncio.run(BackendRaceChain([a, b]).generate("hi"))


def test_best_of_n_picks_highest_score_deterministically():
    a = _TimedMock("a", 0.01, "short")
    b = _TimedMock("b", 0.01, "a much longer answer")
    r = asyncio.run(
        BackendRaceChain([a, b], scorer=lambda g: len(g.text)).generate("hi")
    )
    assert r.text == "a much longer answer"


def test_best_of_n_tie_breaks_on_original_order():
    a = _TimedMock("a", 0.01, "same")
    b = _TimedMock("b", 0.01, "same")
    r = asyncio.run(
        BackendRaceChain([a, b], scorer=lambda g: len(g.text)).generate("hi")
    )
    assert r.model == "a", "equal scores tie-break to earliest in the list"


def test_race_is_a_backend_droppable_anywhere():
    from graqle.backends.base import BaseBackend
    from graqle.core.types import ModelBackend
    race = BackendRaceChain([_TimedMock("a", 0.01, "x")])
    assert isinstance(race, BaseBackend)
    assert isinstance(race, ModelBackend)
    assert race.name.startswith("race:[")


# ── D2: CostAwareRouter ───────────────────────────────────────────────────────

def test_router_requires_candidates():
    with pytest.raises(ValueError):
        CostAwareRouter().select([], Difficulty.SIMPLE)


def test_router_simple_picks_cheapest():
    cheap, mid, strong = _CostMock("cheap", 0.001), _CostMock("mid", 0.01), _CostMock("strong", 0.06)
    picked = CostAwareRouter().select([strong, mid, cheap], Difficulty.SIMPLE)
    assert picked.name == "cheap"


def test_router_hard_forces_strongest():
    cheap, mid, strong = _CostMock("cheap", 0.001), _CostMock("mid", 0.01), _CostMock("strong", 0.06)
    picked = CostAwareRouter().select([cheap, mid, strong], Difficulty.HARD)
    assert picked.name == "strong"


def test_router_hard_with_only_cheap_returns_strongest_available():
    a, b = _CostMock("a", 0.001), _CostMock("b", 0.002)
    picked = CostAwareRouter().select([a, b], Difficulty.HARD)
    assert picked.name == "b", "never None — the dearest available is returned"


def test_router_cost_ceiling_never_empties():
    cheap, strong = _CostMock("cheap", 0.001), _CostMock("strong", 0.06)
    # a ceiling below even the cheapest must still return something
    picked = CostAwareRouter(max_cost_per_1k=0.0001).select([cheap, strong], Difficulty.SIMPLE)
    assert picked.name in ("cheap", "strong")


def test_router_tie_breaks_on_latency_then_name():
    a, b = _CostMock("a", 0.01), _CostMock("b", 0.01)  # equal cost
    picked = CostAwareRouter().select(
        [a, b], Difficulty.SIMPLE, latency_hint={"a": 200.0, "b": 50.0}
    )
    assert picked.name == "b", "equal cost → lower latency wins"
