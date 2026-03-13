"""JSON graph connector — file-based graph persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graqle.connectors.base import BaseConnector


class JSONGraphConnector(BaseConnector):
    """Load/save graph data from a JSON file.

    JSON format:
    {
        "nodes": {"id": {"label": "...", "type": "...", "description": "...", ...}},
        "edges": {"id": {"source": "...", "target": "...", "relationship": "...", ...}}
    }
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load graph from JSON file."""
        if not self.path.exists():
            raise FileNotFoundError(f"Graph file not found: {self.path}")

        data = json.loads(self.path.read_text(encoding="utf-8"))
        nodes = data.get("nodes", {})
        edges = data.get("edges", {})
        return nodes, edges

    def save(
        self,
        nodes: dict[str, Any],
        edges: dict[str, Any],
    ) -> None:
        """Save graph to JSON file."""
        data = {"nodes": nodes, "edges": edges}
        self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def validate(self) -> bool:
        return self.path.exists()
