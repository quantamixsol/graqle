"""OntologyRefiner — refine ontology from activation usage patterns.

Analyzes ActivationMemory data to suggest ontology improvements:
- Underused entity types (candidates for merging)
- Frequently co-activated types (candidates for explicit relationships)
- High-value types that should be promoted (higher activation priority)

Usage:
    from graqle.learning.ontology_refiner import OntologyRefiner
    from graqle.learning.activation_memory import ActivationMemory

    memory = ActivationMemory()
    memory.load()

    refiner = OntologyRefiner(memory, graph)
    suggestions = refiner.analyze()
    for s in suggestions:
        print(f"{s.action}: {s.description}")
"""

# ── graqle:intelligence ──
# module: graqle.learning.ontology_refiner
# risk: LOW (impact radius: 1 modules)
# consumers: test_ontology_refiner
# dependencies: __future__, logging, collections, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.learning.ontology_refiner")


@dataclass
class RefinementSuggestion:
    """A single ontology refinement suggestion."""
    action: str  # merge, split, add_relationship, promote, demote
    entity_types: list[str]
    description: str
    confidence: float  # 0.0-1.0 how confident we are this is useful
    evidence: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"RefinementSuggestion({self.action}: {self.description})"


class OntologyRefiner:
    """Analyzes activation patterns to suggest ontology refinements.

    Works with ActivationMemory to understand which entity types
    are actually used vs. which exist in the schema but never activate.
    """

    def __init__(
        self,
        activation_memory: Any,  # ActivationMemory
        graph: Any,  # Graqle graph
        min_queries: int = 10,
        underuse_threshold: float = 0.05,
        coactivation_threshold: float = 0.7,
    ) -> None:
        self._memory = activation_memory
        self._graph = graph
        self._min_queries = min_queries
        self._underuse_threshold = underuse_threshold
        self._coactivation_threshold = coactivation_threshold

    def analyze(self) -> list[RefinementSuggestion]:
        """Run all analyses and return refinement suggestions.

        Returns empty list if insufficient data (< min_queries).
        """
        if self._memory._total_queries < self._min_queries:
            logger.info(
                "Not enough queries for refinement (%d < %d)",
                self._memory._total_queries, self._min_queries,
            )
            return []

        suggestions: list[RefinementSuggestion] = []

        # Gather entity type stats from the graph
        type_stats = self._compute_type_stats()
        if not type_stats:
            return []

        suggestions.extend(self._find_underused_types(type_stats))
        suggestions.extend(self._find_coactivation_patterns(type_stats))
        suggestions.extend(self._find_high_value_types(type_stats))

        # Sort by confidence descending
        suggestions.sort(key=lambda s: s.confidence, reverse=True)

        logger.info(
            "Ontology refinement: %d suggestions from %d queries",
            len(suggestions), self._memory._total_queries,
        )
        return suggestions

    def _compute_type_stats(self) -> dict[str, dict[str, Any]]:
        """Compute activation statistics per entity type."""
        type_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "node_count": 0,
                "total_activations": 0,
                "useful_activations": 0,
                "node_ids": [],
                "avg_confidence": 0.0,
            }
        )

        # Count nodes per type in the graph
        for nid, node in self._graph.nodes.items():
            etype = node.entity_type.upper() if node.entity_type else "UNKNOWN"
            type_stats[etype]["node_count"] += 1
            type_stats[etype]["node_ids"].append(nid)

        # Aggregate activation memory stats per type
        for nid, record in self._memory._records.items():
            # Find this node's type
            node = self._graph.nodes.get(nid)
            if not node:
                continue
            etype = node.entity_type.upper() if node.entity_type else "UNKNOWN"
            type_stats[etype]["total_activations"] += record.activations
            type_stats[etype]["useful_activations"] += record.useful_activations
            if record.activations > 0:
                type_stats[etype]["avg_confidence"] = (
                    type_stats[etype]["avg_confidence"] + record.avg_confidence
                ) / 2  # running average

        return dict(type_stats)

    def _find_underused_types(
        self, type_stats: dict[str, dict[str, Any]]
    ) -> list[RefinementSuggestion]:
        """Find entity types that are rarely or never activated."""
        suggestions = []
        total_activations = sum(
            s["total_activations"] for s in type_stats.values()
        )
        if total_activations == 0:
            return []

        for etype, stats in type_stats.items():
            if etype in ("UNKNOWN", "KNOWLEDGE", "LESSON"):
                continue  # Skip meta-types

            activation_rate = stats["total_activations"] / max(total_activations, 1)
            if (
                stats["node_count"] >= 2
                and activation_rate < self._underuse_threshold
            ):
                suggestions.append(RefinementSuggestion(
                    action="review",
                    entity_types=[etype],
                    description=(
                        f"Entity type '{etype}' has {stats['node_count']} nodes "
                        f"but only {activation_rate:.1%} of total activations. "
                        f"Consider merging into a parent type or improving descriptions."
                    ),
                    confidence=min(0.9, 1.0 - activation_rate * 10),
                    evidence={
                        "node_count": stats["node_count"],
                        "activation_rate": round(activation_rate, 4),
                        "total_activations": stats["total_activations"],
                    },
                ))

        return suggestions

    def _find_coactivation_patterns(
        self, type_stats: dict[str, dict[str, Any]]
    ) -> list[RefinementSuggestion]:
        """Find entity types that are frequently co-activated."""
        suggestions = []

        # Build co-activation matrix from memory records
        # Group nodes by type, then check if types share query patterns
        type_patterns: dict[str, set[str]] = {}
        for etype, stats in type_stats.items():
            patterns: set[str] = set()
            for nid in stats["node_ids"]:
                record = self._memory._records.get(nid)
                if record:
                    patterns.update(record.query_patterns)
            if patterns:
                type_patterns[etype] = patterns

        # Compare pattern overlap between type pairs
        types = list(type_patterns.keys())
        for i, t1 in enumerate(types):
            for t2 in types[i + 1:]:
                p1 = type_patterns[t1]
                p2 = type_patterns[t2]
                if not p1 or not p2:
                    continue

                overlap = len(p1 & p2) / min(len(p1), len(p2))
                if overlap >= self._coactivation_threshold:
                    suggestions.append(RefinementSuggestion(
                        action="add_relationship",
                        entity_types=[t1, t2],
                        description=(
                            f"Types '{t1}' and '{t2}' share {overlap:.0%} query patterns. "
                            f"Consider adding an explicit relationship between them."
                        ),
                        confidence=min(0.85, overlap),
                        evidence={
                            "pattern_overlap": round(overlap, 3),
                            "shared_patterns": len(p1 & p2),
                            "t1_patterns": len(p1),
                            "t2_patterns": len(p2),
                        },
                    ))

        return suggestions

    def _find_high_value_types(
        self, type_stats: dict[str, dict[str, Any]]
    ) -> list[RefinementSuggestion]:
        """Find entity types with high usefulness that could be promoted."""
        suggestions = []

        for etype, stats in type_stats.items():
            if stats["total_activations"] < 5:
                continue

            usefulness = stats["useful_activations"] / max(stats["total_activations"], 1)
            if usefulness >= 0.8 and stats["avg_confidence"] >= 0.6:
                suggestions.append(RefinementSuggestion(
                    action="promote",
                    entity_types=[etype],
                    description=(
                        f"Entity type '{etype}' has {usefulness:.0%} usefulness rate "
                        f"with {stats['avg_confidence']:.0%} avg confidence. "
                        f"Consider giving it activation priority boost."
                    ),
                    confidence=min(0.8, usefulness * stats["avg_confidence"]),
                    evidence={
                        "usefulness_rate": round(usefulness, 3),
                        "avg_confidence": round(stats["avg_confidence"], 3),
                        "total_activations": stats["total_activations"],
                    },
                ))

        return suggestions

    def get_type_usage_report(self) -> dict[str, Any]:
        """Get a summary report of entity type usage.

        Useful for `graq inspect --ontology` or Studio dashboard.
        """
        type_stats = self._compute_type_stats()
        total_activations = sum(s["total_activations"] for s in type_stats.values())

        report: dict[str, Any] = {
            "total_queries": self._memory._total_queries,
            "total_entity_types": len(type_stats),
            "total_activations": total_activations,
            "types": {},
        }

        for etype, stats in sorted(
            type_stats.items(),
            key=lambda x: x[1]["total_activations"],
            reverse=True,
        ):
            usefulness = (
                stats["useful_activations"] / max(stats["total_activations"], 1)
                if stats["total_activations"] > 0
                else 0.0
            )
            report["types"][etype] = {
                "node_count": stats["node_count"],
                "activations": stats["total_activations"],
                "useful_activations": stats["useful_activations"],
                "usefulness_rate": round(usefulness, 3),
                "activation_share": round(
                    stats["total_activations"] / max(total_activations, 1), 3
                ),
            }

        return report
