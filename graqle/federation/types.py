"""R9 Federated Activation data types.

Defines the core data structures for federated knowledge graph
activation, provenance tracking, and multi-agent reasoning rounds.
"""

# ── graqle:intelligence ──
# module: graqle.federation.types
# risk: MEDIUM (impact radius: federation subsystem)
# consumers: federation.registry, federation.activator, federation.merger
# dependencies: __future__, dataclasses, enum, typing, numpy
# constraints: internal-pattern-B (no hardcoded thresholds), ProvenanceTag frozen=True
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np


class KGStatus(Enum):
    """Operational status of a federated knowledge graph."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    DRAINING = "draining"


@dataclass
class KGRegistration:
    """Registration record for a knowledge graph in the federation."""

    kg_id: str
    display_name: str
    language: str  # "python" | "typescript"
    node_count: int
    edge_count: int
    embedding_model: str  # e.g. "all-MiniLM-L6-v2"
    embedding_dim: int  # e.g. 384
    endpoint: str  # local path or URL
    status: KGStatus = KGStatus.ACTIVE
    authority_weight: float = 1.0
    last_heartbeat: Optional[str] = None  # ISO-8601
    avg_response_ms: float = 0.0
    error_rate: float = 0.0
    domains: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "kg_id": self.kg_id,
            "display_name": self.display_name,
            "language": self.language,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "endpoint": self.endpoint,
            "status": self.status.value,
            "authority_weight": self.authority_weight,
            "last_heartbeat": self.last_heartbeat,
            "avg_response_ms": self.avg_response_ms,
            "error_rate": self.error_rate,
            "domains": list(self.domains),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class ProvenanceTag:
    """Immutable provenance tag attached to every federated node.

    ``frozen=True`` guarantees that provenance cannot be mutated after
    creation, preserving audit integrity across federation boundaries.
    """

    home_kg_id: str
    activation_score: float  # RAW score from source KG
    activation_rank: int
    query_timestamp: str  # ISO-8601
    response_ms: float
    embedding_model: str


@dataclass
class ProvenanceNode:
    """A node returned from a federated KG query, with full provenance."""

    node_id: str
    node_type: str
    language: str
    description: str
    chunk_text: str
    embedding: Optional[np.ndarray]
    properties: Dict[str, Any]
    provenance: ProvenanceTag  # immutable
    normalized_score: float = 0.0
    federation_rank: int = 0
    is_duplicate: bool = False
    conflict_flag: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "language": self.language,
            "description": self.description,
            "chunk_text": self.chunk_text,
            "embedding": self.embedding.tolist() if self.embedding is not None else None,
            "properties": dict(self.properties),
            "provenance": {
                "home_kg_id": self.provenance.home_kg_id,
                "activation_score": self.provenance.activation_score,
                "activation_rank": self.provenance.activation_rank,
                "query_timestamp": self.provenance.query_timestamp,
                "response_ms": self.provenance.response_ms,
                "embedding_model": self.provenance.embedding_model,
            },
            "normalized_score": self.normalized_score,
            "federation_rank": self.federation_rank,
            "is_duplicate": self.is_duplicate,
            "conflict_flag": self.conflict_flag,
        }


@dataclass
class FederatedQuery:
    """A query dispatched across the federation."""

    query_text: str
    query_embedding: np.ndarray  # e.g. 384-dim
    top_k_per_kg: int
    timeout_ms: int
    min_quorum: int
    unaligned_penalty: float
    requesting_kg_id: Optional[str] = None


@dataclass
class KGQueryResult:
    """Result returned by a single KG in response to a federated query."""

    kg_id: str
    nodes: List[ProvenanceNode]
    response_ms: float
    status: str  # "success" | "timeout" | "error"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "kg_id": self.kg_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "response_ms": self.response_ms,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class DomainAgent:
    """A domain-specialist agent activated during federated reasoning."""

    agent_id: str
    home_kg_id: str
    domain: str
    expertise: List[str]
    activated_nodes: List[ProvenanceNode]
    confidence: float


@dataclass
class FederatedReasoningRound:
    """A single round of multi-agent federated reasoning."""

    query: str
    agents: List[DomainAgent]
    round_number: int
    contributions: List[Dict[str, Any]]
    synthesis: str
    confidence: float
    provenance_trail: List[ProvenanceTag]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "query": self.query,
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "home_kg_id": a.home_kg_id,
                    "domain": a.domain,
                    "expertise": list(a.expertise),
                    "activated_nodes": [n.to_dict() for n in a.activated_nodes],
                    "confidence": a.confidence,
                }
                for a in self.agents
            ],
            "round_number": self.round_number,
            "contributions": list(self.contributions),
            "synthesis": self.synthesis,
            "confidence": self.confidence,
            "provenance_trail": [
                {
                    "home_kg_id": p.home_kg_id,
                    "activation_score": p.activation_score,
                    "activation_rank": p.activation_rank,
                    "query_timestamp": p.query_timestamp,
                    "response_ms": p.response_ms,
                    "embedding_model": p.embedding_model,
                }
                for p in self.provenance_trail
            ],
        }
