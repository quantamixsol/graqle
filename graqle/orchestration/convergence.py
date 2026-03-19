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
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""Convergence detection — determines when message passing should stop.

v2: Semantic convergence using embedding similarity + constraint-aware blocking.
"""

# ── graqle:intelligence ──
# module: graqle.orchestration.convergence
# risk: LOW (impact radius: 5 modules)
# consumers: run_multigov_v2, run_multigov_v3, orchestrator, __init__, test_convergence
# dependencies: __future__, logging, typing, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from graqle.core.message import Message

logger = logging.getLogger("graqle.convergence")


class ConvergenceDetector:
    """Determines when message-passing reasoning has converged.

    Convergence criteria (ANY triggers stop):
    1. max_rounds reached
    2. Average semantic similarity between rounds exceeds threshold
    3. All node confidences exceed confidence_threshold

    Convergence blockers (ANY prevents convergence):
    - SHACL gate rejected output this round
    - Observer detected contradiction
    """

    def __init__(
        self,
        max_rounds: int = 5,
        min_rounds: int = 2,
        similarity_threshold: float = 0.88,
        confidence_threshold: float = 0.8,
        embedding_fn: Any = None,
    ) -> None:
        self.max_rounds = max_rounds
        self.min_rounds = min_rounds
        self.similarity_threshold = similarity_threshold
        self.confidence_threshold = confidence_threshold
        self.embedding_fn = embedding_fn  # callable: str -> np.ndarray
        self._round = 0
        self._convergence_blocked = False
        self._block_reason = ""

    def block_convergence(self, reason: str) -> None:
        """Block convergence for this round (e.g., SHACL gate failure)."""
        self._convergence_blocked = True
        self._block_reason = reason

    def check(
        self,
        current_round: int,
        current_messages: list[Message],
        previous_messages: list[Message] | None,
    ) -> bool:
        """Returns True if reasoning has converged."""
        self._round = current_round

        # Never stop before min_rounds
        if current_round < self.min_rounds:
            self._convergence_blocked = False
            return False

        # Always stop at max_rounds (even if blocked)
        if current_round >= self.max_rounds:
            logger.info(f"Converged: max_rounds ({self.max_rounds}) reached")
            self._convergence_blocked = False
            return True

        # Check convergence blockers
        if self._convergence_blocked:
            logger.info(
                f"Convergence blocked: {self._block_reason}"
            )
            self._convergence_blocked = False
            return False

        # Check confidence threshold
        if current_messages:
            avg_confidence = sum(m.confidence for m in current_messages) / len(
                current_messages
            )
            if avg_confidence >= self.confidence_threshold:
                logger.info(
                    f"Converged: avg confidence {avg_confidence:.2f} >= {self.confidence_threshold}"
                )
                return True

        # Check semantic similarity between rounds
        if previous_messages and current_messages:
            similarity = self._compute_round_similarity(
                current_messages, previous_messages
            )
            if similarity >= self.similarity_threshold:
                logger.info(
                    f"Converged: round similarity {similarity:.3f} >= {self.similarity_threshold}"
                )
                return True

        return False

    def _compute_round_similarity(
        self,
        current: list[Message],
        previous: list[Message],
    ) -> float:
        """Compute average similarity between current and previous round messages.

        Uses embedding similarity if available, falls back to bag-of-words Jaccard.
        """
        if not current or not previous:
            return 0.0

        similarities = []
        for curr_msg in current:
            prev_match = [
                p for p in previous if p.source_node_id == curr_msg.source_node_id
            ]
            if prev_match:
                if self.embedding_fn is not None:
                    sim = self._embedding_similarity(
                        curr_msg.content, prev_match[0].content
                    )
                else:
                    sim = self._text_similarity(
                        curr_msg.content, prev_match[0].content
                    )
                similarities.append(sim)

        return float(np.mean(similarities)) if similarities else 0.0

    def _embedding_similarity(self, text_a: str, text_b: str) -> float:
        """Compute semantic similarity using embeddings."""
        try:
            emb_a = self.embedding_fn(text_a[:1000])
            emb_b = self.embedding_fn(text_b[:1000])
            dot = np.dot(emb_a, emb_b)
            norm_a = np.linalg.norm(emb_a)
            norm_b = np.linalg.norm(emb_b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(dot / (norm_a * norm_b))
        except Exception:
            return self._text_similarity(text_a, text_b)

    @staticmethod
    def _text_similarity(text_a: str, text_b: str) -> float:
        """Lightweight bag-of-words Jaccard similarity (fallback)."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / (len(words_a | words_b) or 1)

    def reset(self) -> None:
        """Reset for a new query."""
        self._round = 0
        self._convergence_blocked = False
        self._block_reason = ""
