"""Graqle Cloud Gateway client — API client for cloud-hosted services.

The gateway provides:
1. Graph sync (push/pull deltas to Neptune)
2. Team management (create/invite/manage)
3. Cloud observability (metrics, usage analytics, health)
4. Value-added services (cross-repo graphs, team insights)

This is the upsell path: free users who find value locally are shown
the additional value of cloud features (observability, shared graphs,
team analytics) and prompted to upgrade.
"""

# ── graqle:intelligence ──
# module: graqle.cloud.gateway
# risk: LOW (impact radius: 1 modules)
# consumers: test_gateway
# dependencies: __future__, json, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.cloud.gateway")


# ---------------------------------------------------------------------------
# Cloud service status
# ---------------------------------------------------------------------------

@dataclass
class CloudServiceStatus:
    """Status of cloud-hosted services for display in CLI/Studio."""

    available: bool = False
    plan: str = "free"
    team_id: str = ""
    sync_enabled: bool = False
    observability_enabled: bool = False
    metrics_cloud_enabled: bool = False
    usage_this_month: dict[str, Any] = field(default_factory=dict)
    message: str = ""


# ---------------------------------------------------------------------------
# Value-added cloud features (upsell triggers)
# ---------------------------------------------------------------------------

# These are the cloud features that provide additional value over local-only.
# Each trigger point shows users what they're missing and offers upgrade.

CLOUD_VALUE_PROPS = {
    "observability": {
        "title": "Cloud Observability",
        "description": (
            "Track graph health, query patterns, and knowledge coverage "
            "across your entire team from a single dashboard."
        ),
        "features": [
            "Real-time graph health monitoring",
            "Query pattern analytics (what your team asks most)",
            "Knowledge coverage heatmap (what's well-documented vs gaps)",
            "Stale knowledge alerts (docs that drift from code)",
            "Cross-repo dependency visualization",
        ],
        "min_plan": "team",
        "price": "$29/dev/mo",
    },
    "metrics": {
        "title": "Cloud Metrics & Analytics",
        "description": (
            "See how your knowledge graph saves your team time. "
            "Track token savings, context hit rates, and ROI."
        ),
        "features": [
            "Team-wide token savings dashboard",
            "Per-developer usage analytics",
            "Context hit rate tracking (% of queries answered by graph)",
            "ROI calculator (time saved × developer hourly rate)",
            "Monthly trend reports",
        ],
        "min_plan": "team",
        "price": "$29/dev/mo",
    },
    "shared_graph": {
        "title": "Shared Knowledge Graph",
        "description": (
            "One team member teaches the graph, everyone benefits. "
            "New developers onboard instantly with the team's knowledge."
        ),
        "features": [
            "Push/pull graph sync (like git for knowledge)",
            "Cross-developer knowledge sharing",
            "New dev onboarding in seconds (not weeks)",
            "Persistent graph survives laptop wipes",
            "Cross-repo architecture views",
        ],
        "min_plan": "team",
        "price": "$29/dev/mo",
    },
    "cross_repo": {
        "title": "Cross-Repo Intelligence",
        "description": (
            "Connect microservice repos into a unified architecture view. "
            "See how changes in one repo affect the entire system."
        ),
        "features": [
            "Unified graph across all team repos",
            "Cross-repo impact analysis",
            "Service dependency mapping",
            "API contract verification",
            "Architecture drift detection",
        ],
        "min_plan": "team",
        "price": "$29/dev/mo",
    },
}


# ---------------------------------------------------------------------------
# Upsell trigger detection
# ---------------------------------------------------------------------------

@dataclass
class UpsellTrigger:
    """An upsell opportunity detected from user behavior."""

    trigger_type: str  # signal that triggered the upsell
    feature_key: str   # key in CLOUD_VALUE_PROPS
    message: str       # user-facing message
    upgrade_command: str = "graq billing"

    @property
    def value_prop(self) -> dict[str, Any]:
        return CLOUD_VALUE_PROPS.get(self.feature_key, {})


