"""AdapterRegistry — catalog of available LoRA adapters."""

# ── graqle:intelligence ──
# module: graqle.adapters.registry
# risk: MEDIUM (impact radius: 10 modules)
# consumers: sdk_self_audit, __init__, __init__, governance, governance_v3 +5 more
# dependencies: __future__, json, logging, pathlib, typing +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from graqle.adapters.config import AdapterConfig

logger = logging.getLogger("graqle.adapters.registry")


class AdapterRegistry:
    """Catalog of available LoRA adapters.

    The registry tracks which adapters exist, where they're stored,
    and their configurations. Supports local file storage and
    HuggingFace Hub.
    """

    def __init__(self, registry_path: str | Path = "./adapters") -> None:
        self.registry_path = Path(registry_path)
        self._adapters: dict[str, AdapterConfig] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._scan_local()
        self._loaded = True

    def _scan_local(self) -> None:
        """Scan local adapter directory for available adapters."""
        if not self.registry_path.exists():
            return

        for domain_dir in self.registry_path.iterdir():
            if not domain_dir.is_dir() or domain_dir.name.startswith("."):
                continue
            for adapter_dir in domain_dir.iterdir():
                if not adapter_dir.is_dir():
                    continue
                config_file = adapter_dir / "adapter_config.json"
                if config_file.exists():
                    try:
                        data = json.loads(config_file.read_text(encoding="utf-8"))
                        config = AdapterConfig(
                            adapter_id=f"{domain_dir.name}/{adapter_dir.name}",
                            name=adapter_dir.name,
                            domain=domain_dir.name,
                            **{k: v for k, v in data.items()
                               if k in AdapterConfig.__dataclass_fields__},
                        )
                        self._adapters[config.adapter_id] = config
                    except Exception as e:
                        logger.warning(f"Failed to load adapter {adapter_dir}: {e}")

    def register(self, config: AdapterConfig) -> None:
        """Register an adapter in the catalog."""
        self._adapters[config.adapter_id or config.full_id] = config

    def get(self, adapter_id: str) -> AdapterConfig | None:
        """Get adapter config by ID."""
        self._ensure_loaded()
        return self._adapters.get(adapter_id)

    def list_adapters(self, domain: str | None = None) -> list[AdapterConfig]:
        """List all registered adapters, optionally filtered by domain."""
        self._ensure_loaded()
        adapters = list(self._adapters.values())
        if domain:
            adapters = [a for a in adapters if a.domain == domain]
        return adapters

    def list_domains(self) -> list[str]:
        """List all domains with available adapters."""
        self._ensure_loaded()
        return list(set(a.domain for a in self._adapters.values()))

    @property
    def count(self) -> int:
        self._ensure_loaded()
        return len(self._adapters)
