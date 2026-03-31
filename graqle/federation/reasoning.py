"""R9 Federated reasoning — multi-agent protocol without KG merge."""

# ── graqle:intelligence ──
# module: graqle.federation.reasoning
# risk: HIGH (impact radius: reasoning pipeline)
# consumers: graq_reason federated mode
# dependencies: asyncio, graqle.federation.*
# constraints: each KG maintains sovereignty, provenance never lost
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from graqle.alignment.r9_config import FederatedActivationConfig
from graqle.federation.types import (
    DomainAgent,
    FederatedReasoningRound,
    ProvenanceNode,
    ProvenanceTag,
)

logger = logging.getLogger("graqle.federation.reasoning")


def _infer_domain(dominant_type: str) -> str:
    """Infer domain from dominant node type."""
    domain_map = {
        "Function": "code",
        "Class": "code",
        "PythonModule": "code",
        "JavaScriptModule": "code",
        "ReactComponent": "code",
        "MCP_TOOL": "mcp",
        "MCP_REQUEST": "mcp",
        "MCP_RESPONSE": "mcp",
        "DOCUMENT": "docs",
        "SECTION": "docs",
        "KNOWLEDGE": "knowledge",
        "Entity": "general",
    }
    return domain_map.get(dominant_type, "general")


def create_domain_agents(
    merged_nodes: List[ProvenanceNode],
) -> List[DomainAgent]:
    """Create domain-specific agents from federated activation results.

    Each KG's activated nodes become the context for a domain agent.
    """
    nodes_by_kg: Dict[str, List[ProvenanceNode]] = {}
    for node in merged_nodes:
        kg_id = node.provenance.home_kg_id
        nodes_by_kg.setdefault(kg_id, []).append(node)

    agents: list[DomainAgent] = []
    for kg_id, kg_nodes in nodes_by_kg.items():
        node_types = [n.node_type for n in kg_nodes]
        dominant_type = max(set(node_types), key=node_types.count) if node_types else "Entity"

        agent = DomainAgent(
            agent_id=f"agent-{kg_id}-{dominant_type.lower()}",
            home_kg_id=kg_id,
            domain=_infer_domain(dominant_type),
            expertise=list(set(node_types)),
            activated_nodes=kg_nodes,
            confidence=0.0,
        )
        agents.append(agent)

    return agents


def synthesize_contributions(
    question: str,
    contributions: List[Dict[str, Any]],
    config: FederatedActivationConfig,
) -> Dict[str, Any]:
    """Merge agent contributions into a single answer.

    If all agents agree: return consensus with averaged confidence.
    If agents disagree: present perspectives with provenance, discount confidence.
    """
    if not contributions:
        return {"answer": "No contributions.", "confidence": 0.0, "consensus": True}

    answers = [c.get("response", "") for c in contributions]
    confidences = [c.get("confidence", 0.0) for c in contributions]

    total_weight = sum(confidences)
    if total_weight > 0:
        weighted_answer = max(contributions, key=lambda c: c.get("confidence", 0.0))
        avg_confidence = total_weight / len(confidences)
    else:
        weighted_answer = contributions[0]
        avg_confidence = 0.0

    # Check for consensus (approximate — first 100 chars)
    unique_answers = set(a[:100] for a in answers if a)
    if len(unique_answers) <= 1:
        return {
            "answer": weighted_answer.get("response", ""),
            "confidence": avg_confidence,
            "consensus": True,
        }

    # Disagreement: present all perspectives
    combined = f"Multiple perspectives from {len(contributions)} agents:\n"
    for c in sorted(contributions, key=lambda x: x.get("confidence", 0.0), reverse=True):
        home_kg = c.get("home_kg", "unknown")
        domain = c.get("domain", "unknown")
        conf = c.get("confidence", 0.0)
        combined += f"\n[{home_kg}:{domain}] (confidence: {conf:.2f}): "
        combined += c.get("response", "")

    return {
        "answer": combined,
        "confidence": avg_confidence * config.disagreement_discount,
        "consensus": False,
    }


def build_reasoning_round(
    question: str,
    agents: List[DomainAgent],
    contributions: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
    round_number: int,
    merged_nodes: List[ProvenanceNode],
) -> FederatedReasoningRound:
    """Build a FederatedReasoningRound from synthesis results."""
    provenance_trail = [n.provenance for n in merged_nodes]

    return FederatedReasoningRound(
        query=question,
        agents=agents,
        round_number=round_number,
        contributions=contributions,
        synthesis=synthesis.get("answer", ""),
        confidence=synthesis.get("confidence", 0.0),
        provenance_trail=provenance_trail,
    )
