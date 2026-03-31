"""
tests/test_ontology/test_mcp_domain.py
Phase 1 (ADR-128) — Unit tests for the MCP protocol domain ontology.
Zero-regression: verifies domain structure, type mapping, hierarchy disjointness,
skill inheritance, and relationship constraints.
"""
from __future__ import annotations

import pytest

from graqle.ontology.domains.mcp import (
    MCP_CLASS_HIERARCHY,
    MCP_ENTITY_SHAPES,
    MCP_OUTPUT_GATES,
    MCP_RELATIONSHIP_SHAPES,
    MCP_SKILL_MAP,
    MCP_SKILLS,
    register_mcp_domain,
)
from graqle.ontology.domains.coding import CODING_CLASS_HIERARCHY
from graqle.ontology.domain_registry import DomainRegistry


# ---------------------------------------------------------------------------
# Expected constants
# ---------------------------------------------------------------------------

EXPECTED_MCP_TYPES = {
    "MCP_TOOL", "MCP_REQUEST", "MCP_RESPONSE", "MCP_NOTIFICATION",
    "MCP_SERVER", "MCP_CLIENT", "MCP_TRANSPORT", "MCP_SCHEMA",
}

EXPECTED_MCP_EDGES = {
    "CALLS_VIA_MCP", "EXPOSES_TOOL", "CALLS_TOOL", "HANDLES_REQUEST",
    "RETURNS_RESPONSE", "ROUTES_TO", "HAS_PARAM_SCHEMA", "ALIASES",
}

EXPECTED_MCP_SKILLS = {
    "PROTOCOL_TRACE", "SCHEMA_VALIDATE", "RPC_LINEAGE",
    "TRANSPORT_CONSTRAINT_CHECK",
}


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestMcpDomainStructure:
    def test_class_hierarchy_has_8_entity_types(self) -> None:
        # "Mcp" is the parent, not an entity type
        entity_types = {k for k in MCP_CLASS_HIERARCHY if k != "Mcp"}
        assert entity_types == EXPECTED_MCP_TYPES

    def test_entity_shapes_cover_all_types(self) -> None:
        for entity_type in EXPECTED_MCP_TYPES:
            assert entity_type in MCP_ENTITY_SHAPES, (
                f"{entity_type!r} missing from MCP_ENTITY_SHAPES"
            )

    def test_entity_shapes_have_required_fields(self) -> None:
        for shape_name, shape in MCP_ENTITY_SHAPES.items():
            assert "required" in shape, f"{shape_name} missing 'required'"
            assert isinstance(shape["required"], list)
            assert len(shape["required"]) > 0, f"{shape_name} has empty required list"

    def test_relationship_shapes_cover_7_edge_types(self) -> None:
        assert set(MCP_RELATIONSHIP_SHAPES.keys()) == EXPECTED_MCP_EDGES

    def test_relationship_shapes_have_domain_and_range(self) -> None:
        for edge_name, shape in MCP_RELATIONSHIP_SHAPES.items():
            assert "domain" in shape, f"{edge_name} missing 'domain'"
            assert "range" in shape, f"{edge_name} missing 'range'"
            assert isinstance(shape["domain"], set), f"{edge_name} domain must be a set"
            assert isinstance(shape["range"], set), f"{edge_name} range must be a set"

    def test_4_skills_defined(self) -> None:
        assert set(MCP_SKILLS.keys()) == EXPECTED_MCP_SKILLS

    def test_skills_have_handler_prompts(self) -> None:
        for skill_name, skill in MCP_SKILLS.items():
            assert skill.name == skill_name
            assert skill.description, f"{skill_name} has empty description"
            assert skill.handler_prompt, f"{skill_name} has empty handler_prompt"

    def test_skill_map_covers_all_types(self) -> None:
        for entity_type in EXPECTED_MCP_TYPES:
            assert entity_type in MCP_SKILL_MAP, (
                f"{entity_type!r} missing from MCP_SKILL_MAP"
            )
            assert len(MCP_SKILL_MAP[entity_type]) > 0

    def test_output_gates_are_well_formed(self) -> None:
        for gate_name, gate in MCP_OUTPUT_GATES.items():
            assert isinstance(gate, dict), f"Gate {gate_name!r} must be a dict"
            assert "description" in gate, f"Gate {gate_name!r} missing 'description'"
            assert "required" in gate, f"Gate {gate_name!r} missing 'required'"


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestMcpDomainRegistration:
    def test_register_mcp_domain_succeeds(self) -> None:
        registry = DomainRegistry()
        register_mcp_domain(registry)
        assert "mcp" in registry.registered_domains

    def test_find_domain_for_type_mcp_tool(self) -> None:
        """The core acceptance test — ADR-128 done-when criteria."""
        registry = DomainRegistry()
        register_mcp_domain(registry)
        domain = registry.find_domain_for_type("MCP_TOOL")
        assert domain is not None
        assert domain.name == "mcp"

    @pytest.mark.parametrize("entity_type", sorted(EXPECTED_MCP_TYPES))
    def test_find_domain_for_type_all_8(self, entity_type: str) -> None:
        registry = DomainRegistry()
        register_mcp_domain(registry)
        domain = registry.find_domain_for_type(entity_type)
        assert domain is not None, f"find_domain_for_type({entity_type!r}) returned None"
        assert domain.name == "mcp"

    def test_get_skills_for_mcp_tool(self) -> None:
        registry = DomainRegistry()
        register_mcp_domain(registry)
        skills = registry.get_skills_for_type("MCP_TOOL")
        assert "PROTOCOL_TRACE" in skills
        assert "SCHEMA_VALIDATE" in skills

    def test_mcp_valid_entity_types(self) -> None:
        registry = DomainRegistry()
        register_mcp_domain(registry)
        domain = registry.get_domain("mcp")
        assert domain is not None
        # "Mcp" parent should be in valid types (it's in hierarchy, not Thing/empty)
        assert EXPECTED_MCP_TYPES.issubset(domain.valid_entity_types)


