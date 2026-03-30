"""
tests/test_ontology/test_domain_overlap.py
Phase 1B (ADR-128) — Domain overlap enforcement tests.
Guards against the non-deterministic domain resolution risk
identified by graq_predict (pse-pred-12f8041de710, 91% confidence).
"""
from __future__ import annotations

import pytest

from graqle.ontology.domain_registry import DomainRegistry


class TestDomainOverlapEnforcement:
    def test_no_domain_type_overlap_across_all_builtin_domains(self) -> None:
        """Register ALL built-in domains and assert pairwise disjoint valid_entity_types."""
        from graqle.ontology.domains import register_all_domains

        registry = DomainRegistry()
        results = register_all_domains(registry)

        # Collect all valid_entity_types per domain
        domain_types: dict[str, set[str]] = {}
        for domain_name in registry.registered_domains:
            domain = registry.get_domain(domain_name)
            assert domain is not None
            domain_types[domain_name] = domain.valid_entity_types

        # Check pairwise disjointness
        domain_names = list(domain_types.keys())
        for i in range(len(domain_names)):
            for j in range(i + 1, len(domain_names)):
                name_a = domain_names[i]
                name_b = domain_names[j]
                overlap = domain_types[name_a] & domain_types[name_b]
                assert not overlap, (
                    f"Domains '{name_a}' and '{name_b}' share types: {overlap}. "
                    "This causes non-deterministic find_domain_for_type. "
                    "See ADR-128 risk pse-pred-12f8041de710."
                )

    def test_overlap_raises_on_registration(self) -> None:
        """Registering a domain with overlapping types must raise ValueError."""
        registry = DomainRegistry()

        # Register first domain
        registry.register_domain(
            name="domain_a",
            class_hierarchy={"TypeX": "Thing", "TypeY": "Thing"},
            entity_shapes={"TypeX": {"required": ["name"]}, "TypeY": {"required": ["name"]}},
            relationship_shapes={},
        )

        # Attempt to register overlapping domain — must raise
        with pytest.raises(ValueError, match="overlaps with 'domain_a'"):
            registry.register_domain(
                name="domain_b",
                class_hierarchy={"TypeX": "Thing", "TypeZ": "Thing"},
                entity_shapes={"TypeX": {"required": ["name"]}, "TypeZ": {"required": ["name"]}},
                relationship_shapes={},
            )

    def test_non_overlapping_domains_register_fine(self) -> None:
        """Disjoint domains must register without error."""
        registry = DomainRegistry()

        registry.register_domain(
            name="domain_a",
            class_hierarchy={"TypeA": "Thing"},
            entity_shapes={"TypeA": {"required": ["name"]}},
            relationship_shapes={},
        )
        registry.register_domain(
            name="domain_b",
            class_hierarchy={"TypeB": "Thing"},
            entity_shapes={"TypeB": {"required": ["name"]}},
            relationship_shapes={},
        )

        assert "domain_a" in registry.registered_domains
        assert "domain_b" in registry.registered_domains
