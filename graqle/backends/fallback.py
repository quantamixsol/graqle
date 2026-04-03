"""BackendFallbackChain — resilient multi-backend with automatic failover.

Tries backends in priority order. If primary fails, falls back to
secondary, then tertiary. Logs which backend succeeded.
"""

# ── graqle:intelligence ──
# module: graqle.backends.fallback
# risk: LOW (impact radius: 1 modules)
# consumers: test_error_scenarios
# dependencies: __future__, logging, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging

from graqle.backends.base import BaseBackend, GenerateResult

logger = logging.getLogger("graqle.backends.fallback")


class BackendFallbackChain(BaseBackend):
    """Chain multiple backends with automatic failover.

    Usage:
        chain = BackendFallbackChain([
            AnthropicBackend(model="claude-haiku"),
            OpenAIBackend(model="gpt-4o-mini"),
            OllamaBackend(model="qwen2.5:0.5b"),
        ])
        result = await chain.generate("prompt")
        # Tries Anthropic first, falls back to OpenAI, then Ollama
    """

    def __init__(self, backends: list[BaseBackend]) -> None:
        if not backends:
            raise ValueError("BackendFallbackChain requires at least one backend")
        self._backends = backends
        self._last_used: str = ""
        self._failure_counts: dict[str, int] = {b.name: 0 for b in backends}

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> GenerateResult:
        errors: list[tuple[str, Exception]] = []

        for backend in self._backends:
            try:
                result = await backend.generate(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                )
                self._last_used = backend.name
                if errors:
                    logger.info(
                        f"Fallback succeeded: {backend.name} "
                        f"(after {len(errors)} failures: "
                        f"{', '.join(e[0] for e in errors)})"
                    )
                return result
            except Exception as e:
                self._failure_counts[backend.name] = (
                    self._failure_counts.get(backend.name, 0) + 1
                )
                errors.append((backend.name, e))
                logger.warning(f"Backend {backend.name} failed: {e}")

        # All backends failed
        error_summary = "; ".join(
            f"{name}: {err}" for name, err in errors
        )
        raise RuntimeError(
            f"All {len(self._backends)} backends failed: {error_summary}"
        )

    @property
    def name(self) -> str:
        names = [b.name for b in self._backends]
        return f"fallback:[{' -> '.join(names)}]"

    @property
    def cost_per_1k_tokens(self) -> float:
        # Return cost of the last successfully used backend
        if self._last_used:
            for b in self._backends:
                if b.name == self._last_used:
                    return b.cost_per_1k_tokens
        return self._backends[0].cost_per_1k_tokens

    @property
    def last_used(self) -> str:
        return self._last_used

    @property
    def failure_counts(self) -> dict[str, int]:
        return dict(self._failure_counts)
