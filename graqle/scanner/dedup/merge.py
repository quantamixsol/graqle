"""Merge engine — strategy for combining two nodes into one.

When two nodes are confirmed as the same entity:
- Sources: always accumulate
- Description: keep the longer one
- Confidence: take higher value
- Properties: incoming fills gaps, doesn't overwrite
- Edges: union of both (handled by orchestrator)

Merge priority (when data conflicts):
  Code > API spec > JSON config > User-taught > Documents
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.merge
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_merge
# dependencies: __future__, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Source type priority — lower = higher authority
_DEFAULT_PRIORITY: dict[str, int] = {
    "code": 1,
    "api_spec": 2,
    "json_config": 3,
    "user_knowledge": 4,
    "document": 5,
}


@dataclass
class MergeDecision:
    """Result of a merge attempt."""

    accepted: bool
    merged_node: dict[str, Any]
    primary_id: str
    secondary_id: str
    confidence: float
    method: str
    conflicts: list[str] = field(default_factory=list)


class MergeEngine:
    """Merges two nodes using source-priority strategy.

    Parameters
    ----------
    source_priority:
        List of source types in priority order (first = highest authority).
    """

    def __init__(self, source_priority: list[str] | None = None) -> None:
        if source_priority:
            self._priority = {s: i for i, s in enumerate(source_priority)}
        else:
            self._priority = dict(_DEFAULT_PRIORITY)

    def merge(
        self,
        primary: dict[str, Any],
        secondary: dict[str, Any],
        confidence: float = 1.0,
        method: str = "unknown",
    ) -> MergeDecision:
        """Merge *secondary* into *primary*.

        Returns a ``MergeDecision`` with the merged node data.
        """
        conflicts: list[str] = []

        # Determine which is truly primary based on source priority
        p_source = self._get_source_type(primary)
        s_source = self._get_source_type(secondary)
        p_rank = self._priority.get(p_source, 10)
        s_rank = self._priority.get(s_source, 10)

        if s_rank < p_rank:
            # Secondary has higher priority — swap
            primary, secondary = secondary, primary

        # Build merged node
        merged = dict(primary)
        merged_props = dict(primary.get("properties", {}))

        # Description: keep the longer one
        p_desc = primary.get("description", "")
        s_desc = secondary.get("description", "")
        if len(s_desc) > len(p_desc):
            merged["description"] = s_desc

        # Properties: incoming fills gaps
        s_props = secondary.get("properties", {})
        for key, val in s_props.items():
            if key not in merged_props:
                merged_props[key] = val
            elif merged_props[key] != val:
                # Detect conflict
                conflicts.append(
                    f"Property '{key}': primary={merged_props[key]}, secondary={val}"
                )

        # Track merge provenance
        sources = set()
        if "merge_sources" in merged_props:
            sources.update(merged_props["merge_sources"])
        sources.add(primary.get("id", ""))
        sources.add(secondary.get("id", ""))
        merged_props["merge_sources"] = sorted(sources - {""})
        merged_props["merge_method"] = method
        merged_props["merge_confidence"] = confidence

        merged["properties"] = merged_props

        return MergeDecision(
            accepted=True,
            merged_node=merged,
            primary_id=primary.get("id", ""),
            secondary_id=secondary.get("id", ""),
            confidence=confidence,
            method=method,
            conflicts=conflicts,
        )

    @staticmethod
    def _get_source_type(node: dict) -> str:
        """Classify a node's source type."""
        etype = node.get("entity_type", "").upper()
        props = node.get("properties", {})
        source = props.get("source", "")

        if etype in ("FUNCTION", "CLASS", "MODULE", "PYTHONMODULE", "JAVASCRIPTMODULE"):
            return "code"
        if etype == "ENDPOINT":
            return "api_spec"
        if etype in ("DEPENDENCY", "SCRIPT", "CONFIG", "TOOL_RULE", "RESOURCE"):
            return "json_config"
        if etype == "KNOWLEDGE" or "graq_learn" in source:
            return "user_knowledge"
        if etype in ("DOCUMENT", "SECTION"):
            return "document"
        return "code"
