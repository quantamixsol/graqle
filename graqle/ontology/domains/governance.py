"""Governance Domain — OWL hierarchy, SHACL shapes, skills, output shapes.

Ported from TAMR+ production ontology (ontology.py + ontology_v2.py).
Registers via DomainRegistry — same API any domain uses.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.governance
# risk: LOW (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, test_router, test_skill_resolver, test_governance_routes
# dependencies: __future__, typing, domain_registry, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any, Dict, List

from graqle.ontology.domain_registry import DomainRegistry
from graqle.ontology.skill_resolver import Skill


# ============================================================================
# OWL CLASS HIERARCHY — Governance entity types
# ============================================================================

GOVERNANCE_CLASS_HIERARCHY: Dict[str, str] = {
    # Core governance types
    "REGULATION": "Governance",
    "POLICY": "Governance",
    "CONTROL": "Governance",
    "RISK": "Governance",
    "STANDARD": "Governance",
    # Governance Library (pre-processed frameworks)
    "GOV_FRAMEWORK": "Governance",
    "GOV_DOMAIN": "Governance",
    "GOV_REQUIREMENT": "Governance",
    "GOV_CONTROL": "Governance",
    # Governance v2 (granular types)
    "GOV_SUB_CONTROL": "Governance",
    "GOV_EVIDENCE": "Governance",
    "GOV_RISK_CATEGORY": "Governance",
    "GOV_ENFORCEMENT": "Governance",
    "GOV_CAUSAL_LINK": "Governance",
}


# ============================================================================
# SHACL ENTITY SHAPES — Property constraints per entity type
# ============================================================================

GOVERNANCE_ENTITY_SHAPES: Dict[str, Dict[str, Any]] = {
    "_default": {
        "required": ["name", "type"],
        "optional": ["description", "importance", "confidence", "sourceDocument"],
        "constraints": {
            "confidence": {"min": 0.0, "max": 1.0, "type": "float"},
            "importance": {"min": 0, "max": 10, "type": "int"},
            "name": {"min_length": 1, "max_length": 500, "type": "str"},
        },
    },
    "REGULATION": {
        "required": ["name", "type"],
        "optional": ["description", "jurisdiction", "effective_date", "article"],
    },
    "GOV_FRAMEWORK": {
        "required": ["name", "type"],
        "optional": ["description", "jurisdiction", "effective_date", "scope"],
    },
    "GOV_REQUIREMENT": {
        "required": ["name", "type"],
        "optional": ["description", "article", "obligation_type", "scope"],
    },
    "GOV_CONTROL": {
        "required": ["name", "type"],
        "optional": ["description", "controlId", "implementationGuidance"],
    },
    "GOV_SUB_CONTROL": {
        "required": ["name", "type", "controlId"],
        "optional": [
            "description", "stepOrder", "implementationGuidance",
            "testCriteria", "automatable", "difficulty",
        ],
        "constraints": {
            "stepOrder": {"min": 1, "max": 999, "type": "int"},
            "difficulty": {"values": ["low", "medium", "high"], "type": "enum"},
        },
    },
    "GOV_EVIDENCE": {
        "required": ["name", "type", "evidenceCategory"],
        "optional": [
            "description", "format", "retentionPeriod",
            "frequency", "automatable", "exampleArtifacts",
        ],
        "constraints": {
            "evidenceCategory": {
                "values": [
                    "policy", "procedure", "record", "test_result",
                    "audit_report", "training_log", "incident_report",
                    "impact_assessment", "technical_documentation",
                    "monitoring_output", "certification",
                ],
                "type": "enum",
            },
        },
    },
    "GOV_RISK_CATEGORY": {
        "required": ["name", "type", "riskTier"],
        "optional": [
            "description", "criteria", "examples",
            "mitigationRequired", "assessmentFrequency",
        ],
        "constraints": {
            "riskTier": {
                "values": [
                    "unacceptable", "high", "limited", "minimal",
                    "systemic", "critical", "moderate", "low",
                ],
                "type": "enum",
            },
        },
    },
    "GOV_ENFORCEMENT": {
        "required": ["name", "type", "enforcementType"],
        "optional": [
            "description", "maxPenaltyEUR", "penaltyFormula",
            "enforcingBody", "appealProcess", "probability",
        ],
        "constraints": {
            "enforcementType": {
                "values": [
                    "fine", "ban", "suspension", "warning",
                    "corrective_action", "market_withdrawal",
                    "public_notice", "criminal_prosecution",
                ],
                "type": "enum",
            },
            "probability": {"min": 0.0, "max": 1.0, "type": "float"},
        },
    },
    "GOV_CAUSAL_LINK": {
        "required": ["name", "type", "causeType", "effectType"],
        "optional": [
            "description", "likelihood", "severity",
            "timeToImpact", "mitigationPath",
        ],
        "constraints": {
            "likelihood": {"min": 0.0, "max": 1.0, "type": "float"},
            "severity": {"min": 1, "max": 5, "type": "int"},
        },
    },
}


# ============================================================================
# SHACL RELATIONSHIP SHAPES — Domain/range constraints
# ============================================================================

GOVERNANCE_RELATIONSHIP_SHAPES: Dict[str, Dict[str, Any]] = {
    "COMPLIES_WITH": {
        "domain": ["ORGANIZATION", "SYSTEM", "PROCESS", "PRODUCT"],
        "range": ["REGULATION", "POLICY", "STANDARD"],
    },
    "GOVERNED_BY": {
        "domain": ["SYSTEM", "PROCESS", "PRODUCT", "SERVICE"],
        "range": ["REGULATION", "POLICY", "CONTROL"],
    },
    "PART_OF": {
        "domain": None,  # Any type
        "range": None,  # Any type
    },
    "MITIGATED": {
        "domain": ["CONTROL", "ACTION", "PROCESS", "GOV_CONTROL", "GOV_SUB_CONTROL"],
        "range": ["RISK", "GOV_RISK_CATEGORY"],
    },
    "HAS_SUB_CONTROL": {
        "domain": ["GOV_CONTROL"],
        "range": ["GOV_SUB_CONTROL"],
    },
    "REQUIRES_EVIDENCE": {
        "domain": ["GOV_REQUIREMENT", "GOV_CONTROL", "GOV_SUB_CONTROL"],
        "range": ["GOV_EVIDENCE"],
    },
    "APPLIES_TO_RISK": {
        "domain": ["GOV_REQUIREMENT"],
        "range": ["GOV_RISK_CATEGORY"],
    },
    "MITIGATES_RISK_CATEGORY": {
        "domain": ["GOV_CONTROL", "GOV_SUB_CONTROL"],
        "range": ["GOV_RISK_CATEGORY"],
    },
    "TRIGGERS_ENFORCEMENT": {
        "domain": ["GOV_RISK_CATEGORY"],
        "range": ["GOV_ENFORCEMENT"],
    },
    "NON_COMPLIANCE_LEADS_TO": {
        "domain": ["GOV_REQUIREMENT"],
        "range": ["GOV_ENFORCEMENT"],
    },
    "HAS_CAUSAL_LINK": {
        "domain": ["GOV_REQUIREMENT", "GOV_CONTROL"],
        "range": ["GOV_CAUSAL_LINK"],
    },
    "DEPENDS_ON": {
        "domain": ["GOV_REQUIREMENT"],
        "range": ["GOV_REQUIREMENT"],
    },
    "MAPS_TO": {
        "domain": None,  # Any governance type
        "range": None,  # Any governance type
    },
}


# ============================================================================
# SKILL MAP — Skills per entity type (inherit up hierarchy)
# ============================================================================

GOVERNANCE_SKILL_MAP: Dict[str, List[str]] = {
    # Branch-level skills (all governance types inherit these)
    "Governance": [
        "check_compliance",
        "identify_gaps",
        "cross_reference_framework",
    ],
    # Type-specific skills
    "GOV_FRAMEWORK": [
        "scope_determination",
        "framework_comparison",
    ],
    "GOV_REQUIREMENT": [
        "obligation_analysis",
        "scope_determination",
        "deadline_check",
        "cross_framework_mapping",
    ],
    "GOV_CONTROL": [
        "control_assessment",
        "implementation_guidance",
        "gap_analysis",
    ],
    "GOV_ENFORCEMENT": [
        "penalty_lookup",
        "enforcement_timeline",
        "authority_identification",
        "penalty_calculation",
    ],
    "GOV_EVIDENCE": [
        "evidence_sufficiency",
        "evidence_format_check",
        "audit_readiness",
    ],
    "GOV_RISK_CATEGORY": [
        "risk_assessment",
        "impact_analysis",
        "risk_tier_classification",
    ],
    "GOV_CAUSAL_LINK": [
        "causal_chain_trace",
        "root_cause_identify",
        "impact_propagation",
    ],
    "REGULATION": [
        "regulatory_interpretation",
        "jurisdiction_check",
    ],
}


# ============================================================================
# OUTPUT SHAPES — SHACL gate validation for node reasoning outputs
# ============================================================================

GOVERNANCE_OUTPUT_SHAPES: Dict[str, Dict[str, Any]] = {
    "GOV_REQUIREMENT": {
        "must_reference": ["article_number"],
        "must_include_if_relevant": ["penalty", "timeline", "obligation_type"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [
            "I don't know",
            "not in my domain",
            "I cannot determine",
        ],
    },
    "GOV_ENFORCEMENT": {
        "must_reference": ["penalty_amount_or_percentage", "enforcement_authority"],
        "must_include_if_relevant": ["timeline", "enforcement_type"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [
            "I'm not sure about penalties",
            "I don't know the penalty",
        ],
    },
    "GOV_RISK_CATEGORY": {
        "must_reference": ["risk_tier"],
        "must_include_if_relevant": ["criteria", "mitigation"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [],
    },
    "GOV_FRAMEWORK": {
        "must_reference": [],
        "must_include_if_relevant": ["scope", "jurisdiction", "effective_date"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [],
    },
    "GOV_CONTROL": {
        "must_reference": [],
        "must_include_if_relevant": ["implementation", "evidence"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [],
    },
    "GOV_EVIDENCE": {
        "must_reference": [],
        "must_include_if_relevant": ["format", "frequency", "retention"],
        "max_length_words": 150,
        "min_length_words": 10,
        "forbidden_patterns": [],
    },
    "GOV_CAUSAL_LINK": {
        "must_reference": [],
        "must_include_if_relevant": ["cause", "effect", "likelihood"],
        "max_length_words": 150,
        "min_length_words": 15,
        "forbidden_patterns": [],
    },
}


# ============================================================================
# GOVERNANCE SKILL DEFINITIONS — Full skill objects with handler prompts
# ============================================================================

GOVERNANCE_SKILLS: Dict[str, Skill] = {
    "check_compliance": Skill(
        name="check_compliance",
        description="Verify compliance status against regulatory requirements",
        handler_prompt="Check if the subject complies with the specific regulatory requirement. Cite the article.",
    ),
    "identify_gaps": Skill(
        name="identify_gaps",
        description="Identify compliance gaps between requirements and controls",
        handler_prompt="Identify gaps between what is required and what is implemented. Be specific.",
    ),
    "cross_reference_framework": Skill(
        name="cross_reference_framework",
        description="Find related requirements across different frameworks",
        handler_prompt="Identify overlapping or related requirements in other frameworks.",
    ),
    "obligation_analysis": Skill(
        name="obligation_analysis",
        description="Analyze specific obligations, timelines, and scope",
        handler_prompt="Break down the obligation: what must be done, by whom, by when.",
    ),
    "scope_determination": Skill(
        name="scope_determination",
        description="Determine applicability scope for a requirement",
        handler_prompt="Determine who/what this requirement applies to and any exceptions.",
    ),
    "deadline_check": Skill(
        name="deadline_check",
        description="Check compliance deadlines and transition periods",
        handler_prompt="State the specific deadline or transition period for compliance.",
    ),
    "penalty_lookup": Skill(
        name="penalty_lookup",
        description="Look up penalties for non-compliance",
        handler_prompt="State the specific penalty: amount/percentage, authority, type of enforcement.",
    ),
    "enforcement_timeline": Skill(
        name="enforcement_timeline",
        description="Determine enforcement timeline and precedents",
        handler_prompt="State when enforcement begins and any relevant precedent cases.",
    ),
    "authority_identification": Skill(
        name="authority_identification",
        description="Identify the enforcing authority",
        handler_prompt="Name the specific authority responsible for enforcement.",
    ),
    "penalty_calculation": Skill(
        name="penalty_calculation",
        description="Calculate potential penalties based on turnover/violation",
        handler_prompt="Calculate the penalty range based on the specific formula in the regulation.",
    ),
    "risk_assessment": Skill(
        name="risk_assessment",
        description="Assess risk tier and impact",
        handler_prompt="Classify the risk tier and explain the criteria for this classification.",
    ),
    "impact_analysis": Skill(
        name="impact_analysis",
        description="Analyze business impact of compliance/non-compliance",
        handler_prompt="Analyze the business impact: financial, operational, reputational.",
    ),
    "evidence_sufficiency": Skill(
        name="evidence_sufficiency",
        description="Assess whether evidence is sufficient for compliance demonstration",
        handler_prompt="Assess if the available evidence is sufficient to demonstrate compliance.",
    ),
    "causal_chain_trace": Skill(
        name="causal_chain_trace",
        description="Trace causal chains from compliance gaps to consequences",
        handler_prompt="Trace the causal chain: what gap leads to what consequence.",
    ),
    "root_cause_identify": Skill(
        name="root_cause_identify",
        description="Identify root causes of compliance failures",
        handler_prompt="Identify the root cause of the compliance failure.",
    ),
    "cross_framework_mapping": Skill(
        name="cross_framework_mapping",
        description="Map requirements across frameworks (e.g., GDPR ↔ AI Act)",
        handler_prompt="Map this requirement to equivalent requirements in other frameworks.",
    ),
    "control_assessment": Skill(
        name="control_assessment",
        description="Assess control effectiveness and implementation status",
        handler_prompt="Assess if this control effectively addresses its target requirement.",
    ),
    "risk_tier_classification": Skill(
        name="risk_tier_classification",
        description="Classify risk tier per regulatory framework",
        handler_prompt="Classify the risk tier according to the framework's classification system.",
    ),
    "framework_comparison": Skill(
        name="framework_comparison",
        description="Compare frameworks and their requirements",
        handler_prompt="Compare the scope, requirements, and enforcement of the frameworks.",
    ),
    "regulatory_interpretation": Skill(
        name="regulatory_interpretation",
        description="Interpret regulatory text and requirements",
        handler_prompt="Interpret the regulatory text: obligations, exceptions, scope.",
    ),
    "jurisdiction_check": Skill(
        name="jurisdiction_check",
        description="Check jurisdictional applicability",
        handler_prompt="Determine the jurisdictional scope and territorial applicability.",
    ),
    "implementation_guidance": Skill(
        name="implementation_guidance",
        description="Provide implementation guidance for controls",
        handler_prompt="Provide specific steps to implement this control.",
    ),
    "gap_analysis": Skill(
        name="gap_analysis",
        description="Analyze gaps in control coverage",
        handler_prompt="Identify gaps in the control's coverage of its target requirements.",
    ),
    "evidence_format_check": Skill(
        name="evidence_format_check",
        description="Verify evidence format and completeness",
        handler_prompt="Verify the evidence format meets regulatory requirements.",
    ),
    "audit_readiness": Skill(
        name="audit_readiness",
        description="Assess audit readiness based on evidence",
        handler_prompt="Assess if the evidence base is sufficient for an audit.",
    ),
    "impact_propagation": Skill(
        name="impact_propagation",
        description="Trace how impacts propagate through the causal chain",
        handler_prompt="Trace how this impact propagates through connected entities.",
    ),
}


def register_governance_domain(registry: DomainRegistry) -> None:
    """Register the governance domain with the registry.

    This is the canonical way to add governance ontology to Graqle.
    Call this once at startup.
    """
    from graqle.ontology.skill_resolver import SkillResolver

    registry.register_domain(
        name="governance",
        class_hierarchy=GOVERNANCE_CLASS_HIERARCHY,
        entity_shapes=GOVERNANCE_ENTITY_SHAPES,
        relationship_shapes=GOVERNANCE_RELATIONSHIP_SHAPES,
        skill_map=GOVERNANCE_SKILL_MAP,
        output_shapes=GOVERNANCE_OUTPUT_SHAPES,
    )

    return None
