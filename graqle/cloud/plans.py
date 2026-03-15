"""Graqle Cloud Plans — plan limits and monetization gating.

Defines tier limits and gates features behind plan boundaries.
The gating is soft (helpful suggestions, not hard blocks for most features)
because we want users to experience value before asking them to pay.

Monetization philosophy:
- Free tier: generous enough to hook developers (500 nodes, unlimited queries)
- Pro tier: for power users who outgrow free ($19/mo, 5,000 nodes)
- Team tier: the real product ($29/dev/mo, 50,000 nodes, cloud sync)
- Enterprise: custom pricing, private deployment

Upsell strategy:
- Users who find value locally are shown cloud benefits naturally
- Never block a user mid-workflow — show upgrade after completion
- Observability, metrics, and shared graphs are the key value-adds
"""

# ── graqle:intelligence ──
# module: graqle.cloud.plans
# risk: LOW (impact radius: 1 modules)
# consumers: test_plans
# dependencies: __future__, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("graqle.cloud.plans")


# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanLimits:
    """Hard limits for each plan tier."""

    max_nodes: int
    max_docs: int          # -1 = unlimited
    max_repos: int         # -1 = unlimited
    max_team_members: int  # -1 = unlimited
    cloud_sync: bool
    cloud_observability: bool
    cloud_metrics: bool
    semantic_linking: bool
    llm_assisted: bool
    cross_repo: bool
    shared_graph: bool
    priority_support: bool
    custom_extractors: bool


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        max_nodes=500,
        max_docs=10,
        max_repos=1,
        max_team_members=1,
        cloud_sync=False,
        cloud_observability=False,
        cloud_metrics=False,
        semantic_linking=False,
        llm_assisted=False,
        cross_repo=False,
        shared_graph=False,
        priority_support=False,
        custom_extractors=False,
    ),
    "pro": PlanLimits(
        max_nodes=5_000,
        max_docs=-1,
        max_repos=1,
        max_team_members=1,
        cloud_sync=False,
        cloud_observability=False,
        cloud_metrics=False,
        semantic_linking=True,
        llm_assisted=True,
        cross_repo=False,
        shared_graph=False,
        priority_support=True,
        custom_extractors=False,
    ),
    "team": PlanLimits(
        max_nodes=50_000,
        max_docs=-1,
        max_repos=-1,
        max_team_members=-1,
        cloud_sync=True,
        cloud_observability=True,
        cloud_metrics=True,
        semantic_linking=True,
        llm_assisted=True,
        cross_repo=True,
        shared_graph=True,
        priority_support=True,
        custom_extractors=True,
    ),
    "enterprise": PlanLimits(
        max_nodes=-1,  # unlimited
        max_docs=-1,
        max_repos=-1,
        max_team_members=-1,
        cloud_sync=True,
        cloud_observability=True,
        cloud_metrics=True,
        semantic_linking=True,
        llm_assisted=True,
        cross_repo=True,
        shared_graph=True,
        priority_support=True,
        custom_extractors=True,
    ),
}

PLAN_PRICING: dict[str, dict[str, Any]] = {
    "free": {
        "price": "$0/forever",
        "billing": "free",
        "tagline": "Everything a solo developer needs",
    },
    "pro": {
        "price": "$19/mo",
        "billing": "monthly",
        "tagline": "Power features for serious developers",
    },
    "team": {
        "price": "$29/dev/mo",
        "billing": "monthly per seat",
        "tagline": "Shared knowledge, cloud observability, team insights",
    },
    "enterprise": {
        "price": "Custom",
        "billing": "annual",
        "tagline": "Private deployment, compliance, SLA",
    },
}


# ---------------------------------------------------------------------------
# Plan checking
# ---------------------------------------------------------------------------

@dataclass
class PlanCheckResult:
    """Result of checking a feature against plan limits."""

    allowed: bool
    current_plan: str
    required_plan: str = ""
    message: str = ""
    upgrade_command: str = ""
    value_prop: str = ""  # Why upgrading helps

    @property
    def upgrade_hint(self) -> str:
        if self.allowed:
            return ""
        pricing = PLAN_PRICING.get(self.required_plan, {})
        return (
            f"\n  Upgrade to {self.required_plan.title()} ({pricing.get('price', '')}) "
            f"to unlock this feature.\n"
            f"  {pricing.get('tagline', '')}\n"
            f"  Run: graq billing"
        )


