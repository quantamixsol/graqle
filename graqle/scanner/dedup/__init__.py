"""Cross-source deduplication engine.

Provides 3-layer deduplication:
  1. Canonical IDs — deterministic hashing prevents re-scan duplicates
  2. Entity Unification — name variant registry matches across sources
  3. Concept Clustering — optional embedding-based semantic matching

Usage::

    dedup = DedupOrchestrator(graph_nodes, graph_edges)
    report = dedup.run()
"""

# ── graqle:intelligence ──
# module: graqle.scanner.dedup.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, logging, dataclasses, typing, canonical +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from graqle.scanner.dedup.canonical import compute_canonical_id
from graqle.scanner.dedup.merge import MergeDecision, MergeEngine
from graqle.scanner.dedup.unifier import EntityUnifier

logger = logging.getLogger("graqle.scanner.dedup")


@dataclass
class DedupReport:
    """Result of a deduplication pass."""

    canonical_merges: int = 0
    unifier_merges: int = 0
    cluster_merges: int = 0
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    total_nodes_before: int = 0
    total_nodes_after: int = 0
    duration_seconds: float = 0.0


@dataclass
class DedupOptions:
    """Configuration for deduplication."""

    canonical_ids: bool = True
    entity_matching: bool = True
    case_insensitive: bool = True
    naming_conventions: bool = True
    fuzzy_max_distance: int = 2
    auto_merge_above: float = 0.90
    review_between: tuple[float, float] = (0.70, 0.90)
    reject_below: float = 0.70
    source_priority: list[str] = field(default_factory=lambda: [
        "code", "api_spec", "json_config", "user_knowledge", "document",
        "audit",  # GOVERNANCE_BYPASS, TOOL_EXECUTION — lowest priority, never win merge
    ])


class DedupOrchestrator:
    """Orchestrates the deduplication pipeline.

    Parameters
    ----------
    graph_nodes:
        Dict of graph nodes ``{node_id: node_dict}`` (mutated in-place).
    graph_edges:
        Dict of graph edges ``{edge_id: edge_dict}`` (mutated in-place).
    options:
        Dedup configuration.
    """

    def __init__(
        self,
        graph_nodes: dict[str, dict[str, Any]],
        graph_edges: dict[str, dict[str, Any]],
        options: DedupOptions | None = None,
    ) -> None:
        self._nodes = graph_nodes
        self._edges = graph_edges
        self._opts = options or DedupOptions()
        self._unifier = EntityUnifier(
            case_insensitive=self._opts.case_insensitive,
            naming_conventions=self._opts.naming_conventions,
        )
        self._merge = MergeEngine(
            source_priority=self._opts.source_priority,
        )

    def run(self) -> DedupReport:
        """Execute the deduplication pipeline."""
        import time

        t0 = time.time()
        report = DedupReport(total_nodes_before=len(self._nodes))

        # Layer 1: Canonical IDs
        if self._opts.canonical_ids:
            report.canonical_merges = self._apply_canonical()

        # Layer 2: Entity Unification
        if self._opts.entity_matching:
            report.unifier_merges = self._apply_unification()

        # Layer 3: Contradiction detection (always runs after merges)
        from graqle.scanner.dedup.contradictions import detect_contradictions
        report.contradictions = detect_contradictions(self._nodes)

        report.total_nodes_after = len(self._nodes)
        report.duration_seconds = time.time() - t0
        return report

    def _apply_canonical(self) -> int:
        """Merge nodes with the same canonical ID."""
        canonical_map: dict[str, list[str]] = {}

        for nid, node in list(self._nodes.items()):
            cid = compute_canonical_id(node)
            if cid:
                canonical_map.setdefault(cid, []).append(nid)

        merges = 0
        for cid, node_ids in canonical_map.items():
            if len(node_ids) <= 1:
                continue
            # Keep the first, merge the rest into it
            primary = node_ids[0]
            for secondary in node_ids[1:]:
                decision = self._merge.merge(
                    self._nodes[primary],
                    self._nodes[secondary],
                    confidence=1.0,
                    method="canonical_id",
                )
                if decision.accepted:
                    self._apply_merge(primary, secondary, decision)
                    merges += 1

        return merges

    def _apply_unification(self) -> int:
        """Merge nodes that match via entity name unification."""
        # Register all nodes
        for nid, node in self._nodes.items():
            source_type = self._classify_source(node)
            self._unifier.register(nid, node.get("label", ""), source_type)

        # Find matches
        matches = self._unifier.find_matches(self._nodes)
        merges = 0

        for primary_id, secondary_id, confidence in matches:
            if primary_id not in self._nodes or secondary_id not in self._nodes:
                continue
            if confidence < self._opts.reject_below:
                continue

            if confidence >= self._opts.auto_merge_above:
                decision = self._merge.merge(
                    self._nodes[primary_id],
                    self._nodes[secondary_id],
                    confidence=confidence,
                    method="entity_unification",
                )
                if decision.accepted:
                    self._apply_merge(primary_id, secondary_id, decision)
                    merges += 1

        return merges

    def _apply_merge(
        self, primary_id: str, secondary_id: str, decision: MergeDecision
    ) -> None:
        """Execute a merge: update primary node, remove secondary, rewire edges."""
        if secondary_id not in self._nodes:
            return

        # Update primary with merged data
        self._nodes[primary_id] = decision.merged_node

        # Rewire edges
        edges_to_remove = []
        edges_to_add = {}
        for eid, edge in self._edges.items():
            if edge.get("source") == secondary_id or edge.get("target") == secondary_id:
                edges_to_remove.append(eid)
                new_source = primary_id if edge.get("source") == secondary_id else edge["source"]
                new_target = primary_id if edge.get("target") == secondary_id else edge["target"]
                if new_source != new_target:  # no self-loops
                    new_eid = f"{new_source}___{edge.get('relationship', 'RELATES_TO')}___{new_target}"
                    edges_to_add[new_eid] = {
                        "id": new_eid,
                        "source": new_source,
                        "target": new_target,
                        "relationship": edge.get("relationship", "RELATES_TO"),
                    }

        for eid in edges_to_remove:
            del self._edges[eid]
        self._edges.update(edges_to_add)

        # Remove secondary
        del self._nodes[secondary_id]

    @staticmethod
    def _classify_source(node: dict) -> str:
        """Classify a node's source type for priority ordering."""
        etype = node.get("entity_type", "").upper()
        props = node.get("properties", {})
        source = props.get("source", "")

        if etype in ("FUNCTION", "CLASS", "MODULE", "PYTHONMODULE", "JAVASCRIPTMODULE"):
            return "code"
        if etype == "ENDPOINT":
            return "api_spec"
        if etype in ("DEPENDENCY", "SCRIPT", "CONFIG", "TOOL_RULE", "RESOURCE"):
            return "json_config"
        if etype == "KNOWLEDGE" or "graq_learn" in source:
            return "user_knowledge"
        if etype in ("DOCUMENT", "SECTION"):
            return "document"
        # Audit nodes (GOVERNANCE_BYPASS, TOOL_EXECUTION) are runtime-generated
        # and must never win merge conflicts over real code/document nodes.
        if etype in ("GOVERNANCE_BYPASS", "TOOL_EXECUTION"):
            return "audit"
        return "code"  # default to highest priority
