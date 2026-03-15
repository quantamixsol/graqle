"""AdapterAutoSelector — automatic LoRA adapter selection per entity type.

Maps CogniNode entity types to the best available LoRA adapter from the registry.
Supports exact match, fuzzy match, and domain-level fallback.

Usage:
    selector = AdapterAutoSelector(registry)
    selector.register_mapping("GOV_REQUIREMENT", "governance/eu-ai-act-v1")

    # Auto-assign during activation:
    for node in active_nodes:
        adapter = selector.select(node)
        if adapter:
            loader.swap_adapter(adapter.path, adapter.adapter_id)
"""

# ── graqle:intelligence ──
# module: graqle.adapters.auto_select
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_auto_select
# dependencies: __future__, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.adapters.auto_select")


@dataclass
class SelectionResult:
    """Result of adapter auto-selection."""
    node_id: str
    entity_type: str
    adapter_id: str | None
    match_type: str  # "exact", "fuzzy", "domain", "none"
    confidence: float  # 0-1


class AdapterAutoSelector:
    """Automatically select LoRA adapters based on node entity type.

    Selection priority:
    1. Explicit mapping (entity_type -> adapter_id)
    2. Domain match (entity_type domain prefix -> adapter domain)
    3. Fuzzy match (entity_type substring in adapter name)
    4. None (use default backend, no adapter)
    """

    def __init__(self, registry: Any = None) -> None:
        self._registry = registry
        self._explicit_map: dict[str, str] = {}  # entity_type -> adapter_id
        self._domain_map: dict[str, str] = {}  # domain -> adapter_id
        self._cache: dict[str, SelectionResult] = {}

    def register_mapping(self, entity_type: str, adapter_id: str) -> None:
        """Register explicit entity_type -> adapter_id mapping."""
        self._explicit_map[entity_type.upper()] = adapter_id
        self._cache.clear()

    def register_domain(self, domain: str, adapter_id: str) -> None:
        """Register domain-level fallback mapping."""
        self._domain_map[domain.lower()] = adapter_id
        self._cache.clear()

    def select(self, node: Any) -> SelectionResult:
        """Select the best adapter for a CogniNode.

        Args:
            node: CogniNode with entity_type and id fields

        Returns:
            SelectionResult with adapter_id (or None if no match)
        """
        entity_type = getattr(node, "entity_type", "Entity").upper()
        node_id = getattr(node, "id", "unknown")

        # Check cache
        cache_key = f"{node_id}:{entity_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._do_select(node_id, entity_type)
        self._cache[cache_key] = result
        return result

    def _do_select(self, node_id: str, entity_type: str) -> SelectionResult:
        # 1. Explicit mapping
        if entity_type in self._explicit_map:
            aid = self._explicit_map[entity_type]
            logger.debug(f"Exact match: {entity_type} -> {aid}")
            return SelectionResult(node_id, entity_type, aid, "exact", 1.0)

        # 2. Domain match
        # Extract domain from entity_type (e.g., "GOV_REQUIREMENT" -> "gov")
        domain_prefix = entity_type.split("_")[0].lower() if "_" in entity_type else entity_type.lower()
        if domain_prefix in self._domain_map:
            aid = self._domain_map[domain_prefix]
            logger.debug(f"Domain match: {entity_type} (domain={domain_prefix}) -> {aid}")
            return SelectionResult(node_id, entity_type, aid, "domain", 0.7)

        # 3. Fuzzy match from registry
        if self._registry is not None:
            adapters = self._registry.list_adapters()
            for adapter in adapters:
                # Check if entity_type appears in adapter name or domain
                adapter_name = (adapter.name or "").upper()
                adapter_domain = (adapter.domain or "").upper()
                if entity_type in adapter_name or entity_type in adapter_domain:
                    aid = adapter.adapter_id
                    logger.debug(f"Fuzzy match: {entity_type} -> {aid}")
                    return SelectionResult(node_id, entity_type, aid, "fuzzy", 0.5)

        # 4. No match
        return SelectionResult(node_id, entity_type, None, "none", 0.0)

    def select_batch(self, nodes: list[Any]) -> list[SelectionResult]:
        """Select adapters for multiple nodes."""
        return [self.select(node) for node in nodes]

    def clear_cache(self) -> None:
        """Clear selection cache."""
        self._cache.clear()

    @property
    def mapping_count(self) -> int:
        return len(self._explicit_map) + len(self._domain_map)
