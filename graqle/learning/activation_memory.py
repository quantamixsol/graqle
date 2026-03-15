"""ActivationMemory — cross-query learning for node activation.

Tracks which nodes produced useful results for which query patterns.
Over time, nodes that consistently contribute high-confidence answers
get an activation boost for similar future queries.

This addresses the tester feedback:
- "No learning across queries — each query starts fresh"
- "No adaptive node count based on past performance"
- "The graph doesn't reorganize based on which nodes produce useful answers"

Architecture:
    After each reasoning pass, the orchestrator calls:
        memory.record(query, active_nodes, result)

    Before the next activation, ChunkScorer can call:
        boosts = memory.get_boosts(query)
        # Returns {node_id: boost_score} for nodes historically useful
        # for similar queries

Storage: JSON file at .graqle/activation_memory.json
"""

# ── graqle:intelligence ──
# module: graqle.learning.activation_memory
# risk: LOW (impact radius: 1 modules)
# consumers: test_activation_memory
# dependencies: __future__, json, logging, math, collections +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.learning.activation_memory")


@dataclass
class NodeRecord:
    """Tracks a node's performance across queries."""
    activations: int = 0          # How many times this node was activated
    useful_activations: int = 0   # Times it contributed high-confidence answer
    avg_confidence: float = 0.0   # Running average confidence when activated
    query_patterns: list[str] = field(default_factory=list)  # Last N query keywords


@dataclass
class ActivationMemoryConfig:
    """Configuration for activation memory."""
    # Minimum confidence to count as "useful"
    useful_threshold: float = 0.5
    # Maximum boost from memory (added to chunk score)
    max_boost: float = 0.15
    # How many query keywords to remember per node
    max_patterns_per_node: int = 20
    # Decay factor per query (older memories fade)
    decay_factor: float = 0.98
    # Minimum activations before memory influences scoring
    min_activations: int = 3
    # Persist to disk
    persist: bool = True
    persist_path: str = ".graqle/activation_memory.json"


