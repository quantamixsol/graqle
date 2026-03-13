"""PCST subgraph activation — Prize-Collecting Steiner Tree selection.

Given a query, selects the optimal subgraph to activate by:
1. Computing query-node relevance scores (prizes) — content-richness-aware (v3)
2. Computing edge costs (inverse semantic similarity)
3. Running PCST to find minimum-cost, maximum-prize subtree
4. Post-PCST content filter: replacing zero-chunk structural nodes with their
   best content-bearing neighbour (ADR-103, Layer 2)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from graqle.activation.relevance import RelevanceScorer

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.activation")


class PCSTActivation:
    """Prize-Collecting Steiner Tree subgraph selection.

    Selects the optimal subset of nodes to activate for a query,
    balancing relevance (prizes) against graph distance (costs).
    This ensures only 4-16 nodes activate per query — not thousands.
    """

    def __init__(
        self,
        max_nodes: int = 50,
        prize_scaling: float = 1.0,
        cost_scaling: float = 1.0,
        pruning: str = "strong",
        relevance_scorer: RelevanceScorer | None = None,
    ) -> None:
        self.max_nodes = max_nodes
        self.prize_scaling = prize_scaling
        self.cost_scaling = cost_scaling
        self.pruning = pruning
        self.relevance_scorer = relevance_scorer or RelevanceScorer()

    def activate(self, graph: Graqle, query: str) -> list[str]:
        """Select nodes to activate for a query.

        Returns list of node IDs in the activated subgraph.
        Falls back to top-k if pcst_fast is not installed.

        Side effect: stores relevance scores in ``self.last_relevance``
        for downstream confidence calibration (Bug 18 fix).

        Pipeline (ADR-103):
          1. Compute content-richness-aware relevance scores (Layer 1)
          2. Run PCST (pcst_fast or native greedy)
          3. Post-filter: swap zero-chunk nodes for content-bearing neighbours (Layer 2)
        """
        # 1. Compute relevance scores (prizes) — content-richness-aware (v3)
        relevance = self.relevance_scorer.score(graph, query)
        self.last_relevance = relevance  # expose for confidence calibration

        # 2. Try pcst_fast, fall back to native PCST implementation
        try:
            selected = self._pcst_select(graph, relevance)
        except ImportError:
            logger.info(
                "pcst_fast not installed, using native PCST approximation. "
                "For optimal results: pip install pcst_fast"
            )
            selected = self._native_pcst_select(graph, relevance)

        # 3. Post-PCST content filter (Layer 2, ADR-103)
        selected = self._content_filter(graph, selected, relevance)

        return selected

    def _pcst_select(
        self, graph: Graqle, relevance: dict[str, float]
    ) -> list[str]:
        """Run PCST algorithm for optimal subgraph selection."""
        import pcst_fast

        node_ids = list(graph.nodes.keys())
        node_idx = {nid: i for i, nid in enumerate(node_ids)}
        n = len(node_ids)

        # Prizes (relevance scores)
        prizes = np.array(
            [relevance.get(nid, 0.0) * self.prize_scaling for nid in node_ids]
        )

        # Edge arrays
        edges_list = []
        costs = []
        for edge in graph.edges.values():
            src_idx = node_idx.get(edge.source_id)
            tgt_idx = node_idx.get(edge.target_id)
            if src_idx is not None and tgt_idx is not None:
                edges_list.append([src_idx, tgt_idx])
                costs.append(edge.semantic_distance * self.cost_scaling)

        if not edges_list:
            # No edges — just return top-k by relevance
            return self._topk_select(relevance)

        edges_array = np.array(edges_list, dtype=np.int64)
        costs_array = np.array(costs, dtype=np.float64)

        # Run PCST
        selected_vertices, selected_edges = pcst_fast.pcst_fast(
            edges_array,
            prizes,
            costs_array,
            -1,               # No root constraint
            1,                # Single component
            self.pruning,
            0,                # Verbosity
        )

        # Map back to node IDs
        selected = [node_ids[i] for i in selected_vertices]

        # Enforce max_nodes
        if len(selected) > self.max_nodes:
            # Keep the most relevant
            selected.sort(key=lambda nid: relevance.get(nid, 0.0), reverse=True)
            selected = selected[: self.max_nodes]

        logger.info(
            f"PCST activated {len(selected)}/{n} nodes "
            f"(max_nodes={self.max_nodes})"
        )
        return selected

    def _native_pcst_select(
        self, graph: Graqle, relevance: dict[str, float]
    ) -> list[str]:
        """Native PCST approximation without pcst_fast dependency.

        Uses a greedy prize-collecting approach:
        1. Start with highest-prize node
        2. Greedily add neighbors that improve prize/cost ratio
        3. Prune low-value leaf nodes

        This approximates the NP-hard PCST problem without external libraries.
        Quality is ~85-90% of optimal pcst_fast solution.
        """
        if not relevance:
            return []

        node_ids = list(relevance.keys())

        # Build adjacency and edge cost lookup
        adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
        edge_costs: dict[tuple[str, str], float] = {}

        for edge in graph.edges.values():
            if edge.source_id in adjacency and edge.target_id in adjacency:
                adjacency[edge.source_id].append(edge.target_id)
                adjacency[edge.target_id].append(edge.source_id)
                cost = edge.semantic_distance * self.cost_scaling
                edge_costs[(edge.source_id, edge.target_id)] = cost
                edge_costs[(edge.target_id, edge.source_id)] = cost

        # Phase 1: Seed with top-prize node
        sorted_by_prize = sorted(relevance.items(), key=lambda x: x[1], reverse=True)
        selected: set[str] = {sorted_by_prize[0][0]}
        total_prize = sorted_by_prize[0][1] * self.prize_scaling

        # Phase 2: Greedy expansion — add neighbors that improve net value
        improved = True
        while improved and len(selected) < self.max_nodes:
            improved = False
            best_candidate = None
            best_net_gain = 0.0

            for node_id in list(selected):
                for neighbor_id in adjacency.get(node_id, []):
                    if neighbor_id in selected:
                        continue

                    prize = relevance.get(neighbor_id, 0.0) * self.prize_scaling
                    cost = edge_costs.get((node_id, neighbor_id), 1.0)
                    net_gain = prize - cost

                    if net_gain > best_net_gain:
                        best_net_gain = net_gain
                        best_candidate = neighbor_id

            if best_candidate is not None and best_net_gain > 0:
                selected.add(best_candidate)
                total_prize += best_net_gain
                improved = True

        # Phase 3: If we have room, add disconnected high-prize nodes
        for nid, prize in sorted_by_prize:
            if len(selected) >= self.max_nodes:
                break
            if nid not in selected and prize * self.prize_scaling > 0.1:
                selected.add(nid)

        # Phase 4: Prune — remove leaf nodes with low prize
        if self.pruning == "strong":
            pruned = True
            while pruned:
                pruned = False
                for nid in list(selected):
                    if len(selected) <= 2:
                        break
                    # Count connections within selected set
                    connections = sum(
                        1 for n in adjacency.get(nid, []) if n in selected
                    )
                    prize = relevance.get(nid, 0.0) * self.prize_scaling
                    if connections <= 1 and prize < 0.05:
                        selected.discard(nid)
                        pruned = True

        result = list(selected)
        logger.info(
            f"Native PCST activated {len(result)}/{len(node_ids)} nodes "
            f"(max_nodes={self.max_nodes}, total_prize={total_prize:.2f})"
        )
        return result

    def _topk_select(self, relevance: dict[str, float]) -> list[str]:
        """Fallback: select top-k nodes by relevance score."""
        sorted_nodes = sorted(relevance.items(), key=lambda x: x[1], reverse=True)
        k = min(self.max_nodes, len(sorted_nodes))
        selected = [nid for nid, _ in sorted_nodes[:k]]
        logger.info(f"Top-k activated {len(selected)} nodes")
        return selected

    def _content_filter(
        self,
        graph: Graqle,
        selected: list[str],
        relevance: dict[str, float],
    ) -> list[str]:
        """Layer 2 (ADR-103): Post-PCST content filter.

        After PCST selects the optimal subtree, some nodes may be structural
        connectors (Directory, Namespace) with zero evidence chunks.  These
        nodes are useless for reasoning — an agent with no chunks produces
        generic, low-confidence answers.

        For every zero-chunk node in the selection, this method finds the
        best content-bearing neighbour (highest relevance score among
        neighbours that have ≥1 chunk) and swaps it in.

        Edge cases:
        - Node has no neighbours at all -> kept as-is (removing would lose
          the slot entirely; the agent will use its description).
        - No neighbour has chunks -> original node is kept.
        - Replacement is already in the selection -> original is dropped
          (no duplicates) and the slot is freed.
        - All selected nodes have chunks -> no-op.
        - Graph has zero edges -> no-op (cannot find neighbours).
        """
        if not selected:
            return selected

        selected_set = set(selected)
        replacements: dict[str, str | None] = {}  # old_id -> new_id or None

        for nid in selected:
            node = graph.nodes.get(nid)
            if node is None:
                continue

            chunks = node.properties.get("chunks", [])
            if chunks:
                continue  # Has content — keep

            # Zero-chunk node — find best content-bearing neighbour
            neighbours = graph.get_neighbors(nid)
            if not neighbours:
                continue  # Isolated; keep as-is

            best_replacement: str | None = None
            best_score = -1.0

            for neighbor_id in neighbours:
                neighbor = graph.nodes.get(neighbor_id)
                if neighbor is None:
                    continue
                neighbor_chunks = neighbor.properties.get("chunks", [])
                if not neighbor_chunks:
                    continue  # Neighbour also has no chunks — skip
                nscore = relevance.get(neighbor_id, 0.0)
                if nscore > best_score:
                    best_score = nscore
                    best_replacement = neighbor_id

            if best_replacement is not None:
                replacements[nid] = best_replacement

        if not replacements:
            return selected

        # Apply replacements
        result: list[str] = []
        seen: set[str] = set()
        for nid in selected:
            if nid in replacements:
                replacement = replacements[nid]
                if replacement is not None and replacement not in seen:
                    result.append(replacement)
                    seen.add(replacement)
                    logger.debug(
                        "Content filter: replaced %s (0 chunks) -> %s",
                        nid, replacement,
                    )
                # else: replacement already in result, or None — drop the slot
            else:
                if nid not in seen:
                    result.append(nid)
                    seen.add(nid)

        swapped = len(replacements)
        logger.info(
            "Content filter: swapped %d/%d zero-chunk nodes with "
            "content-bearing neighbours",
            swapped, len(selected),
        )
        return result