def get_plan_limits(plan: str) -> PlanLimits:
    """Get limits for a plan tier."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def check_node_limit(plan: str, current_nodes: int) -> PlanCheckResult:
    """Check if adding more nodes is allowed under the current plan."""
    limits = get_plan_limits(plan)
    if limits.max_nodes == -1 or current_nodes < limits.max_nodes:
        return PlanCheckResult(allowed=True, current_plan=plan)

    # Determine upgrade target
    if plan == "free":
        required = "pro"
        value = "Pro supports 5,000 nodes — 10x your current limit."
    elif plan == "pro":
        required = "team"
        value = "Team supports 50,000 nodes + cloud sync for your whole team."
    else:
        required = "enterprise"
        value = "Enterprise has unlimited nodes."

    return PlanCheckResult(
        allowed=False,
        current_plan=plan,
        required_plan=required,
        message=f"Graph has {current_nodes:,} nodes (limit: {limits.max_nodes:,} on {plan.title()} plan).",
        upgrade_command="graq billing",
        value_prop=value,
    )


def check_doc_limit(plan: str, current_docs: int) -> PlanCheckResult:
    """Check if scanning more documents is allowed."""
    limits = get_plan_limits(plan)
    if limits.max_docs == -1 or current_docs < limits.max_docs:
        return PlanCheckResult(allowed=True, current_plan=plan)

    return PlanCheckResult(
        allowed=False,
        current_plan=plan,
        required_plan="pro",
        message=(
            f"Scanned {current_docs} documents (free tier limit: {limits.max_docs}). "
            f"{current_docs - limits.max_docs} documents not scanned."
        ),
        upgrade_command="graq billing",
        value_prop="Pro plan includes unlimited document scanning.",
    )


def check_feature(plan: str, feature: str) -> PlanCheckResult:
    """Check if a specific feature is available on the current plan."""
    limits = get_plan_limits(plan)

    feature_checks: dict[str, tuple[bool, str, str]] = {
        "cloud_sync": (limits.cloud_sync, "team", "Cloud sync lets your team share one knowledge graph."),
        "cloud_observability": (limits.cloud_observability, "team", "Track graph health and usage across your team."),
        "cloud_metrics": (limits.cloud_metrics, "team", "See ROI: token savings, time saved, context hit rates."),
        "semantic_linking": (limits.semantic_linking, "pro", "Semantic linking finds connections humans miss."),
        "llm_assisted": (limits.llm_assisted, "pro", "LLM-assisted analysis extracts deeper relationships."),
        "cross_repo": (limits.cross_repo, "team", "Connect microservice repos into one architecture view."),
        "shared_graph": (limits.shared_graph, "team", "One dev teaches, everyone benefits. Instant onboarding."),
        "custom_extractors": (limits.custom_extractors, "team", "Build custom extractors for your domain."),
    }

    check = feature_checks.get(feature)
    if check is None:
        return PlanCheckResult(allowed=True, current_plan=plan)

    available, required, value = check
    if available:
        return PlanCheckResult(allowed=True, current_plan=plan)

    return PlanCheckResult(
        allowed=False,
        current_plan=plan,
        required_plan=required,
        message=f"{feature.replace('_', ' ').title()} requires {required.title()} plan.",
        upgrade_command="graq billing",
        value_prop=value,
    )


def check_team_member_limit(plan: str, current_members: int) -> PlanCheckResult:
    """Check if adding more team members is allowed."""
    limits = get_plan_limits(plan)
    if limits.max_team_members == -1 or current_members < limits.max_team_members:
        return PlanCheckResult(allowed=True, current_plan=plan)

    return PlanCheckResult(
        allowed=False,
        current_plan=plan,
        required_plan="team",
        message=f"Team features require the Team plan ({PLAN_PRICING['team']['price']}).",
        upgrade_command="graq billing",
        value_prop="Share your knowledge graph with your entire team.",
    )


# ---------------------------------------------------------------------------
# Usage tracking (local — for upsell trigger detection)
# ---------------------------------------------------------------------------

def get_usage_summary(plan: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Generate a usage summary with upgrade recommendations.

    This is shown in `graq billing` and `graq metrics` to help users
    understand the value they're getting and what they'd gain by upgrading.
    """
    limits = get_plan_limits(plan)
    node_count = stats.get("node_count", 0)
    query_count = stats.get("query_count", 0)
    doc_count = stats.get("doc_count", 0)

    summary: dict[str, Any] = {
        "plan": plan,
        "pricing": PLAN_PRICING.get(plan, {}),
        "usage": {
            "nodes": {
                "current": node_count,
                "limit": limits.max_nodes,
                "percent": (node_count / limits.max_nodes * 100)
                           if limits.max_nodes > 0 else 0,
            },
            "documents": {
                "current": doc_count,
                "limit": limits.max_docs,
            },
            "queries": {
                "current": query_count,
                "limit": -1,  # unlimited on all plans
            },
        },
        "value_delivered": {},
        "upgrade_benefits": [],
    }

    # Calculate value delivered
    if query_count > 0:
        # Rough estimate: each graph query saves ~30 seconds of file searching
        time_saved_hours = query_count * 30 / 3600
        # Rough estimate: each query saves ~500 tokens vs brute-force
        tokens_saved = query_count * 500
        summary["value_delivered"] = {
            "estimated_time_saved_hours": round(time_saved_hours, 1),
            "estimated_tokens_saved": tokens_saved,
            "queries_answered_by_graph": query_count,
        }

    # Upgrade benefits based on current usage
    if plan == "free":
        if node_count > 300:
            summary["upgrade_benefits"].append({
                "plan": "pro",
                "reason": f"Your graph ({node_count} nodes) is approaching the 500-node free limit.",
                "benefit": "Pro gives you 5,000 nodes + semantic linking.",
            })
        if query_count > 20:
            summary["upgrade_benefits"].append({
                "plan": "team",
                "reason": f"You've run {query_count} queries — your graph is clearly valuable.",
                "benefit": "Team adds cloud observability so you can see ROI across your team.",
            })
    elif plan == "pro":
        if node_count > 3000:
            summary["upgrade_benefits"].append({
                "plan": "team",
                "reason": f"Your graph ({node_count} nodes) is approaching the 5,000-node Pro limit.",
                "benefit": "Team gives you 50,000 nodes + cloud sync + observability.",
            })

    return summary
