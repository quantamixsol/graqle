"""GraphLearner — online Bayesian edge weight updates from reasoning outcomes.

After each reasoning pass, the learner:
1. Reads the message trace to compute pairwise agent agreement scores
2. Updates edge weights using Bayesian belief updating
3. Applies temporal decay so old learnings fade unless reinforced
4. Persists updated weights to the graph (modifies Graqle.edges in-place)

The signal source is the MasterObserver's message trace: pairs of agents
that converge (high cosine similarity in final round) get edge weight increases.
Pairs that diverge get decreases.
"""

# ── graqle:intelligence ──
# module: graqle.learning.graph_learner
# risk: MEDIUM (impact radius: 2 modules)
# consumers: __init__, test_graph_learner
# dependencies: __future__, json, logging, math, dataclasses +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("graqle.learning")


@dataclass
class LearningConfig:
    """Configuration for online graph learning."""
    # Bayesian update strength (higher = more aggressive updates)
    learning_rate: float = 0.1
    # Temporal decay factor per reasoning pass (0.95 = 5% decay)
    decay_factor: float = 0.95
    # Minimum edge weight (prevents edges from vanishing)
    min_weight: float = 0.1
    # Maximum edge weight (prevents runaway reinforcement)
    max_weight: float = 5.0
    # Agreement threshold: similarity above this = converged
    agreement_threshold: float = 0.7
    # Disagreement threshold: similarity below this = diverged
    disagreement_threshold: float = 0.3
    # Whether to persist weights to disk
    persist: bool = False
    persist_path: str = "./learned_weights.json"


@dataclass
class EdgeUpdate:
    """Record of a single edge weight update."""
    edge_id: str
    source_id: str
    target_id: str
    old_weight: float
    new_weight: float
    agreement_score: float
    reason: str  # "converged" or "diverged" or "decayed"


