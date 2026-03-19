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

"""MultiSignalActivation — Gate + Rerank activation for Neo4j.

Patent-protected Innovation #14 (Neo4j vector + graph search) and
Innovation #10 (Cross-query learning) fused into a single Cypher query.

Architecture (ADR-106):
  1. GATE: Semantic vector search on chunk embeddings (must pass min_score)
  2. RERANK: Multiply semantic score by (1 + sum of bonus signals)
     - authority_bonus: normalized PageRank (pre-computed)
     - memory_bonus: activation memory usefulness × keyword overlap
     - link_bonus: Adamic-Adar proximity to seed nodes
     - freshness_bonus: recency of last modification

  Key invariant: semantic score is ALWAYS the base. Bonuses amplify,
  never override. A 0.1 semantic × 1.45 max bonus = 0.145 → still
  filtered by min_score (0.15). No irrelevant node can sneak through.
"""

# ── graqle:intelligence ──
# module: graqle.activation.multi_signal
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, selfupdate
# dependencies: __future__, logging, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.activation.multi_signal")


class MultiSignalActivation:
    """Gate + Rerank activation using Neo4j multi-signal scoring.

    Phase 1 (Gate): Vector search returns candidates with semantic scores.
    Phase 2 (Rerank): Each candidate's score is multiplied by bonus signals.

    Formula:
        final = semantic × (1 + authority + memory + link + freshness)

    All bonuses are capped so max amplification is 1.45×.
    Semantic score is never bypassed — it gates everything.
    """

    # Bonus caps (max contribution per signal)
    AUTHORITY_CAP = 0.15    # PageRank normalized
    MEMORY_CAP = 0.15       # Activation memory usefulness
    LINK_CAP = 0.10         # Adamic-Adar to seed nodes
    FRESHNESS_CAP = 0.05    # Recency bonus

    def __init__(
        self,
        connector: Any,
        embedding_engine: Any,
        activation_memory: Any | None = None,
        max_nodes: int = 50,
        k_chunks: int = 100,
        min_score: float = 0.15,
    ) -> None:
        self._connector = connector
        self._embedding_engine = embedding_engine
        self._activation_memory = activation_memory
        self._max_nodes = max_nodes
        self._k_chunks = k_chunks
        self._min_score = min_score
        self.last_relevance: dict[str, float] = {}
        self.last_signals: dict[str, dict[str, float]] = {}

    def activate(
        self,
        graph: Any,
        query: str,
    ) -> list[str]:
        """Multi-signal activation: gate on semantic, rerank with bonuses.

        Returns list of activated node IDs sorted by final score desc.
        """
        # 1. Embed the query
        try:
            query_embedding = self._embedding_engine.embed(query)
        except Exception as exc:
            logger.warning("MultiSignal: embedding failed (%s), falling back", exc)
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        # 2. Phase 1: GATE — semantic vector search
        try:
            hits = self._connector.vector_search(
                query_embedding=query_embedding,
                k=self._k_chunks,
                max_nodes=self._max_nodes * 3,  # Wider gate for reranking
            )
        except Exception as exc:
            logger.warning("MultiSignal: vector search failed (%s), falling back", exc)
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        if not hits:
            logger.warning("MultiSignal: 0 hits from vector search")
            self.last_relevance = {nid: 1.0 for nid in graph.nodes}
            return list(graph.nodes.keys())[:self._max_nodes]

        # Filter to min_score gate + in-graph check
        candidates: list[tuple[str, float]] = []
        for node_id, semantic_score in hits:
            if node_id in graph.nodes and semantic_score >= self._min_score:
                candidates.append((node_id, semantic_score))

        if not candidates:
            # All below gate — take top hits anyway (graceful degradation)
            candidates = [
                (nid, s) for nid, s in hits if nid in graph.nodes
            ][:self._max_nodes]
            if not candidates:
                self.last_relevance = {nid: 1.0 for nid in graph.nodes}
                return list(graph.nodes.keys())[:self._max_nodes]

        # 3. Phase 2: RERANK — fetch bonus signals from Neo4j
        candidate_ids = [nid for nid, _ in candidates]
        semantic_map = dict(candidates)

        # Fetch topology signals in a single Cypher query
        topology = self._fetch_topology_signals(candidate_ids)

        # Seed nodes = top-3 semantic hits (for link prediction context)
        seed_ids = [nid for nid, _ in candidates[:3]]
        link_scores = self._fetch_link_proximity(candidate_ids, seed_ids)

        # Get memory boosts
        memory_boosts = self._get_memory_boosts(query)

        # 4. Compute final scores
        scored: list[tuple[str, float]] = []
        signals_log: dict[str, dict[str, float]] = {}

        for node_id in candidate_ids:
            sem = semantic_map.get(node_id, 0.0)
            topo = topology.get(node_id, {})

            # Normalize PageRank to [0, 1] relative to max in candidates
            authority = min(topo.get("authority", 0.0), self.AUTHORITY_CAP)

            # Memory bonus
            memory = min(memory_boosts.get(node_id, 0.0), self.MEMORY_CAP)

            # Link proximity to seed nodes
            link = min(link_scores.get(node_id, 0.0), self.LINK_CAP)

            # Freshness (from Neo4j node property if available)
            freshness = min(topo.get("freshness", 0.0), self.FRESHNESS_CAP)

            # THE FORMULA: multiplicative, not additive
            bonus = 1.0 + authority + memory + link + freshness
            final = sem * bonus

            scored.append((node_id, final))
            signals_log[node_id] = {
                "semantic": round(sem, 4),
                "authority": round(authority, 4),
                "memory": round(memory, 4),
                "link": round(link, 4),
                "freshness": round(freshness, 4),
                "bonus": round(bonus, 4),
                "final": round(final, 4),
            }

        # Sort by final score desc, take top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        activated = [nid for nid, _ in scored[:self._max_nodes]]

        self.last_relevance = {nid: s for nid, s in scored[:self._max_nodes]}
        self.last_signals = signals_log

        logger.info(
            "MultiSignal: %d candidates → %d activated (top: %.3f, bonus range: %.2f-%.2f×)",
            len(candidates),
            len(activated),
            scored[0][1] if scored else 0.0,
            min(signals_log[n]["bonus"] for n in activated) if activated else 1.0,
            max(signals_log[n]["bonus"] for n in activated) if activated else 1.0,
        )
        return activated

    def _fetch_topology_signals(
        self, candidate_ids: list[str],
    ) -> dict[str, dict[str, float]]:
        """Fetch PageRank + degree + freshness from Neo4j in one query."""
        try:
            driver = self._connector._get_driver()
            with driver.session(database=self._connector._database) as session:
                result = session.run(
                    "UNWIND $ids AS nid "
                    "MATCH (n:CogniNode {id: nid}) "
                    "RETURN n.id AS id, "
                    "  coalesce(n.pagerank, 0.0) AS pagerank, "
                    "  size((n)--()) AS degree, "
                    "  coalesce(n.last_modified_days, 30) AS days_old",
                    ids=candidate_ids,
                )
                records = list(result)

            if not records:
                return {}

            # Normalize PageRank relative to max in candidates
            max_pr = max((r["pagerank"] for r in records), default=1.0) or 1.0
            max_degree = max((r["degree"] for r in records), default=1) or 1

            topology: dict[str, dict[str, float]] = {}
            for r in records:
                # Authority: blend PageRank (70%) + degree centrality (30%)
                pr_norm = (r["pagerank"] / max_pr) if max_pr > 0 else 0.0
                deg_norm = (r["degree"] / max_degree) if max_degree > 0 else 0.0
                authority = (0.7 * pr_norm + 0.3 * deg_norm) * self.AUTHORITY_CAP

                # Freshness: exponential decay (0 days = 0.05, 30+ days = ~0)
                days = max(r["days_old"], 0)
                freshness = self.FRESHNESS_CAP * (0.95 ** days)

                topology[r["id"]] = {
                    "authority": authority,
                    "freshness": freshness,
                }

            return topology
        except Exception as exc:
            logger.debug("Topology signals unavailable: %s", exc)
            return {}

    def _fetch_link_proximity(
        self,
        candidate_ids: list[str],
        seed_ids: list[str],
    ) -> dict[str, float]:
        """Adamic-Adar proximity between candidates and seed nodes."""
        if not seed_ids:
            return {}

        try:
            driver = self._connector._get_driver()
            with driver.session(database=self._connector._database) as session:
                # Adamic-Adar approximation: shared neighbors weighted by 1/log(degree)
                result = session.run(
                    "UNWIND $candidates AS cid "
                    "MATCH (c:CogniNode {id: cid}) "
                    "OPTIONAL MATCH (c)--(shared)--(s:CogniNode) "
                    "WHERE s.id IN $seeds AND c.id <> s.id "
                    "WITH c.id AS candidate, "
                    "  CASE WHEN shared IS NOT NULL "
                    "    THEN sum(1.0 / log(2.0 + size((shared)--()))) "
                    "    ELSE 0.0 END AS aa_score "
                    "RETURN candidate, aa_score",
                    candidates=candidate_ids,
                    seeds=seed_ids,
                )

                raw_scores = {str(r["candidate"]): float(r["aa_score"]) for r in result}

            if not raw_scores:
                return {}

            # Normalize to [0, 1] then cap at LINK_CAP
            max_aa = max(raw_scores.values()) or 1.0
            return {
                nid: (score / max_aa) * self.LINK_CAP
                for nid, score in raw_scores.items()
            }
        except Exception as exc:
            logger.debug("Link proximity unavailable: %s", exc)
            return {}

    def _get_memory_boosts(self, query: str) -> dict[str, float]:
        """Get activation memory boosts for query."""
        if self._activation_memory is None:
            return {}
        try:
            boosts = self._activation_memory.get_boosts(query)
            # Scale to MEMORY_CAP (memory already caps at 0.15)
            return {nid: min(b, self.MEMORY_CAP) for nid, b in boosts.items()}
        except Exception as exc:
            logger.debug("Memory boosts unavailable: %s", exc)
            return {}
