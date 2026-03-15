"""Marketing & Brand domain — skills for audience analysis, brand, content, GTM.

20 skills organized by marketing function:
- Brand & Positioning (5)
- Content & Copy (5)
- Audience & Segmentation (4)
- GTM & Channels (3)
- Competitive Intelligence (3)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.marketing
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


# ---------------------------------------------------------------------------
# OWL Class Hierarchy
# ---------------------------------------------------------------------------

MARKETING_CLASS_HIERARCHY: dict[str, str] = {
    # Branch level
    "Marketing": "Thing",
    # Entity types
    "BRAND": "Marketing",
    "AUDIENCE": "Marketing",
    "CAMPAIGN": "Marketing",
    "CONTENT": "Marketing",
    "CHANNEL": "Marketing",
    "COMPETITOR": "Marketing",
    "PRODUCT_POSITION": "Marketing",
    "MARKET_SEGMENT": "Marketing",
    "PERSONA": "AUDIENCE",
    "CONTENT_PIECE": "CONTENT",
    "SOCIAL_POST": "CONTENT",
    "LANDING_PAGE": "CONTENT",
}

# ---------------------------------------------------------------------------
# Entity Shapes (SHACL)
# ---------------------------------------------------------------------------

MARKETING_ENTITY_SHAPES: dict[str, dict] = {
    "BRAND": {
        "required": ["name", "voice_tone"],
        "optional": ["tagline", "values", "visual_identity", "guidelines_url"],
    },
    "AUDIENCE": {
        "required": ["name", "description"],
        "optional": ["demographics", "psychographics", "pain_points", "channels"],
    },
    "CAMPAIGN": {
        "required": ["name", "objective"],
        "optional": ["budget", "start_date", "end_date", "channels", "kpis"],
    },
    "COMPETITOR": {
        "required": ["name"],
        "optional": ["positioning", "strengths", "weaknesses", "market_share"],
    },
}

# ---------------------------------------------------------------------------
# Relationship Shapes
# ---------------------------------------------------------------------------

MARKETING_RELATIONSHIP_SHAPES: dict[str, dict] = {
    "TARGETS": {"domain": {"CAMPAIGN", "CONTENT"}, "range": {"AUDIENCE", "PERSONA", "MARKET_SEGMENT"}},
    "COMPETES_WITH": {"domain": {"BRAND", "PRODUCT_POSITION"}, "range": {"COMPETITOR"}},
    "PUBLISHED_ON": {"domain": {"CONTENT", "CONTENT_PIECE"}, "range": {"CHANNEL"}},
    "PART_OF_CAMPAIGN": {"domain": {"CONTENT", "SOCIAL_POST", "LANDING_PAGE"}, "range": {"CAMPAIGN"}},
    "REPRESENTS": {"domain": {"PERSONA"}, "range": {"AUDIENCE", "MARKET_SEGMENT"}},
    "DIFFERENTIATES_FROM": {"domain": {"PRODUCT_POSITION"}, "range": {"COMPETITOR"}},
}

# ---------------------------------------------------------------------------
# Skill Map — which entity types get which skills
# ---------------------------------------------------------------------------

MARKETING_SKILL_MAP: dict[str, list[str]] = {
    # Branch-level (all marketing entities inherit)
    "Marketing": ["analyze_brand_voice", "audience_analysis", "competitive_positioning"],
    # Brand
    "BRAND": ["brand_voice_audit", "brand_consistency_check", "visual_identity_review"],
    # Audience
    "AUDIENCE": ["persona_analysis", "pain_point_mapping", "channel_preference"],
    "PERSONA": ["persona_analysis", "journey_mapping"],
    # Content
    "CONTENT": ["content_strategy", "seo_analysis", "readability_check", "cta_effectiveness"],
    "CONTENT_PIECE": ["content_strategy", "readability_check"],
    "SOCIAL_POST": ["engagement_prediction", "hashtag_analysis"],
    "LANDING_PAGE": ["conversion_optimization", "cta_effectiveness"],
    # Campaign
    "CAMPAIGN": ["campaign_performance", "budget_allocation", "attribution_analysis"],
    # Competitive
    "COMPETITOR": ["competitive_analysis", "market_share_assessment", "positioning_gap"],
    "PRODUCT_POSITION": ["positioning_gap", "value_proposition_analysis"],
    # Channel
    "CHANNEL": ["channel_performance", "audience_reach"],
}

# ---------------------------------------------------------------------------
# Skill Definitions
# ---------------------------------------------------------------------------

MARKETING_SKILLS: dict[str, Skill] = {
    # -- Brand & Positioning --
    "analyze_brand_voice": Skill(
        name="analyze_brand_voice",
        description="Analyze brand voice consistency across content",
        handler_prompt=(
            "Evaluate whether the content matches the brand's tone, voice, and personality guidelines. "
            "Flag deviations. Rate consistency 1-10."
        ),
    ),
    "brand_voice_audit": Skill(
        name="brand_voice_audit",
        description="Audit brand voice guidelines completeness",
        handler_prompt=(
            "Review the brand voice guidelines for completeness: tone, personality, do's/don'ts, "
            "examples for each channel. Identify gaps."
        ),
    ),
    "brand_consistency_check": Skill(
        name="brand_consistency_check",
        description="Check brand consistency across touchpoints",
        handler_prompt=(
            "Check if visual identity, messaging, and tone are consistent across all touchpoints. "
            "Flag inconsistencies with specific examples."
        ),
    ),
    "visual_identity_review": Skill(
        name="visual_identity_review",
        description="Review visual identity elements and usage",
        handler_prompt="Review logo usage, color palette, typography, and imagery guidelines compliance.",
    ),
    "value_proposition_analysis": Skill(
        name="value_proposition_analysis",
        description="Analyze value proposition clarity and differentiation",
        handler_prompt=(
            "Evaluate the value proposition: Is it clear? Unique? Does it address the target audience's "
            "primary pain point? How does it compare to competitors?"
        ),
    ),
    # -- Content & Copy --
    "content_strategy": Skill(
        name="content_strategy",
        description="Analyze content strategy alignment with goals",
        handler_prompt=(
            "Evaluate content against strategic goals: target audience, funnel stage, key messages, "
            "CTA, and distribution channel fit."
        ),
    ),
    "seo_analysis": Skill(
        name="seo_analysis",
        description="Analyze SEO elements and keyword strategy",
        handler_prompt=(
            "Review title tags, meta descriptions, headings, keyword usage, internal linking, "
            "and content structure for SEO best practices."
        ),
    ),
    "readability_check": Skill(
        name="readability_check",
        description="Check content readability and clarity",
        handler_prompt="Assess reading level, sentence complexity, jargon usage, and scan-ability.",
    ),
    "cta_effectiveness": Skill(
        name="cta_effectiveness",
        description="Evaluate call-to-action effectiveness",
        handler_prompt=(
            "Evaluate CTAs for: clarity, urgency, value proposition, placement, and visual prominence. "
            "Suggest improvements."
        ),
    ),
    "engagement_prediction": Skill(
        name="engagement_prediction",
        description="Predict content engagement potential",
        handler_prompt=(
            "Assess engagement potential based on: hook strength, emotional triggers, relevance to audience, "
            "shareability, and timing."
        ),
    ),
    # -- Audience & Segmentation --
    "audience_analysis": Skill(
        name="audience_analysis",
        description="Analyze target audience characteristics and needs",
        handler_prompt=(
            "Profile the target audience: demographics, psychographics, pain points, goals, "
            "preferred channels, and buying behavior."
        ),
    ),
    "persona_analysis": Skill(
        name="persona_analysis",
        description="Analyze buyer persona accuracy and completeness",
        handler_prompt=(
            "Evaluate the persona: Is it data-backed? Does it include goals, challenges, objections, "
            "and preferred content formats?"
        ),
    ),
    "pain_point_mapping": Skill(
        name="pain_point_mapping",
        description="Map audience pain points to solutions",
        handler_prompt="Map each pain point to: severity, frequency, current workaround, and your solution.",
    ),
    "journey_mapping": Skill(
        name="journey_mapping",
        description="Map customer journey stages and touchpoints",
        handler_prompt="Map the journey: awareness, consideration, decision, retention. Identify gaps and drop-off points.",
    ),
    # -- GTM & Channels --
    "campaign_performance": Skill(
        name="campaign_performance",
        description="Analyze campaign performance metrics",
        handler_prompt="Analyze KPIs: reach, engagement, conversion, CAC, ROAS. Compare to benchmarks.",
    ),
    "channel_performance": Skill(
        name="channel_performance",
        description="Analyze channel effectiveness and ROI",
        handler_prompt="Evaluate channel: audience fit, cost efficiency, engagement rate, conversion rate.",
    ),
    "budget_allocation": Skill(
        name="budget_allocation",
        description="Optimize marketing budget allocation",
        handler_prompt="Recommend budget allocation across channels based on historical performance and goals.",
    ),
    # -- Competitive Intelligence --
    "competitive_analysis": Skill(
        name="competitive_analysis",
        description="Analyze competitor strategy and positioning",
        handler_prompt=(
            "Analyze competitor: positioning, messaging, channels, content strategy, pricing, "
            "and market share. Identify vulnerabilities."
        ),
    ),
    "competitive_positioning": Skill(
        name="competitive_positioning",
        description="Evaluate competitive positioning and differentiation",
        handler_prompt="Compare positioning on key dimensions: price, features, brand perception, market fit.",
    ),
    "positioning_gap": Skill(
        name="positioning_gap",
        description="Identify gaps in competitive positioning",
        handler_prompt="Identify unoccupied positions in the competitive landscape that could be exploited.",
    ),
}


def register_marketing_domain(registry: DomainRegistry) -> None:
    """Register the marketing domain with a DomainRegistry."""
    registry.register_domain(
        name="marketing",
        class_hierarchy=MARKETING_CLASS_HIERARCHY,
        entity_shapes=MARKETING_ENTITY_SHAPES,
        relationship_shapes=MARKETING_RELATIONSHIP_SHAPES,
        skill_map=MARKETING_SKILL_MAP,
    )
