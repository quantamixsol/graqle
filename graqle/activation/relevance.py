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

"""Query-node relevance scoring for subgraph activation.

v3: Content-richness-aware + property-aware + filename-match scoring.
- Node embedding includes label + type + description + top chunk summaries
- Property-aware boosts for framework/article matches
- Content-hash caching for embedding invalidation
- Layer 1 (ADR-103): log2 content richness multiplier — nodes with chunks
  score higher than empty structural nodes (directories, namespaces)
- Layer 3 partial (ADR-103): Direct filename match boost — when the query
  mentions a specific filename, that node is guaranteed selection
"""

# ── graqle:intelligence ──
# module: graqle.activation.relevance
# risk: MEDIUM (impact radius: 5 modules)
# consumers: pcst, __init__, test_content_aware_pcst, test_pcst, test_relevance_chunks
# dependencies: __future__, hashlib, logging, math, re +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from graqle.activation.embeddings import EmbeddingEngine, cosine_similarity

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.relevance")

# Minimum content multiplier for nodes with zero chunks.
# log2(2 + 0) = 1.0, so zero-chunk nodes get no boost (neutral).
# log2(2 + 3) ≈ 2.32, so a node with 3 chunks gets ~2.3x the prize.
_CONTENT_RICHNESS_BASE = 2


