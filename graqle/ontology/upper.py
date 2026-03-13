"""Upper Ontology — domain-agnostic type hierarchy.

Defines the abstract entity types that ALL domains share. Domain-specific
types extend these via the DomainRegistry.

The upper ontology maps to OWL class hierarchy concepts:
- Thing is the root (owl:Thing)
- Intermediate types are abstract classes
- Leaf types are instantiable entity types
"""

from __future__ import annotations

from typing import Dict, List, Set


# Domain-agnostic upper ontology — these types exist in every domain
UPPER_HIERARCHY: Dict[str, str] = {
    "Thing": "",
    # Abstract branches
    "Agent": "Thing",
    "Spatial": "Thing",
    "Temporal": "Thing",
    "Governance": "Thing",
    "Artifact": "Thing",
    "Measurement": "Thing",
    "Cognitive": "Thing",
    "Lineage": "Thing",
}


class UpperOntology:
    """Domain-agnostic OWL-like class hierarchy.

    Supports inheritance queries: get_ancestors, is_subtype_of, get_valid_children.
    Domains extend this by registering additional types under the upper branches.
    """

    def __init__(self, hierarchy: Dict[str, str] | None = None) -> None:
        self._hierarchy: Dict[str, str] = dict(UPPER_HIERARCHY)
        if hierarchy:
            self._hierarchy.update(hierarchy)
        self._children_cache: Dict[str, List[str]] | None = None

    @property
    def hierarchy(self) -> Dict[str, str]:
        return self._hierarchy

    def extend(self, additional: Dict[str, str]) -> None:
        """Add types to the hierarchy (domain registration)."""
        self._hierarchy.update(additional)
        self._children_cache = None  # invalidate

    def get_ancestors(self, entity_type: str) -> List[str]:
        """Return the full ancestor chain for a type (bottom-up, excluding self)."""
        ancestors = []
        current = entity_type
        seen: Set[str] = set()
        while current and current in self._hierarchy:
            parent = self._hierarchy[current]
            if not parent or parent in seen:
                break
            ancestors.append(parent)
            seen.add(parent)
            current = parent
        return ancestors

    def is_subtype_of(self, child: str, parent: str) -> bool:
        """Check if child type is equal to or a subtype of parent (OWL subsumption)."""
        if child == parent:
            return True
        return parent in self.get_ancestors(child)

    def get_valid_children(self, parent: str) -> List[str]:
        """Get all direct children of a type."""
        if self._children_cache is None:
            self._children_cache = {}
            for child, par in self._hierarchy.items():
                if par:
                    self._children_cache.setdefault(par, []).append(child)
        return self._children_cache.get(parent, [])

    def get_all_descendants(self, parent: str) -> Set[str]:
        """Get all descendants (transitive children) of a type."""
        descendants: Set[str] = set()
        stack = self.get_valid_children(parent)
        while stack:
            child = stack.pop()
            if child not in descendants:
                descendants.add(child)
                stack.extend(self.get_valid_children(child))
        return descendants

    def get_branch(self, entity_type: str) -> str:
        """Get the top-level branch for an entity type (child of Thing)."""
        ancestors = self.get_ancestors(entity_type)
        if not ancestors:
            return entity_type  # It's Thing or unknown
        # The last ancestor before Thing is the branch
        for i, anc in enumerate(ancestors):
            if anc == "Thing":
                return ancestors[i - 1] if i > 0 else entity_type
        return ancestors[-1] if ancestors else entity_type

    def is_valid_type(self, entity_type: str) -> bool:
        """Check if a type exists in the hierarchy."""
        return entity_type in self._hierarchy

    def get_leaf_types(self) -> Set[str]:
        """Get all leaf types (types with no children)."""
        parents = set(self._hierarchy.values())
        return {t for t in self._hierarchy if t not in parents and t != "Thing"}

    def normalize_type(self, raw_type: str) -> str:
        """Normalize and validate an entity type."""
        if not raw_type:
            return "UNKNOWN"
        normalized = raw_type.upper().strip().replace(" ", "_")
        if normalized in self._hierarchy:
            return normalized
        # Try partial match against valid types
        for valid in self._hierarchy:
            if normalized in valid or valid in normalized:
                return valid
        return "UNKNOWN"
