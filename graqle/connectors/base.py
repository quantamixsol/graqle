"""Base connector — abstract interface for loading graph data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract connector for loading graph data from any source.

    Implement load() to return nodes and edges from ANY source:
    Neo4j, Postgres, MongoDB, Elasticsearch, CSV, custom API, etc.
    """

    @abstractmethod
    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load graph data and return (nodes_dict, edges_dict).

        Returns:
            nodes_dict: {node_id: {label, type, description, properties...}}
            edges_dict: {edge_id: {source, target, relationship, weight, properties...}}
        """
        ...

    def validate(self) -> bool:
        """Validate connection/data source. Override for custom validation."""
        return True
