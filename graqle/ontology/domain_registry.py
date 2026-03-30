"""Domain Registry — register and load domain ontologies at runtime.

Any domain (governance, medical, coding, financial) registers via the same API.
Each domain provides: class hierarchy, entity shapes, relationship shapes,
skill map, and output shapes for the SHACL gate.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domain_registry
# risk: MEDIUM (impact radius: 7 modules)
# consumers: sdk_self_audit, __init__, governance, governance_v3, test_registry +2 more
# dependencies: __future__, logging, dataclasses, typing, upper
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from graqle.ontology.upper import UpperOntology

logger = logging.getLogger("graqle.ontology.registry")


@dataclass
class DomainOntology:
    """A registered domain's full ontology specification."""

    name: str
    class_hierarchy: dict[str, str]
    entity_shapes: dict[str, dict[str, Any]]
    relationship_shapes: dict[str, dict[str, Any]]
    skill_map: dict[str, list[str]] = field(default_factory=dict)
    output_shapes: dict[str, dict[str, Any]] = field(default_factory=dict)
    valid_entity_types: set[str] = field(default_factory=set)
    causal_tiers: dict[str, Any] = field(default_factory=dict)

    def get_entity_shape(self, entity_type: str) -> dict[str, Any]:
        """Get the SHACL shape for an entity type, with fallback to _default."""
        return self.entity_shapes.get(
            entity_type, self.entity_shapes.get("_default", {})
        )

    def get_output_shape(self, entity_type: str) -> dict[str, Any]:
        """Get the output validation shape for a node's entity type."""
        return self.output_shapes.get(entity_type, {})

    def get_valid_targets(self, source_type: str, relationship: str) -> list[str]:
        """Get valid target types for a relationship from a source type."""
        shape = self.relationship_shapes.get(relationship)
        if not shape:
            return []  # unknown relationship — no constraint
        domain = shape.get("domain")
        if domain is not None and source_type not in domain:
            return []  # source type not in domain
        range_types = shape.get("range")
        return list(range_types) if range_types else []


class DomainRegistry:
    """Registry for domain ontologies. Domain-agnostic by design.

    Usage:
        registry = DomainRegistry()
        registry.register_domain("governance", hierarchy, shapes, rels, skills)
        gov = registry.get_domain("governance")
    """

    def __init__(self) -> None:
        self._domains: dict[str, DomainOntology] = {}
        self._upper = UpperOntology()

    @property
    def upper_ontology(self) -> UpperOntology:
        return self._upper

    @property
    def registered_domains(self) -> list[str]:
        return list(self._domains.keys())

    def register_domain(
        self,
        name: str,
        class_hierarchy: dict[str, str],
        entity_shapes: dict[str, dict[str, Any]],
        relationship_shapes: dict[str, dict[str, Any]],
        skill_map: dict[str, list[str]] | None = None,
        output_shapes: dict[str, dict[str, Any]] | None = None,
        causal_tiers: dict[str, Any] | None = None,
    ) -> DomainOntology:
        """Register a domain ontology.

        The class hierarchy extends the upper ontology. Entity and relationship
        shapes define SHACL constraints. Skills map entity types to capabilities.
        """
        # Validate that hierarchy types extend existing upper ontology branches
        for child, parent in class_hierarchy.items():
            if parent and parent not in self._upper.hierarchy and parent not in class_hierarchy:
                logger.warning(
                    f"Domain '{name}': type '{child}' has parent '{parent}' "
                    f"not in upper ontology or domain hierarchy"
                )

        # ADR-128 Phase 1B: Reject overlapping entity types across domains.
        # Non-deterministic find_domain_for_type resolution is a P0 risk
        # (graq_predict pse-pred-12f8041de710, 91% confidence).
        new_types = {t for t in class_hierarchy if t not in ("Thing", "")}
        for existing_name, existing_domain in self._domains.items():
            overlap = new_types & existing_domain.valid_entity_types
            if overlap:
                raise ValueError(
                    f"Domain '{name}' overlaps with '{existing_name}' "
                    f"on entity types: {overlap}. "
                    f"This causes non-deterministic domain resolution in "
                    f"find_domain_for_type. See ADR-128."
                )

        # Extend upper ontology with domain types
        self._upper.extend(class_hierarchy)

        # Compute valid entity types for this domain
        valid_types: set[str] = set()
        for t in class_hierarchy:
            if t not in ("Thing", ""):
                valid_types.add(t)

        domain = DomainOntology(
            name=name,
            class_hierarchy=class_hierarchy,
            entity_shapes=entity_shapes,
            relationship_shapes=relationship_shapes,
            skill_map=skill_map or {},
            output_shapes=output_shapes or {},
            valid_entity_types=valid_types,
            causal_tiers=causal_tiers or {},
        )

        self._domains[name] = domain
        logger.info(
            f"Registered domain '{name}': {len(class_hierarchy)} types, "
            f"{len(entity_shapes)} entity shapes, "
            f"{len(relationship_shapes)} relationship shapes, "
            f"{len(skill_map or {})} skill groups"
        )
        return domain

    def get_domain(self, name: str) -> DomainOntology | None:
        """Get a registered domain ontology by name."""
        return self._domains.get(name)

    def get_all_relationship_shapes(self) -> dict[str, dict[str, Any]]:
        """Get merged relationship shapes across all registered domains."""
        merged: dict[str, dict[str, Any]] = {}
        for domain in self._domains.values():
            merged.update(domain.relationship_shapes)
        return merged

    def get_all_entity_shapes(self) -> dict[str, dict[str, Any]]:
        """Get merged entity shapes across all registered domains."""
        merged: dict[str, dict[str, Any]] = {}
        for domain in self._domains.values():
            merged.update(domain.entity_shapes)
        return merged

    def get_all_output_shapes(self) -> dict[str, dict[str, Any]]:
        """Get merged output shapes across all registered domains."""
        merged: dict[str, dict[str, Any]] = {}
        for domain in self._domains.values():
            merged.update(domain.output_shapes)
        return merged

    def find_domain_for_type(self, entity_type: str) -> DomainOntology | None:
        """Find which domain owns a given entity type."""
        for domain in self._domains.values():
            if entity_type in domain.valid_entity_types:
                return domain
        return None

    def get_skills_for_type(self, entity_type: str) -> list[str]:
        """Get all skills for an entity type, including inherited skills.

        Skills inherit up the OWL class hierarchy:
        GOV_ENFORCEMENT gets its own skills + Governance skills + Thing skills.
        """
        all_skills: list[str] = []

        # Get ancestor chain
        ancestors = [entity_type] + self._upper.get_ancestors(entity_type)

        # Collect skills from all domains, walking up the hierarchy
        for domain in self._domains.values():
            for ancestor in ancestors:
                domain_skills = domain.skill_map.get(ancestor, [])
                for s in domain_skills:
                    if s not in all_skills:
                        all_skills.append(s)

        return all_skills
