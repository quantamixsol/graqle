# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""GraQle Graph Health Engine.

Shared engine used by:
  - scripts/graqle_graph_health.py  (CLI)
  - graqle/plugins/mcp_dev_server.py via _handle_graph_health (MCP tool)

Works with ANY user's project: auto-detects backend (local JSON / Neo4j)
from graqle.yaml. Zero manual config required.

Backend matrix
--------------
  local  → graqle.json + ChunkScorer + .graqle/chunk_embeddings.npz
  neo4j  → Neo4jConnector + CypherActivation (db.index.vector.queryNodes)
  neptune → NeptuneConnector (read-only, vector search via separate index)
"""

# ── graqle:intelligence ──
# module: graqle.tools.graph_health
# risk: MEDIUM (impact radius: 3 modules)
# consumers: mcp_dev_server, scripts/graqle_graph_health
# dependencies: __future__, collections, dataclasses, hashlib, json, logging,
#               pathlib, re, shutil, time, typing, numpy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import collections
import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("graqle.tools.graph_health")

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RebuildResult:
    new_chunks_embedded: int = 0
    total_chunks: int = 0
    duration_s: float = 0.0
    zero_count: int = 0
    regression_clean: bool = True
    skipped_reason: str | None = None


@dataclass
class LinkResult:
    new_code_links: int = 0
    new_adr_links: int = 0
    total_links_after: int = 0


@dataclass
class HealthReport:
    backend: dict[str, Any] = field(default_factory=dict)
    graph_stats: dict[str, Any] = field(default_factory=dict)
    activation: dict[str, Any] = field(default_factory=dict)
    latency_estimate: dict[str, Any] = field(default_factory=dict)
    cache_status: dict[str, Any] = field(default_factory=dict)
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    rebuild_result: RebuildResult | None = None
    link_result: LinkResult | None = None
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "backend": self.backend,
            "graph_stats": self.graph_stats,
            "activation": self.activation,
            "latency_estimate": self.latency_estimate,
            "cache_status": self.cache_status,
            "gates": self.gates,
            "recommendation": self.recommendation,
        }
        if self.rebuild_result:
            d["rebuild_result"] = self.rebuild_result.__dict__
        if self.link_result:
            d["link_result"] = self.link_result.__dict__
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sha256_bytes(data: bytes, limit: int = 1024 * 1024) -> str:
    return hashlib.sha256(data[:limit]).hexdigest()[:16]


def _resolve_config_path(override: Path | None) -> Path | None:
    if override:
        return override
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        p = parent / "graqle.yaml"
        if p.exists():
            return p
    return None


def _resolve_graph_path(override: Path | None, config_path: Path | None) -> Path | None:
    if override:
        return override
    # Look alongside graqle.yaml
    if config_path:
        candidate = config_path.parent / "graqle.json"
        if candidate.exists():
            return candidate
    # Fallback: cwd
    fallback = Path.cwd() / "graqle.json"
    if fallback.exists():
        return fallback
    return None


def _load_graqle_config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None or not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Could not load graqle.yaml: %s", exc)
        return {}


def _detect_backend(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return backend info dict from graqle.yaml config."""
    graph_cfg = cfg.get("graph", {}) or {}
    backend_type = (graph_cfg.get("backend") or "local").lower()

    if backend_type in ("neo4j",):
        return {
            "type": "neo4j",
            "uri": graph_cfg.get("uri", "bolt://localhost:7687"),
            "database": graph_cfg.get("database", "neo4j"),
            "vector_index": graph_cfg.get(
                "vector_index", "cogni_chunk_embedding_index"
            ),
            "reachable": None,  # probed lazily
        }

    if backend_type in ("neptune",):
        return {
            "type": "neptune",
            "uri": graph_cfg.get("uri", ""),
            "region": graph_cfg.get("region", "eu-central-1"),
            "reachable": None,
        }

    return {"type": "local", "reachable": True}


