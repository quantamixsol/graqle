"""Tests for SkillResolver — skill inheritance and resolution."""

# ── graqle:intelligence ──
# module: tests.test_ontology.test_skill_resolver
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, skill_resolver, domain_registry, governance
# constraints: none
# ── /graqle:intelligence ──


from graqle.ontology.domain_registry import DomainRegistry
from graqle.ontology.domains.governance import (
    register_governance_domain,
)
from graqle.ontology.skill_resolver import DEFAULT_SKILLS, Skill, SkillResolver


class TestSkillResolver:
    def test_default_skills_without_registry(self):
        resolver = SkillResolver()
        skills = resolver.resolve("ANY_TYPE")
        assert len(skills) == len(DEFAULT_SKILLS)
        skill_names = [s.name for s in skills]
        assert "cite_evidence" in skill_names
        assert "state_confidence" in skill_names

    def test_governance_skills_inherited(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        resolver = SkillResolver(registry=registry)

        skills = resolver.resolve("GOV_ENFORCEMENT")
        skill_names = [s.name for s in skills]

        # Own skills
        assert "penalty_lookup" in skill_names
        assert "enforcement_timeline" in skill_names
        assert "authority_identification" in skill_names

        # Inherited from Governance branch
        assert "check_compliance" in skill_names
        assert "identify_gaps" in skill_names

        # Default skills always included
        assert "cite_evidence" in skill_names

    def test_requirement_skills(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        resolver = SkillResolver(registry=registry)

        skills = resolver.resolve("GOV_REQUIREMENT")
        skill_names = [s.name for s in skills]
        assert "obligation_analysis" in skill_names
        assert "deadline_check" in skill_names
        assert "cross_framework_mapping" in skill_names

    def test_skills_to_prompt(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        resolver = SkillResolver(registry=registry)

        prompt = resolver.skills_to_prompt("GOV_ENFORCEMENT")
        assert "YOUR SKILLS:" in prompt
        assert "penalty_lookup" in prompt

    def test_register_custom_skill(self):
        resolver = SkillResolver()
        custom = Skill(
            name="custom_skill",
            description="A custom skill",
            handler_prompt="Use custom logic.",
        )
        resolver.register_skill(custom)
        assert "custom_skill" in resolver._skill_library

    def test_unknown_skill_creates_basic(self):
        registry = DomainRegistry()
        registry.register_domain(
            name="test",
            class_hierarchy={"TEST_TYPE": "Thing"},
            entity_shapes={},
            relationship_shapes={},
            skill_map={"TEST_TYPE": ["unknown_skill_name"]},
        )
        resolver = SkillResolver(registry=registry)
        skills = resolver.resolve("TEST_TYPE")
        skill_names = [s.name for s in skills]
        assert "unknown_skill_name" in skill_names

    def test_no_duplicate_skills(self):
        registry = DomainRegistry()
        register_governance_domain(registry)
        resolver = SkillResolver(registry=registry)

        skills = resolver.resolve("GOV_ENFORCEMENT")
        skill_names = [s.name for s in skills]
        # No duplicates
        assert len(skill_names) == len(set(skill_names))

    def test_skill_prompt_text(self):
        skill = Skill(name="test", description="Test skill", handler_prompt="Do test.")
        text = skill.to_prompt_text()
        assert "test: Test skill" in text
