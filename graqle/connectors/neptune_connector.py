"""NeptuneConnector — BaseConnector implementation for AWS Neptune read path.

Used by Studio for cross-project queries when plan=team and Neptune is
reachable. Falls back gracefully if Neptune is unavailable.

This connector is read-only. Writes go through the Lambda ingest path
(server-side, VPC-only) — never directly from the client SDK.

Usage:
    connector = NeptuneConnector(project_id="graqle-sdk")
    nodes, edges = connector.load()
"""

# ── graqle:intelligence ──
# module: graqle.connectors.neptune_connector
# risk: MEDIUM (impact radius: 2 modules)
# consumers: graqle.server.app
# dependencies: __future__, logging, graqle.connectors.base, graqle.connectors.neptune
# constraints: VPC-only in production — never reachable from local dev
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any

from graqle.connectors.base import BaseConnector

logger = logging.getLogger("graqle.connectors.neptune")


class NeptuneConnector(BaseConnector):
    """Read-only connector that loads a project graph from Neptune.

    The connector implements BaseConnector.load() and returns nodes/edges
    in the standard {id: node_dict} / {id: edge_dict} format used by Graqle.

    Parameters
    ----------
    project_id:
        Neptune project identifier (e.g. "graqle-sdk", "the studio frontend").
    """

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load all nodes and edges for the project from Neptune.

        Returns
        -------
        nodes_dict: {node_id: {label, type, description, properties, ...}}
        edges_dict: {edge_id: {source, target, relationship, weight, ...}}

        Raises RuntimeError if Neptune is unreachable.
        """
        from graqle.connectors.neptune import get_edges, get_nodes

        raw_nodes = get_nodes(self._project_id)
        raw_edges = get_edges(self._project_id)

        nodes: dict[str, Any] = {}
        for n in raw_nodes:
            nid = n.get("id", "")
            if not nid:
                continue
            # Parse properties JSON if stored as string
            props = n.get("properties") or {}
            if isinstance(props, str):
                import json
                try:
                    props = json.loads(props)
                except Exception:
                    props = {}
            nodes[nid] = {
                "id": nid,
                "label": n.get("label", nid),
                "type": n.get("type", "Entity"),
                "description": (n.get("description") or "")[:500],
                "properties": props,
            }

        edges: dict[str, Any] = {}
        for e in raw_edges:
            eid = e.get("id", "")
            src = e.get("source", "")
            tgt = e.get("target", "")
            if not (src and tgt):
                continue
            if not eid:
                eid = f"{src}__{tgt}"
            edges[eid] = {
                "id": eid,
                "source": src,
                "target": tgt,
                "relationship": e.get("relationship", "RELATED_TO"),
                "weight": float(e.get("weight") or 1.0),
            }

        logger.info(
            "NeptuneConnector loaded project=%s: %d nodes, %d edges",
            self._project_id, len(nodes), len(edges),
        )
        return nodes, edges

    def validate(self) -> bool:
        """Return True if Neptune is reachable for this project."""
        try:
            from graqle.connectors.neptune import neptune_health
            health = neptune_health()
            return health.get("status") == "connected"
        except Exception:
            return False

    @property
    def project_id(self) -> str:
        return self._project_id
