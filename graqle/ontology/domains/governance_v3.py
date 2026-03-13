"""Governance Domain v3 — Semantic Constraints.

Replaces format-based output shapes with deep semantic constraints.
OWL hierarchy unchanged. SHACL shapes are now SemanticConstraints
that encode governance truths, not format rules.

Design: "Skills = HOW to reason. Constraints = WHERE to reason."
"""

from __future__ import annotations

from typing import Any, Dict, List

from graqle.ontology.domain_registry import DomainRegistry
from graqle.ontology.semantic_shacl_gate import SemanticConstraint
from graqle.ontology.skill_resolver import Skill

# ============================================================================
# OWL CLASS HIERARCHY — unchanged from v2
# ============================================================================

GOVERNANCE_CLASS_HIERARCHY: Dict[str, str] = {
    "REGULATION": "Governance",
    "POLICY": "Governance",
    "CONTROL": "Governance",
    "RISK": "Governance",
    "STANDARD": "Governance",
    "GOV_FRAMEWORK": "Governance",
    "GOV_DOMAIN": "Governance",
    "GOV_REQUIREMENT": "Governance",
    "GOV_CONTROL": "Governance",
    "GOV_SUB_CONTROL": "Governance",
    "GOV_EVIDENCE": "Governance",
    "GOV_RISK_CATEGORY": "Governance",
    "GOV_ENFORCEMENT": "Governance",
    "GOV_CAUSAL_LINK": "Governance",
    "GOV_ACTOR": "Governance",
    "GOV_PROCESS": "Governance",
}


# ============================================================================
# SEMANTIC CONSTRAINTS — the core redesign
# ============================================================================

