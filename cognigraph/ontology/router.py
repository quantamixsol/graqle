"""Ontology Router — filters message recipients by relationship shapes.

Messages are routed only along ontologically valid paths.
GOV_REQUIREMENT can send to GOV_CONTROL, GOV_ENFORCEMENT, GOV_EVIDENCE
but NOT to unrelated DORA nodes unless they share a valid relationship.

Falls back to graph neighbors if no ontology is loaded (backward compatible).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from cognigraph.core.graph import CogniGraph
    from cognigraph.ontology.domain_registry import DomainRegistry

logger = logging.getLogger("cognigraph.ontology.router")


class OntologyRouter:
    """Routes messages between nodes based on relationship shapes.

    Uses RELATIONSHIP_SHAPES from the domain ontology to determine
    which entity types can communicate via which relationship types.
    """

    def __init__(self, registry: Optional[DomainRegistry] = None) -> None:
        self._registry = registry
        self._stats = {"routed": 0, "filtered": 0, "fallback": 0}

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def set_registry(self, registry: DomainRegistry) -> None:
        """Set the domain registry for ontology-based routing."""
        self._registry = registry

    def get_valid_recipients(
        self,
        graph: CogniGraph,
        source_node_id: str,
        active_node_ids: List[str] | None = None,
    ) -> List[str]:
        """Get valid message recipients for a source node.

        Filters graph neighbors by relationship shape constraints.
        Falls back to all neighbors if no ontology is loaded.
        """
        if self._registry is None:
            self._stats["fallback"] += 1
            return graph.get_neighbors(source_node_id)

        source_node = graph.nodes.get(source_node_id)
        if source_node is None:
            return []

        source_type = source_node.entity_type
        all_neighbors = graph.get_neighbors(source_node_id)

        # Filter to active nodes if specified
        if active_node_ids is not None:
            all_neighbors = [n for n in all_neighbors if n in active_node_ids]

        # Get all relationship shapes across registered domains
        rel_shapes = self._registry.get_all_relationship_shapes()

        # For each neighbor, check if there's a valid relationship path
        valid_recipients: List[str] = []
        for neighbor_id in all_neighbors:
            neighbor_node = graph.nodes.get(neighbor_id)
            if neighbor_node is None:
                continue

            target_type = neighbor_node.entity_type

            # Check if any edge between source and neighbor has a valid shape
            edges = graph.get_edges_between(source_node_id, neighbor_id)
            if not edges:
                # No edge — allow if they share the same branch
                if self._same_branch(source_type, target_type):
                    valid_recipients.append(neighbor_id)
                    self._stats["routed"] += 1
                else:
                    self._stats["filtered"] += 1
                continue

            # Check each edge's relationship type against shapes
            edge_valid = False
            for edge in edges:
                rel_type = edge.relationship.upper()
                shape = rel_shapes.get(rel_type)

                if shape is None:
                    # Unknown relationship — allow (conservative)
                    edge_valid = True
                    break

                # Check domain constraint
                domain = shape.get("domain")
                if domain is not None:
                    source_valid = source_type in domain or any(
                        self._registry.upper_ontology.is_subtype_of(source_type, d)
                        for d in domain
                    )
                    if not source_valid:
                        continue

                # Check range constraint
                range_types = shape.get("range")
                if range_types is not None:
                    target_valid = target_type in range_types or any(
                        self._registry.upper_ontology.is_subtype_of(target_type, r)
                        for r in range_types
                    )
                    if not target_valid:
                        continue

                edge_valid = True
                break

            if edge_valid:
                valid_recipients.append(neighbor_id)
                self._stats["routed"] += 1
            else:
                self._stats["filtered"] += 1
                logger.debug(
                    f"Filtered: {source_node.label} ({source_type}) "
                    f"-> {neighbor_node.label} ({target_type})"
                )

        return valid_recipients

    def _same_branch(self, type_a: str, type_b: str) -> bool:
        """Check if two types share the same upper ontology branch."""
        if self._registry is None:
            return True
        upper = self._registry.upper_ontology
        branch_a = upper.get_branch(type_a)
        branch_b = upper.get_branch(type_b)
        return branch_a == branch_b

    def reset_stats(self) -> None:
        self._stats = {"routed": 0, "filtered": 0, "fallback": 0}
