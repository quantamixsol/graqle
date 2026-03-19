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

"""TAMRConnector — end-to-end TAMR+ retrieval -> Graqle reasoning pipeline.

Connects TAMR+ (patent-protected retrieval, EP26162901.8) with Graqle
(governed multi-agent reasoning) in a unified pipeline:

1. TAMR+ retrieves relevant subgraph + TRACE scores via API
2. TAMRConnector converts TAMR+ output to Graqle format
3. TRACE scores initialize node priors (higher TRACE = higher activation prize)
4. Graqle reasons over the TAMR+-selected subgraph

Supports both live TAMR+ API calls and offline JSON import.
"""

# ── graqle:intelligence ──
# module: graqle.connectors.tamr
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_tamr
# dependencies: __future__, json, logging, dataclasses, pathlib +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.connectors.tamr")


@dataclass
class TAMRDocument:
    """A document retrieved by TAMR+ with TRACE scores."""
    doc_id: str
    title: str
    content: str
    trace_score: float = 0.5  # TRACE composite (0-1)
    relevance_score: float = 0.0  # Query relevance
    gap_score: float = 0.0  # Gap attribution score
    framework: str = ""  # Regulatory framework (e.g., "EU AI Act")
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TAMRSubgraph:
    """A subgraph retrieved by TAMR+ PCST activation."""
    documents: list[TAMRDocument]
    edges: list[dict[str, Any]]  # [{source, target, relationship, weight}]
    query: str = ""
    total_cost: float = 0.0
    pcst_nodes_selected: int = 0


@dataclass
class PipelineConfig:
    """Configuration for the TAMR+ -> Graqle pipeline."""
    # TAMR+ API settings (for live mode)
    tamr_api_url: str = ""
    tamr_api_key: str = ""
    # TRACE score -> node prior mapping (weights configured externally)
    trace_weight: float = 0.0
    relevance_weight: float = 0.0
    gap_weight: float = 0.0
    # Graqle reasoning settings
    max_rounds: int = 3
    activation_strategy: str = "pcst"