def build_governance_semantic_constraints(
    framework_info: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, SemanticConstraint]:
    """Build semantic constraints for governance entity types.

    If framework_info is provided (from ontology auto-generator or KG),
    uses it to create framework-specific constraints. Otherwise uses
    sensible defaults for multi-regulation governance.

    Args:
        framework_info: Optional dict of framework_name -> {markers, scope, rules}

    Returns:
        Dict of entity_type -> SemanticConstraint
    """
    # Default framework markers for cross-reference detection
    FRAMEWORK_MARKERS = {
        "EU AI Act": ["EU AI Act", "AI Act", "Regulation 2024/1689", "artificial intelligence act"],
        "GDPR": ["GDPR", "General Data Protection Regulation", "Regulation 2016/679", "data protection"],
        "DORA": ["DORA", "Digital Operational Resilience Act", "Regulation 2022/2554"],
        "NIS2": ["NIS2", "NIS 2", "Network and Information Security", "Directive 2022/2555"],
    }

    if framework_info:
        for fw_name, fw_data in framework_info.items():
            if "markers" in fw_data:
                FRAMEWORK_MARKERS[fw_name] = fw_data["markers"]

    constraints: Dict[str, SemanticConstraint] = {}

    # --- GOV_FRAMEWORK constraint ---
    constraints["GOV_FRAMEWORK"] = SemanticConstraint(
        entity_type="GOV_FRAMEWORK",
        framework="",  # Framework nodes ARE frameworks — they don't belong to one
        own_framework_markers=[],
        other_framework_markers={},
        scope_description="Top-level regulatory framework metadata: scope, jurisdiction, effective dates",
        in_scope_topics=[
            "framework scope and applicability",
            "jurisdictional reach",
            "effective dates and transition periods",
            "relationship to other frameworks",
        ],
        out_of_scope_topics=[
            "specific article obligations (GOV_REQUIREMENT handles those)",
            "penalty calculations (GOV_ENFORCEMENT handles those)",
            "risk classification details (GOV_RISK_CATEGORY handles those)",
        ],
        reasoning_rules=[
            "State the framework's overall scope, not individual article obligations",
            "When comparing frameworks, state overlaps AND distinctions",
            "Do not summarize individual articles — other nodes handle those",
        ],
        cross_reference_rules={
            fw: f"Compare scope and jurisdiction with {fw}, noting overlaps and distinctions"
            for fw in FRAMEWORK_MARKERS
        },
    )

    # --- GOV_REQUIREMENT constraint ---
    constraints["GOV_REQUIREMENT"] = SemanticConstraint(
        entity_type="GOV_REQUIREMENT",
        framework="",  # Set per-node from KG data
        own_framework_markers=[],  # Set per-node from KG data
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Specific regulatory obligations from a single framework article",
        in_scope_topics=[
            "what this specific article requires",
            "who this obligation applies to (scope)",
            "deadlines and transition periods for this obligation",
            "exceptions and exemptions to this obligation",
        ],
        out_of_scope_topics=[
            "penalty amounts (GOV_ENFORCEMENT handles those)",
            "risk tier classification (GOV_RISK_CATEGORY handles those)",
            "implementation controls (GOV_CONTROL handles those)",
            "obligations from other frameworks (other GOV_REQUIREMENT nodes handle those)",
        ],
        reasoning_rules=[
            "Cite YOUR article number. Do not cite articles from other frameworks as your own.",
            "If the query asks about a topic covered by a different article in your framework, "
            "state 'see [Article X]' rather than answering for it",
            "Distinguish between 'provider obligations' and 'deployer obligations' — they are different",
            "If asked about penalties, state 'non-compliance leads to [enforcement node]' but do not calculate",
        ],
        cross_reference_rules={
            fw: (
                f"If mentioning {fw}, state: 'Related: {fw} [Article X] also addresses this "
                f"under a different legal basis.' Do not claim {fw} provisions as your own."
            )
            for fw in FRAMEWORK_MARKERS
        },
    )

    # --- GOV_ENFORCEMENT constraint ---
    constraints["GOV_ENFORCEMENT"] = SemanticConstraint(
        entity_type="GOV_ENFORCEMENT",
        framework="",
        own_framework_markers=[],
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Penalties, fines, enforcement actions, and enforcing authorities",
        in_scope_topics=[
            "penalty amounts and calculation formulas",
            "which authority enforces",
            "types of enforcement actions (fine, ban, suspension)",
            "appeal processes",
        ],
        out_of_scope_topics=[
            "what the obligation requires (GOV_REQUIREMENT handles that)",
            "risk classification (GOV_RISK_CATEGORY handles that)",
            "how to implement compliance (GOV_CONTROL handles that)",
        ],
        reasoning_rules=[
            "State the EXACT penalty formula from YOUR framework — do not guess",
            "Different frameworks have DIFFERENT penalty regimes — do not mix them",
            "EU AI Act penalties: Art. 99 — up to 35M EUR or 7% (prohibited), 15M/3% (obligations), 7.5M/1% (misinformation)",
            "GDPR penalties: Art. 83 — up to 20M EUR or 4% global turnover",
            "DORA penalties: determined by member states, not EU-level fixed amounts",
            "NIS2 penalties: Art. 34 — up to 10M EUR or 2% global turnover for essential entities",
            "Always specify WHICH penalty tier applies to the specific violation asked about",
        ],
        cross_reference_rules={
            fw: f"If asked about combined penalties across {fw} and your framework, state each separately with its own legal basis"
            for fw in FRAMEWORK_MARKERS
        },
    )

    # --- GOV_RISK_CATEGORY constraint ---
    constraints["GOV_RISK_CATEGORY"] = SemanticConstraint(
        entity_type="GOV_RISK_CATEGORY",
        framework="",
        own_framework_markers=[],
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Risk classification tiers and criteria for categorizing systems/activities",
        in_scope_topics=[
            "risk tier definitions (unacceptable, high, limited, minimal)",
            "criteria for classification into each tier",
            "examples of systems in each tier",
            "Annex III use cases (for AI Act high-risk)",
        ],
        out_of_scope_topics=[
            "specific article obligations (GOV_REQUIREMENT handles those)",
            "penalty amounts (GOV_ENFORCEMENT handles those)",
            "control implementation (GOV_CONTROL handles those)",
        ],
        reasoning_rules=[
            "Prohibited (Art. 5) is NOT a risk tier — it's an outright ban. Do not call it 'high-risk'.",
            "High-risk (Art. 6 + Annex III) is ALLOWED with obligations. Do not confuse with prohibited.",
            "Limited risk (Art. 50) = transparency obligations only",
            "GPAI models have their OWN classification (systemic risk vs non-systemic) — separate from the 4-tier system",
            "GDPR does not use the same risk tiers — do not apply AI Act risk tiers to GDPR",
        ],
    )

    # --- GOV_CONTROL constraint ---
    constraints["GOV_CONTROL"] = SemanticConstraint(
        entity_type="GOV_CONTROL",
        framework="",
        own_framework_markers=[],
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Implementation controls, technical measures, and compliance mechanisms",
        in_scope_topics=[
            "how to implement a specific requirement",
            "technical and organizational measures",
            "control effectiveness assessment",
            "evidence requirements for this control",
        ],
        out_of_scope_topics=[
            "what the regulation requires (GOV_REQUIREMENT handles that)",
            "penalty for non-compliance (GOV_ENFORCEMENT handles that)",
            "risk classification (GOV_RISK_CATEGORY handles that)",
        ],
        reasoning_rules=[
            "Focus on HOW to comply, not WHAT is required — requirements are other nodes' scope",
            "Cite specific technical measures, not general principles",
            "If a control maps to multiple frameworks, specify which requirement it addresses in each",
        ],
    )

    # --- GOV_ACTOR constraint ---
    constraints["GOV_ACTOR"] = SemanticConstraint(
        entity_type="GOV_ACTOR",
        framework="",
        own_framework_markers=[],
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Regulatory actors, roles, and their responsibilities",
        in_scope_topics=[
            "who this actor is (provider, deployer, authority, etc.)",
            "what obligations fall on this actor specifically",
            "how this actor role is defined across frameworks",
        ],
        out_of_scope_topics=[
            "detailed article requirements (GOV_REQUIREMENT handles those)",
            "penalty amounts (GOV_ENFORCEMENT handles those)",
        ],
        reasoning_rules=[
            "AI Act defines 'provider', 'deployer', 'importer', 'distributor' — each has DIFFERENT obligations",
            "GDPR defines 'controller', 'processor' — these are DIFFERENT from AI Act roles",
            "A single company may hold multiple roles (e.g., provider under AI Act AND controller under GDPR)",
            "Do not assume AI Act 'provider' = GDPR 'controller'. They can overlap but are legally distinct.",
        ],
    )

    # --- GOV_PROCESS constraint ---
    constraints["GOV_PROCESS"] = SemanticConstraint(
        entity_type="GOV_PROCESS",
        framework="",
        own_framework_markers=[],
        other_framework_markers=FRAMEWORK_MARKERS,
        scope_description="Regulatory processes, procedures, and workflows",
        in_scope_topics=[
            "notification timelines and procedures",
            "assessment processes (DPIA, conformity assessment)",
            "reporting obligations and frequencies",
        ],
        out_of_scope_topics=[
            "substantive obligations (GOV_REQUIREMENT handles those)",
            "penalties for missing deadlines (GOV_ENFORCEMENT handles those)",
        ],
        reasoning_rules=[
            "State SPECIFIC timelines (e.g., '72 hours' for GDPR breach notification, '24 hours' for NIS2)",
            "Do not mix up notification timelines across frameworks",
            "DORA incident reporting: initial notification within 4 hours, intermediate within 72 hours",
        ],
    )

    return constraints


