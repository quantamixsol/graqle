"""Neo4j GDS Intelligence — graph-topology-based link prediction and community detection.

Uses Neo4j Graph Data Science (GDS) algorithms when a Neo4j connector is active,
with pure-NetworkX fallbacks for JSON-only graphs. This module provides:

1. Link Prediction: Adamic Adar, Common Neighbors, Preferential Attachment
2. Community Detection: Louvain algorithm
3. Node Similarity: Jaccard/Overlap coefficient
4. Missing Link Discovery: topology-based edge suggestions

All algorithms work in two modes:
- **Neo4j GDS mode**: Runs algorithms on the server (scales to millions of nodes)
- **NetworkX mode**: Runs locally (works without Neo4j, good for <50K nodes)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.learning.gds")


@dataclass
class LinkPrediction:
    """A predicted (missing) link between two nodes."""
    source: str
    target: str
    score: float
    algorithm: str
    reason: str = ""


@dataclass
class Community:
    """A detected community/cluster of nodes."""
    id: int
    members: list[str]
    size: int
    label: str = ""  # Auto-generated from dominant entity types


@dataclass
class SimilarityPair:
    """A pair of nodes with their similarity score."""
    node_a: str
    node_b: str
    score: float
    shared_neighbors: list[str] = field(default_factory=list)


@dataclass
class GDSReport:
    """Complete GDS intelligence report."""
    link_predictions: list[LinkPrediction]
    communities: list[Community]
    similarities: list[SimilarityPair]
    method: str  # "neo4j_gds" or "networkx"
    stats: dict[str, Any] = field(default_factory=dict)


class GDSIntelligence:
    """Graph Data Science intelligence layer.

    Provides link prediction, community detection, and node similarity
    using either Neo4j GDS (when available) or NetworkX (fallback).
    """

    def __init__(self, graph: Any, neo4j_connector: Any | None = None) -> None:
        """Initialize with a Graqle graph and optional Neo4j connector.

        Args:
            graph: A Graqle instance.
            neo4j_connector: Optional Neo4jConnector for server-side GDS algorithms.
        """
        self._graph = graph
        self._neo4j = neo4j_connector
        self._gds_available = False

        if neo4j_connector is not None:
            self._gds_available = self._check_gds()

    def _check_gds(self) -> bool:
        """Check if Neo4j GDS plugin is available."""
        if self._neo4j is None:
            return False
        try:
            driver = self._neo4j._get_driver()
            with driver.session(database=self._neo4j._database) as session:
                result = session.run("RETURN gds.version() AS version")
                version = result.single()["version"]
                logger.info("Neo4j GDS available: v%s", version)
                return True
        except Exception as e:
            logger.debug("Neo4j GDS not available: %s", e)
            return False

    @property
    def method(self) -> str:
        return "neo4j_gds" if self._gds_available else "networkx"

    # =========================================================================
    # Link Prediction
    # =========================================================================

    def predict_links(
        self,
        *,
        top_k: int = 20,
        min_score: float = 0.01,
        algorithms: list[str] | None = None,
        focus_nodes: list[str] | None = None,
    ) -> list[LinkPrediction]:
        """Predict missing links using multiple algorithms.

        Args:
            top_k: Number of top predictions to return per algorithm.
            min_score: Minimum score threshold.
            algorithms: List of algorithms to use. Default: all available.
                Options: "adamic_adar", "common_neighbors", "preferential_attachment"
            focus_nodes: If provided, only predict links involving these nodes.

        Returns:
            Sorted list of LinkPrediction objects (highest score first).
        """
        if algorithms is None:
            algorithms = ["adamic_adar", "common_neighbors", "preferential_attachment"]

        if self._gds_available:
            return self._predict_links_gds(
                top_k=top_k, min_score=min_score, algorithms=algorithms,
                focus_nodes=focus_nodes,
            )
        return self._predict_links_nx(
            top_k=top_k, min_score=min_score, algorithms=algorithms,
            focus_nodes=focus_nodes,
        )

    def _predict_links_nx(
        self,
        *,
        top_k: int,
        min_score: float,
        algorithms: list[str],
        focus_nodes: list[str] | None,
    ) -> list[LinkPrediction]:
        """Link prediction using NetworkX algorithms."""
        import networkx as nx

        G = self._graph.to_networkx()
        # Convert to undirected for link prediction algorithms
        G_undirected = G.to_undirected()

        all_predictions: list[LinkPrediction] = []

        # Build candidate pairs
        if focus_nodes:
            # Only pairs involving focus nodes
            candidates = [
                (u, v) for u in focus_nodes if u in G_undirected
                for v in G_undirected.nodes()
                if u != v and not G_undirected.has_edge(u, v)
            ]
        else:
            candidates = list(nx.non_edges(G_undirected))
            # For large graphs, sample to avoid O(n^2) explosion
            if len(candidates) > 50000:
                import random
                random.shuffle(candidates)
                candidates = candidates[:50000]

        if not candidates:
            return []

        for algo_name in algorithms:
            try:
                if algo_name == "adamic_adar":
                    preds = nx.adamic_adar_index(G_undirected, candidates)
                    for u, v, score in preds:
                        if score >= min_score:
                            all_predictions.append(LinkPrediction(
                                source=u, target=v, score=score,
                                algorithm="adamic_adar",
                                reason=f"Adamic-Adar index: {score:.4f}",
                            ))

                elif algo_name == "common_neighbors":
                    preds = nx.common_neighbor_centrality(G_undirected, candidates)
                    for u, v, score in preds:
                        if score >= min_score:
                            cn_list = sorted(nx.common_neighbors(G_undirected, u, v))
                            all_predictions.append(LinkPrediction(
                                source=u, target=v, score=score,
                                algorithm="common_neighbors",
                                reason=f"{len(cn_list)} common neighbor(s): {', '.join(cn_list[:5])}",
                            ))

                elif algo_name == "preferential_attachment":
                    preds = nx.preferential_attachment(G_undirected, candidates)
                    for u, v, score in preds:
                        # Normalize PA score to 0-1 range for comparability
                        max_degree = max(d for _, d in G_undirected.degree()) or 1
                        norm_score = score / (max_degree ** 2) if max_degree > 0 else 0
                        if norm_score >= min_score:
                            all_predictions.append(LinkPrediction(
                                source=u, target=v, score=norm_score,
                                algorithm="preferential_attachment",
                                reason=f"Preferential attachment: {score} (deg({u})={G_undirected.degree(u)}, deg({v})={G_undirected.degree(v)})",
                            ))

            except Exception as e:
                logger.warning("Link prediction algorithm '%s' failed: %s", algo_name, e)

        # Deduplicate (keep highest score per pair)
        seen: dict[tuple[str, str], LinkPrediction] = {}
        for pred in all_predictions:
            key = (min(pred.source, pred.target), max(pred.source, pred.target))
            if key not in seen or pred.score > seen[key].score:
                seen[key] = pred
        deduped = sorted(seen.values(), key=lambda p: p.score, reverse=True)
        return deduped[:top_k]

    def _predict_links_gds(
        self,
        *,
        top_k: int,
        min_score: float,
        algorithms: list[str],
        focus_nodes: list[str] | None,
    ) -> list[LinkPrediction]:
        """Link prediction using Neo4j GDS server-side algorithms."""
        all_predictions: list[LinkPrediction] = []
        driver = self._neo4j._get_driver()

        graph_name = "_graqle_link_pred_temp"

        try:
            with driver.session(database=self._neo4j._database) as session:
                # Project a temporary in-memory graph
                session.run(
                    "CALL gds.graph.project($name, 'CogniNode', "
                    "{RELATED_TO: {orientation: 'UNDIRECTED'}, "
                    " SEMANTICALLY_RELATED: {orientation: 'UNDIRECTED'}, "
                    " DEPENDS_ON: {orientation: 'UNDIRECTED'}})",
                    name=graph_name,
                )

                focus_filter = ""
                params: dict[str, Any] = {"name": graph_name, "top_k": top_k}
                if focus_nodes:
                    focus_filter = "WHERE node1.id IN $focus OR node2.id IN $focus"
                    params["focus"] = focus_nodes

                for algo_name in algorithms:
                    try:
                        if algo_name == "adamic_adar":
                            result = session.run(
                                f"CALL gds.alpha.linkprediction.adamicAdar.stream($name) "
                                f"YIELD node1, node2, score "
                                f"{focus_filter} "
                                f"RETURN node1.id AS source, node2.id AS target, score "
                                f"ORDER BY score DESC LIMIT $top_k",
                                **params,
                            )
                        elif algo_name == "common_neighbors":
                            result = session.run(
                                f"CALL gds.alpha.linkprediction.commonNeighbors.stream($name) "
                                f"YIELD node1, node2, score "
                                f"{focus_filter} "
                                f"RETURN node1.id AS source, node2.id AS target, score "
                                f"ORDER BY score DESC LIMIT $top_k",
                                **params,
                            )
                        elif algo_name == "preferential_attachment":
                            result = session.run(
                                f"CALL gds.alpha.linkprediction.preferentialAttachment.stream($name) "
                                f"YIELD node1, node2, score "
                                f"{focus_filter} "
                                f"RETURN node1.id AS source, node2.id AS target, score "
                                f"ORDER BY score DESC LIMIT $top_k",
                                **params,
                            )
                        else:
                            continue

                        for record in result:
                            score = float(record["score"])
                            if score >= min_score:
                                all_predictions.append(LinkPrediction(
                                    source=str(record["source"]),
                                    target=str(record["target"]),
                                    score=score,
                                    algorithm=algo_name,
                                    reason=f"GDS {algo_name}: {score:.4f}",
                                ))
                    except Exception as e:
                        logger.warning("GDS %s failed: %s", algo_name, e)

        finally:
            # Drop temporary graph
            try:
                with driver.session(database=self._neo4j._database) as session:
                    session.run("CALL gds.graph.drop($name, false)", name=graph_name)
            except Exception:
                pass

        all_predictions.sort(key=lambda p: p.score, reverse=True)
        return all_predictions[:top_k]

    # =========================================================================
    # Community Detection
    # =========================================================================

    def detect_communities(
        self, *, resolution: float = 1.0, min_community_size: int = 2,
    ) -> list[Community]:
        """Detect communities using the Louvain algorithm.

        Args:
            resolution: Louvain resolution parameter. Higher = more communities.
            min_community_size: Minimum number of nodes to form a community.

        Returns:
            List of Community objects sorted by size (largest first).
        """
        if self._gds_available:
            return self._detect_communities_gds(
                resolution=resolution, min_community_size=min_community_size
            )
        return self._detect_communities_nx(
            resolution=resolution, min_community_size=min_community_size
        )

    def _detect_communities_nx(
        self, *, resolution: float, min_community_size: int,
    ) -> list[Community]:
        """Community detection using NetworkX Louvain."""
        import networkx as nx

        try:
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("Louvain not available in this NetworkX version")
            return []

        G = self._graph.to_networkx()
        G_undirected = G.to_undirected()

        if len(G_undirected) < 2:
            return []

        try:
            partitions = louvain_communities(
                G_undirected, resolution=resolution, seed=42
            )
        except Exception as e:
            logger.warning("Louvain community detection failed: %s", e)
            return []

        communities = []
        for i, partition in enumerate(partitions):
            members = sorted(partition)
            if len(members) < min_community_size:
                continue
            # Auto-label from dominant entity type
            type_counts: dict[str, int] = {}
            for nid in members:
                if nid in self._graph.nodes:
                    etype = self._graph.nodes[nid].entity_type
                    type_counts[etype] = type_counts.get(etype, 0) + 1
            dominant_type = max(type_counts, key=type_counts.get) if type_counts else "Mixed"
            communities.append(Community(
                id=i,
                members=members,
                size=len(members),
                label=f"{dominant_type} cluster ({len(members)} nodes)",
            ))

        communities.sort(key=lambda c: c.size, reverse=True)
        return communities

    def _detect_communities_gds(
        self, *, resolution: float, min_community_size: int,
    ) -> list[Community]:
        """Community detection using Neo4j GDS Louvain."""
        driver = self._neo4j._get_driver()
        graph_name = "_graqle_community_temp"

        try:
            with driver.session(database=self._neo4j._database) as session:
                session.run(
                    "CALL gds.graph.project($name, 'CogniNode', "
                    "{RELATED_TO: {orientation: 'UNDIRECTED'}, "
                    " SEMANTICALLY_RELATED: {orientation: 'UNDIRECTED'}, "
                    " DEPENDS_ON: {orientation: 'UNDIRECTED'}})",
                    name=graph_name,
                )

                result = session.run(
                    "CALL gds.louvain.stream($name, {maxLevels: 10, "
                    "maxIterations: 20, tolerance: 0.0001, includeIntermediateCommunities: false}) "
                    "YIELD nodeId, communityId "
                    "WITH gds.util.asNode(nodeId).id AS nodeId, communityId "
                    "RETURN communityId, collect(nodeId) AS members "
                    "ORDER BY size(members) DESC",
                    name=graph_name,
                )

                communities = []
                for i, record in enumerate(result):
                    members = sorted(record["members"])
                    if len(members) < min_community_size:
                        continue
                    type_counts: dict[str, int] = {}
                    for nid in members:
                        if nid in self._graph.nodes:
                            etype = self._graph.nodes[nid].entity_type
                            type_counts[etype] = type_counts.get(etype, 0) + 1
                    dominant = max(type_counts, key=type_counts.get) if type_counts else "Mixed"
                    communities.append(Community(
                        id=record["communityId"],
                        members=members,
                        size=len(members),
                        label=f"{dominant} cluster ({len(members)} nodes)",
                    ))

                return communities

        finally:
            try:
                with driver.session(database=self._neo4j._database) as session:
                    session.run("CALL gds.graph.drop($name, false)", name=graph_name)
            except Exception:
                pass

    # =========================================================================
    # Node Similarity
    # =========================================================================

    def find_similar_nodes(
        self,
        node_id: str | None = None,
        *,
        top_k: int = 10,
        min_score: float = 0.1,
        metric: str = "jaccard",
    ) -> list[SimilarityPair]:
        """Find similar nodes based on shared neighborhood topology.

        Args:
            node_id: If provided, find nodes similar to this one.
                     If None, find all pairwise similarities above threshold.
            top_k: Number of results to return.
            min_score: Minimum similarity score.
            metric: "jaccard" or "overlap".

        Returns:
            List of SimilarityPair objects sorted by score descending.
        """
        if self._gds_available:
            return self._find_similar_gds(
                node_id=node_id, top_k=top_k, min_score=min_score, metric=metric
            )
        return self._find_similar_nx(
            node_id=node_id, top_k=top_k, min_score=min_score, metric=metric
        )

    def _find_similar_nx(
        self,
        *,
        node_id: str | None,
        top_k: int,
        min_score: float,
        metric: str,
    ) -> list[SimilarityPair]:
        """Node similarity using NetworkX neighborhood comparison."""
        G = self._graph.to_networkx().to_undirected()

        if node_id and node_id not in G:
            return []

        results: list[SimilarityPair] = []

        if node_id:
            # Compare one node against all others
            neighbors_a = set(G.neighbors(node_id))
            if not neighbors_a:
                return []
            for other in G.nodes():
                if other == node_id:
                    continue
                neighbors_b = set(G.neighbors(other))
                if not neighbors_b:
                    continue
                shared = neighbors_a & neighbors_b
                if not shared:
                    continue
                if metric == "jaccard":
                    union = neighbors_a | neighbors_b
                    score = len(shared) / len(union) if union else 0.0
                else:  # overlap
                    score = len(shared) / min(len(neighbors_a), len(neighbors_b))
                if score >= min_score:
                    results.append(SimilarityPair(
                        node_a=node_id, node_b=other,
                        score=round(score, 4),
                        shared_neighbors=sorted(shared),
                    ))
        else:
            # Pairwise comparison (capped for performance)
            nodes = list(G.nodes())
            neighbor_map = {n: set(G.neighbors(n)) for n in nodes}
            checked = 0
            for i, a in enumerate(nodes):
                na = neighbor_map[a]
                if not na:
                    continue
                for b in nodes[i + 1:]:
                    nb = neighbor_map[b]
                    if not nb:
                        continue
                    shared = na & nb
                    if not shared:
                        continue
                    if metric == "jaccard":
                        union = na | nb
                        score = len(shared) / len(union) if union else 0.0
                    else:
                        score = len(shared) / min(len(na), len(nb))
                    if score >= min_score:
                        results.append(SimilarityPair(
                            node_a=a, node_b=b,
                            score=round(score, 4),
                            shared_neighbors=sorted(shared),
                        ))
                    checked += 1
                    if checked > 100000:
                        break
                if checked > 100000:
                    break

        results.sort(key=lambda s: s.score, reverse=True)
        return results[:top_k]

    def _find_similar_gds(
        self,
        *,
        node_id: str | None,
        top_k: int,
        min_score: float,
        metric: str,
    ) -> list[SimilarityPair]:
        """Node similarity using Neo4j GDS."""
        driver = self._neo4j._get_driver()
        graph_name = "_graqle_similarity_temp"

        algo = "gds.nodeSimilarity" if metric == "jaccard" else "gds.nodeSimilarity"
        sim_metric = "JACCARD" if metric == "jaccard" else "OVERLAP"

        try:
            with driver.session(database=self._neo4j._database) as session:
                session.run(
                    "CALL gds.graph.project($name, 'CogniNode', "
                    "{RELATED_TO: {orientation: 'UNDIRECTED'}, "
                    " SEMANTICALLY_RELATED: {orientation: 'UNDIRECTED'}, "
                    " DEPENDS_ON: {orientation: 'UNDIRECTED'}})",
                    name=graph_name,
                )

                query = (
                    f"CALL gds.nodeSimilarity.stream($name, "
                    f"{{similarityMetric: '{sim_metric}', topK: $top_k, "
                    f"similarityCutoff: $min_score}}) "
                    f"YIELD node1, node2, similarity "
                    f"WITH gds.util.asNode(node1).id AS nodeA, "
                    f"gds.util.asNode(node2).id AS nodeB, similarity "
                )
                if node_id:
                    query += f"WHERE nodeA = $focus OR nodeB = $focus "
                    query += "RETURN nodeA, nodeB, similarity ORDER BY similarity DESC LIMIT $top_k"
                else:
                    query += "RETURN nodeA, nodeB, similarity ORDER BY similarity DESC LIMIT $top_k"

                params: dict[str, Any] = {
                    "name": graph_name,
                    "top_k": top_k,
                    "min_score": min_score,
                }
                if node_id:
                    params["focus"] = node_id

                result = session.run(query, **params)
                results = []
                for record in result:
                    results.append(SimilarityPair(
                        node_a=str(record["nodeA"]),
                        node_b=str(record["nodeB"]),
                        score=round(float(record["similarity"]), 4),
                    ))
                return results

        finally:
            try:
                with driver.session(database=self._neo4j._database) as session:
                    session.run("CALL gds.graph.drop($name, false)", name=graph_name)
            except Exception:
                pass

    # =========================================================================
    # Missing Link Discovery (combines all signals)
    # =========================================================================

    def discover_missing_links(
        self,
        *,
        focus_nodes: list[str] | None = None,
        top_k: int = 15,
        include_communities: bool = True,
    ) -> GDSReport:
        """Full intelligence report: link predictions + communities + similarities.

        This is the main entry point for `graq learn discover --gds`.

        Args:
            focus_nodes: Optional list of nodes to focus analysis on.
            top_k: Number of top results per category.
            include_communities: Whether to run community detection.

        Returns:
            GDSReport with all findings.
        """
        # Link predictions
        predictions = self.predict_links(
            top_k=top_k, focus_nodes=focus_nodes
        )

        # Communities
        communities: list[Community] = []
        if include_communities:
            communities = self.detect_communities()

        # Similarities
        similarities: list[SimilarityPair] = []
        if focus_nodes:
            for nid in focus_nodes[:5]:  # Cap to avoid explosion
                sims = self.find_similar_nodes(nid, top_k=5)
                similarities.extend(sims)
            # Deduplicate
            seen_pairs: set[tuple[str, str]] = set()
            deduped = []
            for s in similarities:
                key = (min(s.node_a, s.node_b), max(s.node_a, s.node_b))
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    deduped.append(s)
            similarities = sorted(deduped, key=lambda s: s.score, reverse=True)[:top_k]
        else:
            similarities = self.find_similar_nodes(top_k=top_k)

        return GDSReport(
            link_predictions=predictions,
            communities=communities,
            similarities=similarities,
            method=self.method,
            stats={
                "total_nodes": len(self._graph),
                "total_edges": len(self._graph.edges),
                "predictions_found": len(predictions),
                "communities_found": len(communities),
                "similarity_pairs": len(similarities),
            },
        )
