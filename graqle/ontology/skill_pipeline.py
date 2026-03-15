"""Unified Skill Pipeline — single entry point for skill assignment.

Merges SkillResolver (fast, type-based) and SkillAdmin (semantic, query-aware)
into one pipeline with configurable modes:

    auto       — Type-first via registry, semantic fallback for untyped nodes (DEFAULT)
    type_only  — Registry lookup only, zero API calls, sub-ms (<0.001ms per node)
    semantic   — Always use SkillAdmin semantic matching (Titan V2 / sentence-transformers)
    hybrid     — Always use SkillAdmin fused scoring (regex + semantic + type boost)

For typed nodes (90%+ in most graphs), the "auto" mode resolves skills in <0.001ms
with zero API calls. Only genuinely untyped/dynamic nodes fall back to semantic matching.

Usage:
    from graqle.ontology.skill_pipeline import SkillPipeline

    pipeline = SkillPipeline(mode="auto")
    pipeline.register_domain_skills(governance_skills)  # from domain packages
    skills_text = pipeline.assign_to_node(node, query)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.skill_pipeline
# risk: LOW (impact radius: 1 modules)
# consumers: sdk_self_audit
# dependencies: __future__, logging, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from graqle.ontology.skill_resolver import DEFAULT_SKILLS, Skill, SkillResolver

if TYPE_CHECKING:
    from graqle.config.settings import SkillConfig
    from graqle.ontology.domain_registry import DomainRegistry

logger = logging.getLogger("graqle.ontology.skill_pipeline")


class SkillPipeline:
    """Unified skill assignment pipeline.

    Replaces the SkillAdmin-vs-SkillResolver confusion with one entry point.

    Parameters
    ----------
    mode:
        "auto" (default) — type-first, semantic fallback
        "type_only" — registry-only, zero API calls
        "semantic" — always semantic matching
        "hybrid" — always fused scoring (regex + semantic + type)
    max_per_node:
        Maximum skills assigned per node (default 5).
    use_titan:
        Prefer Titan V2 for semantic embeddings (default True).
    registry:
        Optional DomainRegistry for type-based resolution.
    """

    def __init__(
        self,
        *,
        mode: str = "auto",
        max_per_node: int = 5,
        use_titan: bool = True,
        registry: DomainRegistry | None = None,
    ) -> None:
        self.mode = mode
        self.max_per_node = max_per_node
        self._use_titan = use_titan

        # Fast path: type-based resolver
        self._resolver = SkillResolver(registry=registry)
        self._registry = registry

        # Slow path: semantic admin (lazy-initialized)
        self._admin: Any = None
        self._admin_initialized = False

        # Domain skill libraries (registered from domain packages)
        self._domain_skills: dict[str, Skill] = {}

    @classmethod
    def from_config(
        cls,
        config: SkillConfig,
        registry: DomainRegistry | None = None,
    ) -> SkillPipeline:
        """Create pipeline from SkillConfig."""
        return cls(
            mode=config.mode,
            max_per_node=config.max_per_node,
            use_titan=config.use_titan,
            registry=registry,
        )

    def set_registry(self, registry: DomainRegistry) -> None:
        """Set or update the domain registry."""
        self._registry = registry
        self._resolver.set_registry(registry)

    def register_domain_skills(self, skills: dict[str, Skill]) -> None:
        """Register skills from a domain package (e.g., marketing, financial).

        These are added to both the resolver library and the admin library
        so they're available in all modes.
        """
        self._domain_skills.update(skills)
        self._resolver.register_skills(skills)
        # Invalidate admin so it picks up new skills on next use
        if self._admin is not None:
            for name, skill in skills.items():
                self._admin.register_skill(skill)

    def _ensure_admin(self) -> Any:
        """Lazy-initialize SkillAdmin only when semantic path is needed."""
        if self._admin_initialized:
            return self._admin

        self._admin_initialized = True
        try:
            from graqle.ontology.skill_admin import SkillAdmin
            self._admin = SkillAdmin(
                max_skills_per_node=self.max_per_node,
                use_titan=self._use_titan,
                custom_skills=self._domain_skills or None,
            )
            logger.info(
                "SkillPipeline: semantic admin initialized (%s), %d skills",
                self._admin.mode, self._admin.skill_count,
            )
        except Exception as exc:
            logger.warning("SkillPipeline: failed to init SkillAdmin: %s", exc)
            self._admin = None
        return self._admin

    def resolve(
        self,
        node: Any,
        query: str = "",
    ) -> list[Skill]:
        """Resolve skills for a node using the configured mode.

        This is the single entry point that replaces both SkillResolver.resolve()
        and SkillAdmin.assign().

        Returns
        -------
        List of Skill objects, ordered by relevance, capped at max_per_node.
        """
        entity_type = getattr(node, "entity_type", "")

        # ── type_only mode: registry-only, sub-ms ────────────────────────
        if self.mode == "type_only":
            return self._resolve_by_type(entity_type)

        # ── semantic mode: always use SkillAdmin ─────────────────────────
        if self.mode == "semantic":
            return self._resolve_by_semantic(node, query)

        # ── hybrid mode: always use fused scoring ────────────────────────
        if self.mode == "hybrid":
            return self._resolve_by_semantic(node, query)

        # ── auto mode (default): type-first, semantic fallback ───────────
        type_skills = self._resolve_by_type(entity_type)

        # If registry returned domain-specific skills (not just defaults),
        # the node is typed and we're done — no API calls needed.
        has_domain_skills = any(
            s.name not in DEFAULT_SKILLS for s in type_skills
        )
        if has_domain_skills:
            logger.debug(
                "SkillPipeline(auto): %s resolved by type (%d skills, sub-ms)",
                entity_type, len(type_skills),
            )
            return type_skills

        # Untyped node — fall back to semantic matching
        semantic_skills = self._resolve_by_semantic(node, query)
        if semantic_skills:
            return semantic_skills

        # Last resort: just defaults
        return type_skills

    def _resolve_by_type(self, entity_type: str) -> list[Skill]:
        """Fast path: resolve via OWL hierarchy + registry."""
        skills = self._resolver.resolve(entity_type)
        return skills[:self.max_per_node]

    def _resolve_by_semantic(self, node: Any, query: str) -> list[Skill]:
        """Slow path: resolve via SkillAdmin semantic matching."""
        admin = self._ensure_admin()
        if admin is None:
            return self._resolve_by_type(getattr(node, "entity_type", ""))

        chunks = getattr(node, "properties", {}).get("chunks", [])
        skills = admin.assign(
            entity_type=getattr(node, "entity_type", ""),
            description=getattr(node, "description", ""),
            query=query,
            chunks=chunks,
        )

        # Ensure defaults are always present
        seen = {s.name for s in skills}
        for name, skill in DEFAULT_SKILLS.items():
            if name not in seen and len(skills) < self.max_per_node:
                skills.append(skill)

        return skills[:self.max_per_node]

    def assign_to_node(self, node: Any, query: str) -> str:
        """Assign skills to a node and return formatted skills_text.

        Uses skill condensation: top 2 get full handler_prompt,
        skills 3-5 get summary only (saves ~60% tokens).
        """
        skills = self.resolve(node, query)

        if not skills:
            return ""

        lines = ["YOUR SKILLS (use these capabilities in your analysis):"]
        for i, skill in enumerate(skills):
            if i < 2:
                lines.append(f"- **{skill.name}**: {skill.description}")
                lines.append(f"  HOW: {skill.handler_prompt}")
            else:
                lines.append(f"- {skill.name}: {skill.description}")

        return "\n".join(lines)

    @property
    def stats(self) -> dict[str, Any]:
        """Return pipeline stats for diagnostics."""
        return {
            "mode": self.mode,
            "max_per_node": self.max_per_node,
            "domain_skills_registered": len(self._domain_skills),
            "resolver_skills": len(self._resolver._skill_library),
            "admin_initialized": self._admin_initialized,
            "admin_mode": self._admin.mode if self._admin else None,
            "admin_skill_count": self._admin.skill_count if self._admin else 0,
        }
