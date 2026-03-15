"""Skill Resolver — derives skills from OWL class hierarchy + inheritance.

Skills inherit up the tree: GOV_ENFORCEMENT gets its own skills +
Governance skills + Thing skills. Skills are injected into the
NODE_REASONING_PROMPT as available capabilities.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.skill_resolver
# risk: MEDIUM (impact radius: 12 modules)
# consumers: skill_admin, skill_pipeline, __init__, data_analytics, engineering +7 more
# dependencies: __future__, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry

logger = logging.getLogger("graqle.ontology.skill_resolver")


@dataclass
class Skill:
    """A skill that a node agent can use during reasoning."""

    name: str
    description: str
    handler_prompt: str  # injected into NODE_REASONING_PROMPT

    def to_prompt_text(self) -> str:
        return f"- {self.name}: {self.description}"


# Default skill library — available to all entity types
DEFAULT_SKILLS: Dict[str, Skill] = {
    "cite_evidence": Skill(
        name="cite_evidence",
        description="Cite specific evidence chunks by number [1], [2]",
        handler_prompt="Always cite evidence by chunk number when making claims.",
    ),
    "state_confidence": Skill(
        name="state_confidence",
        description="Assess and state confidence level (0-100%)",
        handler_prompt="End your response with 'Confidence: X%' based on evidence strength.",
    ),
    "flag_contradiction": Skill(
        name="flag_contradiction",
        description="Detect and flag contradictions with neighbor analyses",
        handler_prompt="If you detect contradictions with neighbor messages, explicitly state them.",
    ),
}


class SkillResolver:
    """Resolves skills for nodes based on entity type and OWL inheritance.

    Skills cascade down the class hierarchy:
    Thing skills → Branch skills → Type skills → Entity-specific skills
    """

    def __init__(self, registry: Optional[DomainRegistry] = None) -> None:
        self._registry = registry
        self._skill_library: Dict[str, Skill] = dict(DEFAULT_SKILLS)

    def set_registry(self, registry: DomainRegistry) -> None:
        self._registry = registry

    def register_skill(self, skill: Skill) -> None:
        """Register a skill in the library."""
        self._skill_library[skill.name] = skill

    def register_skills(self, skills: Dict[str, Skill]) -> None:
        """Register multiple skills."""
        self._skill_library.update(skills)

    def resolve(self, entity_type: str) -> List[Skill]:
        """Resolve all skills for an entity type, including inherited.

        Returns skills in order: entity-specific → branch → Thing (most specific first).
        """
        if self._registry is None:
            return list(DEFAULT_SKILLS.values())

        # Get skill names from registry (includes inheritance)
        skill_names = self._registry.get_skills_for_type(entity_type)

        # Resolve to Skill objects
        resolved: List[Skill] = []
        seen: set = set()
        for name in skill_names:
            if name not in seen:
                skill = self._skill_library.get(name)
                if skill:
                    resolved.append(skill)
                else:
                    # Create a basic skill from the name
                    resolved.append(Skill(
                        name=name,
                        description=name.replace("_", " ").title(),
                        handler_prompt=f"Use your {name.replace('_', ' ')} capability.",
                    ))
                seen.add(name)

        # Always include default skills
        for name, skill in DEFAULT_SKILLS.items():
            if name not in seen:
                resolved.append(skill)
                seen.add(name)

        return resolved

    def skills_to_prompt(self, entity_type: str) -> str:
        """Get skills formatted for injection into node prompt."""
        skills = self.resolve(entity_type)
        if not skills:
            return ""
        lines = ["YOUR SKILLS:"]
        for s in skills:
            lines.append(s.to_prompt_text())
        return "\n".join(lines)
