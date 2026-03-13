"""Base model backend — the protocol that all backends implement."""

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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
