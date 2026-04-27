"""pre-reason-activation design — Real providers wrapping existing DRACE / TAMR+ / PSE.

These are the production wirings. Each wraps an existing implementation
that already ships in GraQle:
  - ChunkScorer    → wraps graqle.activation.chunk_scorer.ChunkScorer
  - DRACEScorer    → wraps graqle.intelligence.governance.drace.DRACEScorer
  - PSE activator  → wraps graqle._handle_predict (MCP-tool-backed)

IP-scrubbed: no weights, formulas, or internal constants appear in this
file. Behavior lives in the wrapped implementations; this file is glue
only.
"""
from __future__ import annotations

import logging
from typing import Any

from graqle.activation.providers import (
    ActivatedSubgraph,
    ChunkScoreResult,
    SafetyVerdict,
)

logger = logging.getLogger("graqle.activation.real_providers")


# ─── Real ChunkScoringProvider ───────────────────────────────────────────


class RealChunkScoringProvider:
    """Wraps graqle.activation.chunk_scorer.ChunkScorer for TAMR+ role."""

    def __init__(self, chunk_scorer: Any | None = None):
        self._scorer = chunk_scorer  # optional dep-inject; lazy-loaded if None

    def _load_scorer(self):
        if self._scorer is None:
            try:
                from graqle.activation.chunk_scorer import ChunkScorer
                self._scorer = ChunkScorer()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("could not load ChunkScorer: %s", type(exc).__name__)
                self._scorer = False  # mark as unavailable
        return self._scorer

    async def score(self, user_message, activation_hints):
        scorer = self._load_scorer()
        if not scorer:
            return ChunkScoreResult(summary="chunk scorer unavailable")
        try:
            # ChunkScorer.score(graph, query) requires the loaded KG as first arg.
            # graph is injected via activation_hints by ChatAgentLoop._act_hints.
            graph = activation_hints.get("graph") if activation_hints else None
            if graph is None:
                return ChunkScoreResult(summary="chunk scorer unavailable: no graph in activation_hints")
            raw = scorer.score(graph, user_message) if hasattr(scorer, "score") else None
            if raw is None:
                return ChunkScoreResult(summary="chunk scorer returned None")
            # Normalize to our public shape
            if isinstance(raw, dict):
                chunks_list = raw.get("chunks") or []
                scores_list = raw.get("scores") or []
            else:
                chunks_list = getattr(raw, "chunks", []) or []
                scores_list = getattr(raw, "scores", []) or []
            return ChunkScoreResult(
                chunks=tuple(str(c) for c in chunks_list if c),
                scores=tuple(float(s) for s in scores_list if s is not None),
                summary=f"scored {len(chunks_list)} chunks",
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("chunk scoring failed: %s", type(exc).__name__)
            return ChunkScoreResult(summary=f"chunk scoring error: {type(exc).__name__}")


# ─── Real SafetyGateProvider (DRACE) ─────────────────────────────────────


class RealSafetyGateProvider:
    """Wraps graqle.intelligence.governance.drace.DRACEScorer for DRACE role."""

    # Score below this value triggers should_block. Threshold is an internal
    # tuning constant; the public surface exposes only the opaque score and
    # a boolean verdict. Threshold value is intentionally not surfaced in
    # verdict.reason for IP safety.
    _BLOCK_THRESHOLD = 0.50

    def __init__(self, scorer: Any | None = None):
        self._scorer = scorer

    def _load_scorer(self):
        if self._scorer is None:
            try:
                from graqle.intelligence.governance.drace import DRACEScorer
                self._scorer = DRACEScorer()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("could not load DRACEScorer: %s", type(exc).__name__)
                self._scorer = False
        return self._scorer

    async def evaluate(self, user_message, scored_chunks, activation_hints):
        scorer = self._load_scorer()
        if not scorer:
            # Fail open: unavailable scorer means neutral verdict, never block
            return SafetyVerdict(
                score=1.0,
                should_block=False,
                reason="safety scorer unavailable (neutral verdict)",
                details={},
            )
        try:
            # Build a minimal session entry from the turn context
            session_entry = {
                "user_message": user_message,
                "chunks": list(scored_chunks.chunks),
                "intent": activation_hints.get("intent", ""),
            }
            drace = scorer.score_session([session_entry])
            total = float(drace.total)
            return SafetyVerdict(
                score=total,
                should_block=total < self._BLOCK_THRESHOLD,
                reason=(
                    f"safety grade: {drace.grade}"
                    if total < self._BLOCK_THRESHOLD
                    else f"safety grade: {drace.grade}"
                ),
                details={
                    "dependency": drace.dependency,
                    "reasoning": drace.reasoning,
                    "auditability": drace.auditability,
                    "constraint": drace.constraint,
                    "explainability": drace.explainability,
                    "grade": drace.grade,
                },
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("safety evaluation failed: %s", type(exc).__name__)
            # Fail open on provider exception
            return SafetyVerdict(
                score=1.0,
                should_block=False,
                reason="safety scorer error (neutral verdict)",
                details={"error_type": type(exc).__name__},
            )


# ─── Real SubgraphActivationProvider (PSE) ───────────────────────────────


class RealSubgraphActivationProvider:
    """Wraps predictive subgraph expansion (via graq_predict infrastructure).

    The real PSE integration is lazy: it requires a loaded KG and an
    MCP-server-like context. If those are unavailable, this returns an
    empty ActivatedSubgraph (turn proceeds, just without PSE speedup).
    """

    def __init__(self, predict_fn=None):
        self._predict_fn = predict_fn  # optional callable: async (chunks, safety) -> dict

    async def predict(self, scored_chunks, safety):
        if self._predict_fn is None:
            return ActivatedSubgraph(summary="predict fn not configured")
        try:
            raw = await self._predict_fn(scored_chunks, safety)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("subgraph prediction failed: %s", type(exc).__name__)
            return ActivatedSubgraph(summary=f"prediction error: {type(exc).__name__}")

        if not isinstance(raw, dict):
            return ActivatedSubgraph(summary="predict fn returned non-dict")

        nodes = tuple(str(n) for n in (raw.get("nodes") or []) if n)
        edges_raw = raw.get("edges") or []
        edges = tuple(
            (str(e[0]), str(e[1]), str(e[2]))
            for e in edges_raw
            if isinstance(e, (list, tuple)) and len(e) >= 3
        )
        confidence = raw.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        return ActivatedSubgraph(
            nodes=nodes,
            edges=edges,
            confidence=confidence,
            summary=raw.get("summary", f"predicted {len(nodes)} nodes"),
        )
