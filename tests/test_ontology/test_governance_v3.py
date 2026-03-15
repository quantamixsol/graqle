"""Tests for Governance Domain v3 — semantic constraints."""

# ── graqle:intelligence ──
# module: tests.test_ontology.test_governance_v3
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, governance_v3, semantic_shacl_gate
# constraints: none
# ── /graqle:intelligence ──

import pytest

from graqle.ontology.domains.governance_v3 import (
    GOVERNANCE_CLASS_HIERARCHY,
    build_governance_semantic_constraints,
    GOVERNANCE_SKILL_MAP,
    register_governance_domain_v3,
)
from graqle.ontology.semantic_shacl_gate import SemanticConstraint, SemanticSHACLGate


class TestGovernanceClassHierarchy:
    def test_all_types_present(self):
        expected = [
            "GOV_FRAMEWORK", "GOV_REQUIREMENT", "GOV_ENFORCEMENT",
            "GOV_RISK_CATEGORY", "GOV_CONTROL", "GOV_ACTOR", "GOV_PROCESS",
        ]
        for etype in expected:
            assert etype in GOVERNANCE_CLASS_HIERARCHY

    def test_all_types_under_governance(self):
        for etype, parent in GOVERNANCE_CLASS_HIERARCHY.items():
            assert parent == "Governance"


class TestBuildGovernanceConstraints:
    def test_returns_semantic_constraints(self):
        constraints = build_governance_semantic_constraints()
        assert isinstance(constraints, dict)
        assert len(constraints) >= 7

    def test_each_constraint_is_semantic(self):
        constraints = build_governance_semantic_constraints()
        for etype, c in constraints.items():
            assert isinstance(c, SemanticConstraint)
            assert c.entity_type == etype

    def test_framework_constraint(self):
        constraints = build_governance_semantic_constraints()
        fw = constraints.get("GOV_FRAMEWORK")
        assert fw is not None
        assert len(fw.reasoning_rules) >= 1
        assert fw.scope_description != ""

    def test_requirement_constraint(self):
        constraints = build_governance_semantic_constraints()
        req = constraints.get("GOV_REQUIREMENT")
        assert req is not None
        assert len(req.reasoning_rules) >= 1

    def test_enforcement_constraint(self):
        constraints = build_governance_semantic_constraints()
        enf = constraints.get("GOV_ENFORCEMENT")
        assert enf is not None
        assert len(enf.reasoning_rules) >= 1

    def test_constraints_have_scope_boundary(self):
        constraints = build_governance_semantic_constraints()
        for c in constraints.values():
            assert c.scope_description != ""

    def test_custom_framework_info(self):
        framework_info = {
            "EU AI Act": {
                "markers": ["EU AI Act", "Regulation 2024/1689"],
                "cross_refs": {"GDPR": "Related regulation"},
            }
        }
        constraints = build_governance_semantic_constraints(framework_info)
        assert len(constraints) >= 7

    def test_constraints_usable_by_gate(self):
        constraints = build_governance_semantic_constraints()
        gate = SemanticSHACLGate(constraints=constraints)
        result = gate.validate(
            "GOV_FRAMEWORK",
            "The EU AI Act establishes rules for artificial intelligence.",
        )
        assert isinstance(result.governance_accuracy, float)


class TestGovernanceSkillMap:
    def test_skill_map_has_entries(self):
        assert len(GOVERNANCE_SKILL_MAP) >= 3

    def test_skill_map_values_are_lists(self):
        for skill_name, skills in GOVERNANCE_SKILL_MAP.items():
            assert isinstance(skills, list)


class TestRegisterGovernanceDomainV3:
    def test_returns_constraints(self):
        from graqle.ontology.domain_registry import DomainRegistry
        registry = DomainRegistry()
        result = register_governance_domain_v3(registry)
        assert isinstance(result, dict)
        for etype, c in result.items():
            assert isinstance(c, SemanticConstraint)
