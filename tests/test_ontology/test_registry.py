"""Tests for DomainRegistry — domain registration and lookup."""

import pytest

from graqle.ontology.domain_registry import DomainRegistry, DomainOntology


class TestDomainRegistry:
    def setup_method(self):
        self.registry = DomainRegistry()

    def test_empty_registry(self):
        assert self.registry.registered_domains == []
        assert self.registry.get_domain("governance") is None

    def test_register_domain(self):
        domain = self.registry.register_domain(
            name="governance",
            class_hierarchy={"REGULATION": "Governance", "GOV_ENFORCEMENT": "Governance"},
            entity_shapes={"REGULATION": {"required": ["name", "type"]}},
            relationship_shapes={"COMPLIES_WITH": {"domain": ["ORGANIZATION"], "range": ["REGULATION"]}},
            skill_map={"Governance": ["check_compliance"], "GOV_ENFORCEMENT": ["penalty_lookup"]},
        )
        assert domain.name == "governance"
        assert "governance" in self.registry.registered_domains

    def test_get_domain(self):
        self.registry.register_domain(
            name="governance",
            class_hierarchy={"REGULATION": "Governance"},
            entity_shapes={},
            relationship_shapes={},
        )
        domain = self.registry.get_domain("governance")
        assert domain is not None
        assert domain.name == "governance"

    def test_upper_ontology_extended(self):
        self.registry.register_domain(
            name="governance",
            class_hierarchy={"REGULATION": "Governance"},
            entity_shapes={},
            relationship_shapes={},
        )
        upper = self.registry.upper_ontology
        assert upper.is_subtype_of("REGULATION", "Governance")
        assert upper.is_subtype_of("REGULATION", "Thing")

    def test_get_skills_with_inheritance(self):
        self.registry.register_domain(
            name="governance",
            class_hierarchy={"GOV_ENFORCEMENT": "Governance"},
            entity_shapes={},
            relationship_shapes={},
            skill_map={
                "Governance": ["check_compliance", "identify_gaps"],
                "GOV_ENFORCEMENT": ["penalty_lookup", "enforcement_timeline"],
            },
        )
        skills = self.registry.get_skills_for_type("GOV_ENFORCEMENT")
        # Should get own skills + Governance inherited skills
        assert "penalty_lookup" in skills
        assert "enforcement_timeline" in skills
        assert "check_compliance" in skills
        assert "identify_gaps" in skills

    def test_find_domain_for_type(self):
        self.registry.register_domain(
            name="governance",
            class_hierarchy={"REGULATION": "Governance"},
            entity_shapes={},
            relationship_shapes={},
        )
        domain = self.registry.find_domain_for_type("REGULATION")
        assert domain is not None
        assert domain.name == "governance"

    def test_find_domain_for_unknown_type(self):
        domain = self.registry.find_domain_for_type("FAKE_TYPE")
        assert domain is None

    def test_get_all_relationship_shapes(self):
        self.registry.register_domain(
            name="gov",
            class_hierarchy={"REGULATION": "Governance"},
            entity_shapes={},
            relationship_shapes={"COMPLIES_WITH": {"domain": ["ORG"], "range": ["REG"]}},
        )
        shapes = self.registry.get_all_relationship_shapes()
        assert "COMPLIES_WITH" in shapes

    def test_multiple_domains(self):
        self.registry.register_domain(
            name="governance",
            class_hierarchy={"REGULATION": "Governance"},
            entity_shapes={},
            relationship_shapes={},
        )
        self.registry.register_domain(
            name="medical",
            class_hierarchy={"DIAGNOSIS": "Cognitive"},
            entity_shapes={},
            relationship_shapes={},
        )
        assert len(self.registry.registered_domains) == 2
        assert self.registry.find_domain_for_type("REGULATION").name == "governance"
        assert self.registry.find_domain_for_type("DIAGNOSIS").name == "medical"


class TestDomainOntology:
    def test_get_entity_shape_default(self):
        domain = DomainOntology(
            name="test",
            class_hierarchy={},
            entity_shapes={"_default": {"required": ["name"]}},
            relationship_shapes={},
        )
        shape = domain.get_entity_shape("UNKNOWN_TYPE")
        assert shape == {"required": ["name"]}

    def test_get_entity_shape_specific(self):
        domain = DomainOntology(
            name="test",
            class_hierarchy={},
            entity_shapes={
                "_default": {"required": ["name"]},
                "REGULATION": {"required": ["name", "type", "article"]},
            },
            relationship_shapes={},
        )
        shape = domain.get_entity_shape("REGULATION")
        assert "article" in shape["required"]

    def test_get_valid_targets(self):
        domain = DomainOntology(
            name="test",
            class_hierarchy={},
            entity_shapes={},
            relationship_shapes={
                "COMPLIES_WITH": {
                    "domain": ["ORGANIZATION"],
                    "range": ["REGULATION", "STANDARD"],
                },
            },
        )
        targets = domain.get_valid_targets("ORGANIZATION", "COMPLIES_WITH")
        assert "REGULATION" in targets
        assert "STANDARD" in targets

    def test_get_valid_targets_wrong_source(self):
        domain = DomainOntology(
            name="test",
            class_hierarchy={},
            entity_shapes={},
            relationship_shapes={
                "COMPLIES_WITH": {
                    "domain": ["ORGANIZATION"],
                    "range": ["REGULATION"],
                },
            },
        )
        targets = domain.get_valid_targets("PERSON", "COMPLIES_WITH")
        assert targets == []
