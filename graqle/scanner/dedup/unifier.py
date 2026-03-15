"""Entity Unifier — cross-source name matching via naming convention variants.

Maintains a lookup table of all entity names with their naming convention
variants (camelCase, snake_case, kebab-case, space-separated, etc.).
When a document mentions any variant → link to the existing node.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.unifier
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_unifier
# dependencies: __future__, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityEntry:
    """A registered entity with its name variants."""

    node_id: str
    label: str
    source_type: str  # code, api_spec, json_config, user_knowledge, document
    variants: set[str] = field(default_factory=set)


# Source type priority (lower = higher authority)
_SOURCE_PRIORITY: dict[str, int] = {
    "code": 1,
    "api_spec": 2,
    "json_config": 3,
    "user_knowledge": 4,
    "document": 5,
}


class EntityUnifier:
    """Matches entities across sources by name variants.

    Parameters
    ----------
    case_insensitive:
        If ``True``, all matching is case-insensitive.
    naming_conventions:
        If ``True``, generate camelCase/snake_case/kebab variants.
    """

    def __init__(
        self,
        case_insensitive: bool = True,
        naming_conventions: bool = True,
    ) -> None:
        self._case_insensitive = case_insensitive
        self._naming_conventions = naming_conventions
        self._registry: dict[str, EntityEntry] = {}  # node_id → entry
        self._variant_index: dict[str, list[str]] = {}  # variant → [node_ids]

    def register(self, node_id: str, label: str, source_type: str) -> None:
        """Register a node with its name variants."""
        variants = self._generate_variants(label)
        entry = EntityEntry(
            node_id=node_id,
            label=label,
            source_type=source_type,
            variants=variants,
        )
        self._registry[node_id] = entry

        for v in variants:
            self._variant_index.setdefault(v, []).append(node_id)

    def find_matches(
        self, nodes: dict[str, dict[str, Any]]
    ) -> list[tuple[str, str, float]]:
        """Find entity matches across different source types.

        Returns list of ``(primary_id, secondary_id, confidence)`` tuples.
        Primary = higher authority source.
        """
        matches: list[tuple[str, str, float]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for variant, node_ids in self._variant_index.items():
            if len(node_ids) <= 1:
                continue

            # Only match across different source types
            for i, nid_a in enumerate(node_ids):
                for nid_b in node_ids[i + 1:]:
                    if nid_a == nid_b:
                        continue
                    pair = tuple(sorted([nid_a, nid_b]))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    entry_a = self._registry.get(nid_a)
                    entry_b = self._registry.get(nid_b)
                    if not entry_a or not entry_b:
                        continue

                    # Skip same-source matches
                    if entry_a.source_type == entry_b.source_type:
                        continue

                    # Compute confidence based on variant overlap
                    overlap = entry_a.variants & entry_b.variants
                    total = min(len(entry_a.variants), len(entry_b.variants))
                    confidence = len(overlap) / max(total, 1)

                    # Determine primary (higher authority)
                    pri_a = _SOURCE_PRIORITY.get(entry_a.source_type, 10)
                    pri_b = _SOURCE_PRIORITY.get(entry_b.source_type, 10)

                    if pri_a <= pri_b:
                        primary, secondary = nid_a, nid_b
                    else:
                        primary, secondary = nid_b, nid_a

                    matches.append((primary, secondary, confidence))

        # Sort by confidence descending
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches

    def _generate_variants(self, name: str) -> set[str]:
        """Generate naming convention variants for a name."""
        variants: set[str] = set()

        if not name or len(name) < 2:
            return variants

        # Original
        if self._case_insensitive:
            variants.add(name.lower())
        else:
            variants.add(name)

        if not self._naming_conventions:
            return variants

        # Split into tokens
        tokens = _tokenise(name)
        if not tokens:
            return variants

        # snake_case
        variants.add("_".join(tokens))
        # camelCase
        if len(tokens) > 1:
            variants.add(tokens[0] + "".join(t.capitalize() for t in tokens[1:]))
        # PascalCase
        variants.add("".join(t.capitalize() for t in tokens))
        # kebab-case
        variants.add("-".join(tokens))
        # space separated
        variants.add(" ".join(tokens))
        # joined lowercase
        variants.add("".join(tokens))

        return variants


def _tokenise(name: str) -> list[str]:
    """Split a name into lowercase tokens.

    Handles: camelCase, PascalCase, snake_case, kebab-case, dot.case,
    path/segments, file.ext.
    """
    # Remove file extension
    if "." in name:
        base = name.rsplit(".", 1)[0]
    else:
        base = name

    # Split on common delimiters
    parts = re.split(r'[_\-./\\:\s]+', base)

    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        # Split camelCase/PascalCase
        camel_parts = re.findall(r'[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)', part)
        if camel_parts:
            tokens.extend(p.lower() for p in camel_parts)
        else:
            tokens.append(part.lower())

    return [t for t in tokens if len(t) >= 2]
