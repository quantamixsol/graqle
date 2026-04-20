"""pre-reason-activation design — Protocols and data contracts for the pre-reason activation layer.

IP-scrubbed on purpose: no weights, thresholds, formulas, or internal
constants appear in this file's docstrings, comments, or type names.
These are public-surface Protocols; the inventive concepts live in the
wrapped implementations (DRACEScorer, TAMRConnector, graq_predict).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Tuple


class TierMode(str, Enum):
    """License tier behavior.

    ADVISORY mode (Free tier):
        - Providers run
        - Scores are visible
        - Safety verdicts below threshold emit an upgrade chip
        - Turn continues regardless
    ENFORCED mode (Pro / Enterprise):
        - Providers run
        - Scores are visible
        - Safety verdicts below threshold raise TurnBlocked
        - Turn halts with structured reason
    """
    ADVISORY = "ADVISORY"
    ENFORCED = "ENFORCED"


class TurnBlocked(Exception):
    """Raised in ENFORCED mode when the safety gate blocks a turn.

    The exception carries the ActivationVerdict so callers can surface it
    to the user. ChatAgentLoop catches this and converts it to a
    governance_chip event + turn_state=blocked transition.
    """

    def __init__(self, verdict: "ActivationVerdict"):
        self.verdict = verdict
        super().__init__(verdict.block_reason or "turn blocked by safety gate")


# ─── Chunk scoring (relevance role) ──────────────────────────────────────


@dataclass(frozen=True)
class ChunkScoreResult:
    """Normalized output of a ChunkScoringProvider.

    chunks: tuple of opaque chunk identifiers (strings). Empty tuple means
        "no scored chunks" (will not prevent downstream layers from running).
    scores: tuple aligned with chunks; each a 0.0–1.0 float.
    summary: short human-safe description of the scoring outcome.
    """
    chunks: Tuple[str, ...] = ()
    scores: Tuple[float, ...] = ()
    summary: str = ""


class ChunkScoringProvider(Protocol):
    """Relevance-scoring contract for the pre-reason layer.

    Concrete implementations wrap the existing TAMR+ retrieval pipeline
    or a local semantic scorer. The contract surface is intentionally
    small: give us a message + tcg activation output, we return scored
    chunks. No internal weights, no formula knobs exposed.
    """
    async def score(
        self,
        user_message: str,
        activation_hints: dict,
    ) -> ChunkScoreResult: ...


# ─── Safety gate (DRACE role) ────────────────────────────────────────────


@dataclass(frozen=True)
class SafetyVerdict:
    """Normalized output of a SafetyGateProvider.

    score: opaque 0.0–1.0 composite. Higher = safer.
    should_block: True iff the provider recommends blocking this turn.
    reason: short caller-safe explanation. Never exposes internal
        weights or threshold values.
    details: opaque dict of per-pillar sub-scores for UI rendering.
    """
    score: float = 0.0
    should_block: bool = False
    reason: str = ""
    details: dict = field(default_factory=dict)


class SafetyGateProvider(Protocol):
    """Safety-evaluation contract for the pre-reason layer.

    Concrete implementations wrap the existing DRACEScorer pipeline.
    """
    async def evaluate(
        self,
        user_message: str,
        scored_chunks: ChunkScoreResult,
        activation_hints: dict,
    ) -> SafetyVerdict: ...


# ─── Subgraph activation (PSE role) ──────────────────────────────────────


@dataclass(frozen=True)
class ActivatedSubgraph:
    """Normalized output of a SubgraphActivationProvider.

    nodes: tuple of opaque KG node ids that should be pre-loaded into
        turn_context so the planner sees them.
    edges: tuple of (src, dst, relation) triples.
    confidence: opaque 0.0–1.0 confidence in the activation.
    summary: short human-safe description.
    """
    nodes: Tuple[str, ...] = ()
    edges: Tuple[Tuple[str, str, str], ...] = ()
    confidence: float = 0.0
    summary: str = ""


class SubgraphActivationProvider(Protocol):
    """Predictive subgraph-expansion contract for the pre-reason layer.

    Concrete implementations wrap the existing graq_predict + PSE
    infrastructure. Output is merged into turn_context so subsequent
    tool calls (graq_reason, graq_plan, graq_edit, etc.) see the same
    activated surface without each re-running graq_context.
    """
    async def predict(
        self,
        scored_chunks: ChunkScoreResult,
        safety: SafetyVerdict,
    ) -> ActivatedSubgraph: ...


# ─── Composed verdict (what run_turn receives) ───────────────────────────


@dataclass(frozen=True)
class ActivationVerdict:
    """Result of one full pass through the pre-reason activation layer.

    Produced by ActivationLayer.run(). ChatAgentLoop.run_turn inspects
    this to decide whether to continue (CLEAR / ADVISORY) or halt
    (TurnBlocked raised in ENFORCED mode).
    """
    tier_mode: TierMode
    chunk_result: ChunkScoreResult
    safety: SafetyVerdict
    subgraph: ActivatedSubgraph
    block_reason: str = ""  # set only when safety.should_block AND tier_mode == ENFORCED

    @property
    def is_blocked(self) -> bool:
        return bool(self.block_reason)

    @property
    def advisory_chip(self) -> dict | None:
        """The advisory upgrade chip to emit (Free tier only).

        Returned as a dict suitable for ChatEventBuffer.append. Returns
        None when nothing advisory should be shown (i.e. CLEAR, or
        already ENFORCED/blocked).
        """
        if self.tier_mode != TierMode.ADVISORY:
            return None
        if not self.safety.should_block:
            return None
        return {
            "kind": "upgrade_to_enforce",
            "drace_score": self.safety.score,
            "reason": self.safety.reason,
            "message": (
                f"This turn scored {self.safety.score:.2f} (DRACE). Pro mode "
                "would block this automatically. Upgrade to enforce "
                "governance in your workflow: https://graqle.dev/pricing"
            ),
        }

    def to_dict(self) -> dict:
        """JSON-safe serialization for event buffers + audit logs."""
        return {
            "tier_mode": self.tier_mode.value,
            "chunks": {
                "count": len(self.chunk_result.chunks),
                "summary": self.chunk_result.summary,
            },
            "safety": {
                "score": self.safety.score,
                "should_block": self.safety.should_block,
                "reason": self.safety.reason,
                "details": self.safety.details,
            },
            "subgraph": {
                "node_count": len(self.subgraph.nodes),
                "edge_count": len(self.subgraph.edges),
                "confidence": self.subgraph.confidence,
                "summary": self.subgraph.summary,
            },
            "block_reason": self.block_reason,
            "is_blocked": self.is_blocked,
        }
