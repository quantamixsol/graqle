"""BackendPool — parallel panelist dispatch for debate rounds.

Implements concurrent multi-backend dispatch with per-panelist
timeout isolation, optional clearance filtering, and cost/latency
aggregation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

from graqle.core.types import ModelBackend

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ClearanceFilterFn = Callable[[str, str], str]
"""(prompt, panelist_name) -> filtered_prompt."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanelistResponse:
    """Immutable result from a single panelist invocation."""

    panelist: str
    response: str = ""
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return ``True`` when the call succeeded without error."""
        return self.error is None


# ---------------------------------------------------------------------------
# BackendPool
# ---------------------------------------------------------------------------


class BackendPool:
    """Fan-out a prompt to multiple panelist backends in parallel."""

    def __init__(
        self,
        panelists: list[tuple[str, ModelBackend]],
        clearance_filter: ClearanceFilterFn | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._panelists = panelists
        self._clearance_filter = clearance_filter
        self._timeout_s = timeout_s

    @property
    def panelist_names(self) -> list[str]:
        """Return ordered list of registered panelist names."""
        return [name for name, _ in self._panelists]

    async def dispatch_all(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> list[PanelistResponse]:
        """Send *prompt* to every panelist concurrently and collect responses."""
        tasks = [
            self._dispatch_one(name, backend, prompt, max_tokens, temperature)
            for name, backend in self._panelists
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter: BaseException/CancelledError bypass _dispatch_one's try/except
        results: list[PanelistResponse] = []
        for i, r in enumerate(raw):
            if isinstance(r, BaseException):
                name = self._panelists[i][0] if i < len(self._panelists) else "unknown"
                results.append(PanelistResponse(
                    panelist=name, error=f"{type(r).__name__}: {r}",
                ))
            else:
                results.append(r)
        return results

    async def _dispatch_one(
        self,
        name: str,
        backend: ModelBackend,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> PanelistResponse:
        """Invoke a single panelist with timeout and error isolation."""
        effective_prompt = prompt
        if self._clearance_filter is not None:
            effective_prompt = self._clearance_filter(prompt, name)

        t0 = time.perf_counter()
        try:
            raw_result = await asyncio.wait_for(
                backend.generate(
                    effective_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=self._timeout_s,
            )
            # B2/M1: Extract truncation before str conversion
            _is_truncated = getattr(raw_result, "truncated", False)
            raw: str = str(raw_result)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            approx_tokens = max(len(raw) / 4, 1)
            cost_usd = approx_tokens * getattr(backend, "cost_per_1k_tokens", 0.0) / 1000.0
            if _is_truncated:
                logger.warning(
                    " Panelist %s response truncated (stop_reason=%s)",
                    name, getattr(raw_result, "stop_reason", ""),
                )
            return PanelistResponse(
                panelist=name, response=raw,
                cost_usd=cost_usd, latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return PanelistResponse(panelist=name, latency_ms=latency_ms, error=str(exc))

    @staticmethod
    def summary(results: list[PanelistResponse]) -> dict[str, Any]:
        """Aggregate statistics from a batch of panelist responses."""
        succeeded = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        return {
            "total": len(results),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "cost_usd": sum(r.cost_usd for r in results),
            "latency_ms": max((r.latency_ms for r in results), default=0.0),
            "errors": {r.panelist: r.error for r in failed},
        }
