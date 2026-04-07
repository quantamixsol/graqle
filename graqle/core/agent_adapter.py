"""CogniNodeAgent — wraps CogniNode + ModelBackend into AgentProtocol compliance."""
from __future__ import annotations

from typing import Any

from graqle.core.types import AgentProtocol, ClearanceLevel


class CogniNodeAgent:
    """Adapts a CogniNode + ModelBackend pair to satisfy AgentProtocol.

    AgentProtocol requires: name (str), model_id (str), generate(prompt, **kwargs) -> str.
    Additional governance properties: clearance_level, capability_tags, id, cost_per_1k_tokens.
    """

    def __init__(
        self,
        node: Any,
        backend: Any,
        *,
        clearance_level: ClearanceLevel = ClearanceLevel.PUBLIC,
    ) -> None:
        if node is None:
            raise ValueError("node must not be None")
        if backend is None:
            raise ValueError("backend must not be None")
        self._node = node
        self._backend = backend
        self._clearance_level = clearance_level

    @property
    def name(self) -> str:
        return getattr(self._node, "label", None) or getattr(self._node, "id", None) or "unknown"

    @property
    def model_id(self) -> str:
        return getattr(self._backend, "name", "unknown")

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Delegate to ModelBackend.generate() which is async."""
        kw: dict[str, Any] = {
            "max_tokens": kwargs.get("max_tokens", 1024),
            "temperature": kwargs.get("temperature", 0.3),
        }
        if "stop" in kwargs:
            kw["stop"] = kwargs["stop"]
        result = await self._backend.generate(prompt, **kw)
        if result is None:
            return ""
        return result.text if hasattr(result, "text") else str(result)

    @property
    def clearance_level(self) -> ClearanceLevel:
        return self._clearance_level

    @property
    def capability_tags(self) -> tuple[str, ...]:
        return tuple(getattr(self._node, "capability_tags", ()))

    @property
    def id(self) -> str:
        return getattr(self._node, "id", None) or getattr(self._node, "node_id", str(id(self._node)))

    @property
    def cost_per_1k_tokens(self) -> float:
        try:
            return float(getattr(self._backend, "cost_per_1k_tokens", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def __repr__(self) -> str:
        return f"CogniNodeAgent(name={self.name!r}, model={self.model_id!r})"
