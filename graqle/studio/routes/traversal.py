"""Graqle Studio — Neo4j-native traversal API routes.

Exposes Cypher-native graph traversal operations for the Studio frontend:
- Shortest path between nodes
- Hub detection
- Node context with chunks
- Impact analysis (fast path)

All routes return in <50ms when Neo4j is available.
Falls back gracefully to Python-based operations when Neo4j is not configured.
"""

# ── graqle:intelligence ──
# module: graqle.studio.routes.traversal
# risk: LOW (impact radius: 2 modules)
# consumers: test_neo4j_traversal, test_traversal_routes
# dependencies: logging, typing, fastapi
# constraints: none
# ── /graqle:intelligence ──

import logging
from typing import Any

from fastapi import APIRouter, Query, Request

logger = logging.getLogger("graqle.studio.traversal")

router = APIRouter(tags=["traversal"])


def _get_traversal(request: Request) -> Any:
    """Get Neo4j traversal engine from app state."""
    state = getattr(request.app.state, "studio_state", {})
    return state.get("neo4j_traversal")


@router.get("/shortest-path")
async def shortest_path(
    request: Request,
    source: str = Query(..., description="Source node ID"),
    target: str = Query(..., description="Target node ID"),
    max_hops: int = Query(6, ge=1, le=10),
):
    """Find shortest path between two nodes via Neo4j native algorithm."""
    traversal = _get_traversal(request)
    if traversal is None:
        return {"error": "Neo4j traversal not available (using JSON backend)"}

    return traversal.shortest_path(source, target, max_hops=max_hops)


@router.get("/hubs")
async def hub_nodes(
    request: Request,
    top_k: int = Query(20, ge=1, le=100),
    min_degree: int = Query(5, ge=1),
):
    """Get most connected hub nodes by degree centrality."""
    traversal = _get_traversal(request)
    if traversal is None:
        return {"error": "Neo4j traversal not available"}

    return traversal.hub_nodes(top_k=top_k, min_degree=min_degree)


@router.get("/context/{node_id:path}")
async def node_context(
    request: Request,
    node_id: str,
    include_chunks: bool = Query(False),
    max_neighbors: int = Query(30, ge=1, le=100),
):
    """Full context for a node: properties, neighbors, optional chunks."""
    traversal = _get_traversal(request)
    if traversal is None:
        return {"error": "Neo4j traversal not available"}

    return traversal.node_context(
        node_id,
        max_neighbors=max_neighbors,
        include_chunks=include_chunks,
    )


@router.get("/impact/{node_id:path}")
async def impact_analysis(
    request: Request,
    node_id: str,
    max_depth: int = Query(3, ge=1, le=5),
    change_type: str = Query("modify", pattern="^(modify|remove|deploy|add)$"),
):
    """Neo4j-native impact analysis — Cypher BFS traversal."""
    traversal = _get_traversal(request)
    if traversal is None:
        return {"error": "Neo4j traversal not available"}

    results = traversal.impact_bfs(
        node_id,
        max_depth=max_depth,
        change_type=change_type,
    )

    risk_scores = {"remove": 3, "deploy": 2, "modify": 1, "add": 0.5}
    base_risk = risk_scores.get(change_type, 1)
    total_affected = len(results)
    overall_risk = "low"
    if total_affected > 5 or base_risk >= 3:
        overall_risk = "high"
    elif total_affected > 2 or base_risk >= 2:
        overall_risk = "medium"

    return {
        "node_id": node_id,
        "change_type": change_type,
        "overall_risk": overall_risk,
        "affected_count": total_affected,
        "impact_tree": results,
    }


@router.post("/materialize")
async def materialize_neighborhoods(
    request: Request,
    max_hops: int = Query(2, ge=1, le=3),
):
    """Pre-compute N-hop neighborhoods for instant context serving.

    After this, node context lookups are a single property read (~0.5ms).
    """
    traversal = _get_traversal(request)
    if traversal is None:
        return {"error": "Neo4j traversal not available"}

    count = traversal.materialize_neighborhoods(max_hops=max_hops)
    return {
        "status": "materialized",
        "hops": max_hops,
        "nodes_with_neighborhoods": count,
    }
