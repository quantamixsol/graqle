"""NodeState — agent belief and memory state for a CogniNode."""

# ── graqle:intelligence ──
# module: graqle.core.state
# risk: LOW (impact radius: 5 modules)
# consumers: __init__, graph, node, __init__, conftest
# dependencies: __future__, dataclasses, typing, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class NodeState:
    """Internal state of a CogniNode agent.

    Tracks the agent's evolving beliefs across message-passing rounds.
    Belief updates happen via incoming messages from neighbors — this is
    the mechanism through which emergent reasoning occurs.
    """

    # Current belief (updated each round)
    belief: str = ""
    confidence: float = 0.0

    # Belief history across rounds
    belief_history: list[str] = field(default_factory=list)
    confidence_history: list[float] = field(default_factory=list)

    # Embedding of current belief (for convergence detection)
    belief_embedding: np.ndarray | None = field(default=None, repr=False)

    # Evidence accumulated from messages
    evidence: list[str] = field(default_factory=list)

    # Contradictions detected
    contradictions: list[dict[str, Any]] = field(default_factory=list)

    # Round counter
    current_round: int = 0

    def update(self, new_belief: str, new_confidence: float) -> None:
        """Update belief state and record history."""
        self.belief_history.append(self.belief)
        self.confidence_history.append(self.confidence)
        self.belief = new_belief
        self.confidence = new_confidence
        self.current_round += 1

    def add_evidence(self, evidence_id: str) -> None:
        """Record a piece of evidence supporting current belief."""
        if evidence_id not in self.evidence:
            self.evidence.append(evidence_id)

    def add_contradiction(
        self, source_node: str, claim_a: str, claim_b: str
    ) -> None:
        """Record a detected contradiction between agents."""
        self.contradictions.append({
            "source": source_node,
            "claim_a": claim_a,
            "claim_b": claim_b,
            "round": self.current_round,
        })

    def reset(self) -> None:
        """Reset state for a new reasoning query."""
        self.belief = ""
        self.confidence = 0.0
        self.belief_history.clear()
        self.confidence_history.clear()
        self.belief_embedding = None
        self.evidence.clear()
        self.contradictions.clear()
        self.current_round = 0

    @property
    def has_converged(self) -> bool:
        """Check if belief has stabilized (simple heuristic)."""
        if len(self.confidence_history) < 2:
            return False
        return abs(self.confidence - self.confidence_history[-1]) < 0.05
