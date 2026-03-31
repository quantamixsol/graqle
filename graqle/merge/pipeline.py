"""R2 Bridge Injection Pipeline orchestrator (ADR-133).

Orchestrates the full bridge injection workflow:
detect → validate → reconcile → inject.
"""

# ── graqle:intelligence ──
# module: graqle.merge.pipeline
# risk: MEDIUM (impact radius: 3 modules)
# consumers: cli, mcp_dev_server
# dependencies: __future__, dataclasses, logging, typing,
#               graqle.analysis.bridge, graqle.merge.reconcile
# constraints: ADR-133 R2 bridge validation protocol
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

try:
    import networkx as nx
except ImportError:
    nx = None  # type: ignore[assignment]

from graqle.analysis.bridge import (
    BridgeDetectionReport,
    BridgeDetector,
    SCANNER_ENTITY_TYPES,
    SECONDARY_ENTITY_TYPES,
)
from graqle.merge.reconcile import BridgeReconciler, ReconciliationReport

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger(__name__)

# ADR-133 R2 success criteria thresholds
_R2_MIN_CC_DELTA: int = 12
_R2_MIN_CROSS_EDGES: int = 15
_R2_MIN_BDS: float = 0.03


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BridgeMetrics:
    """Post-injection graph connectivity metrics."""

    cc_delta: int = 0
    cross_edges: int = 0
    bds: float = 0.0  # bridge density score = cross_edges / total_edges

    @property
    def meets_success_criteria(self) -> bool:
        """Check R2 success criteria (ADR-133)."""
        return (
            self.cc_delta >= _R2_MIN_CC_DELTA
            and self.cross_edges >= _R2_MIN_CROSS_EDGES
            and self.bds >= _R2_MIN_BDS
        )


