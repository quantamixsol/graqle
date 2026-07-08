"""BackendRaceChain — race multiple backends, take the first (or best-of-N).

ADR-240 D1: the SDK had FALLBACK (sequential) and PARALLEL fan-out (BackendPool,
wait-for-ALL) but no RACE / first-to-finish / best-of-N primitive. This adds one.

Mirrors BackendFallbackChain exactly (subclasses BaseBackend, takes
list[BaseBackend], empty→ValueError, all-fail→RuntimeError) so it is a drop-in
ModelBackend anywhere a backend is expected — the agent behind AutonomousExecutor,
a TaskRouter target, a BackendPool panelist, or nested in a BackendFallbackChain.

Two modes:
  - scorer=None (default): FIRST-TO-FINISH — return the first successful result,
    cancel the losers (stops paying for slower providers).
  - scorer set:           BEST-OF-N — await all, return the highest-scored result
    (deterministic tie-break: score, then original backend order).

Uses ONLY BaseBackend.generate — no per-provider logic. Generic asyncio hedge
pattern; contains none of the patented debate/clearance machinery.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from graqle.backends.base import BaseBackend, GenerateResult

logger = logging.getLogger("graqle.backends.race")


class BackendRaceChain(BaseBackend):
    """Race backends concurrently; return the first success or the best-of-N.

    Usage:
        # first-to-finish (hedged request) — take whichever provider answers first
        race = BackendRaceChain([AnthropicBackend(...), OpenAIBackend(...)])
        result = await race.generate("prompt")

        # best-of-N — run both, keep the higher-scored answer
        race = BackendRaceChain([a, b], scorer=lambda r: len(r.text))
        result = await race.generate("prompt")
    """

    def __init__(
        self,
        backends: list[BaseBackend],
        *,
        timeout_s: float | None = None,
        scorer: Callable[[GenerateResult], float] | None = None,
    ) -> None:
        if not backends:
            raise ValueError("BackendRaceChain requires at least one backend")
        self._backends = backends
        self._timeout_s = timeout_s
        self._scorer = scorer
        self._last_used: str = ""
        self._last_cost_per_1k: float = backends[0].cost_per_1k_tokens

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> GenerateResult:
        async def _run(b: BaseBackend) -> tuple[str, float, GenerateResult]:
            coro = b.generate(
                prompt, max_tokens=max_tokens, temperature=temperature, stop=stop
            )
            if self._timeout_s is not None:
                coro = asyncio.wait_for(coro, timeout=self._timeout_s)
            return b.name, b.cost_per_1k_tokens, await coro

        tasks = {asyncio.ensure_future(_run(b)) for b in self._backends}

        if self._scorer is None:
            # ── FIRST-TO-FINISH ─────────────────────────────────────────────
            errors: list[BaseException] = []
            pending = tasks
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    exc = t.exception()
                    if exc is None:
                        name, cpk, result = t.result()
                        self._last_used, self._last_cost_per_1k = name, cpk
                        await self._cancel(pending)  # stop the losers
                        if errors:
                            logger.info(
                                "Race won by %s after %d failure(s)", name, len(errors)
                            )
                        return result
                    errors.append(exc)  # this one failed — keep waiting for a winner
            self._raise_all_failed(errors)

        # ── BEST-OF-N ───────────────────────────────────────────────────────
        done, _ = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
        scored: list[tuple[float, str, float, GenerateResult]] = []
        errors = []
        for t in done:
            exc = t.exception()
            if exc is None:
                name, cpk, result = t.result()
                scored.append((self._scorer(result), name, cpk, result))
            else:
                errors.append(exc)
        if not scored:
            self._raise_all_failed(errors)
        # deterministic tie-break: highest score, then earliest in the original list
        order = {b.name: i for i, b in enumerate(self._backends)}
        best = max(scored, key=lambda s: (s[0], -order.get(s[1], 0)))
        _, self._last_used, self._last_cost_per_1k, result = best
        return result

    async def _cancel(self, pending: set) -> None:
        for t in pending:
            t.cancel()
        if pending:
            # drain cancellations so no "Task was destroyed but pending" warnings
            await asyncio.gather(*pending, return_exceptions=True)

    def _raise_all_failed(self, errors: list[BaseException]) -> None:
        summary = "; ".join(f"{type(e).__name__}: {e}" for e in errors)
        raise RuntimeError(
            f"All {len(self._backends)} backends failed: {summary}"
        )

    @property
    def name(self) -> str:
        mode = "race" if self._scorer is None else "best_of"
        return f"{mode}:[{' | '.join(b.name for b in self._backends)}]"

    @property
    def cost_per_1k_tokens(self) -> float:
        # cost of the winning backend; before any run, defaults to the first.
        return self._last_cost_per_1k

    @property
    def last_used(self) -> str:
        return self._last_used
