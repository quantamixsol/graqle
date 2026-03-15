"""Financial domain — skills for revenue, pricing, unit economics, reporting.

20 skills organized by financial function:
- Revenue & Pricing (5)
- Unit Economics (4)
- Financial Analysis (4)
- Forecasting & Planning (4)
- Compliance & Reporting (3)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.financial
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


FINANCIAL_CLASS_HIERARCHY: dict[str, str] = {
    "Financial": "Thing",
    "REVENUE_MODEL": "Financial",
    "PRICING_TIER": "Financial",
    "COST_CENTER": "Financial",
    "METRIC": "Financial",
    "FINANCIAL_REPORT": "Financial",
    "BUDGET": "Financial",
    "FORECAST": "Financial",
    "COHORT": "Financial",
    "SUBSCRIPTION": "REVENUE_MODEL",
    "TRANSACTION": "Financial",
    "INVOICE": "TRANSACTION",
    "UNIT_ECONOMICS": "Financial",
}

FINANCIAL_ENTITY_SHAPES: dict[str, dict] = {
    "REVENUE_MODEL": {"required": ["name", "type"], "optional": ["mrr", "arr", "churn_rate", "ltv"]},
    "PRICING_TIER": {"required": ["name", "price"], "optional": ["features", "limits", "billing_cycle"]},
    "METRIC": {"required": ["name", "value"], "optional": ["unit", "period", "trend", "benchmark"]},
    "COHORT": {"required": ["name", "start_date"], "optional": ["size", "retention_rate", "ltv"]},
}

FINANCIAL_RELATIONSHIP_SHAPES: dict[str, dict] = {
    "GENERATES_REVENUE": {"domain": {"PRICING_TIER", "SUBSCRIPTION"}, "range": {"REVENUE_MODEL"}},
    "COSTS": {"domain": {"SERVICE", "COST_CENTER"}, "range": {"BUDGET"}},
    "TRACKS": {"domain": {"FINANCIAL_REPORT"}, "range": {"METRIC"}},
    "BELONGS_TO_COHORT": {"domain": {"TRANSACTION", "SUBSCRIPTION"}, "range": {"COHORT"}},
    "FORECASTS": {"domain": {"FORECAST"}, "range": {"METRIC", "REVENUE_MODEL"}},
}

FINANCIAL_SKILL_MAP: dict[str, list[str]] = {
    "Financial": ["financial_health_check", "metric_interpretation"],
    "REVENUE_MODEL": ["revenue_analysis", "churn_analysis", "ltv_calculation", "pricing_analysis"],
    "PRICING_TIER": ["pricing_analysis", "price_elasticity", "competitive_pricing"],
    "COST_CENTER": ["cost_optimization", "budget_variance"],
    "METRIC": ["metric_interpretation", "trend_detection", "anomaly_flagging"],
    "FINANCIAL_REPORT": ["report_analysis", "variance_analysis"],
    "BUDGET": ["budget_variance", "cost_optimization"],
    "FORECAST": ["forecast_accuracy", "scenario_modeling"],
    "COHORT": ["cohort_analysis", "retention_analysis"],
    "SUBSCRIPTION": ["churn_analysis", "expansion_revenue", "ltv_calculation"],
    "UNIT_ECONOMICS": ["unit_economics_analysis", "cac_payback", "margin_analysis"],
}

FINANCIAL_SKILLS: dict[str, Skill] = {
    # -- Revenue & Pricing --
    "revenue_analysis": Skill(
        name="revenue_analysis",
        description="Analyze revenue streams, MRR/ARR, and growth",
        handler_prompt="Break down revenue: MRR, ARR, net new, expansion, contraction, churn. Calculate growth rate.",
    ),
    "pricing_analysis": Skill(
        name="pricing_analysis",
        description="Analyze pricing strategy and tier structure",
        handler_prompt="Evaluate pricing: value metric, tier structure, feature gating, willingness-to-pay alignment.",
    ),
    "price_elasticity": Skill(
        name="price_elasticity",
        description="Assess price elasticity and optimization",
        handler_prompt="Estimate price sensitivity. Analyze: conversion at price points, competitive pricing, value perception.",
    ),
    "competitive_pricing": Skill(
        name="competitive_pricing",
        description="Compare pricing against competitors",
        handler_prompt="Map competitive pricing: feature parity at each tier, price-to-value ratio, positioning.",
    ),
    "expansion_revenue": Skill(
        name="expansion_revenue",
        description="Analyze expansion revenue opportunities",
        handler_prompt="Identify expansion levers: upsell triggers, usage-based growth, seat expansion, add-on potential.",
    ),
    # -- Unit Economics --
    "unit_economics_analysis": Skill(
        name="unit_economics_analysis",
        description="Analyze unit economics (CAC, LTV, payback)",
        handler_prompt="Calculate: CAC, LTV, LTV:CAC ratio, payback period, gross margin. Flag if LTV:CAC < 3.",
    ),
    "cac_payback": Skill(
        name="cac_payback",
        description="Calculate CAC payback period",
        handler_prompt="Calculate payback: CAC / (monthly gross margin per customer). Benchmark against 12-month target.",
    ),
    "margin_analysis": Skill(
        name="margin_analysis",
        description="Analyze gross and contribution margins",
        handler_prompt="Break down margins: gross margin, contribution margin, COGS components, margin trends.",
    ),
    "ltv_calculation": Skill(
        name="ltv_calculation",
        description="Calculate customer lifetime value",
        handler_prompt="Calculate LTV using: ARPU, gross margin, churn rate. Compare cohort LTVs.",
    ),
    # -- Financial Analysis --
    "financial_health_check": Skill(
        name="financial_health_check",
        description="Overall financial health assessment",
        handler_prompt="Assess: burn rate, runway, revenue growth, margins, cash position, key ratios.",
    ),
    "metric_interpretation": Skill(
        name="metric_interpretation",
        description="Interpret financial metrics in context",
        handler_prompt="Interpret the metric: what does this value mean? Is it good/bad? What benchmark applies?",
    ),
    "variance_analysis": Skill(
        name="variance_analysis",
        description="Analyze variance between actual and planned",
        handler_prompt="Calculate variance: actual vs plan, vs prior period. Identify root causes of significant variances.",
    ),
    "report_analysis": Skill(
        name="report_analysis",
        description="Analyze financial report completeness and accuracy",
        handler_prompt="Review: data completeness, calculation accuracy, trend consistency, anomaly detection.",
    ),
    # -- Forecasting & Planning --
    "forecast_accuracy": Skill(
        name="forecast_accuracy",
        description="Assess forecast accuracy and methodology",
        handler_prompt="Evaluate forecast: methodology, assumptions, confidence intervals, historical accuracy.",
    ),
    "scenario_modeling": Skill(
        name="scenario_modeling",
        description="Model financial scenarios (bull/base/bear)",
        handler_prompt="Model 3 scenarios: bull (best case), base (expected), bear (worst case). Key assumptions for each.",
    ),
    "budget_variance": Skill(
        name="budget_variance",
        description="Analyze budget vs actual variance",
        handler_prompt="Compare budget to actual: line-by-line variance, percentage deviation, trend direction.",
    ),
    "cost_optimization": Skill(
        name="cost_optimization",
        description="Identify cost optimization opportunities",
        handler_prompt="Identify savings: unused resources, right-sizing, vendor negotiation, process efficiency.",
    ),
    # -- Cohort & Retention --
    "cohort_analysis": Skill(
        name="cohort_analysis",
        description="Analyze cohort behavior and retention",
        handler_prompt="Analyze cohort: retention curve, revenue per cohort, activation rate, time-to-value.",
    ),
    "retention_analysis": Skill(
        name="retention_analysis",
        description="Analyze retention and churn patterns",
        handler_prompt="Analyze retention: gross/net churn, logo vs revenue churn, churn reasons, at-risk signals.",
    ),
    "churn_analysis": Skill(
        name="churn_analysis",
        description="Deep-dive into churn causes and prevention",
        handler_prompt="Analyze churn: rate trend, top reasons, cohort differences, prevention strategies, win-back potential.",
    ),
    "trend_detection": Skill(
        name="trend_detection",
        description="Detect trends in financial data",
        handler_prompt="Identify trends: direction, acceleration, seasonality, inflection points. Statistical significance.",
    ),
    "anomaly_flagging": Skill(
        name="anomaly_flagging",
        description="Flag anomalies in financial metrics",
        handler_prompt="Flag values outside 2-sigma: spike/drop, data quality issues, one-time events vs patterns.",
    ),
}


def register_financial_domain(registry: DomainRegistry) -> None:
    """Register the financial domain with a DomainRegistry."""
    registry.register_domain(
        name="financial",
        class_hierarchy=FINANCIAL_CLASS_HIERARCHY,
        entity_shapes=FINANCIAL_ENTITY_SHAPES,
        relationship_shapes=FINANCIAL_RELATIONSHIP_SHAPES,
        skill_map=FINANCIAL_SKILL_MAP,
    )
