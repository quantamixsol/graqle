"""Base model backend — the protocol that all backends implement."""

# ── graqle:intelligence ──
# module: graqle.backends.base
# risk: MEDIUM (impact radius: 31 modules)
# consumers: api, fallback, gemini, llamacpp_backend, local +26 more
# dependencies: __future__, abc
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBackend(ABC):
    """Abstract base class for model backends.

    All backends must implement async generate(). The ModelBackend protocol
    in core/types.py defines the structural interface; this ABC provides
    a convenient base class with shared functionality.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        """Generate text from a prompt."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    @abstractmethod
    def cost_per_1k_tokens(self) -> float:
        """Cost in USD per 1,000 tokens."""
        ...

    async def agenerate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ):
        """Stream generated text as an AsyncIterator[str].

        Default implementation: yields the full result as a single chunk.
        Backward-compatible for all existing backends — they get streaming
        for free without any changes.

        Override in backends that support native streaming (Anthropic, etc.)
        to yield token-by-token chunks for lower time-to-first-token.

        v0.38.0: Added for graq_generate streaming support (Phase 3).
        """
        result = await self.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
        yield result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