# ---------------------------------------------------------------------------
# Disjointness tests (CRITICAL — prevents domain cascade risk)
# ---------------------------------------------------------------------------

class TestMcpCodingDisjoint:
    def test_mcp_coding_hierarchy_disjoint(self) -> None:
        """ZERO overlap between MCP and coding class hierarchies.

        This is the primary guard against the domain reclassification cascade
        identified by graq_predict (pse-pred-12f8041de710, 91% confidence).
        If this test fails, find_domain_for_type becomes non-deterministic.
        """
        mcp_types = set(MCP_CLASS_HIERARCHY.keys()) - {"Mcp"}
        coding_types = set(CODING_CLASS_HIERARCHY.keys()) - {"Coding"}
        overlap = mcp_types & coding_types
        assert not overlap, (
            f"CRITICAL: MCP and coding domains share types: {overlap}. "
            "This causes non-deterministic domain resolution in "
            "find_domain_for_type. See ADR-128 risk pse-pred-12f8041de710."
        )

    def test_both_domains_register_without_conflict(self) -> None:
        """Register both domains and verify neither shadows the other."""
        from graqle.ontology.domains.coding import register_coding_domain

        registry = DomainRegistry()
        register_coding_domain(registry)
        register_mcp_domain(registry)

        # MCP types resolve to mcp domain
        assert registry.find_domain_for_type("MCP_TOOL").name == "mcp"
        assert registry.find_domain_for_type("MCP_SCHEMA").name == "mcp"

        # Coding types still resolve to coding domain
        assert registry.find_domain_for_type("CodeModule").name == "coding"
        assert registry.find_domain_for_type("CodeFunction").name == "coding"

    def test_relationship_shapes_no_key_collision(self) -> None:
        """MCP and coding edge type names must not collide."""
        from graqle.ontology.domains.coding import CODING_RELATIONSHIP_SHAPES

        mcp_edges = set(MCP_RELATIONSHIP_SHAPES.keys())
        coding_edges = set(CODING_RELATIONSHIP_SHAPES.keys())
        overlap = mcp_edges & coding_edges
        assert not overlap, (
            f"Edge type name collision: {overlap}. "
            "get_all_relationship_shapes() uses dict.update — "
            "last domain wins, silently overwriting the other."
        )