class ActivationMemory:
    """Cross-query learning for node activation patterns.

    Remembers which nodes were useful for which types of queries
    and provides activation boosts for future similar queries.

    Usage:
        memory = ActivationMemory()
        memory.load()

        # After reasoning:
        memory.record(query, active_nodes, result)

        # Before activation:
        boosts = memory.get_boosts(new_query)
        # {node_id: 0.0-0.15 boost score}
    """

    def __init__(self, config: ActivationMemoryConfig | None = None) -> None:
        self._config = config or ActivationMemoryConfig()
        self._records: dict[str, NodeRecord] = defaultdict(NodeRecord)
        self._total_queries: int = 0

    @property
    def config(self) -> ActivationMemoryConfig:
        return self._config

    @property
    def stats(self) -> dict[str, Any]:
        total_nodes = len(self._records)
        useful_nodes = sum(
            1 for r in self._records.values()
            if r.useful_activations >= self._config.min_activations
        )
        return {
            "total_queries": self._total_queries,
            "tracked_nodes": total_nodes,
            "useful_nodes": useful_nodes,
            "avg_usefulness": (
                sum(
                    r.useful_activations / max(r.activations, 1)
                    for r in self._records.values()
                ) / max(total_nodes, 1)
            ),
        }

    def record(
        self,
        query: str,
        active_node_ids: list[str],
        result: Any,  # ReasoningResult
    ) -> None:
        """Record which nodes were activated and how useful they were.

        Call this after each reasoning pass.
        """
        self._total_queries += 1
        keywords = self._extract_keywords(query)

        # Apply temporal decay to all existing records
        for record in self._records.values():
            record.avg_confidence *= self._config.decay_factor

        # Extract per-node confidence from the result
        node_confidences: dict[str, float] = {}
        if hasattr(result, "message_trace") and result.message_trace:
            for msg in result.message_trace:
                src = None
                if isinstance(msg, dict):
                    src = msg.get("source_node_id")
                    conf = msg.get("confidence", 0.0)
                elif hasattr(msg, "source_node_id"):
                    src = msg.source_node_id
                    conf = msg.confidence
                if src and src in active_node_ids:
                    # Keep the highest confidence per node
                    node_confidences[src] = max(
                        node_confidences.get(src, 0.0), conf
                    )

        # Update records for activated nodes
        for nid in active_node_ids:
            record = self._records[nid]
            record.activations += 1

            conf = node_confidences.get(nid, 0.0)
            # Running average confidence
            n = record.activations
            record.avg_confidence = (
                record.avg_confidence * (n - 1) + conf
            ) / n

            if conf >= self._config.useful_threshold:
                record.useful_activations += 1

            # Remember query keywords (ring buffer)
            record.query_patterns.extend(keywords)
            if len(record.query_patterns) > self._config.max_patterns_per_node:
                record.query_patterns = record.query_patterns[
                    -self._config.max_patterns_per_node:
                ]

        # Auto-persist
        if self._config.persist:
            self.save()

        logger.info(
            "Activation memory updated: query %d, %d nodes recorded, "
            "%d useful (conf >= %.0f%%)",
            self._total_queries,
            len(active_node_ids),
            sum(1 for nid in active_node_ids
                if node_confidences.get(nid, 0) >= self._config.useful_threshold),
            self._config.useful_threshold * 100,
        )

    def get_boosts(self, query: str) -> dict[str, float]:
        """Get activation boosts for nodes based on past performance.

        Returns dict of {node_id: boost_score} where boost_score
        is 0.0 to max_boost. Higher = historically more useful for
        similar queries.
        """
        if self._total_queries < self._config.min_activations:
            return {}  # Not enough history yet

        keywords = set(self._extract_keywords(query))
        if not keywords:
            return {}

        boosts: dict[str, float] = {}
        for nid, record in self._records.items():
            if record.activations < self._config.min_activations:
                continue

            # Usefulness ratio: how often was this node useful?
            usefulness = record.useful_activations / max(record.activations, 1)

            # Pattern overlap: how similar is this query to past queries
            # where this node was activated?
            past_keywords = set(record.query_patterns)
            if not past_keywords:
                continue
            overlap = len(keywords & past_keywords) / max(len(keywords), 1)

            # Combined boost: usefulness * overlap * max_boost
            boost = usefulness * overlap * self._config.max_boost

            if boost > 0.01:
                boosts[nid] = round(min(boost, self._config.max_boost), 4)

        if boosts:
            logger.debug(
                "Activation memory: %d nodes boosted (max boost=%.3f)",
                len(boosts),
                max(boosts.values()) if boosts else 0,
            )

        return boosts

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract meaningful keywords from a query."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "as", "into", "through", "during", "before", "after",
            "above", "below", "between", "under", "about",
            "and", "but", "or", "nor", "not", "so", "yet",
            "this", "that", "these", "those", "it", "its",
            "what", "which", "who", "whom", "how", "when", "where", "why",
            "i", "me", "my", "we", "our", "you", "your", "he", "she",
            "they", "them", "their",
        }
        words = query.lower().split()
        return [w for w in words if len(w) > 2 and w not in stop_words]

    def save(self) -> None:
        """Persist activation memory to disk."""
        path = Path(self._config.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "total_queries": self._total_queries,
            "records": {
                nid: {
                    "activations": r.activations,
                    "useful_activations": r.useful_activations,
                    "avg_confidence": round(r.avg_confidence, 4),
                    "query_patterns": r.query_patterns[-self._config.max_patterns_per_node:],
                }
                for nid, r in self._records.items()
            },
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> int:
        """Load activation memory from disk.

        Returns number of node records loaded.
        """
        path = Path(self._config.persist_path)
        if not path.exists():
            return 0

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._total_queries = data.get("total_queries", 0)
            for nid, rdata in data.get("records", {}).items():
                record = NodeRecord(
                    activations=rdata.get("activations", 0),
                    useful_activations=rdata.get("useful_activations", 0),
                    avg_confidence=rdata.get("avg_confidence", 0.0),
                    query_patterns=rdata.get("query_patterns", []),
                )
                self._records[nid] = record
            logger.info(
                "Loaded activation memory: %d queries, %d nodes",
                self._total_queries, len(self._records),
            )
            return len(self._records)
        except Exception as e:
            logger.warning("Failed to load activation memory: %s", e)
            return 0

    def reset(self) -> None:
        """Reset all memory."""
        self._records.clear()
        self._total_queries = 0