class GraphLearner:
    """Online Bayesian edge weight learner.

    Usage:
        learner = GraphLearner()
        # After each reasoning pass:
        updates = learner.update_from_reasoning(graph, result)
        print(f"Updated {len(updates)} edges")
        # Inspect:
        print(learner.stats)
    """

    def __init__(self, config: LearningConfig | None = None) -> None:
        self._config = config or LearningConfig()
        self._update_count: int = 0
        self._total_strengthened: int = 0
        self._total_weakened: int = 0
        self._total_decayed: int = 0
        self._history: list[list[EdgeUpdate]] = []

    @property
    def config(self) -> LearningConfig:
        return self._config

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "update_rounds": self._update_count,
            "total_strengthened": self._total_strengthened,
            "total_weakened": self._total_weakened,
            "total_decayed": self._total_decayed,
            "history_length": len(self._history),
        }

    def compute_agreement_matrix(
        self,
        messages: dict[str, str],
        embedder: Any = None,
    ) -> dict[tuple[str, str], float]:
        """Compute pairwise agreement scores between node messages.

        Args:
            messages: {node_id: final_message_text}
            embedder: Optional embedding engine with embed_batch method.
                     If None, uses simple token overlap (Jaccard).

        Returns:
            {(node_a, node_b): similarity_score}
        """
        node_ids = sorted(messages.keys())
        n = len(node_ids)
        if n < 2:
            return {}

        if embedder is not None:
            texts = [messages[nid] for nid in node_ids]
            try:
                vecs = embedder.embed_batch(texts)
                # Normalize
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1, norms)
                vecs = vecs / norms
                sim_matrix = vecs @ vecs.T
            except Exception:
                # Fallback to Jaccard
                sim_matrix = self._jaccard_matrix(node_ids, messages)
        else:
            sim_matrix = self._jaccard_matrix(node_ids, messages)

        pairs: dict[tuple[str, str], float] = {}
        for i in range(n):
            for j in range(i + 1, n):
                pairs[(node_ids[i], node_ids[j])] = float(sim_matrix[i, j])
        return pairs

    def _jaccard_matrix(
        self, node_ids: list[str], messages: dict[str, str]
    ) -> np.ndarray:
        """Compute Jaccard similarity matrix as embedding fallback."""
        n = len(node_ids)
        token_sets = []
        for nid in node_ids:
            tokens = set(messages[nid].lower().split())
            token_sets.append(tokens)

        matrix = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                intersection = len(token_sets[i] & token_sets[j])
                union = len(token_sets[i] | token_sets[j])
                sim = intersection / max(union, 1)
                matrix[i, j] = sim
                matrix[j, i] = sim
        return matrix

    def update_from_reasoning(
        self,
        graph: Any,  # Graqle
        result: Any,  # ReasoningResult
        embedder: Any = None,
    ) -> list[EdgeUpdate]:
        """Update edge weights based on reasoning outcome.

        Args:
            graph: Graqle with nodes and edges
            result: ReasoningResult with message_trace and active_nodes
            embedder: Optional embedding engine for similarity computation

        Returns:
            List of EdgeUpdate records
        """
        cfg = self._config
        updates: list[EdgeUpdate] = []

        # Extract final-round messages per node
        final_messages: dict[str, str] = {}
        if hasattr(result, "message_trace") and result.message_trace:
            # Group by source, take last message per node
            for msg in result.message_trace:
                src = msg.source if hasattr(msg, "source") else getattr(msg, "sender", None)
                content = msg.content if hasattr(msg, "content") else str(msg)
                if src:
                    final_messages[src] = content

        if len(final_messages) < 2:
            logger.debug("Not enough messages for learning update")
            return updates

        # Compute agreement matrix
        agreements = self.compute_agreement_matrix(final_messages, embedder)

        # Phase 1: Apply temporal decay to ALL edges
        for edge in graph.edges.values():
            old_w = edge.weight
            new_w = max(cfg.min_weight, old_w * cfg.decay_factor)
            if abs(new_w - old_w) > 1e-6:
                updates.append(EdgeUpdate(
                    edge_id=edge.id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    old_weight=old_w,
                    new_weight=round(new_w, 4),
                    agreement_score=0.0,
                    reason="decayed",
                ))
                edge.weight = round(new_w, 4)
                self._total_decayed += 1

        # Phase 2: Bayesian update for edges between active nodes
        for (node_a, node_b), sim in agreements.items():
            # Find edge between these nodes (either direction)
            edge = self._find_edge(graph, node_a, node_b)
            if edge is None:
                continue

            old_w = edge.weight
            if sim >= cfg.agreement_threshold:
                # Strengthen: Bayesian reinforcement
                delta = cfg.learning_rate * (sim - cfg.agreement_threshold)
                new_w = min(cfg.max_weight, old_w + delta)
                reason = "converged"
                self._total_strengthened += 1
            elif sim <= cfg.disagreement_threshold:
                # Weaken: Bayesian penalty
                delta = cfg.learning_rate * (cfg.disagreement_threshold - sim)
                new_w = max(cfg.min_weight, old_w - delta)
                reason = "diverged"
                self._total_weakened += 1
            else:
                continue  # Neutral — no update

            updates.append(EdgeUpdate(
                edge_id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                old_weight=old_w,
                new_weight=round(new_w, 4),
                agreement_score=round(sim, 4),
                reason=reason,
            ))
            edge.weight = round(new_w, 4)

        self._update_count += 1
        self._history.append(updates)

        # Persist if configured
        if cfg.persist:
            self._save_weights(graph)

        logger.info(
            f"Learning update #{self._update_count}: "
            f"{len(updates)} edge updates "
            f"({self._total_strengthened} strengthened, "
            f"{self._total_weakened} weakened, "
            f"{self._total_decayed} decayed)"
        )
        return updates

    def _find_edge(self, graph: Any, node_a: str, node_b: str) -> Any | None:
        """Find edge between two nodes (either direction)."""
        for edge in graph.edges.values():
            if (edge.source_id == node_a and edge.target_id == node_b) or \
               (edge.source_id == node_b and edge.target_id == node_a):
                return edge
        return None

    def _save_weights(self, graph: Any) -> None:
        """Persist learned weights to JSON."""
        weights = {
            eid: {"weight": e.weight, "source": e.source_id, "target": e.target_id}
            for eid, e in graph.edges.items()
        }
        path = Path(self._config.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(weights, indent=2))
        logger.debug(f"Saved {len(weights)} edge weights to {path}")

    def load_weights(self, graph: Any) -> int:
        """Load previously learned weights and apply to graph.

        Returns:
            Number of weights applied
        """
        path = Path(self._config.persist_path)
        if not path.exists():
            return 0

        data = json.loads(path.read_text(encoding="utf-8"))
        applied = 0
        for eid, info in data.items():
            if eid in graph.edges:
                graph.edges[eid].weight = info["weight"]
                applied += 1

        logger.info(f"Loaded {applied} learned weights from {path}")
        return applied

    def reset(self) -> None:
        """Reset learner state."""
        self._update_count = 0
        self._total_strengthened = 0
        self._total_weakened = 0
        self._total_decayed = 0
        self._history.clear()