# ============================================================================
# UNIFIED SKILL+CONSTRAINT MAP
# ============================================================================

# Skills define HOW to reason. Constraints define WHERE to reason.
# Both are injected into the node prompt together.

GOVERNANCE_SKILL_MAP: Dict[str, List[str]] = {
    "Governance": [
        "check_compliance",
        "identify_gaps",
        "cross_reference_framework",
    ],
    "GOV_FRAMEWORK": ["scope_determination", "framework_comparison"],
    "GOV_REQUIREMENT": [
        "obligation_analysis",
        "scope_determination",
        "deadline_check",
        "cross_framework_mapping",
    ],
    "GOV_CONTROL": ["control_assessment", "implementation_guidance", "gap_analysis"],
    "GOV_ENFORCEMENT": [
        "penalty_lookup",
        "enforcement_timeline",
        "authority_identification",
        "penalty_calculation",
    ],
    "GOV_EVIDENCE": ["evidence_sufficiency", "evidence_format_check", "audit_readiness"],
    "GOV_RISK_CATEGORY": ["risk_assessment", "impact_analysis", "risk_tier_classification"],
    "GOV_CAUSAL_LINK": ["causal_chain_trace", "root_cause_identify", "impact_propagation"],
    "GOV_ACTOR": ["role_identification", "obligation_mapping"],
    "GOV_PROCESS": ["timeline_check", "procedure_mapping"],
    "REGULATION": ["regulatory_interpretation", "jurisdiction_check"],
}

