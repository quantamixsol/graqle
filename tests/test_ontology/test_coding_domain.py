"""
tests/test_ontology/test_coding_domain.py
T1.2 — Unit tests for the coding domain ontology.
5 tests.
"""
from __future__ import annotations

import pytest

from graqle.ontology.domains.coding import (
    CODING_CLASS_HIERARCHY,
    CODING_ENTITY_SHAPES,
    CODING_OUTPUT_GATES,
    CODING_SKILL_MAP,
    CODING_SKILLS,
    register_coding_domain,
)
from graqle.ontology.domain_registry import DomainRegistry


class TestCodingDomainStructure:
    def test_four_skills_defined(self) -> None:
        # v0.38.0 Phase 7: expanded from 4 → 14 skills (added PERFORMANCE_PROFILING)
        original = {"CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION"}
        assert original.issubset(set(CODING_SKILLS.keys()))
        assert len(CODING_SKILLS) == 14

    def test_skill_map_covers_scanner_types(self) -> None:
        # Scanner emits Function, Class, Module — all must have coding skills
        for entity_type in ("Function", "Class", "Module", "PythonModule", "PythonFunction"):
            assert entity_type in CODING_SKILL_MAP, f"{entity_type!r} missing from CODING_SKILL_MAP"
            assert len(CODING_SKILL_MAP[entity_type]) > 0

    def test_entity_shapes_have_required_fields(self) -> None:
        for shape_name, shape in CODING_ENTITY_SHAPES.items():
            assert "required" in shape, f"{shape_name} missing 'required'"
            assert isinstance(shape["required"], list)

    def test_output_gates_are_dicts(self) -> None:
        for gate_name, gate in CODING_OUTPUT_GATES.items():
            assert isinstance(gate, dict), f"Gate {gate_name!r} must be a dict"
            assert "description" in gate, f"Gate {gate_name!r} missing 'description'"

    def test_register_coding_domain_registers_successfully(self) -> None:
        registry = DomainRegistry()
        register_coding_domain(registry)
        assert "coding" in registry.registered_domains
        domain = registry.get_domain("coding")
        assert domain is not None
        assert "CodeModule" in domain.class_hierarchy or "CodeModule" in domain.valid_entity_types
