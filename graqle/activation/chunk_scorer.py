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

"""ChunkScorer -- chunk-level relevance scoring for subgraph activation.

Replaces PCST's node-level embedding approach with chunk-level search.
Each chunk gets its own embedding and is scored independently against
the query. Parent nodes inherit the best chunk score.

v0.12.3: Embedding cache -- precompute chunk embeddings once, store in
.graqle/chunk_embeddings.npz. At query time only the query is
embedded (1 call), then fast numpy cosine similarity against all cached
chunk vectors. This reduces 11K-node activation from ~30s to <1s.
"""

# ── graqle:intelligence ──
# module: graqle.activation.chunk_scorer
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_chunk_scorer
# dependencies: __future__, hashlib, logging, pathlib, typing +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from graqle.activation.embeddings import EmbeddingEngine, cosine_similarity

if TYPE_CHECKING:
    from graqle.core.graph import Graqle

logger = logging.getLogger("graqle.activation.chunk_scorer")


class ChunkScorer:
    """Score nodes by chunk-level embedding similarity.

    For each node, every chunk is embedded separately and compared
    to the query embedding. The node's score is the MAX chunk score
    (best-matching chunk wins), not an average.

    v0.12.3: Uses precomputed embedding cache (.graqle/chunk_embeddings.npz)
    when available. Falls back to live embedding when cache is missing.
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine | None = None,
        max_nodes: int = 50,
        min_score: float = 0.15,
        domain_registry: Any | None = None,
    ) -> None:
        if embedding_engine is not None:
            self.embedding_engine = embedding_engine
        else:
            from graqle.activation.embeddings import create_embedding_engine
            from graqle.config.settings import GraqleConfig
            from pathlib import Path
            cfg = GraqleConfig.from_yaml(Path("graqle.yaml")) if Path("graqle.yaml").exists() else None
            self.embedding_engine = create_embedding_engine(cfg)
        self.max_nodes = max_nodes
        self.min_score = min_score
        self.last_relevance: dict[str, float] = {}
        self._domain_registry = domain_registry
        # Embedding cache: chunk_key -> embedding vector
        self._cache_loaded = False
        self._chunk_keys: list[str] = []        # [node_id::chunk_idx, ...]
        self._chunk_node_ids: list[str] = []     # parallel: node_id for each chunk
        self._chunk_matrix: np.ndarray | None = None  # (N, dim) matrix
        self._desc_keys: list[str] = []          # node_ids with desc-only embeddings
        self._desc_matrix: np.ndarray | None = None

    def _load_cache(self, graph: Any) -> bool:
        """Try loading precomputed chunk embeddings from .graqle/chunk_embeddings.npz."""
        if self._cache_loaded:
            return self._chunk_matrix is not None

        self._cache_loaded = True
        cache_path = Path(".graqle/chunk_embeddings.npz")
        if not cache_path.exists():
            return False

        try:
            data = np.load(str(cache_path), allow_pickle=True)
            self._chunk_keys = list(data["chunk_keys"])
            self._chunk_node_ids = list(data["chunk_node_ids"])
            self._chunk_matrix = data["chunk_matrix"]
            if "desc_keys" in data:
                self._desc_keys = list(data["desc_keys"])
                self._desc_matrix = data["desc_matrix"]
            logger.info(
                "Loaded embedding cache: %d chunks, %d desc-only nodes",
                len(self._chunk_keys), len(self._desc_keys),
            )
            return True
        except Exception as e:
            logger.warning("Failed to load embedding cache: %s", e)
            return False

    def build_cache(self, graph: Any) -> None:
        """Precompute embeddings for all chunks and save to .graqle/chunk_embeddings.npz.

        Called by `graq rebuild --embeddings` or `graq init`.
        """
        chunk_keys: list[str] = []
        chunk_node_ids: list[str] = []
        chunk_texts: list[str] = []
        desc_keys: list[str] = []
        desc_texts: list[str] = []

        for node_id, node in graph.nodes.items():
            chunks = node.properties.get("chunks", [])
            if not chunks:
                desc_text = f"{node.label} {node.entity_type} {node.description}"
                desc_keys.append(node_id)
                desc_texts.append(desc_text)
                continue

            for idx, chunk in enumerate(chunks):
                if isinstance(chunk, dict):
                    text = chunk.get("text", "")
                    chunk_type = chunk.get("type", "")
                elif isinstance(chunk, str):
                    text = chunk
                    chunk_type = ""
                else:
                    continue

                if not text or len(text.strip()) < 10:
                    continue

                chunk_text = f"{node.label} {chunk_type}: {text}"
                chunk_keys.append(f"{node_id}::{idx}")
                chunk_node_ids.append(node_id)
                chunk_texts.append(chunk_text)

        logger.info(
            "Building embedding cache: %d chunks + %d descriptions",
            len(chunk_texts), len(desc_texts),
        )

        # G4: Redact sensitive content before embedding API calls
        # Fail-CLOSED: security gate must load
        # Block SECRET+ content from cloud embedding
        from graqle.security.content_gate import ContentSecurityGate
        from graqle.security.sensitivity import SensitivityClassifier, SensitivityLevel
        _g4_gate = ContentSecurityGate()
        _g4_classifier = SensitivityClassifier()
        _redacted_chunk_texts = []
        for t in chunk_texts:
            level = _g4_classifier.classify_node({}, description=t)
            if level >= SensitivityLevel.SECRET:
                # Non-empty sentinel prevents API error
                _redacted_chunk_texts.append("[CONTENT_REDACTED]")
            else:
                _redacted_chunk_texts.append(_g4_gate.redact_for_embedding(t))
        chunk_texts = _redacted_chunk_texts
        desc_texts = [_g4_gate.redact_for_embedding(t) for t in desc_texts]

        # Batch embed
        chunk_embeddings = []
        for text in chunk_texts:
            chunk_embeddings.append(self.embedding_engine.embed(text))
        chunk_matrix = np.array(chunk_embeddings) if chunk_embeddings else np.empty((0, 0))

        desc_embeddings = []
        for text in desc_texts:
            desc_embeddings.append(self.embedding_engine.embed(text))
        desc_matrix = np.array(desc_embeddings) if desc_embeddings else np.empty((0, 0))

        # Save cache
        cache_dir = Path(".graqle")
        cache_dir.mkdir(exist_ok=True)
        np.savez_compressed(
            str(cache_dir / "chunk_embeddings.npz"),
            chunk_keys=np.array(chunk_keys, dtype=object),
            chunk_node_ids=np.array(chunk_node_ids, dtype=object),
            chunk_matrix=chunk_matrix,
            desc_keys=np.array(desc_keys, dtype=object),
            desc_matrix=desc_matrix,
        )

        # Load into memory
        self._chunk_keys = chunk_keys
        self._chunk_node_ids = chunk_node_ids
        self._chunk_matrix = chunk_matrix
        self._desc_keys = desc_keys
        self._desc_matrix = desc_matrix
        self._cache_loaded = True

        logger.info(
            "Embedding cache saved: %d chunks (%s), %d desc-only",
            len(chunk_keys),
            f"{chunk_matrix.nbytes / 1024:.0f}KB" if chunk_matrix.size else "0KB",
            len(desc_keys),
        )

    def _score_cached(self, graph: Any, query: str) -> dict[str, float]:
        """Fast scoring using precomputed embedding cache."""
        query_embedding = self.embedding_engine.embed(query)
        query_lower = query.lower()
        scores: dict[str, float] = {}

        # Batch cosine similarity: query vs all chunk embeddings
        if self._chunk_matrix is not None and self._chunk_matrix.size > 0:
            q = np.array(query_embedding).reshape(1, -1)
            # Normalize for cosine similarity
            q_norm = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-10)
            m_norm = self._chunk_matrix / (
                np.linalg.norm(self._chunk_matrix, axis=1, keepdims=True) + 1e-10
            )
            sims = (q_norm @ m_norm.T).flatten()

            # Aggregate: max similarity per node
            for i, node_id in enumerate(self._chunk_node_ids):
                sim = float(sims[i])
                if node_id not in scores or sim > scores[node_id]:
                    scores[node_id] = max(sim, 0.0)

        # Description-only nodes
        if self._desc_matrix is not None and self._desc_matrix.size > 0:
            q = np.array(query_embedding).reshape(1, -1)
            q_norm = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-10)
            d_norm = self._desc_matrix / (
                np.linalg.norm(self._desc_matrix, axis=1, keepdims=True) + 1e-10
            )
            sims = (q_norm @ d_norm.T).flatten()
            for i, node_id in enumerate(self._desc_keys):
                sim = float(sims[i]) * 0.5  # penalize: no chunks
                if node_id not in scores or sim > scores[node_id]:
                    scores[node_id] = max(sim, 0.0)

        # Filter out stale cache references (node IDs that no longer exist in graph)
        live_ids = set(graph.nodes.keys())
        scores = {nid: s for nid, s in scores.items() if nid in live_ids}

        # Filename boost
        for node_id, node in graph.nodes.items():
            label_lower = (node.label or "").lower()
            if label_lower and len(label_lower) >= 3:
                bare = label_lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                bare_no_ext = bare.rsplit(".", 1)[0] if "." in bare else bare
                if len(bare_no_ext) >= 3 and (bare in query_lower or bare_no_ext in query_lower):
                    scores[node_id] = max(scores.get(node_id, 0.0), 2.0)

        return scores

    def score(
        self, graph: Graqle, query: str
    ) -> dict[str, float]:
        """Score all nodes by chunk-level similarity.

        Uses embedding cache when available (O(1) embed + O(N) cosine).
        Falls back to live embedding when cache is missing (O(N*chunks) embed).

        Returns dict mapping node_id -> best_chunk_score.
        """
        # Try cached path first (fast: 1 embed call + batch cosine)
        if self._load_cache(graph):
            return self._score_cached(graph, query)

        # Fallback: live embedding per chunk (slow for large graphs)
        query_embedding = self.embedding_engine.embed(query)
        query_lower = query.lower()
        scores: dict[str, float] = {}

        for node_id, node in graph.nodes.items():
            chunks = node.properties.get("chunks", [])

            if not chunks:
                desc_text = f"{node.label} {node.entity_type} {node.description}"
                desc_emb = self.embedding_engine.embed(desc_text)
                sim = float(cosine_similarity(query_embedding, desc_emb))
                scores[node_id] = max(sim * 0.5, 0.0)
                continue

            best_chunk_score = 0.0
            for chunk in chunks:
                if isinstance(chunk, dict):
                    text = chunk.get("text", "")
                    chunk_type = chunk.get("type", "")
                elif isinstance(chunk, str):
                    text = chunk
                    chunk_type = ""
                else:
                    continue

                if not text or len(text.strip()) < 10:
                    continue

                chunk_text = f"{node.label} {chunk_type}: {text}"
                chunk_emb = self.embedding_engine.embed(chunk_text)
                sim = float(cosine_similarity(query_embedding, chunk_emb))

                if sim > best_chunk_score:
                    best_chunk_score = sim

            scores[node_id] = max(best_chunk_score, 0.0)

            label_lower = (node.label or "").lower()
            if label_lower and len(label_lower) >= 3:
                bare = label_lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                bare_no_ext = bare.rsplit(".", 1)[0] if "." in bare else bare
                if len(bare_no_ext) >= 3 and (bare in query_lower or bare_no_ext in query_lower):
                    scores[node_id] = max(scores[node_id], 2.0)

        return scores

    def _property_search_fallback(
        self, graph: Any, query: str
    ) -> dict[str, float]:
        """Fallback: regex-match on node IDs, labels, and descriptions.

        Used when embedding-based activation returns low confidence.
        This mirrors Neo4j's ``WHERE n.id =~ '.*pattern.*'`` approach.
        """
        import re

        scores: dict[str, float] = {}

        # Extract meaningful keywords from query (3+ chars, not stopwords)
        stopwords = {
            "the", "and", "for", "from", "with", "that", "this", "what",
            "how", "does", "which", "where", "when", "who", "are", "was",
            "will", "can", "into", "each", "all", "its", "our", "your",
            "has", "have", "had", "been", "being", "their", "them",
            "trace", "show", "find", "list", "give", "tell", "explain",
            "flow", "between", "across", "through",
        }
        words = re.findall(r"[a-zA-Z_]\w{2,}", query.lower())
        keywords = [w for w in words if w not in stopwords]

        if not keywords:
            return scores

        # Build regex patterns from keywords
        patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]

        for node_id, node in graph.nodes.items():
            label = node.label or ""
            desc = node.description or ""
            # Also check the raw node_id path
            searchable = f"{node_id} {label} {desc}"

            # Score: number of keyword matches / total keywords
            matches = sum(1 for pat in patterns if pat.search(searchable))
            if matches > 0:
                score = matches / len(keywords)
                # Bonus for matching in node ID (strongest signal)
                id_matches = sum(1 for pat in patterns if pat.search(node_id))
                if id_matches:
                    score += 0.3 * (id_matches / len(keywords))
                # Bonus for matching in label
                label_matches = sum(1 for pat in patterns if pat.search(label))
                if label_matches:
                    score += 0.2 * (label_matches / len(keywords))
                scores[node_id] = min(score, 1.5)  # cap to avoid dominating

        return scores

    def _skill_aware_boost(
        self, graph: Graqle, query: str, scores: dict[str, float],
    ) -> int:
        """Boost nodes whose entity_type has skills matching query keywords.

        Extracts keywords from skill names (e.g. "audit_auth_flow" →
        {"audit", "auth", "flow"}) and matches against query words.
        Nodes with matching skills get a +0.15 boost per matching skill
        (capped at +0.45 total).

        Returns count of boosted nodes.
        """
        if self._domain_registry is None:
            return 0

        import re
        query_words = set(re.findall(r"\b[a-z]{3,}\b", query.lower()))
        if not query_words:
            return 0

        # Build a cache of entity_type → skill keywords (once per call)
        type_skill_keywords: dict[str, set[str]] = {}
        boosted = 0

        for nid in scores:
            node = graph.nodes.get(nid) if hasattr(graph, 'nodes') else None
            if node is None:
                continue
            etype = getattr(node, "entity_type", None) or ""
            if not etype:
                continue

            if etype not in type_skill_keywords:
                skills = self._domain_registry.get_skills_for_type(etype)
                kw: set[str] = set()
                for s in skills:
                    kw.update(s.lower().split("_"))
                # Remove very short / generic words
                kw.discard("")
                kw -= {"check", "the", "and", "for"}
                type_skill_keywords[etype] = kw

            skill_kw = type_skill_keywords[etype]
            if not skill_kw:
                continue

            matched = query_words & skill_kw
            if matched:
                boost = min(len(matched) * 0.15, 0.45)
                scores[nid] += boost
                boosted += 1

        return boosted

    def activate(
        self, graph: Graqle, query: str,
        activation_boosts: dict[str, float] | None = None,
    ) -> list[str]:
        """Activate the top-N nodes by chunk-level scoring.

        Uses a 2-tier strategy:
        1. Embedding-based chunk scoring (semantic similarity)
        2. Property-based fallback (regex on node IDs/labels/descriptions)
           when semantic scores are low — prevents the "activation misses
           obvious matches" problem on large multi-repo graphs.

        Args:
            graph: Graqle instance
            query: The reasoning query
            activation_boosts: Optional {node_id: boost} from ActivationMemory.

        Side effect: stores relevance scores in ``self.last_relevance``.

        Returns:
            List of activated node IDs, sorted by relevance descending.
        """
        scores = self.score(graph, query)

        if activation_boosts:
            boosted_count = 0
            for nid, boost in activation_boosts.items():
                if nid in scores:
                    scores[nid] += boost
                    boosted_count += 1
            if boosted_count:
                logger.info(
                    "Applied activation memory boosts to %d nodes", boosted_count
                )

        # Skill-aware boost: nodes whose entity_type has skills
        # matching query keywords get a relevance bump.
        if self._domain_registry is not None:
            skill_boosted = self._skill_aware_boost(graph, query, scores)
            if skill_boosted:
                logger.info(
                    "Skill-aware boost applied to %d nodes", skill_boosted
                )

        # Property-based fallback: when semantic scores are weak,
        # augment with regex matches on node IDs/labels/descriptions.
        # This catches cases like "onboarding flow" matching
        # "onboarding_service.py" even when embeddings miss it.
        top_semantic = sorted(scores.values(), reverse=True)[:5]
        avg_top = sum(top_semantic) / max(len(top_semantic), 1)

        # Lower threshold for multi-file / broad-scope queries
        import re as _re_fb
        _multi_file_kw = _re_fb.compile(
            r"\b(?:audit|consistency|completeness|compare|across|review\s+all|check\s+all)\b",
            _re_fb.IGNORECASE,
        )
        fallback_threshold = 0.25 if _multi_file_kw.search(query) else 0.35

        if avg_top < fallback_threshold:
            property_scores = self._property_search_fallback(graph, query)
            fallback_count = 0
            for nid, pscore in property_scores.items():
                if pscore > scores.get(nid, 0.0):
                    scores[nid] = pscore
                    fallback_count += 1
            if fallback_count:
                logger.info(
                    "Property fallback augmented %d nodes (avg_semantic=%.3f)",
                    fallback_count, avg_top,
                )

        candidates = [
            (nid, score) for nid, score in scores.items()
            if score >= self.min_score
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        activated = candidates[:self.max_nodes]

        self.last_relevance = {nid: score for nid, score in activated}

        if activated:
            logger.info(
                "ChunkScorer activated %d nodes (top: %s=%.3f, cutoff: %.3f)",
                len(activated),
                activated[0][0],
                activated[0][1],
                self.min_score,
            )
        else:
            logger.warning("ChunkScorer: no nodes above min_score=%.3f", self.min_score)

        return [nid for nid, _ in activated]
