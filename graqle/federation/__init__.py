"""R9 Federated Activation — multi-KG querying with provenance."""

from graqle.federation.types import (
    DomainAgent,
    FederatedQuery,
    FederatedReasoningRound,
    KGQueryResult,
    KGRegistration,
    KGStatus,
    ProvenanceNode,
    ProvenanceTag,
)

__all__ = [
    "KGStatus",
    "KGRegistration",
    "ProvenanceTag",
    "ProvenanceNode",
    "FederatedQuery",
    "KGQueryResult",
    "DomainAgent",
    "FederatedReasoningRound",
    "KGRegistry",
    "FederationCoordinator",
    "route_federated_query",
]


def __getattr__(name: str):  # noqa: ANN001
    """Lazy imports for heavier modules."""
    if name == "KGRegistry":
        from graqle.federation.registry import KGRegistry
        return KGRegistry
    if name == "FederationCoordinator":
        from graqle.federation.merger import FederationCoordinator
        return FederationCoordinator
    if name == "route_federated_query":
        from graqle.federation.activator import route_federated_query
        return route_federated_query
    raise AttributeError(f"module 'graqle.federation' has no attribute {name!r}")
