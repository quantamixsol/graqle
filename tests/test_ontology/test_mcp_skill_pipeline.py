"""
tests/test_ontology/test_mcp_skill_pipeline.py
Phase 4 (ADR-128) — Verify MCP skills are loadable through the pipeline.
"""
from __future__ import annotations

from graqle.ontology.domains import collect_all_skills
from graqle.ontology.domain_registry import DomainRegistry
from graqle.ontology.domains import register_all_domains
from graqle.ontology.skill_pipeline import SkillPipeline


class TestMcpSkillsInPipeline:
    def test_mcp_skills_in_collect_all_skills(self) -> None:
        """MCP skills appear in collect_all_skills() output."""
        all_skills = collect_all_skills()
        assert "PROTOCOL_TRACE" in all_skills
        assert "SCHEMA_VALIDATE" in all_skills
        assert "RPC_LINEAGE" in all_skills
        assert "TRANSPORT_CONSTRAINT_CHECK" in all_skills

    def test_mcp_domain_registered_with_all_domains(self) -> None:
        """MCP domain is included in register_all_domains()."""
        registry = DomainRegistry()
        results = register_all_domains(registry)
        assert results.get("mcp") is True
        assert "mcp" in registry.registered_domains

    def test_pipeline_resolves_mcp_skills_by_type(self) -> None:
        """SkillPipeline resolves MCP skills for MCP_TOOL entity type."""
        registry = DomainRegistry()
        register_all_domains(registry)
        skills = registry.get_skills_for_type("MCP_TOOL")
        assert "PROTOCOL_TRACE" in skills
        assert "SCHEMA_VALIDATE" in skills

    def test_pipeline_register_domain_skills_includes_mcp(self) -> None:
        """SkillPipeline.register_domain_skills() accepts MCP skills."""
        pipeline = SkillPipeline(mode="type_only")
        mcp_skills = collect_all_skills(only=["mcp"])
        pipeline.register_domain_skills(mcp_skills)
        stats = pipeline.stats
        assert stats["domain_skills_registered"] >= 4

    def test_existing_coding_skills_still_present(self) -> None:
        """MCP skills don't shadow or remove coding skills."""
        all_skills = collect_all_skills()
        assert "CODE_GENERATION" in all_skills
        assert "REFACTOR" in all_skills
        assert "CODE_REVIEW" in all_skills