# Skill definitions with constraint-aware prompts
GOVERNANCE_SKILLS: Dict[str, Skill] = {
    "check_compliance": Skill(
        name="check_compliance",
        description="Verify compliance status against regulatory requirements",
        handler_prompt=(
            "Check compliance against the specific requirement. "
            "Cite YOUR framework's article. If other frameworks apply, "
            "flag them as cross-references with their own legal basis."
        ),
    ),
    "obligation_analysis": Skill(
        name="obligation_analysis",
        description="Analyze specific obligations, timelines, and scope",
        handler_prompt=(
            "Break down the obligation: what must be done, by whom, by when. "
            "Stay within YOUR article's scope. If the question spans multiple "
            "articles, state what YOUR article covers and reference the others."
        ),
    ),
    "penalty_lookup": Skill(
        name="penalty_lookup",
        description="Look up penalties for non-compliance",
        handler_prompt=(
            "State the EXACT penalty from YOUR framework's enforcement provisions. "
            "Include: amount/percentage, which article defines it, which authority enforces. "
            "Do NOT mix penalty regimes across frameworks."
        ),
    ),
    "cross_reference_framework": Skill(
        name="cross_reference_framework",
        description="Find related requirements across frameworks",
        handler_prompt=(
            "Identify overlapping requirements in other frameworks. "
            "For each: state the other framework, its article, and how it DIFFERS "
            "from YOUR requirement (different legal basis, different scope, different remedy)."
        ),
    ),
    "cross_framework_mapping": Skill(
        name="cross_framework_mapping",
        description="Map requirements across frameworks",
        handler_prompt=(
            "Map YOUR requirement to equivalent requirements in other frameworks. "
            "For each mapping: state what overlaps, what differs, and which legal basis applies."
        ),
    ),
    "risk_tier_classification": Skill(
        name="risk_tier_classification",
        description="Classify risk tier per regulatory framework",
        handler_prompt=(
            "Classify using YOUR framework's risk tiers. "
            "Do not apply one framework's risk classification to another. "
            "State the specific criteria that determine the tier."
        ),
    ),
    "scope_determination": Skill(
        name="scope_determination",
        description="Determine applicability scope",
        handler_prompt="Determine who/what this applies to and any exceptions within YOUR framework.",
    ),
    "deadline_check": Skill(
        name="deadline_check",
        description="Check compliance deadlines",
        handler_prompt="State the specific deadline from YOUR framework. Do not mix timelines across frameworks.",
    ),
    "identify_gaps": Skill(
        name="identify_gaps",
        description="Identify compliance gaps",
        handler_prompt="Identify gaps between requirements and controls within YOUR framework's scope.",
    ),
    "framework_comparison": Skill(
        name="framework_comparison",
        description="Compare frameworks",
        handler_prompt="Compare scope, requirements, and enforcement. State each framework's provisions separately.",
    ),
    "control_assessment": Skill(
        name="control_assessment",
        description="Assess control effectiveness",
        handler_prompt="Assess if this control addresses its target requirement effectively.",
    ),
    "implementation_guidance": Skill(
        name="implementation_guidance",
        description="Provide implementation steps",
        handler_prompt="Provide specific steps to implement. Cite the requirement being addressed.",
    ),
    "gap_analysis": Skill(
        name="gap_analysis",
        description="Analyze control gaps",
        handler_prompt="Identify gaps in control coverage for the target requirements.",
    ),
    "enforcement_timeline": Skill(
        name="enforcement_timeline",
        description="Determine enforcement timeline",
        handler_prompt="State when enforcement begins under YOUR framework.",
    ),
    "authority_identification": Skill(
        name="authority_identification",
        description="Identify enforcing authority",
        handler_prompt="Name the specific authority for YOUR framework's enforcement.",
    ),
    "penalty_calculation": Skill(
        name="penalty_calculation",
        description="Calculate potential penalties",
        handler_prompt="Calculate using YOUR framework's specific penalty formula. State the formula and applicable tier.",
    ),
    "evidence_sufficiency": Skill(
        name="evidence_sufficiency",
        description="Assess evidence sufficiency",
        handler_prompt="Assess if evidence meets YOUR framework's requirements.",
    ),
    "evidence_format_check": Skill(
        name="evidence_format_check",
        description="Verify evidence format",
        handler_prompt="Verify evidence format meets regulatory requirements.",
    ),
    "audit_readiness": Skill(
        name="audit_readiness",
        description="Assess audit readiness",
        handler_prompt="Assess if evidence base is sufficient for audit under YOUR framework.",
    ),
    "risk_assessment": Skill(
        name="risk_assessment",
        description="Assess risk tier and impact",
        handler_prompt="Classify using YOUR framework's risk tiers and criteria.",
    ),
    "impact_analysis": Skill(
        name="impact_analysis",
        description="Analyze business impact",
        handler_prompt="Analyze financial, operational, reputational impact of compliance/non-compliance.",
    ),
    "causal_chain_trace": Skill(
        name="causal_chain_trace",
        description="Trace causal chains",
        handler_prompt="Trace from gap to consequence within YOUR framework.",
    ),
    "root_cause_identify": Skill(
        name="root_cause_identify",
        description="Identify root causes",
        handler_prompt="Identify root cause of compliance failure.",
    ),
    "impact_propagation": Skill(
        name="impact_propagation",
        description="Trace impact propagation",
        handler_prompt="Trace how impact propagates through connected entities.",
    ),
    "regulatory_interpretation": Skill(
        name="regulatory_interpretation",
        description="Interpret regulatory text",
        handler_prompt="Interpret YOUR framework's text: obligations, exceptions, scope.",
    ),
    "jurisdiction_check": Skill(
        name="jurisdiction_check",
        description="Check jurisdictional applicability",
        handler_prompt="Determine jurisdictional scope and territorial applicability.",
    ),
    "role_identification": Skill(
        name="role_identification",
        description="Identify actor roles",
        handler_prompt="Identify what role this actor holds under each applicable framework.",
    ),
    "obligation_mapping": Skill(
        name="obligation_mapping",
        description="Map obligations to actors",
        handler_prompt="Map which obligations apply to this actor under each framework.",
    ),
    "timeline_check": Skill(
        name="timeline_check",
        description="Check process timelines",
        handler_prompt="State specific timelines for this process under YOUR framework.",
    ),
    "procedure_mapping": Skill(
        name="procedure_mapping",
        description="Map process procedures",
        handler_prompt="Map the required procedure steps under YOUR framework.",
    ),
}


