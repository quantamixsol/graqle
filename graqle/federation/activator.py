"""R9 Federated Activator — async fan-out query routing with quorum."""

# ── graqle:intelligence ──
# module: graqle.federation.activator
# risk: HIGH (impact radius: federation query pipeline)
# consumers: federation.reasoning
# dependencies: asyncio, time, graqle.federation.types, graqle.federation.registry, graqle.federation.merger
# constraints: per-KG timeout, quorum enforcement, R10 penalty applied
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from graqle.alignment.r9_config import FederatedActivationConfig
from graqle.federation.merger import FederationCoordinator
from graqle.federation.registry import KGRegistry
from graqle.federation.types import (
    FederatedQuery,
    KGQueryResult,
    KGRegistration,
    ProvenanceNode,
    ProvenanceTag,
)

logger = logging.getLogger("graqle.federation.activator")


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


async def query_single_kg(
    kg: KGRegistration,
    query: FederatedQuery,
    activation_fn: Optional[Callable] = None,
) -> KGQueryResult:
    """Query a single KG with timeout protection.

    Parameters
    ----------
    kg:
        The KG registration to query.
    query:
        The federated query with embedding and parameters.
    activation_fn:
        Optional callable(kg_id, query_embedding, top_k) -> List[(node, score)].
        If None, returns empty results (stub for testing).
    """
    start_time = time.monotonic()

    try:
        if activation_fn is None:
            # Stub: no activation engine available
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return KGQueryResult(
                kg_id=kg.kg_id, nodes=[], response_ms=elapsed_ms,
                status="success", error_message="No activation engine configured",
            )

        raw_results = await asyncio.wait_for(
            activation_fn(kg.kg_id, query.query_embedding, query.top_k_per_kg),
            timeout=query.timeout_ms / 1000.0,
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000

        # Attach provenance to each result
        provenance_nodes: list[ProvenanceNode] = []
        for rank, (node_data, score) in enumerate(raw_results):
            prov = ProvenanceTag(
                home_kg_id=kg.kg_id,
                activation_score=float(score),
                activation_rank=rank,
                query_timestamp=_now_iso8601(),
                response_ms=elapsed_ms,
                embedding_model=kg.embedding_model,
            )
            provenance_nodes.append(ProvenanceNode(
                node_id=node_data.get("id", f"{kg.kg_id}_{rank}"),
                node_type=node_data.get("type", "UNKNOWN"),
                language=node_data.get("language", kg.language),
                description=node_data.get("description", ""),
                chunk_text=node_data.get("chunk_text", ""),
                embedding=node_data.get("embedding"),
                properties=node_data.get("properties", {}),
                provenance=prov,
            ))

        return KGQueryResult(
            kg_id=kg.kg_id,
            nodes=provenance_nodes,
            response_ms=elapsed_ms,
            status="success",
        )

    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.warning("KG %s timed out after %.0fms", kg.kg_id, elapsed_ms)
        return KGQueryResult(
            kg_id=kg.kg_id, nodes=[], response_ms=elapsed_ms,
            status="timeout",
            error_message=f"KG {kg.kg_id} timed out after {query.timeout_ms}ms",
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.error("KG %s query failed: %s", kg.kg_id, e)
        return KGQueryResult(
            kg_id=kg.kg_id, nodes=[], response_ms=elapsed_ms,
            status="error", error_message=str(e),
        )


async def route_federated_query(
    query: FederatedQuery,
    registry: KGRegistry,
    config: FederatedActivationConfig,
    activation_fn: Optional[Callable] = None,
) -> Tuple[List[ProvenanceNode], Dict[str, Any]]:
    """Broadcast query to all active KGs, collect results, merge with provenance.

    Returns (merged_nodes, metadata).
    """
    # Step 1: Get active KGs
    active_kgs = registry.get_active()
    if not active_kgs:
        return [], {"error": "No active KGs in federation"}

    # Step 2+3: Broadcast and collect
    tasks = [query_single_kg(kg, query, activation_fn) for kg in active_kgs]
    kg_results: List[KGQueryResult] = await asyncio.gather(*tasks)

    # Step 4: Check quorum
    successful = [r for r in kg_results if r.status == "success"]
    timed_out = [r for r in kg_results if r.status == "timeout"]
    errored = [r for r in kg_results if r.status == "error"]

    if len(successful) < query.min_quorum:
        return [], {
            "error": f"Quorum not met: {len(successful)} responded, "
                     f"{query.min_quorum} required",
            "successful": [r.kg_id for r in successful],
            "timed_out": [r.kg_id for r in timed_out],
            "errored": [r.kg_id for r in errored],
        }

    # Step 5: Apply R10 alignment penalty to cross-KG scores
    for result in successful:
        for node in result.nodes:
            if result.kg_id != query.requesting_kg_id:
                node.normalized_score = (
                    node.provenance.activation_score * config.unaligned_penalty
                )
            else:
                node.normalized_score = node.provenance.activation_score

    # Step 6: Merge via FederationCoordinator
    coordinator = FederationCoordinator(config)
    all_nodes: list[ProvenanceNode] = []
    for result in successful:
        all_nodes.extend(result.nodes)

    merged = coordinator.merge(all_nodes, config)

    # Step 7: Build metadata
    metadata: Dict[str, Any] = {
        "kgs_queried": len(active_kgs),
        "kgs_responded": len(successful),
        "kgs_timed_out": len(timed_out),
        "kgs_errored": len(errored),
        "total_candidates": len(all_nodes),
        "merged_results": len(merged),
        "per_kg_timing": {r.kg_id: r.response_ms for r in kg_results},
        "quorum_met": True,
        "alignment_penalty": config.unaligned_penalty,
    }

    # Update registry heartbeats
    for result in successful:
        registry.heartbeat(result.kg_id, result.response_ms)
    for result in timed_out:
        registry.mark_degraded(result.kg_id, "timeout")

    return merged, metadata
