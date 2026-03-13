"""NetworkX connector — in-memory graph (zero-dependency default)."""

from __future__ import annotations

from typing import Any

import networkx as nx

from graqle.connectors.base import BaseConnector


class NetworkXConnector(BaseConnector):
    """Load graph data from a NetworkX graph object.

    This is the zero-setup default connector — no database needed.
    """

    def __init__(
        self,
        graph: nx.Graph | None = None,
        node_label_key: str = "label",
        node_type_key: str = "type",
        node_desc_key: str = "description",
        edge_rel_key: str = "relationship",
    ) -> None:
        self.graph = graph or nx.Graph()
        self.node_label_key = node_label_key
        self.node_type_key = node_type_key
        self.node_desc_key = node_desc_key
        self.edge_rel_key = edge_rel_key

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load nodes and edges from the NetworkX graph."""
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        for node_id, data in self.graph.nodes(data=True):
            nid = str(node_id)
            nodes[nid] = {
                "label": data.get(self.node_label_key, nid),
                "type": data.get(self.node_type_key, "Entity"),
                "description": data.get(self.node_desc_key, ""),
                "properties": {
                    k: v
                    for k, v in data.items()
                    if k not in (self.node_label_key, self.node_type_key, self.node_desc_key)
                },
            }

        for i, (src, tgt, data) in enumerate(self.graph.edges(data=True)):
            eid = f"e_{src}_{tgt}_{i}"
            edges[eid] = {
                "source": str(src),
                "target": str(tgt),
                "relationship": data.get(self.edge_rel_key, "RELATED_TO"),
                "weight": data.get("weight", 1.0),
                "properties": {
                    k: v
                    for k, v in data.items()
                    if k not in (self.edge_rel_key, "weight")
                },
            }

        return nodes, edges

    @classmethod
    def from_dict(
        cls,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> NetworkXConnector:
        """Create from a list of node/edge dictionaries."""
        G = nx.Graph()
        for node in nodes:
            nid = node.pop("id")
            G.add_node(nid, **node)
        for edge in edges:
            G.add_edge(edge["source"], edge["target"], **{
                k: v for k, v in edge.items() if k not in ("source", "target")
            })
        return cls(graph=G)
