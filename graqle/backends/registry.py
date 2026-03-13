"""BackendRegistry — resolve and manage model backends by name.

Provides a central registry for backend instances, supporting
lazy initialization, cost tracking, and name-based resolution.
"""

from __future__ import annotations

import logging
from typing import Any

from graqle.backends.base import BaseBackend
from graqle.core.types import ModelBackend

logger = logging.getLogger("graqle.backends.registry")

# Default backend configurations
BUILTIN_BACKENDS = {
    "mock": {
        "class": "graqle.backends.mock.MockBackend",
        "kwargs": {},
    },
    "anthropic:claude-haiku": {
        "class": "graqle.backends.api.AnthropicBackend",
        "kwargs": {"model": "claude-haiku-4-5-20251001"},
    },
    "anthropic:claude-sonnet": {
        "class": "graqle.backends.api.AnthropicBackend",
        "kwargs": {"model": "claude-sonnet-4-6"},
    },
    "openai:gpt-4o-mini": {
        "class": "graqle.backends.api.OpenAIBackend",
        "kwargs": {"model": "gpt-4o-mini"},
    },
    "ollama:qwen2.5": {
        "class": "graqle.backends.api.OllamaBackend",
        "kwargs": {"model": "qwen2.5:0.5b"},
    },
}


class BackendRegistry:
    """Central registry for model backends.

    Usage:
        registry = BackendRegistry()
        registry.register("my-model", MyBackend(args))
        backend = registry.get("my-model")
        # Or use builtin names:
        backend = registry.get("mock")
    """

    def __init__(self) -> None:
        self._instances: dict[str, ModelBackend] = {}
        self._total_cost: float = 0.0

    def register(self, name: str, backend: ModelBackend) -> None:
        """Register a backend instance."""
        self._instances[name] = backend
        logger.debug(f"Registered backend: {name}")

    def get(self, name: str) -> ModelBackend:
        """Get backend by name. Creates from builtin config if needed."""
        if name in self._instances:
            return self._instances[name]

        # Try builtin
        if name in BUILTIN_BACKENDS:
            backend = self._create_builtin(name)
            self._instances[name] = backend
            return backend

        raise KeyError(
            f"Backend '{name}' not found. Available: {list(self.available)}"
        )

    def _create_builtin(self, name: str) -> ModelBackend:
        """Create a backend from builtin configuration."""
        config = BUILTIN_BACKENDS[name]
        module_path, class_name = config["class"].rsplit(".", 1)

        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(**config["kwargs"])

    @property
    def available(self) -> list[str]:
        """List all available backend names."""
        return list(set(list(self._instances.keys()) + list(BUILTIN_BACKENDS.keys())))

    @property
    def registered(self) -> list[str]:
        """List currently instantiated backends."""
        return list(self._instances.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._instances or name in BUILTIN_BACKENDS
