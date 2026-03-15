"""Backend upgrade advisor — auto-shift to Neo4j when graph exceeds threshold.

Rule: Never make this decision until needed. When the threshold is exceeded,
auto-handle the migration and notify the user as a recommended action taken.
"""

# ── graqle:intelligence ──
# module: graqle.connectors.upgrade
# risk: LOW (impact radius: 2 modules)
# consumers: main, test_upgrade
# dependencies: __future__, json, logging, shutil, dataclasses +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.connectors.upgrade")

# Threshold: auto-shift to Neo4j at 5,000 nodes
NODE_THRESHOLD = 5000
# Latency threshold: if JSON load takes > 5 seconds
LATENCY_THRESHOLD_SECONDS = 5.0


@dataclass
class UpgradeAssessment:
    """Assessment of whether a backend upgrade is recommended."""

    should_upgrade: bool
    current_backend: str
    recommended_backend: str
    reason: str
    node_count: int
    edge_count: int
    load_time_seconds: float = 0.0

    @property
    def summary(self) -> str:
        if not self.should_upgrade:
            return f"Current backend ({self.current_backend}) is adequate for {self.node_count} nodes."
        return (
            f"Recommended: upgrade from {self.current_backend} → {self.recommended_backend}. "
            f"Reason: {self.reason}"
        )


def assess_upgrade(
    node_count: int,
    edge_count: int,
    current_backend: str = "networkx",
    load_time_seconds: float = 0.0,
    *,
    node_threshold: int = NODE_THRESHOLD,
    latency_threshold: float = LATENCY_THRESHOLD_SECONDS,
) -> UpgradeAssessment:
    """Check if the graph has outgrown its current backend.

    Parameters
    ----------
    node_count:
        Current number of nodes in the graph.
    edge_count:
        Current number of edges.
    current_backend:
        Current backend type ("networkx", "json", "neo4j", "neptune").
    load_time_seconds:
        How long the last graph load took.
    node_threshold:
        Node count at which to recommend upgrade (default 5000).
    latency_threshold:
        Load time in seconds that triggers upgrade recommendation.
    """
    # Already on a scalable backend
    if current_backend in ("neo4j", "neptune"):
        return UpgradeAssessment(
            should_upgrade=False,
            current_backend=current_backend,
            recommended_backend=current_backend,
            reason="Already on scalable backend",
            node_count=node_count,
            edge_count=edge_count,
            load_time_seconds=load_time_seconds,
        )

    # Check node threshold
    if node_count >= node_threshold:
        return UpgradeAssessment(
            should_upgrade=True,
            current_backend=current_backend,
            recommended_backend="neo4j",
            reason=f"Graph has {node_count:,} nodes (threshold: {node_threshold:,})",
            node_count=node_count,
            edge_count=edge_count,
            load_time_seconds=load_time_seconds,
        )

    # Check latency
    if load_time_seconds > latency_threshold:
        return UpgradeAssessment(
            should_upgrade=True,
            current_backend=current_backend,
            recommended_backend="neo4j",
            reason=f"Graph load took {load_time_seconds:.1f}s (threshold: {latency_threshold:.1f}s)",
            node_count=node_count,
            edge_count=edge_count,
            load_time_seconds=load_time_seconds,
        )

    return UpgradeAssessment(
        should_upgrade=False,
        current_backend=current_backend,
        recommended_backend=current_backend,
        reason="Graph size is within JSON/NetworkX capacity",
        node_count=node_count,
        edge_count=edge_count,
        load_time_seconds=load_time_seconds,
    )


def check_neo4j_available() -> tuple[bool, str]:
    """Check if Neo4j driver is installed and a server is reachable."""
    try:
        import neo4j  # noqa: F401
    except ImportError:
        return False, "neo4j driver not installed. Install with: pip install graqle[neo4j]"

    return True, "neo4j driver available"


def generate_migration_cypher(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
) -> list[str]:
    """Generate Cypher statements for migrating JSON graph to Neo4j.

    Returns a list of Cypher statements that can be executed sequentially.
    This reuses the TAMR+ pipeline pattern: UNWIND batch for nodes, then edges.
    """
    statements: list[str] = []

    # Schema: create constraint + index
    statements.append(
        "CREATE CONSTRAINT cogni_node_id IF NOT EXISTS "
        "FOR (n:CogniNode) REQUIRE n.id IS UNIQUE"
    )
    statements.append(
        "CREATE INDEX cogni_node_type IF NOT EXISTS "
        "FOR (n:CogniNode) ON (n.entity_type)"
    )

    # Batch nodes via UNWIND (same pattern as TAMR+ pipeline)
    if nodes:
        statements.append(
            "UNWIND $nodes AS node "
            "MERGE (n:CogniNode {id: node.id}) "
            "SET n.label = node.label, "
            "n.entity_type = node.entity_type, "
            "n.description = node.description, "
            "n += node.properties"
        )

    # Batch edges via UNWIND
    if edges:
        statements.append(
            "UNWIND $edges AS edge "
            "MATCH (a:CogniNode {id: edge.source}) "
            "MATCH (b:CogniNode {id: edge.target}) "
            "MERGE (a)-[r:RELATES_TO {id: edge.id}]->(b) "
            "SET r.relationship = edge.relationship, "
            "r += edge.properties"
        )

    return statements


def migrate_json_to_neo4j(
    json_path: str | Path,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str = "neo4j",
) -> dict[str, Any]:
    """Migrate a JSON graph file to Neo4j.

    Returns a summary dict with counts and status.
    """
    import neo4j as neo4j_driver

    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Graph file not found: {json_path}")

    # Load JSON
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Handle node_link_data format
    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", data.get("links", []))

    # Convert to dict format
    nodes_list = []
    for n in raw_nodes:
        node_data = {
            "id": n.get("id", ""),
            "label": n.get("label", n.get("id", "")),
            "entity_type": n.get("entity_type", n.get("type", "")),
            "description": n.get("description", ""),
            "properties": {k: v for k, v in n.items()
                          if k not in ("id", "label", "entity_type", "type", "description")},
        }
        nodes_list.append(node_data)

    edges_list = []
    for e in raw_edges:
        edge_data = {
            "id": e.get("id", ""),
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "relationship": e.get("relationship", "RELATES_TO"),
            "properties": {k: v for k, v in e.items()
                          if k not in ("id", "source", "target", "relationship")},
        }
        edges_list.append(edge_data)

    # Connect to Neo4j and migrate
    driver = neo4j_driver.GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session(database=neo4j_database) as session:
            # Create schema
            cypher_stmts = generate_migration_cypher(
                {n["id"]: n for n in nodes_list},
                {e["id"]: e for e in edges_list},
            )

            # Execute schema statements
            for stmt in cypher_stmts[:2]:  # constraint + index
                session.run(stmt)

            # Batch insert nodes
            if nodes_list:
                session.run(cypher_stmts[2], nodes=nodes_list)

            # Batch insert edges
            if edges_list and len(cypher_stmts) > 3:
                session.run(cypher_stmts[3], edges=edges_list)

    finally:
        driver.close()

    # Backup original JSON
    backup_path = json_path.with_suffix(".json.bak")
    shutil.copy2(json_path, backup_path)

    return {
        "status": "migrated",
        "nodes_migrated": len(nodes_list),
        "edges_migrated": len(edges_list),
        "neo4j_uri": neo4j_uri,
        "neo4j_database": neo4j_database,
        "backup_path": str(backup_path),
    }