@dataclass
class PipelineReport:
    """Full report produced by a single pipeline run."""

    detection_report: BridgeDetectionReport | None = None
    reconciliation_report: ReconciliationReport | None = None
    injected_count: int = 0
    cc_before: int = 0
    cc_after: int = 0
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)
    errors: list[str] = field(default_factory=list)

    @property
    def cc_delta(self) -> int:
        """Single source of truth for connected-component reduction."""
        return self.cc_before - self.cc_after


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class BridgePipeline:
    """Orchestrates detect → validate → reconcile → inject for bridge edges.

    Parameters
    ----------
    graph:
        A Graqle graph instance exposing ``nodes``, ``edges``,
        ``add_edge_simple``, and connectivity helpers.
    scan_react_components:
        Include ReactComponent as a valid bridge source type.
    confidence_threshold:
        Minimum confidence for bridge candidates.
    """

    def __init__(
        self,
        graph: Graqle,
        *,
        scan_react_components: bool = False,
        confidence_threshold: float = 0.4,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold must be in [0, 1], got {confidence_threshold}"
            )
        self._graph = graph
        self._scan_react_components = scan_react_components
        self._confidence_threshold = confidence_threshold

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_nodes(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract scanner-typed nodes and KG Entity nodes from the graph."""
        allowed = set(SCANNER_ENTITY_TYPES)
        if self._scan_react_components:
            allowed |= SECONDARY_ENTITY_TYPES

        scanner_nodes: list[dict[str, Any]] = []
        kg_entity_nodes: list[dict[str, Any]] = []

        for node_id, node in self._graph.nodes.items():
            # CogniNode → dict representation (copy to avoid mutating graph state)
            if hasattr(node, "to_dict"):
                node_dict = dict(node.to_dict())
            elif isinstance(node, dict):
                node_dict = dict(node)
            else:
                node_dict = {
                    "id": getattr(node, "id", node_id),
                    "label": getattr(node, "label", ""),
                    "name": getattr(node, "label", ""),
                    "entity_type": getattr(node, "entity_type", ""),
                }

            # Ensure id is set
            node_dict.setdefault("id", node_id)
            node_dict.setdefault("name", node_dict.get("label", node_id))

            etype = node_dict.get("entity_type", node_dict.get("type", ""))
            if etype in allowed:
                scanner_nodes.append(node_dict)
            elif etype == "Entity":
                kg_entity_nodes.append(node_dict)

        return scanner_nodes, kg_entity_nodes

    def _extract_existing_edges(self) -> list[dict[str, Any]]:
        """Extract existing edges as list of dicts for duplicate checking."""
        edges: list[dict[str, Any]] = []
        edge_store = self._graph.edges
        if isinstance(edge_store, dict):
            for edge in edge_store.values():
                if hasattr(edge, "source_id"):
                    edges.append({
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "relationship": getattr(edge, "relationship", ""),
                    })
                elif isinstance(edge, dict):
                    edges.append(edge)
        elif isinstance(edge_store, list):
            for edge in edge_store:
                if isinstance(edge, dict):
                    edges.append(edge)
                elif hasattr(edge, "source_id"):
                    edges.append({
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "relationship": getattr(edge, "relationship", ""),
                    })
        else:
            logger.warning(
                "Unrecognised edge_store type %s; duplicate-check disabled",
                type(edge_store).__name__,
            )
        return edges

    @staticmethod
    def _connected_component_count(graph: Any) -> int:
        """Return the number of connected components in *graph*."""
        if hasattr(graph, "connected_component_count"):
            return graph.connected_component_count()
        if hasattr(graph, "connected_components"):
            cc = graph.connected_components()
            return cc if isinstance(cc, int) else len(cc)
        # Fallback: try networkx-style _graph attribute
        if nx is not None:
            g = getattr(graph, "_graph", None)
            if g is not None:
                try:
                    return nx.number_connected_components(g.to_undirected())
                except Exception as exc:
                    logger.warning("CC count via networkx failed: %s", exc)
        return 0

    @staticmethod
    def _total_edge_count(graph: Any) -> int:
        """Return total edge count in *graph*."""
        if hasattr(graph, "edge_count"):
            return graph.edge_count()
        edges = getattr(graph, "edges", None)
        if edges is not None and hasattr(edges, "__len__"):
            return len(edges)
        return 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> PipelineReport:
        """Execute the full detect → reconcile → inject pipeline."""
        report = PipelineReport()

        # 0. Snapshot connected-component count before injection.
        report.cc_before = self._connected_component_count(self._graph)

        # (a) Extract scanner_nodes and kg_entity_nodes from graph.
        scanner_nodes, kg_entity_nodes = self._extract_nodes()
        existing_edges = self._extract_existing_edges()
        logger.info(
            "Pipeline: %d scanner nodes, %d KG entity nodes, %d existing edges",
            len(scanner_nodes),
            len(kg_entity_nodes),
            len(existing_edges),
        )

        if not scanner_nodes or not kg_entity_nodes:
            report.errors.append(
                f"Insufficient nodes: {len(scanner_nodes)} scanner, "
                f"{len(kg_entity_nodes)} KG entity"
            )
            logger.warning("Pipeline: insufficient nodes, skipping")
            return report

        # (b) Detect candidate bridges.
        detector = BridgeDetector(
            confidence_threshold=self._confidence_threshold,
            scan_react_components=self._scan_react_components,
        )
        detection_report = detector.detect(
            scanner_nodes=scanner_nodes,
            kg_nodes=kg_entity_nodes,
            existing_edges=existing_edges,
        )
        report.detection_report = detection_report

        # (c) Reconcile candidates.
        reconciler = BridgeReconciler(detection_report)
        reconciliation_report = reconciler.reconcile()
        report.reconciliation_report = reconciliation_report

        # (d) Inject accepted bridges into the graph.
        accepted = reconciliation_report.accepted
        injected = 0
        for bridge in accepted:
            try:
                self._graph.add_edge_simple(
                    bridge.source_id,
                    bridge.target_id,
                    bridge.relationship,
                )
                injected += 1
            except Exception as exc:
                logger.warning(
                    "Failed to inject bridge %s→%s: %s",
                    bridge.source_id, bridge.target_id, exc,
                )
                report.errors.append(
                    f"inject_failed:{bridge.source_id}→{bridge.target_id}:{exc}"
                )

        report.injected_count = injected
        logger.info("Injected %d bridge edges", injected)

        # 5. Compute post-injection metrics.
        report.cc_after = self._connected_component_count(self._graph)

        total_edges = self._total_edge_count(self._graph)
        cross_edges = injected
        bds = cross_edges / total_edges if total_edges > 0 else 0.0

        report.metrics = BridgeMetrics(
            cc_delta=report.cc_delta,  # uses PipelineReport.cc_delta property
            cross_edges=cross_edges,
            bds=round(bds, 6),
        )

        logger.info(
            "Pipeline complete: injected=%d cc_delta=%d bds=%.4f success=%s",
            report.injected_count,
            report.cc_delta,
            report.metrics.bds,
            report.metrics.meets_success_criteria,
        )

        return report