def _probe_neo4j(info: dict[str, Any]) -> dict[str, Any]:
    try:
        from neo4j import GraphDatabase  # type: ignore[import]
        driver = GraphDatabase.driver(
            info["uri"],
            auth=(info.get("username", "neo4j"), info.get("password", "")),
        )
        with driver.session(database=info.get("database", "neo4j")) as session:
            session.run("RETURN 1")
        driver.close()
        info["reachable"] = True
    except Exception as exc:
        info["reachable"] = False
        info["error"] = str(exc)
    return info


# ─────────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────────

class GraphHealthEngine:
    """Backend-agnostic graph health check and rebuild engine.

    Parameters
    ----------
    graph_path:   Override path to graqle.json. Auto-detected if None.
    config_path:  Override path to graqle.yaml. Searches upward if None.
    """

    def __init__(
        self,
        graph_path: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._config_path = _resolve_config_path(config_path)
        self._cfg = _load_graqle_config(self._config_path)
        self._backend_info = _detect_backend(self._cfg)
        self._graph_path = _resolve_graph_path(graph_path, self._config_path)
        project_root = (
            self._config_path.parent
            if self._config_path
            else Path.cwd()
        )
        self._npz_path = project_root / ".graqle" / "chunk_embeddings.npz"
        self._project_root = project_root

    # ── public entry point ────────────────────────────────────────────────────

    def run(
        self,
        rebuild: bool = False,
        inject_links: bool = False,
        dry_run: bool = False,
    ) -> HealthReport:
        """Run health check. Optionally rebuild NPZ and/or inject links."""
        report = HealthReport()

        # 1. Backend
        report.backend = self._check_backend()

        # 2. Graph stats
        g_data, nodes, links, stats = self._load_graph_stats()
        report.graph_stats = stats
        report.gates["graph_loaded"] = {
            "ok": len(nodes) > 0,
            "msg": f"{len(nodes):,} nodes loaded",
            "fatal": True,
        }

        # 3. Activation strategy + cache
        cache_info = self._check_cache(nodes)
        report.cache_status = cache_info
        report.activation = self._classify_activation(cache_info)
        report.latency_estimate = self._estimate_latency(report.activation)

        # 4. Gates
        report.gates.update(self._run_gates(nodes, cache_info))

        # 5. Rebuild NPZ (incremental)
        if rebuild and not dry_run:
            report.rebuild_result = self._rebuild_npz(nodes, cache_info)
            # Refresh cache info post-rebuild
            cache_info = self._check_cache(nodes)
            report.cache_status = cache_info
            report.activation = self._classify_activation(cache_info)
            report.latency_estimate = self._estimate_latency(report.activation)

        # 6. ADR link injection
        if inject_links and not dry_run and g_data is not None:
            report.link_result = self._inject_adr_links(g_data, nodes, links)

        # 7. Recommendation
        report.recommendation = self._make_recommendation(
            report, rebuild, inject_links
        )

        return report

    # ── backend ───────────────────────────────────────────────────────────────

    def _check_backend(self) -> dict[str, Any]:
        info = dict(self._backend_info)
        info["graph_file"] = str(self._graph_path) if self._graph_path else "not found"
        info["config_file"] = str(self._config_path) if self._config_path else "not found"

        if info["type"] == "neo4j" and info.get("reachable") is None:
            info = _probe_neo4j(info)
        elif info["type"] == "local":
            info["reachable"] = self._graph_path is not None and self._graph_path.exists()
        return info

    # ── graph stats ───────────────────────────────────────────────────────────

    def _load_graph_stats(
        self,
    ) -> tuple[dict | None, list, list, dict[str, Any]]:
        if self._backend_info["type"] == "local":
            return self._load_local_graph_stats()
        elif self._backend_info["type"] == "neo4j":
            return self._load_neo4j_graph_stats()
        return None, [], [], {"nodes": 0, "edges": 0, "components": 0,
                              "avg_degree": 0.0, "entity_type_count": 0}

    def _load_local_graph_stats(
        self,
    ) -> tuple[dict | None, list, list, dict[str, Any]]:
        if not self._graph_path or not self._graph_path.exists():
            return None, [], [], {
                "nodes": 0, "edges": 0, "components": 0,
                "avg_degree": 0.0, "entity_type_count": 0,
                "error": "graqle.json not found",
            }
        try:
            with open(self._graph_path, encoding="utf-8") as f:
                g_data = json.load(f)
            nodes = g_data.get("nodes", [])
            links = g_data.get("links", [])
            type_counts: dict[str, int] = {}
            for n in nodes:
                et = n.get("type") or n.get("entity_type") or "Unknown"
                type_counts[et] = type_counts.get(et, 0) + 1
            n_count = len(nodes)
            e_count = len(links)
            avg_deg = (2 * e_count / n_count) if n_count else 0.0
            return g_data, nodes, links, {
                "nodes": n_count,
                "edges": e_count,
                "components": self._estimate_components(nodes, links),
                "avg_degree": round(avg_deg, 2),
                "entity_type_count": len(type_counts),
                "top_types": sorted(
                    type_counts.items(), key=lambda x: x[1], reverse=True
                )[:8],
            }
        except Exception as exc:
            logger.warning("Failed to load graph: %s", exc)
            return None, [], [], {"nodes": 0, "edges": 0, "components": 0,
                                  "avg_degree": 0.0, "entity_type_count": 0,
                                  "error": str(exc)}

    def _load_neo4j_graph_stats(
        self,
    ) -> tuple[dict | None, list, list, dict[str, Any]]:
        try:
            from neo4j import GraphDatabase  # type: ignore[import]
            info = self._backend_info
            driver = GraphDatabase.driver(
                info["uri"],
                auth=(info.get("username", "neo4j"), info.get("password", "")),
            )
            with driver.session(database=info.get("database", "neo4j")) as s:
                n_count = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                e_count = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
                types = s.run(
                    "MATCH (n) RETURN n.entity_type AS t, count(*) AS c "
                    "ORDER BY c DESC LIMIT 8"
                ).data()
            driver.close()
            avg_deg = (2 * e_count / n_count) if n_count else 0.0
            return None, [], [], {
                "nodes": n_count,
                "edges": e_count,
                "components": "n/a (Neo4j)",
                "avg_degree": round(avg_deg, 2),
                "entity_type_count": len(types),
                "top_types": [(r["t"], r["c"]) for r in types],
            }
        except Exception as exc:
            return None, [], [], {"nodes": 0, "edges": 0, "components": 0,
                                  "avg_degree": 0.0, "entity_type_count": 0,
                                  "error": str(exc)}

    @staticmethod
    def _estimate_components(nodes: list, links: list) -> int:
        """Union-find component count (cheap, no NetworkX needed)."""
        parent: dict[str, str] = {n.get("id", ""): n.get("id", "") for n in nodes}
        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent.get(x, x), x)
                x = parent.get(x, x)
            return x
        for lk in links:
            a, b = find(lk.get("source", "")), find(lk.get("target", ""))
            if a and b and a != b:
                parent[a] = b
        return len({find(k) for k in parent if k})

    # ── cache ────────────────────────────────────────────────────────────────

    def _check_cache(self, nodes: list) -> dict[str, Any]:
        if not self._npz_path.exists():
            # Count how many chunks exist in graph
            gap_count = sum(
                len(n.get("chunks", [])) for n in nodes
            )
            return {
                "status": "missing",
                "path": None,
                "chunks": 0,
                "new_chunks_available": gap_count,
                "zero_count": 0,
            }

        try:
            npz = np.load(str(self._npz_path), allow_pickle=True)
            mat = npz["chunk_matrix"]
            existing_keys: set[str] = set(npz["chunk_keys"])
            zero_count = int((np.abs(mat).sum(axis=1) == 0).sum())
            size_mb = self._npz_path.stat().st_size / 1024 / 1024

            # Count unembedded chunks
            gap = sum(
                1
                for n in nodes
                for idx in range(len(n.get("chunks", [])))
                if f"{n.get('id', '')}::{idx}" not in existing_keys
            )

            return {
                "status": "ok" if zero_count == 0 else "degraded",
                "path": str(self._npz_path),
                "chunks": len(existing_keys),
                "size_mb": round(size_mb, 1),
                "zero_count": zero_count,
                "new_chunks_available": gap,
                "cache_stale": gap > 0,
                "dim": mat.shape[1] if len(mat.shape) > 1 else 0,
            }
        except Exception as exc:
            return {"status": "corrupt", "error": str(exc), "path": str(self._npz_path)}

    def _classify_activation(self, cache_info: dict[str, Any]) -> dict[str, Any]:
        """Determine which activation strategy is active."""
        if self._backend_info["type"] == "neo4j":
            return {
                "strategy": "cypher_neo4j",
                "vector_index": self._backend_info.get(
                    "vector_index", "cogni_chunk_embedding_index"
                ),
                "description": (
                    "CypherActivation — chunk-level vector search via "
                    "db.index.vector.queryNodes(). Most accurate."
                ),
            }

        if cache_info.get("status") == "ok" and cache_info.get("chunks", 0) > 0:
            return {
                "strategy": "chunk_scorer_cached",
                "cache_path": cache_info["path"],
                "cached_chunks": cache_info["chunks"],
                "cache_stale": cache_info.get("cache_stale", False),
                "description": (
                    "ChunkScorer with NPZ cache — 1 embed call + batch "
                    "numpy cosine. Fast and semantic."
                ),
            }

        return {
            "strategy": "property_fallback",
            "description": (
                "ChunkScorer property fallback — regex keyword matching on "
                "node IDs/labels/descriptions. Fast but not semantic. "
                "Run --rebuild to enable chunk-level embedding."
            ),
        }

    @staticmethod
    def _estimate_latency(activation: dict[str, Any]) -> dict[str, Any]:
        strategy = activation.get("strategy", "property_fallback")
        activation_ms_map = {
            "cypher_neo4j": 100,
            "chunk_scorer_cached": 800,
            "property_fallback": 7000,
        }
        act_ms = activation_ms_map.get(strategy, 7000)
        llm_ms = 90_000  # ~90s for 50 nodes × 2 rounds on Bedrock Sonnet
        return {
            "activation_ms": act_ms,
            "llm_ms": llm_ms,
            "total_ms": act_ms + llm_ms,
            "note": "LLM dominates. Activation fix reduces wrong-node selection, not wall time.",
        }

    # ── gates ─────────────────────────────────────────────────────────────────

    def _run_gates(
        self, nodes: list, cache_info: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        gates: dict[str, dict[str, Any]] = {}

        # G1: graph loaded with meaningful size
        n_count = len(nodes)
        gates["graph_size"] = {
            "ok": n_count >= 100,
            "msg": f"{n_count:,} nodes (expected >= 100)",
            "fatal": True,
        }

        # G2: NPZ cache exists
        gates["npz_cache_exists"] = {
            "ok": cache_info.get("status") not in ("missing", "corrupt"),
            "msg": (
                f"NPZ cache {cache_info.get('status', 'missing')}"
                + (f" — {cache_info.get('chunks', 0):,} chunks" if cache_info.get("chunks") else "")
            ),
            "fatal": False,
        }

        # G3: no zero vectors in cache
        zero = cache_info.get("zero_count", 0)
        gates["no_zero_vectors"] = {
            "ok": zero == 0,
            "msg": f"{zero} zero vectors in NPZ" if zero else "clean (0 zero vectors)",
            "fatal": False,
        }

        # G4: cache stale check
        gap = cache_info.get("new_chunks_available", 0)
        gates["cache_up_to_date"] = {
            "ok": gap == 0,
            "msg": (
                f"{gap} new chunks not yet embedded"
                if gap
                else "cache up to date"
            ),
            "fatal": False,
        }

        # G5: backend reachable
        reachable = self._backend_info.get("reachable", True)
        gates["backend_reachable"] = {
            "ok": bool(reachable),
            "msg": (
                f"{self._backend_info['type']} reachable"
                if reachable
                else f"{self._backend_info['type']} UNREACHABLE: {self._backend_info.get('error', '')}"
            ),
            "fatal": True,
        }

        return gates

    # ── incremental NPZ rebuild ───────────────────────────────────────────────

    def _rebuild_npz(self, nodes: list, cache_info: dict[str, Any]) -> RebuildResult:
        """Incrementally embed new chunks and append to NPZ.

        Only embeds chunks with no existing vector. Never modifies
        existing vectors (regression-safe via SHA check).
        """
        result = RebuildResult()

        # Load existing NPZ (or start fresh)
        if cache_info.get("status") in ("ok", "degraded") and self._npz_path.exists():
            try:
                npz_in = np.load(str(self._npz_path), allow_pickle=True)
                existing_keys: list[str] = list(npz_in["chunk_keys"])
                existing_node_ids: list[str] = list(npz_in["chunk_node_ids"])
                existing_matrix: np.ndarray = npz_in["chunk_matrix"].copy()
                existing_desc_keys: list[str] = list(
                    npz_in.get("desc_keys", np.array([], dtype=object))
                )
                existing_desc_matrix: np.ndarray = npz_in.get(
                    "desc_matrix", np.zeros((0, existing_matrix.shape[1]), dtype=np.float32)
                ).copy()
                existing_sha = _sha256_bytes(existing_matrix.tobytes())
            except Exception as exc:
                logger.error("Cannot load existing NPZ for rebuild: %s", exc)
                result.skipped_reason = f"corrupt NPZ: {exc}"
                return result
        else:
            # Fresh start
            dim = self._detect_embedding_dim()
            existing_keys = []
            existing_node_ids = []
            existing_matrix = np.empty((0, dim), dtype=np.float32)
            existing_desc_keys = []
            existing_desc_matrix = np.empty((0, dim), dtype=np.float32)
            existing_sha = _sha256_bytes(existing_matrix.tobytes())

        existing_key_set = set(existing_keys)

        # Collect gap
        gap: list[tuple[str, int, str]] = []
        for n in nodes:
            nid = n.get("id", "")
            for idx, ch in enumerate(n.get("chunks", [])):
                key = f"{nid}::{idx}"
                if key not in existing_key_set:
                    text = (ch.get("text", "") if isinstance(ch, dict) else str(ch)).strip()
                    gap.append((nid, idx, text[:3000]))

        result.total_chunks = len(existing_keys) + len(gap)
        logger.info("Rebuild: %d existing + %d new chunks", len(existing_keys), len(gap))

        if not gap:
            result.new_chunks_embedded = 0
            result.skipped_reason = "NPZ already up to date"
            result.regression_clean = True
            return result

        # Build embedding engine
        engine = self._build_embedding_engine()

        t0 = time.time()
        new_vecs: list[np.ndarray] = []
        new_keys: list[str] = []
        new_node_ids: list[str] = []
        zero_count = 0

        for i, (nid, idx, text) in enumerate(gap):
            if i > 0 and i % 20 == 0:
                elapsed = time.time() - t0
                rate = i / max(elapsed, 0.01)
                eta = (len(gap) - i) / max(rate, 0.01)
                logger.info(
                    "Embedding %d/%d  (%.1f/s, ETA %.0fs)", i, len(gap), rate, eta
                )

            vec = self._embed_with_retry(engine, text)
            arr = np.array(vec, dtype=np.float32)
            if np.abs(arr).sum() == 0:
                zero_count += 1
                logger.warning("Zero vector for %s::%d", nid, idx)

            new_vecs.append(arr)
            new_keys.append(f"{nid}::{idx}")
            new_node_ids.append(nid)

        new_matrix = np.vstack(new_vecs) if new_vecs else np.empty(
            (0, existing_matrix.shape[1]), dtype=np.float32
        )

        # Merge
        merged_keys = existing_keys + new_keys
        merged_ids = existing_node_ids + new_node_ids
        merged_matrix = np.vstack([existing_matrix, new_matrix])

        # Regression gate
        regression_sha = _sha256_bytes(merged_matrix[:len(existing_matrix)].tobytes())
        result.regression_clean = regression_sha == existing_sha
        if not result.regression_clean:
            logger.error("REGRESSION: existing vectors changed! Aborting NPZ write.")
            result.skipped_reason = "regression SHA mismatch — NPZ NOT written"
            return result

        # Atomic write
        self._npz_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self._npz_path) + ".tmp.npz"
        np.savez(
            tmp,
            chunk_keys=np.array(merged_keys, dtype=object),
            chunk_node_ids=np.array(merged_ids, dtype=object),
            chunk_matrix=merged_matrix,
            desc_keys=np.array(existing_desc_keys, dtype=object),
            desc_matrix=existing_desc_matrix,
        )
        shutil.move(tmp, str(self._npz_path))
        logger.info(
            "NPZ written: %d chunks, shape=%s", len(merged_keys), merged_matrix.shape
        )

        result.new_chunks_embedded = len(new_vecs)
        result.duration_s = time.time() - t0
        result.zero_count = zero_count
        return result

    def _detect_embedding_dim(self) -> int:
        """Probe embedding engine dimension without embedding."""
        from graqle.activation.embeddings import (
            TitanV2Engine,
            SimpleEmbeddingEngine,
            get_engine_dimension,
        )
        try:
            engine = self._build_embedding_engine()
            return get_engine_dimension(engine)
        except Exception:
            return 384  # MiniLM default

    def _build_embedding_engine(self) -> Any:
        """Build the correct embedding engine from graqle.yaml config."""
        from graqle.activation.embeddings import create_embedding_engine
        try:
            from graqle.config.settings import GraqleConfig
            if self._config_path and self._config_path.exists():
                cfg_obj = GraqleConfig.from_yaml(self._config_path)
                return create_embedding_engine(cfg_obj)
        except Exception as exc:
            logger.warning("Cannot load GraqleConfig, using default engine: %s", exc)
        return create_embedding_engine(None)

    @staticmethod
    def _embed_with_retry(engine: Any, text: str, max_retries: int = 6) -> list[float]:
        """Embed with exponential backoff on throttle."""
        for attempt in range(max_retries):
            try:
                result = engine.embed(text if text.strip() else "empty document")
                if hasattr(result, "tolist"):
                    return result.tolist()
                return list(result)
            except Exception as exc:
                err = str(exc)
                if "ThrottlingException" in err or "429" in err:
                    wait = min(120, 30 * (2 ** attempt))
                    logger.warning(
                        "Throttle attempt %d/%d — sleeping %ds", attempt + 1, max_retries, wait
                    )
                    time.sleep(wait)
                elif attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    logger.warning(
                        "Zero-vec fallback after %d attempts: %s", max_retries, exc
                    )
        return [0.0] * 384  # safe zero-dim fallback

    # ── ADR link injection ────────────────────────────────────────────────────

    def _inject_adr_links(
        self,
        g_data: dict,
        nodes: list,
        links: list,
    ) -> LinkResult:
        """Build ADR→code REFERENCES and ADR↔ADR RELATED_TO links.

        Tight matching: filename must be >= 8 chars with a dot (real file),
        and match as a word-boundary in ADR chunk text.
        """
        result = LinkResult()
        if not self._graph_path:
            return result

        # Build file map: basename → [node_id]
        # Only meaningful module-level nodes (no :: in id)
        file_map: dict[str, list[str]] = collections.defaultdict(list)
        for n in nodes:
            nid = n.get("id", "")
            if "::" not in nid:
                fname = os.path.basename(nid).lower()
                if len(fname) >= 8 and "." in fname:
                    file_map[fname].append(nid)

        # ADR nodes
        adr_nodes = [
            n for n in nodes
            if n.get("type") == "ADR" or "knowledge/adr::" in str(n.get("id", ""))
        ]

        existing_link_set: set[tuple[str, str, str]] = {
            (
                lk.get("source", ""),
                lk.get("target", ""),
                lk.get("relationship") or lk.get("type", ""),
            )
            for lk in links
        }
        new_links: list[dict[str, str]] = []

        # ADR → code REFERENCES
        for adr_n in adr_nodes:
            nid = adr_n.get("id", "")
            text = " ".join(
                (ch.get("text", "") if isinstance(ch, dict) else str(ch))
                for ch in adr_n.get("chunks", [])
            ).lower()
            if not text:
                continue
            for fname, targets in file_map.items():
                stem = re.sub(r"\.(py|tsx?|js|jsx)$", "", fname)
                if len(stem) < 5:
                    continue
                pattern = r"\b" + re.escape(stem) + r"\b"
                if re.search(pattern, text):
                    for target in targets:
                        key = (nid, target, "REFERENCES")
                        if key not in existing_link_set:
                            new_links.append({
                                "source": nid,
                                "target": target,
                                "relationship": "REFERENCES",
                            })
                            existing_link_set.add(key)
                            result.new_code_links += 1

        # ADR ↔ ADR RELATED_TO
        adr_num_map: dict[str, str] = {}
        for n in adr_nodes:
            m = re.search(r"ADR-(\d+)", n.get("id", ""), re.IGNORECASE)
            if m:
                adr_num_map[m.group(1)] = n.get("id", "")

        for adr_n in adr_nodes:
            src_id = adr_n.get("id", "")
            text = " ".join(
                (ch.get("text", "") if isinstance(ch, dict) else str(ch))
                for ch in adr_n.get("chunks", [])
            ).lower()
            for num, target_id in adr_num_map.items():
                if target_id == src_id:
                    continue
                if f"adr-{num}" in text or f"adr_{num}" in text:
                    key = (src_id, target_id, "RELATED_TO")
                    if key not in existing_link_set:
                        new_links.append({
                            "source": src_id,
                            "target": target_id,
                            "relationship": "RELATED_TO",
                        })
                        existing_link_set.add(key)
                        result.new_adr_links += 1

        if new_links:
            links_before = len(g_data.get("links", []))
            g_data.setdefault("links", []).extend(new_links)
            # Atomic write
            tmp = str(self._graph_path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(g_data, f, ensure_ascii=False)
            shutil.move(tmp, str(self._graph_path))
            result.total_links_after = links_before + len(new_links)
            logger.info(
                "Injected %d code links + %d ADR links",
                result.new_code_links,
                result.new_adr_links,
            )
        else:
            result.total_links_after = len(links)

        return result

    # ── recommendation ────────────────────────────────────────────────────────

    def _make_recommendation(
        self,
        report: HealthReport,
        did_rebuild: bool,
        did_links: bool,
    ) -> str:
        activation = report.activation.get("strategy", "property_fallback")
        gap = report.cache_status.get("new_chunks_available", 0)
        zero = report.cache_status.get("zero_count", 0)
        missing = report.cache_status.get("status") == "missing"

        if activation == "cypher_neo4j":
            return (
                "Neo4j active — CypherActivation providing best-quality semantic search. "
                "No rebuild needed."
            )
        if activation == "chunk_scorer_cached" and not report.cache_status.get("cache_stale"):
            return (
                "Graph healthy. Chunk-level embedding cache active. "
                "Reasoning quality and activation are optimal for local mode."
            )
        if missing or gap > 0:
            verb = "rebuilt" if did_rebuild else "rebuild needed"
            return (
                f"Activation running on keyword fallback — {gap} chunks unembedded. "
                f"Run: python scripts/graqle_graph_health.py --rebuild   "
                f"(cache {verb})"
            )
        if zero > 0:
            return (
                f"{zero} zero vectors detected in NPZ. "
                "Run --rebuild to re-embed affected chunks."
            )
        return "Graph healthy."
