"""Governed epistemic memory types for GraQle reasoning agents.

Implements TRACE-scored provenance entries with epistemic decay,
clearance-gated redaction, and contradiction tracking.

Reference: — Epistemic Memory Governance & TRACE Scoring.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from graqle.core.types import ClearanceLevel


@dataclass
class TRACEScores:
    """Five TRACE dimensional quality scores for a memory entry.

    Each dimension measures a *gap* (0.0 = no gap, 1.0 = maximum gap).
    The composite ``trace_score`` is ``1.0 - total_gap``.
    """

    scg: float = 0.0  # Specification Compliance Gap
    pkc: float = 0.0  # Prior Knowledge Conformity
    dlt: float = 0.0  # Deficit in Logical Transparency
    adg: float = 0.0  # Auditability Deficit Gap
    fsc: float = 0.0  # Factual Sufficiency Check

    @property
    def total_gap(self) -> float:
        """Sum of all five gap dimensions."""
        return self.scg + self.pkc + self.dlt + self.adg + self.fsc

    @property
    def trace_score(self) -> float:
        """Composite quality score (1.0 = perfect, 0.0 = maximum gap)."""
        return 1.0 - self.total_gap


@dataclass
class ProvenanceEntry:
    """Governed epistemic memory entry with TRACE scoring and decay.

    Mutable dataclass — confidence decays over rounds and trace scores
    are updated as the entry ages or accumulates contradictions.

    All numerical parameters for decay are caller-supplied
    (internal-pattern-B: no hardcoded threshold values in this module).
    """

    value: Any
    confidence: float
    confidence_initial: float
    source_agent_id: str
    round_stored: int
    round_verified: int
    node_id: str
    clearance: ClearanceLevel = ClearanceLevel.PUBLIC
    trace_scores: TRACEScores = field(default_factory=TRACEScores)
    timestamp: float = field(default_factory=time.time)
    contradiction_count: int = 0
    reasoning_impact: str = "LOW"  # HIGH / MED / LOW

    def decay(
        self,
        current_round: int,
        lambda_: float,
        contradiction_penalty: float,
    ) -> float:
        """Apply epistemic decay and return the updated confidence.

        Formula::

            confidence(t) = confidence_initial
                            * lambda_ ^ rounds_since_verification
                            * contradiction_penalty ^ contradiction_count

        Also increases DLT and ADG trace scores proportionally to the
        confidence drop so that transparency and auditability gaps widen
        as the entry becomes stale.

        All numerical parameters are caller-supplied (internal-pattern-B compliance).

        Returns:
            The decayed confidence value (also written to ``self.confidence``).
        """
        rounds_since = max(current_round - self.round_verified, 0)
        decayed = (
            self.confidence_initial
            * (lambda_ ** rounds_since)
            * (contradiction_penalty ** self.contradiction_count)
        )

        confidence_drop = max(self.confidence - decayed, 0.0)

        # Proportionally degrade transparency & auditability scores
        self.trace_scores.dlt = min(1.0, self.trace_scores.dlt + confidence_drop)
        self.trace_scores.adg = min(1.0, self.trace_scores.adg + confidence_drop)

        self.confidence = decayed
        return decayed

    def needs_reverification(self, threshold: float) -> bool:
        """Return ``True`` if current confidence has fallen below *threshold*."""
        return self.confidence < threshold

    def redacted_for(self, viewer_clearance: ClearanceLevel) -> ProvenanceEntry:
        """Return a clearance-appropriate view of this entry.

        If *viewer_clearance* is lower than the entry's clearance the
        returned copy has its ``value`` replaced with a redaction notice.
        TRACE scores remain visible regardless of clearance level.
        """
        if viewer_clearance.value >= self.clearance.value:
            return self

        return ProvenanceEntry(
            value=f"[REDACTED — requires {self.clearance.name} clearance]",
            confidence=self.confidence,
            confidence_initial=self.confidence_initial,
            source_agent_id=self.source_agent_id,
            round_stored=self.round_stored,
            round_verified=self.round_verified,
            node_id=self.node_id,
            clearance=self.clearance,
            trace_scores=self.trace_scores,
            timestamp=self.timestamp,
            contradiction_count=self.contradiction_count,
            reasoning_impact=self.reasoning_impact,
        )
