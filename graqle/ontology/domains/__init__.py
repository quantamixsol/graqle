"""Domain ontology packages — auto-discovery and registration.

Each domain module provides:
    - OWL class hierarchy
    - SHACL entity/relationship shapes
    - Skill map (entity types → skills)
    - Full Skill objects with handler_prompts
    - register_<domain>_domain(registry) function

Auto-discovery: ``register_all_domains(registry)`` finds and registers
all built-in domain packages. External domains can be added via
``register_domain_module(registry, module)``.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, importlib, logging, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any, Dict, List

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry

logger = logging.getLogger("graqle.ontology.domains")

# Built-in domain modules and their registration function names
_BUILTIN_DOMAINS: dict[str, str] = {
    "graqle.ontology.domains.governance": "register_governance_domain",
    "graqle.ontology.domains.engineering": "register_engineering_domain",
    "graqle.ontology.domains.marketing": "register_marketing_domain",
    "graqle.ontology.domains.financial": "register_financial_domain",
    "graqle.ontology.domains.legal": "register_legal_domain",
    "graqle.ontology.domains.data_analytics": "register_data_analytics_domain",
    # v0.38.0: governed code generation domain
    "graqle.ontology.domains.coding": "register_coding_domain",
    # MCP protocol domain (R3 research)
    "graqle.ontology.domains.mcp": "register_mcp_domain",
}


def register_all_domains(
    registry: DomainRegistry,
    *,
    only: list[str] | None = None,
) -> dict[str, bool]:
    """Auto-discover and register all built-in domain packages.

    Parameters
    ----------
    registry:
        The DomainRegistry to register domains into.
    only:
        If provided, only register these domain names (e.g., ["governance", "engineering"]).
        If None, register all available domains.

    Returns
    -------
    Dict mapping domain module name to success (True/False).
    """
    results: dict[str, bool] = {}

    for module_path, func_name in _BUILTIN_DOMAINS.items():
        # Extract short domain name from module path
        domain_name = module_path.rsplit(".", 1)[-1]

        # Filter if 'only' is specified
        if only and domain_name not in only:
            continue

        try:
            mod = importlib.import_module(module_path)
            register_fn = getattr(mod, func_name)
            register_fn(registry)
            results[domain_name] = True
            logger.info("Registered domain: %s", domain_name)
        except Exception as exc:
            results[domain_name] = False
            logger.warning("Failed to register domain %s: %s", domain_name, exc)

    return results


def collect_all_skills(
    *,
    only: list[str] | None = None,
) -> dict[str, Skill]:
    """Collect all Skill objects from all domain packages.

    Useful for registering skills into SkillPipeline without a DomainRegistry.
    """
    all_skills: dict[str, Skill] = {}

    skill_dict_names = {
        "graqle.ontology.domains.governance": "GOVERNANCE_SKILLS",
        "graqle.ontology.domains.engineering": "ENGINEERING_SKILLS",
        "graqle.ontology.domains.marketing": "MARKETING_SKILLS",
        "graqle.ontology.domains.financial": "FINANCIAL_SKILLS",
        "graqle.ontology.domains.legal": "LEGAL_SKILLS",
        "graqle.ontology.domains.data_analytics": "DATA_ANALYTICS_SKILLS",
        # v0.38.0
        "graqle.ontology.domains.coding": "CODING_SKILLS",
        # MCP protocol domain
        "graqle.ontology.domains.mcp": "MCP_SKILLS",
    }

    for module_path, dict_name in skill_dict_names.items():
        domain_name = module_path.rsplit(".", 1)[-1]
        if only and domain_name not in only:
            continue

        try:
            mod = importlib.import_module(module_path)
            skills = getattr(mod, dict_name, {})
            all_skills.update(skills)
        except Exception:
            pass

    return all_skills