class RelevanceScorer:
    """Computes relevance scores between a query and graph nodes.

    Scores are used as PCST prizes — higher relevance = higher prize
    = more likely to be included in the activated subgraph.

    v3 scoring formula:
        base_score      = max(cosine_similarity(query_emb, node_emb), 0)
        property_boost  = framework/article/entity_type match bonuses
        content_mult    = log2(2 + chunk_count)   # ≥1.0; 0 chunks → 1.0
        filename_bonus  = 2.0 if query mentions this node's filename else 0
        final_score     = max(base_score × content_mult, filename_bonus)
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine | None = None,
        chunk_aware: bool = True,
        property_boost: bool = True,
        max_chunks: int = 5,
        max_chunk_chars: int = 500,
    ) -> None:
        self.embedding_engine = embedding_engine or EmbeddingEngine()
        self.chunk_aware = chunk_aware
        self.property_boost = property_boost
        self.max_chunks = max_chunks
        self.max_chunk_chars = max_chunk_chars

    def score(
        self, graph: Graqle, query: str
    ) -> dict[str, float]:
        """Compute relevance scores for all nodes.

        Returns dict mapping node_id → score (unbounded, higher = better).
        The score is NOT clamped to [0, 1] because PCST prizes can exceed 1.
        """
        query_embedding = self.embedding_engine.embed(query)
        query_lower = query.lower()

        scores: dict[str, float] = {}
        for node_id, node in graph.nodes.items():
            # Build embedding text — chunk-aware (v2)
            emb_text = self._build_embedding_text(node)
            content_hash = hashlib.md5(emb_text.encode()).hexdigest()

            # Recompute embedding if content changed or not cached
            cached_hash = node.properties.get("_emb_hash", "")
            if node.embedding is None or cached_hash != content_hash:
                node.embedding = self.embedding_engine.embed(emb_text)
                node.properties["_emb_hash"] = content_hash

            sim = cosine_similarity(query_embedding, node.embedding)
            score = max(sim, 0.0)

            # Property-aware boosts (v2)
            if self.property_boost:
                score = self._apply_property_boosts(score, node, query_lower)

            # --- Layer 1 (ADR-103): Content richness multiplier ---
            # Nodes with evidence chunks get a logarithmic prize boost.
            # This ensures PCST prefers content-bearing nodes (JSModule,
            # Module, Config) over structural connectors (Directory,
            # Namespace) which typically have zero chunks.
            chunk_count = len(node.properties.get("chunks", []))
            content_multiplier = math.log2(
                _CONTENT_RICHNESS_BASE + chunk_count
            )  # log2(2)=1.0 (neutral), log2(5)≈2.32 for 3 chunks
            score = score * content_multiplier

            # --- Layer 3 partial (ADR-103): Direct filename match boost ---
            # When the query explicitly mentions a file (e.g., "auth.ts",
            # "payment_service"), guarantee that node's selection by
            # assigning a floor score of 2.0.
            score = self._apply_filename_boost(score, node, query_lower)

            scores[node_id] = score

        return scores

    def _build_embedding_text(self, node: Any) -> str:
        """Build embedding text — includes chunks for chunk-aware activation.

        v4: Prioritizes function/class chunks over module headers.
        Configurable via ``max_chunks`` (default 5) and ``max_chunk_chars``
        (default 500). For complex queries needing more context, increase
        ``max_chunk_chars`` (e.g. 2000) or use Neo4j mode where each chunk
        gets its own dedicated embedding with no truncation.
        """
        parts = [node.label, node.entity_type, node.description]

        if self.chunk_aware:
            chunks = node.properties.get("chunks", [])
            # Prioritize function/class chunks — these carry the most
            # semantically meaningful content for activation matching
            sorted_chunks = sorted(
                chunks,
                key=lambda c: (
                    0 if (isinstance(c, dict) and c.get("type") in (
                        "function", "class", "method", "export",
                    )) else 1
                ),
            )
            for chunk in sorted_chunks[:self.max_chunks]:
                if isinstance(chunk, dict):
                    text = chunk.get("text", "")
                elif isinstance(chunk, str):
                    text = chunk
                else:
                    continue
                if text:
                    parts.append(text[:self.max_chunk_chars])

        return " ".join(p for p in parts if p)

    @staticmethod
    def _apply_property_boosts(
        score: float, node: Any, query_lower: str
    ) -> float:
        """Apply property-aware boosts based on query-node property matches.

        Returns the boosted score — NOT clamped to 1.0, because the content
        multiplier (Layer 1) may further scale this value.
        """
        boost = 0.0

        # Framework name boost: query mentions framework AND node has matching framework
        framework = node.properties.get("framework", "")
        if framework and framework.lower() in query_lower:
            boost += 0.25

        # Article number boost: query mentions article AND node has matching articles
        articles = node.properties.get("articles", [])
        if articles:
            if isinstance(articles, str):
                articles = [articles]
            for art in articles:
                art_str = str(art).lower()
                # Match patterns like "art. 14", "article 14", "art 14"
                art_num = re.sub(r"[^0-9]", "", art_str)
                if art_num and (
                    f"art. {art_num}" in query_lower
                    or f"article {art_num}" in query_lower
                    or f"art {art_num}" in query_lower
                ):
                    boost += 0.3
                    break

        # Entity type name in query
        if node.entity_type.lower().replace("_", " ") in query_lower:
            boost += 0.1

        return score + boost

    @staticmethod
    def _apply_filename_boost(
        score: float, node: Any, query_lower: str
    ) -> float:
        """Layer 3 partial (ADR-103): boost nodes whose filename is mentioned in the query.

        Edge cases handled:
        - Short labels (<3 chars) are skipped to avoid false matches
          (e.g., node label "a" matching the word "a" in the query).
        - Labels with path separators are stripped to the basename.
        - Extension is stripped for matching ("auth.ts" matches "auth").
        - Both full label and bare name (without extension) are tried.
        - The boost is a *floor* (max), not additive — so a node already
          scoring 3.0 from content richness isn't capped downward.
        """
        label = (node.label or "").strip()
        if not label or len(label) < 3:
            return score

        # Normalize: take basename, lowercase
        label_lower = label.lower()
        # Handle paths: "src/services/auth.ts" → "auth.ts"
        if "/" in label_lower or "\\" in label_lower:
            label_lower = label_lower.replace("\\", "/").rsplit("/", 1)[-1]

        # bare_name = "auth" from "auth.ts"
        bare_name = label_lower.rsplit(".", 1)[0] if "." in label_lower else label_lower

        # Skip very short bare names to avoid false positives
        if len(bare_name) < 3:
            return score

        # Check if query mentions this file by full name or bare name
        # Use word boundary check to avoid substring false matches
        # e.g., "authentication" should not match "auth"
        matched = False
        if label_lower in query_lower:
            matched = True
        elif bare_name in query_lower:
            # Verify it's a word boundary match (not a substring)
            # "auth" in "authentication" → NO
            # "auth" in "the auth service" → YES
            import re as _re
            if _re.search(rf"(?:^|[\s\-_/\\.,;:\"'()]){_re.escape(bare_name)}(?:[\s\-_/\\.,;:\"'()]|$)", query_lower):
                matched = True

        if matched:
            # Guarantee selection: floor at 2.0
            return max(score, 2.0)

        return score
