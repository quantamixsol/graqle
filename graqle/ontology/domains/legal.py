"""Legal domain — skills for contract review, IP, compliance, terms analysis.

15 skills organized by legal function:
- Contract Review (4)
- Intellectual Property (3)
- Compliance (4)
- Terms & Licensing (4)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.legal
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


LEGAL_CLASS_HIERARCHY: Dict[str, str] = {
    "Legal": "Thing",
    "CONTRACT": "Legal",
    "CLAUSE": "CONTRACT",
    "NDA": "CONTRACT",
    "SLA": "CONTRACT",
    "LICENSE": "Legal",
    "PATENT": "Legal",
    "TRADEMARK": "Legal",
    "COPYRIGHT": "Legal",
    "TERMS_OF_SERVICE": "Legal",
    "PRIVACY_POLICY": "Legal",
    "LEGAL_ENTITY": "Legal",
    "JURISDICTION": "Legal",
}

LEGAL_ENTITY_SHAPES: Dict[str, dict] = {
    "CONTRACT": {"required": ["parties", "effective_date"], "optional": ["expiry_date", "value", "governing_law", "status"]},
    "PATENT": {"required": ["title", "application_number"], "optional": ["filing_date", "status", "claims_count", "jurisdiction"]},
    "LICENSE": {"required": ["name", "type"], "optional": ["permissions", "restrictions", "compatibility"]},
}

LEGAL_RELATIONSHIP_SHAPES: Dict[str, dict] = {
    "GOVERNS": {"domain": {"JURISDICTION"}, "range": {"CONTRACT", "LEGAL_ENTITY"}},
    "CONTAINS_CLAUSE": {"domain": {"CONTRACT"}, "range": {"CLAUSE"}},
    "LICENSED_UNDER": {"domain": {"MODULE", "SERVICE"}, "range": {"LICENSE"}},
    "PROTECTS": {"domain": {"PATENT", "COPYRIGHT", "TRADEMARK"}, "range": {"Legal"}},
    "BOUND_BY": {"domain": {"LEGAL_ENTITY"}, "range": {"CONTRACT", "TERMS_OF_SERVICE"}},
}

LEGAL_SKILL_MAP: Dict[str, List[str]] = {
    "Legal": ["legal_risk_assessment", "jurisdiction_analysis"],
    "CONTRACT": ["contract_review", "clause_analysis", "obligation_extraction", "risk_clause_detection"],
    "CLAUSE": ["clause_analysis", "risk_clause_detection"],
    "NDA": ["nda_review", "scope_assessment"],
    "SLA": ["sla_compliance_check", "penalty_clause_review"],
    "LICENSE": ["license_compatibility", "license_obligation_check"],
    "PATENT": ["patent_claims_analysis", "prior_art_assessment", "freedom_to_operate"],
    "TRADEMARK": ["trademark_conflict_check"],
    "TERMS_OF_SERVICE": ["terms_analysis", "data_rights_review"],
    "PRIVACY_POLICY": ["privacy_compliance_check", "data_rights_review"],
}

LEGAL_SKILLS: Dict[str, Skill] = {
    # -- Contract Review --
    "contract_review": Skill(
        name="contract_review",
        description="Review contract for completeness and risk",
        handler_prompt=(
            "Review: parties, obligations, payment terms, termination clauses, liability caps, "
            "indemnification, IP assignment, governing law. Flag missing or unusual terms."
        ),
    ),
    "clause_analysis": Skill(
        name="clause_analysis",
        description="Analyze individual contract clauses",
        handler_prompt="Analyze clause: intent, scope, obligations, exceptions, enforcement mechanism. Flag ambiguity.",
    ),
    "obligation_extraction": Skill(
        name="obligation_extraction",
        description="Extract obligations and deadlines from contracts",
        handler_prompt="List all obligations: who must do what, by when, under what conditions. Map dependencies.",
    ),
    "risk_clause_detection": Skill(
        name="risk_clause_detection",
        description="Detect high-risk clauses in contracts",
        handler_prompt="Flag: unlimited liability, broad indemnification, unilateral termination, auto-renewal, non-compete.",
    ),
    # -- IP --
    "patent_claims_analysis": Skill(
        name="patent_claims_analysis",
        description="Analyze patent claims scope and strength",
        handler_prompt="Analyze claims: independent vs dependent, scope breadth, enablement, novelty arguments.",
    ),
    "prior_art_assessment": Skill(
        name="prior_art_assessment",
        description="Assess prior art relevance to patent claims",
        handler_prompt="Evaluate prior art: does it anticipate claims? Which elements are disclosed? Gaps?",
    ),
    "freedom_to_operate": Skill(
        name="freedom_to_operate",
        description="Assess freedom to operate against patent landscape",
        handler_prompt="Assess FTO: identify blocking patents, claim overlap, design-around options, licensing needs.",
    ),
    # -- Compliance --
    "legal_risk_assessment": Skill(
        name="legal_risk_assessment",
        description="Assess overall legal risk exposure",
        handler_prompt="Assess legal risk: regulatory, contractual, IP, liability. Rate severity and likelihood.",
    ),
    "jurisdiction_analysis": Skill(
        name="jurisdiction_analysis",
        description="Analyze jurisdictional implications",
        handler_prompt="Determine applicable jurisdictions, conflict of laws, enforcement considerations.",
    ),
    "privacy_compliance_check": Skill(
        name="privacy_compliance_check",
        description="Check privacy/data protection compliance",
        handler_prompt="Check: GDPR/CCPA compliance, data processing basis, consent mechanisms, DPA requirements.",
    ),
    "license_compatibility": Skill(
        name="license_compatibility",
        description="Check license compatibility between dependencies",
        handler_prompt="Check license compatibility: copyleft vs permissive, attribution requirements, distribution restrictions.",
    ),
    # -- Terms & Licensing --
    "terms_analysis": Skill(
        name="terms_analysis",
        description="Analyze terms of service for risks and obligations",
        handler_prompt="Analyze ToS: user rights, data usage, liability, dispute resolution, modification rights.",
    ),
    "data_rights_review": Skill(
        name="data_rights_review",
        description="Review data rights and usage terms",
        handler_prompt="Review: data ownership, processing rights, deletion obligations, third-party sharing, portability.",
    ),
    "nda_review": Skill(
        name="nda_review",
        description="Review NDA scope and enforceability",
        handler_prompt="Review NDA: definition of confidential info, exclusions, duration, obligations, remedies.",
    ),
    "sla_compliance_check": Skill(
        name="sla_compliance_check",
        description="Check SLA compliance and penalties",
        handler_prompt="Check: uptime targets, response times, penalty calculations, measurement methodology, exclusions.",
    ),
}


def register_legal_domain(registry: DomainRegistry) -> None:
    """Register the legal domain with a DomainRegistry."""
    registry.register_domain(
        name="legal",
        class_hierarchy=LEGAL_CLASS_HIERARCHY,
        entity_shapes=LEGAL_ENTITY_SHAPES,
        relationship_shapes=LEGAL_RELATIONSHIP_SHAPES,
        skill_map=LEGAL_SKILL_MAP,
    )
