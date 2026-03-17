"""Build RUNTIME_EVENT nodes from fetched log data into the Graqle KG."""

# ── graqle:intelligence ──
# module: graqle.runtime.kg_builder
# risk: LOW (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, json, logging, datetime, pathlib +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from graqle.runtime.fetcher import FetchResult, RuntimeEvent

logger = logging.getLogger("graqle.runtime.kg_builder")


class RuntimeKGBuilder:
    """Converts runtime events into KG nodes and edges, and merges them into an existing graph.

    Each RuntimeEvent becomes a RUNTIME_EVENT node. Edges connect events to
    service nodes (if they exist in the KG) and to other events with the same category.
    """

    def __init__(self, graph_path: str = "graqle.json") -> None:
        self.graph_path = Path(graph_path)

    def build_nodes(self, result: FetchResult) -> list[dict[str, Any]]:
        """Convert a FetchResult into KG-ready node dicts."""
        nodes: list[dict[str, Any]] = []
        for event in result.events:
            node = self._event_to_node(event)
            nodes.append(node)
        return nodes

    def build_edges(
        self,
        result: FetchResult,
        existing_node_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build edges connecting runtime events to services and each other."""
        edges: list[dict[str, Any]] = []
        existing = existing_node_ids or set()

        for event in result.events:
            node_id = event.id

            # Connect to service node if it exists in the KG
            service_candidates = [
                event.service_name,
                event.service_name.lower(),
                event.service_name.replace("-", "_"),
                f"/aws/lambda/{event.service_name}",
            ]
            for candidate in service_candidates:
                if candidate in existing:
                    edges.append({
                        "source": node_id,
                        "target": candidate,
                        "relationship": "OBSERVED_IN",
                        "properties": {
                            "category": event.category,
                            "severity": event.severity,
                            "hit_count": event.hit_count,
                        },
                    })
                    break

        # Group events by category and connect related events
        by_category: dict[str, list[RuntimeEvent]] = {}
        for event in result.events:
            by_category.setdefault(event.category, []).append(event)

        for category, cat_events in by_category.items():
            if len(cat_events) > 1:
                # Connect first event to others in same category
                anchor = cat_events[0]
                for other in cat_events[1:5]:  # Limit cross-links
                    edges.append({
                        "source": anchor.id,
                        "target": other.id,
                        "relationship": "RELATED_EVENT",
                        "properties": {"category": category},
                    })

        return edges

    def ingest_into_graph(self, result: FetchResult) -> dict[str, Any]:
        """Merge runtime events into the existing graqle.json graph file.

        Returns summary of what was added.
        """
        if not self.graph_path.exists():
            return {"error": f"Graph file not found: {self.graph_path}"}

        try:
            with open(self.graph_path, encoding="utf-8") as f:
                graph_data = json.load(f)
        except Exception as e:
            return {"error": f"Failed to read graph: {e}"}

        nodes_list = graph_data.get("nodes", [])
        edges_list = graph_data.get("links", graph_data.get("edges", []))

        existing_ids = {n.get("id", n.get("name", "")) for n in nodes_list}

        # Build new nodes and edges
        new_nodes = self.build_nodes(result)
        new_edges = self.build_edges(result, existing_ids)

        # Remove stale runtime events (older than 24h or replaced)
        runtime_ids_to_add = {n["id"] for n in new_nodes}
        nodes_list = [
            n for n in nodes_list
            if n.get("entity_type") != "RUNTIME_EVENT" or n.get("id") in runtime_ids_to_add
        ]

        # Add new nodes (skip duplicates)
        for node in new_nodes:
            if node["id"] not in existing_ids:
                nodes_list.append(node)
                existing_ids.add(node["id"])

        # Add new edges
        existing_edge_keys = {
            f"{e.get('source', '')}:{e.get('target', '')}:{e.get('relationship', '')}"
            for e in edges_list
        }
        for edge in new_edges:
            key = f"{edge['source']}:{edge['target']}:{edge['relationship']}"
            if key not in existing_edge_keys:
                edges_list.append(edge)
                existing_edge_keys.add(key)

        # Write back
        graph_data["nodes"] = nodes_list
        graph_data["edges"] = edges_list

        try:
            with open(self.graph_path, "w", encoding="utf-8") as f:
                json.dump(graph_data, f, indent=2, default=str)
        except Exception as e:
            return {"error": f"Failed to write graph: {e}"}

        return {
            "nodes_added": len(new_nodes),
            "edges_added": len(new_edges),
            "total_nodes": len(nodes_list),
            "total_edges": len(edges_list),
            "critical_events": result.critical_count,
            "high_events": result.high_count,
            "graph_path": str(self.graph_path),
        }

    @staticmethod
    def _event_to_node(event: RuntimeEvent) -> dict[str, Any]:
        """Convert a RuntimeEvent to a KG node dict."""
        # Build a rich description for agent reasoning
        description = (
            f"[{event.severity}] {event.category} in {event.service_name}: "
            f"{event.message[:300]}"
        )
        if event.hit_count > 1:
            description += f" (occurred {event.hit_count}x)"

        return {
            "id": event.id,
            "label": f"{event.category} — {event.service_name}",
            "entity_type": "RUNTIME_EVENT",
            "description": description,
            "properties": {
                "category": event.category,
                "severity": event.severity,
                "source": event.source,
                "service_name": event.service_name,
                "timestamp": event.timestamp,
                "hit_count": event.hit_count,
                "message": event.message[:500],
                "region": event.region,
                "log_group": event.log_group,
            },
        }

    @staticmethod
    def summary(result: FetchResult) -> dict[str, Any]:
        """Generate a human-readable summary of runtime events."""
        if not result.events:
            return {
                "status": "clean",
                "message": f"No issues found in the last {result.time_range_hours}h",
                "provider": result.provider,
                "source": result.source,
            }

        # Group by severity
        by_severity: dict[str, list[RuntimeEvent]] = {}
        for event in result.events:
            by_severity.setdefault(event.severity, []).append(event)

        # Group by category
        by_category: dict[str, int] = {}
        for event in result.events:
            by_category[event.category] = by_category.get(event.category, 0) + event.hit_count

        # Top events
        top_events = sorted(result.events, key=lambda e: e.hit_count, reverse=True)[:5]

        status = "critical" if result.critical_count > 0 else "warning" if result.high_count > 0 else "info"

        return {
            "status": status,
            "provider": result.provider,
            "source": result.source,
            "time_range_hours": result.time_range_hours,
            "total_events": result.event_count,
            "by_severity": {sev: len(evts) for sev, evts in by_severity.items()},
            "by_category": by_category,
            "top_events": [
                {
                    "category": e.category,
                    "severity": e.severity,
                    "service": e.service_name,
                    "hits": e.hit_count,
                    "message": e.message[:200],
                }
                for e in top_events
            ],
            "fetch_duration_ms": round(result.fetch_duration_ms, 1),
            "errors": result.errors,
        }