# ============================================================================
# ENTITY SHAPES (for backward compat with DomainRegistry)
# ============================================================================

GOVERNANCE_ENTITY_SHAPES: Dict[str, Dict[str, Any]] = {
    "_default": {
        "required": ["name", "type"],
        "optional": ["description", "importance", "confidence", "sourceDocument"],
    },
}

GOVERNANCE_RELATIONSHIP_SHAPES: Dict[str, Dict[str, Any]] = {
    "COMPLIES_WITH": {"domain": None, "range": ["REGULATION", "POLICY", "STANDARD"]},
    "GOVERNED_BY": {"domain": None, "range": ["REGULATION", "POLICY", "CONTROL"]},
    "PART_OF": {"domain": None, "range": None},
    "DEPENDS_ON": {"domain": ["GOV_REQUIREMENT"], "range": ["GOV_REQUIREMENT"]},
    "MAPS_TO": {"domain": None, "range": None},
    "NON_COMPLIANCE_LEADS_TO": {"domain": ["GOV_REQUIREMENT"], "range": ["GOV_ENFORCEMENT"]},
    "TRIGGERS_ENFORCEMENT": {"domain": ["GOV_RISK_CATEGORY"], "range": ["GOV_ENFORCEMENT"]},
    "REQUIRES_EVIDENCE": {"domain": ["GOV_REQUIREMENT", "GOV_CONTROL"], "range": ["GOV_EVIDENCE"]},
    "MITIGATES_RISK_CATEGORY": {"domain": ["GOV_CONTROL"], "range": ["GOV_RISK_CATEGORY"]},
    "HAS_CAUSAL_LINK": {"domain": ["GOV_REQUIREMENT", "GOV_CONTROL"], "range": ["GOV_CAUSAL_LINK"]},
    "HAS_SUB_CONTROL": {"domain": ["GOV_CONTROL"], "range": ["GOV_SUB_CONTROL"]},
    "APPLIES_TO_RISK": {"domain": ["GOV_REQUIREMENT"], "range": ["GOV_RISK_CATEGORY"]},
}

# Empty output shapes — SemanticSHACLGate replaces the old format-based shapes
GOVERNANCE_OUTPUT_SHAPES: Dict[str, Dict[str, Any]] = {}


def register_governance_domain_v3(
    registry: DomainRegistry,
    framework_info: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, SemanticConstraint]:
    """Register governance domain v3 with semantic constraints.

    Returns the semantic constraints for use with SemanticSHACLGate.
    """
    registry.register_domain(
        name="governance",
        class_hierarchy=GOVERNANCE_CLASS_HIERARCHY,
        entity_shapes=GOVERNANCE_ENTITY_SHAPES,
        relationship_shapes=GOVERNANCE_RELATIONSHIP_SHAPES,
        skill_map=GOVERNANCE_SKILL_MAP,
        output_shapes=GOVERNANCE_OUTPUT_SHAPES,  # Empty — semantic gate handles validation
    )

    return build_governance_semantic_constraints(framework_info)