class TAMRConnector:
    """Connect TAMR+ retrieval with Graqle reasoning.

    Usage (offline — from JSON):
        connector = TAMRConnector()
        subgraph = connector.load_from_json("tamr_output.json")
        graph = connector.to_graqle(subgraph)
        result = await graph.areason("What are AI Act requirements?")

    Usage (live — via API):
        connector = TAMRConnector(PipelineConfig(
            tamr_api_url="https://your-tamr-api.example.com",
            tamr_api_key="..."
        ))
        result = await connector.retrieve_and_reason(query)
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig()

    @property
    def config(self) -> PipelineConfig:
        return self._config

    def load_from_json(self, path: str | Path) -> TAMRSubgraph:
        """Load a TAMR+ subgraph from JSON file.

        Expected format:
        {
            "query": "...",
            "documents": [
                {"doc_id": "...", "title": "...", "content": "...",
                 "trace_score": 0.8, "framework": "EU AI Act", ...}
            ],
            "edges": [
                {"source": "doc1", "target": "doc2", "relationship": "CROSS_REF", "weight": 0.9}
            ]
        }
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.load_from_dict(data)

    def compute_node_prior(self, doc: TAMRDocument) -> float:
        """Compute activation prior from TRACE scores."""
        # Proprietary scoring — configure weights via PipelineConfig
        cfg = self._config
        if not any([cfg.trace_weight, cfg.relevance_weight, cfg.gap_weight]):
            return doc.trace_score  # passthrough if no weights configured
        prior = (
            cfg.trace_weight * doc.trace_score
            + cfg.relevance_weight * doc.relevance_score
            + cfg.gap_weight * doc.gap_score
        )
        return round(min(1.0, max(0.0, prior)), 4)

    def to_graqle(self, subgraph: TAMRSubgraph, config: Any = None) -> Any:
        """Convert TAMR+ subgraph to Graqle.

        Args:
            subgraph: TAMRSubgraph from load_from_json or API
            config: Optional GraqleConfig

        Returns:
            Graqle instance with TRACE-informed node priors
        """
        import networkx as nx

        G = nx.Graph()

        # Add nodes with TRACE-informed properties
        for doc in subgraph.documents:
            prior = self.compute_node_prior(doc)
            G.add_node(
                doc.doc_id,
                label=doc.title,
                type=doc.framework or "Document",
                description=doc.content,
                trace_score=doc.trace_score,
                relevance_score=doc.relevance_score,
                gap_score=doc.gap_score,
                activation_prior=prior,
            )

        # Add edges
        for edge in subgraph.edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in G.nodes and tgt in G.nodes:
                G.add_edge(
                    src, tgt,
                    relationship=edge.get("relationship", "RELATED_TO"),
                    weight=edge.get("weight", 1.0),
                )

        # Build Graqle from NetworkX
        from graqle.core.graph import Graqle
        graph = Graqle.from_networkx(G, config=config)

        # Inject TRACE priors into node properties
        for doc in subgraph.documents:
            if doc.doc_id in graph.nodes:
                node = graph.nodes[doc.doc_id]
                node.properties["trace_score"] = doc.trace_score
                node.properties["activation_prior"] = self.compute_node_prior(doc)

        logger.info(
            f"Built Graqle from TAMR+ subgraph: "
            f"{len(graph.nodes)} nodes, {len(graph.edges)} edges"
        )
        return graph

    async def retrieve_and_reason(
        self,
        query: str,
        backend: Any = None,
        max_rounds: int | None = None,
    ) -> Any:
        """Full pipeline: TAMR+ retrieve -> Graqle reason.

        Requires tamr_api_url and tamr_api_key in config.

        Args:
            query: The reasoning query
            backend: ModelBackend for Graqle agents
            max_rounds: Override max reasoning rounds

        Returns:
            ReasoningResult from Graqle
        """
        cfg = self._config
        if not cfg.tamr_api_url:
            raise ValueError("tamr_api_url not configured. Use load_from_json for offline mode.")

        # Call TAMR+ API
        subgraph = await self._call_tamr_api(query)

        # Convert to Graqle
        graph = self.to_graqle(subgraph)

        # Set backend
        if backend:
            graph.set_default_backend(backend)

        # Reason
        result = await graph.areason(
            query,
            max_rounds=max_rounds or cfg.max_rounds,
            strategy=cfg.activation_strategy,
        )

        return result

    async def _call_tamr_api(self, query: str) -> TAMRSubgraph:
        """Call TAMR+ API for subgraph retrieval."""
        try:
            import aiohttp
        except ImportError:
            raise ImportError("aiohttp required for live TAMR+ API. Install with: pip install aiohttp")

        cfg = self._config
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{cfg.tamr_api_url}/retrieve",
                json={"query": query},
                headers={"Authorization": f"Bearer {cfg.tamr_api_key}"},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return self.load_from_dict(data)

    def load_from_dict(self, data: dict) -> TAMRSubgraph:
        """Load TAMRSubgraph from a dictionary (API response or parsed JSON)."""
        docs = []
        for d in data.get("documents", []):
            docs.append(TAMRDocument(
                doc_id=d["doc_id"],
                title=d.get("title", d["doc_id"]),
                content=d.get("content", ""),
                trace_score=d.get("trace_score", 0.5),
                relevance_score=d.get("relevance_score", 0.0),
                gap_score=d.get("gap_score", 0.0),
                framework=d.get("framework", ""),
                metadata={k: v for k, v in d.items()
                         if k not in ("doc_id", "title", "content", "trace_score",
                                     "relevance_score", "gap_score", "framework")},
            ))
        return TAMRSubgraph(
            documents=docs,
            edges=data.get("edges", []),
            query=data.get("query", ""),
            total_cost=data.get("total_cost", 0.0),
            pcst_nodes_selected=len(docs),
        )