def check_upsell_triggers(
    current_plan: str,
    node_count: int = 0,
    developer_count: int = 1,
    query_count: int = 0,
    has_multiple_repos: bool = False,
) -> list[UpsellTrigger]:
    """Check if any upsell triggers should fire based on usage patterns.

    This runs locally — no cloud call needed. Triggers are shown as
    helpful suggestions, never as blockers.
    """
    triggers: list[UpsellTrigger] = []

    if current_plan in ("team", "enterprise"):
        return triggers  # Already on paid plan

    # Signal: Graph getting large (approaching free tier limit)
    if node_count > 400 and current_plan == "free":
        triggers.append(UpsellTrigger(
            trigger_type="graph_size",
            feature_key="shared_graph",
            message=(
                f"Your graph has {node_count:,} nodes (free tier: 500). "
                "Upgrade to Pro for 5,000 nodes, or Team for 50,000 + cloud sync."
            ),
        ))
    elif node_count > 4000 and current_plan == "pro":
        triggers.append(UpsellTrigger(
            trigger_type="graph_size",
            feature_key="shared_graph",
            message=(
                f"Your graph has {node_count:,} nodes (Pro tier: 5,000). "
                "Upgrade to Team for 50,000 nodes + cloud sync."
            ),
        ))

    # Signal: Multiple developers detected
    if developer_count >= 2 and current_plan in ("free", "pro"):
        triggers.append(UpsellTrigger(
            trigger_type="multi_developer",
            feature_key="shared_graph",
            message=(
                f"Detected {developer_count} developers. Share your graph "
                "with your team — one teaches, everyone benefits."
            ),
            upgrade_command="graq team create",
        ))

    # Signal: High query volume (user finds value)
    if query_count > 50 and current_plan in ("free", "pro"):
        triggers.append(UpsellTrigger(
            trigger_type="high_usage",
            feature_key="metrics",
            message=(
                f"You've run {query_count} queries — your graph is saving you time! "
                "Cloud metrics can show your team's total ROI."
            ),
        ))

    # Signal: Multiple repos
    if has_multiple_repos and current_plan in ("free", "pro"):
        triggers.append(UpsellTrigger(
            trigger_type="cross_repo",
            feature_key="cross_repo",
            message=(
                "Multiple repos detected. Connect them into a unified "
                "architecture view with Team plan."
            ),
        ))

    return triggers


# ---------------------------------------------------------------------------
# Gateway client (stub — Phase 2+ will implement actual API calls)
# ---------------------------------------------------------------------------

class CloudGateway:
    """Client for Graqle Cloud Gateway API.

    Phase 1 (foundation): All methods return local/stub responses.
    Phase 2+: Methods will call the actual cloud gateway (Lambda + API Gateway).
    """

    def __init__(self, api_key: str = "", cloud_url: str = "https://api.graqle.com") -> None:
        self._api_key = api_key
        self._cloud_url = cloud_url

    @property
    def is_connected(self) -> bool:
        return bool(self._api_key)

    def get_status(self) -> CloudServiceStatus:
        """Get cloud service status."""
        if not self.is_connected:
            return CloudServiceStatus(
                available=False,
                message="Not connected. Run 'graq login' to connect to Graqle Cloud.",
            )
        # Phase 1: Return stub status
        return CloudServiceStatus(
            available=True,
            plan="free",
            message="Cloud gateway connected (foundation mode).",
        )

    def push_delta(self, delta: dict[str, Any], team_id: str) -> dict[str, Any]:
        """Push a delta to the cloud graph.

        Phase 1: Returns success stub. Phase 2+: actual API call.
        """
        if not self.is_connected:
            return {"error": "Not connected to Graqle Cloud", "code": "NOT_CONNECTED"}

        # Phase 1 stub
        logger.info(
            "Cloud sync push (foundation mode): %d nodes, %d edges to team %s",
            len(delta.get("nodes_added", [])) + len(delta.get("nodes_modified", [])),
            len(delta.get("edges_added", [])) + len(delta.get("edges_modified", [])),
            team_id,
        )
        return {
            "status": "queued",
            "message": "Delta queued for sync (cloud gateway not yet deployed)",
            "phase": "foundation",
        }

    def pull_delta(self, team_id: str, since_version: int) -> dict[str, Any]:
        """Pull remote changes since a version.

        Phase 1: Returns empty delta. Phase 2+: actual API call.
        """
        if not self.is_connected:
            return {"error": "Not connected to Graqle Cloud", "code": "NOT_CONNECTED"}

        # Phase 1 stub
        return {
            "status": "ok",
            "delta": {"nodes_added": [], "nodes_modified": [], "nodes_deleted": [],
                       "edges_added": [], "edges_modified": [], "edges_deleted": []},
            "remote_version": since_version,
            "phase": "foundation",
        }

    def register_team(self, team_name: str, owner_email: str) -> dict[str, Any]:
        """Register a new team with the cloud gateway.

        Phase 1: Returns local config. Phase 2+: actual registration.
        """
        if not self.is_connected:
            return {"error": "Not connected to Graqle Cloud", "code": "NOT_CONNECTED"}

        return {
            "status": "registered_locally",
            "team_id": f"team-{team_name.lower().replace(' ', '-')}",
            "message": "Team registered locally (cloud registration available in next release)",
            "phase": "foundation",
        }

    def get_observability(self, team_id: str) -> dict[str, Any]:
        """Get cloud observability data for the team.

        Phase 1: Returns local metrics only. Phase 2+: cloud dashboard data.
        """
        return {
            "status": "local_only",
            "message": (
                "Cloud observability available with Team plan. "
                "Currently showing local metrics only."
            ),
            "local_metrics": True,
            "cloud_metrics": False,
            "phase": "foundation",
        }
