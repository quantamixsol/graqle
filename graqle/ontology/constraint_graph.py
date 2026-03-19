# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ──────────────────────────────────────────────────────────────────

"""Constraint Graph — shared constraints between nodes.

Implements CSP-style constraint propagation: when two nodes share
overlapping constraints (detected via embedding similarity), those
constraints are propagated to both nodes before reasoning starts.

Example:
    GDPR Art. 22 "human intervention" and AI Act Art. 14 "human oversight"
    share a constraint around human-in-the-loop requirements. Both nodes
    receive this shared constraint before reasoning, ensuring consistency.
"""

# ── graqle:intelligence ──
# module: graqle.ontology.constraint_graph
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_constraint_graph
# dependencies: __future__, logging, dataclasses, typing, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.ontology.constraint_graph")


@dataclass
class SharedConstraint:
    """A constraint shared between two or more nodes."""

    id: str
    description: str
    node_ids: list[str]
    similarity_score: float
    constraint_type: str = "semantic_overlap"  # semantic_overlap, hierarchical, explicit


@dataclass
class NodeConstraints:
    """All constraints applicable to a specific node."""

    node_id: str
    own_constraints: list[str] = field(default_factory=list)
    propagated_constraints: list[SharedConstraint] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Format constraints for injection into node prompt."""
        parts = []
        if self.own_constraints:
            parts.append("Your domain constraints:")
            for c in self.own_constraints:
                parts.append(f"  - {c}")
        if self.propagated_constraints:
            parts.append("Shared constraints (from related nodes):")
            for sc in self.propagated_constraints:
                other_nodes = [n for n in sc.node_ids if n != self.node_id]
                parts.append(
                    f"  - {sc.description} "
                    f"(shared with: {', '.join(other_nodes)}, "
                    f"similarity: {sc.similarity_score:.2f})"
                )
        return "\n".join(parts) if parts else ""


class ConstraintGraph:
    """Secondary graph of shared constraints between nodes.

    Built at graph load time from node properties + embedding similarity.
    Propagates constraints to connected nodes before reasoning starts.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.7,
        embedding_fn: Any = None,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self._embedding_fn = embedding_fn  # callable: str -> np.ndarray
        self._shared_constraints: list[SharedConstraint] = []
        self._node_constraints: dict[str, NodeConstraints] = {}
        self._stats = {"shared_constraints": 0, "propagations": 0}

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def shared_constraints(self) -> list[SharedConstraint]:
        return list(self._shared_constraints)

    def set_embedding_fn(self, fn: Any) -> None:
        """Set the embedding function (e.g., Titan V2 or sentence-transformers)."""
        self._embedding_fn = fn

    def build(self, graph: Graqle, active_node_ids: list[str] | None = None) -> None:
        """Build the constraint graph from node properties.

        Compares constraint-relevant text from each node pair using embeddings.
        If similarity exceeds threshold, creates a shared constraint.
        """
        nodes_to_check = active_node_ids or list(graph.nodes.keys())
        if len(nodes_to_check) < 2:
            return

        # Extract constraint text for each node
        node_texts: dict[str, str] = {}
        for nid in nodes_to_check:
            node = graph.nodes[nid]
            text = self._extract_constraint_text(node)
            if text:
                node_texts[nid] = text

        if not node_texts or self._embedding_fn is None:
            # No embedding function — extract constraints from properties only
            self._build_from_properties(graph, nodes_to_check)
            return

        # Compute embeddings for all constraint texts
        node_ids = list(node_texts.keys())
        texts = [node_texts[nid] for nid in node_ids]
        embeddings = [self._embedding_fn(t) for t in texts]

        # Find pairs with high similarity
        constraint_id = 0
        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                sim = self._cosine_sim(embeddings[i], embeddings[j])
                if sim >= self.similarity_threshold:
                    sc = SharedConstraint(
                        id=f"sc_{constraint_id}",
                        description=(
                            f"Overlap between {graph.nodes[node_ids[i]].label} "
                            f"and {graph.nodes[node_ids[j]].label}"
                        ),
                        node_ids=[node_ids[i], node_ids[j]],
                        similarity_score=float(sim),
                    )
                    self._shared_constraints.append(sc)
                    constraint_id += 1

        self._stats["shared_constraints"] = len(self._shared_constraints)

        # Build node constraint maps
        self._build_node_constraint_map(graph, nodes_to_check)

    def _build_from_properties(
        self, graph: Graqle, node_ids: list[str]
    ) -> None:
        """Build constraints from node properties without embeddings."""
        for nid in node_ids:
            node = graph.nodes[nid]
            constraints = self._extract_own_constraints(node)
            self._node_constraints[nid] = NodeConstraints(
                node_id=nid, own_constraints=constraints
            )

    def _build_node_constraint_map(
        self, graph: Graqle, node_ids: list[str]
    ) -> None:
        """Build per-node constraint sets from shared constraints."""
        for nid in node_ids:
            node = graph.nodes[nid]
            own = self._extract_own_constraints(node)
            propagated = [
                sc for sc in self._shared_constraints if nid in sc.node_ids
            ]
            self._node_constraints[nid] = NodeConstraints(
                node_id=nid,
                own_constraints=own,
                propagated_constraints=propagated,
            )
            if propagated:
                self._stats["propagations"] += len(propagated)

    def get_constraints(self, node_id: str) -> NodeConstraints:
        """Get all constraints for a node."""
        return self._node_constraints.get(
            node_id, NodeConstraints(node_id=node_id)
        )

    @staticmethod
    def _extract_constraint_text(node: Any) -> str:
        """Extract constraint-relevant text from a node for embedding."""
        parts = [node.label, node.entity_type]
        if node.description:
            parts.append(node.description)
        # Include chunk text summaries
        chunks = node.properties.get("chunks", [])
        for chunk in chunks[:3]:  # top 3 chunks
            if isinstance(chunk, dict):
                parts.append(chunk.get("text", "")[:200])
            elif isinstance(chunk, str):
                parts.append(chunk[:200])
        return " ".join(parts)

    @staticmethod
    def _extract_own_constraints(node: Any) -> list[str]:
        """Extract a node's own constraints from its properties."""
        constraints = []
        props = node.properties

        # Framework constraints
        framework = props.get("framework", "")
        if framework:
            constraints.append(f"Framework: {framework}")

        # Article constraints
        articles = props.get("articles", [])
        if articles:
            if isinstance(articles, list):
                constraints.append(f"Articles: {', '.join(str(a) for a in articles)}")
            else:
                constraints.append(f"Articles: {articles}")

        # Obligation constraints
        obligations = props.get("obligations", [])
        if obligations:
            if isinstance(obligations, list):
                for o in obligations[:3]:
                    constraints.append(f"Obligation: {o}")

        # Entity type constraint
        constraints.append(f"Entity type: {node.entity_type}")

        return constraints

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def reset(self) -> None:
        """Reset for a new query."""
        self._shared_constraints.clear()
        self._node_constraints.clear()
        self._stats = {"shared_constraints": 0, "propagations": 0}
