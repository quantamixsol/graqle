"""Auto-enrich the Graqle knowledge graph with SCORCH findings."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("graqle.scorch.kg")


def enrich_graph(graph_data: dict[str, Any], report: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Add SCORCH findings as FRICTION nodes + edges to the KG.

    Args:
        graph_data: The raw graph dict (with "nodes" and "links" keys).
        report: The SCORCH audit report dict.

    Returns:
        Tuple of (updated graph_data, number of nodes added).
    """
    from graqle.plugins.scorch.archetypes import ARCHETYPE_BY_ID

    added = 0
    now = datetime.now(timezone.utc).isoformat()
    issues = report.get("issues", [])

    for i, issue in enumerate(issues):
        if issue.get("severity") not in ("critical", "major"):
            continue  # Only persist critical/major findings

        node_id = f"SCORCH_FINDING_{now[:10]}_{i:03d}"

        archetype = ARCHETYPE_BY_ID.get(issue.get("archetype"))
        node = {
            "id": node_id,
            "label": f"Friction: {issue.get('description', '')[:60]}",
            "entity_type": "FRICTION_FINDING",
            "description": issue.get("description", ""),
            "properties": {
                "severity": issue["severity"],
                "category": issue.get("category", "unknown"),
                "viewport": issue.get("viewport", ""),
                "page": issue.get("page", ""),
                "recommendation": issue.get("recommendation", ""),
                "archetype_id": issue.get("archetype"),
                "archetype_name": archetype.name if archetype else None,
                "detected_at": now,
                "source": "scorch_audit",
            },
        }

        graph_data.setdefault("nodes", []).append(node)
        added += 1

    if added > 0:
        logger.info("Enriched KG with %d friction findings", added)

    return graph_data, added
