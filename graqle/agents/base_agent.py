"""BaseAgent — abstract agent interface for Graqle nodes."""

# ── graqle:intelligence ──
# module: graqle.agents.base_agent
# risk: LOW (impact radius: 3 modules)
# consumers: slm_agent, __init__, test_slm_agent
# dependencies: __future__, abc, typing, message, types
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from graqle.core.message import Message
from graqle.core.types import ModelBackend


class BaseAgent(ABC):
    """Abstract base class for node agents.

    Agents wrap model backends with domain-specific behavior.
    The simplest agent just forwards to the backend, but specialized
    agents can add tool use, structured output, or custom reasoning.
    """

    def __init__(self, backend: ModelBackend, **kwargs: Any) -> None:
        self.backend = backend

    @abstractmethod
    async def reason(
        self, query: str, context: list[Message], node_info: dict[str, Any]
    ) -> str:
        """Produce reasoning given query, neighbor messages, and node metadata."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
