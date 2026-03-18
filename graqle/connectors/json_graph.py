"""JSON graph connector — file-based graph persistence."""

# ── graqle:intelligence ──
# module: graqle.connectors.json_graph
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_json_graph
# dependencies: __future__, json, pathlib, typing, base
# constraints: none
# ── /graqle:intelligence ──

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
        """Save graph to JSON file (atomic write)."""
        from graqle.core.graph import _write_with_lock
        data = {"nodes": nodes, "edges": edges}
        _write_with_lock(str(self.path), json.dumps(data, indent=2, default=str))

    def validate(self) -> bool:
        return self.path.exists()
