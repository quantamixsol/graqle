"""Amazon Neptune connector — cloud-hosted graph database for Team tier.

Neptune Serverless provides:
- Pay-per-query pricing (no idle costs)
- Scales to enterprise workloads
- Gremlin + OpenCypher query support
- Managed backups and snapshots

This connector extends the existing upgrade.py pattern, adding Neptune
as a third backend option alongside JSON/NetworkX and Neo4j.

Architecture: Local graph (JSON) → sync deltas → Neptune (cloud)
The local graph remains the primary store. Neptune is the shared team graph.
"""

# ── graqle:intelligence ──
# module: graqle.connectors.neptune
# risk: MEDIUM (impact radius: 1 modules)
# consumers: test_neptune
# dependencies: __future__, json, logging, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("graqle.connectors.neptune")


def _sanitize_gremlin(value: str) -> str:
    """Sanitize a string value for safe use in Gremlin queries.

    Prevents Gremlin injection by escaping special characters.
    """
    # Escape backslashes first, then single quotes
    return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")


def _sanitize_cypher(value: str) -> str:
    """Sanitize a string value for safe use in OpenCypher queries.

    Prevents Cypher injection by escaping special characters.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Neptune configuration
# ---------------------------------------------------------------------------

@dataclass
class NeptuneConfig:
    """Configuration for Amazon Neptune connection."""

    endpoint: str = ""           # Neptune cluster endpoint
    port: int = 8182             # Default Neptune port
    region: str = ""             # AWS region
    use_iam_auth: bool = True    # Use IAM authentication (recommended)
    database: str = "graqle"     # Neptune database name

    @property
    def websocket_url(self) -> str:
        """WebSocket URL for Gremlin queries."""
        return f"wss://{self.endpoint}:{self.port}/gremlin"

    @property
    def http_url(self) -> str:
        """HTTP URL for OpenCypher queries."""
        return f"https://{self.endpoint}:{self.port}/openCypher"

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.region)


# ---------------------------------------------------------------------------
# Neptune adapter (foundation — actual connection in Phase 3)
# ---------------------------------------------------------------------------

class NeptuneAdapter:
    """Adapter for Amazon Neptune Serverless.

    Phase 1 (foundation): Methods generate Gremlin/OpenCypher queries
    but don't execute them. This validates the query generation logic
    without requiring a Neptune cluster.

    Phase 3+: Methods will execute queries against a real Neptune cluster.
    """

    def __init__(self, config: NeptuneConfig | None = None) -> None:
        self._config = config or NeptuneConfig()
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def connect(self) -> None:
        """Connect to Neptune cluster.

        Phase 1: Validates config. Phase 3+: establishes connection.
        """
        if not self._config.is_configured:
            raise ConnectionError(
                "Neptune not configured. Set endpoint and region in team config, "
                "or use environment variables NEPTUNE_ENDPOINT and AWS_REGION."
            )

        # Phase 1: Validate config only
        logger.info(
            "Neptune adapter initialized (foundation mode): %s:%d in %s",
            self._config.endpoint,
            self._config.port,
            self._config.region,
        )

    def close(self) -> None:
        """Close Neptune connection."""
        self._client = None

    # -- Gremlin query generation ---------------------------------------------

    def generate_upsert_node(self, node: dict[str, Any]) -> str:
        """Generate Gremlin query to upsert a node.

        Uses Neptune's MERGE semantics: create if not exists, update if exists.
        All string values are sanitized to prevent Gremlin injection.
        """
        node_id = _sanitize_gremlin(node.get("id", ""))
        entity_type = _sanitize_gremlin(node.get("entity_type", node.get("type", "Unknown")))

        props = []
        for key, value in node.items():
            if key in ("id",):
                continue
            safe_key = _sanitize_gremlin(key)
            if isinstance(value, str):
                props.append(f".property('{safe_key}', '{_sanitize_gremlin(value)}')")
            elif isinstance(value, (int, float)):
                props.append(f".property('{safe_key}', {value})")
            elif isinstance(value, bool):
                props.append(f".property('{safe_key}', {'true' if value else 'false'})")

        prop_str = "".join(props)
        return (
            f"g.V().has('id', '{node_id}')"
            f".fold()"
            f".coalesce("
            f"  unfold(),"
            f"  addV('{entity_type}').property('id', '{node_id}')"
            f"){prop_str}"
        )

    def generate_upsert_edge(self, edge: dict[str, Any]) -> str:
        """Generate Gremlin query to upsert an edge.

        All string values are sanitized to prevent Gremlin injection.
        """
        edge_id = _sanitize_gremlin(edge.get("id", ""))
        source = _sanitize_gremlin(edge.get("source", ""))
        target = _sanitize_gremlin(edge.get("target", ""))
        relationship = _sanitize_gremlin(edge.get("relationship", "RELATES_TO"))

        props = []
        for key, value in edge.items():
            if key in ("id", "source", "target", "relationship"):
                continue
            safe_key = _sanitize_gremlin(key)
            if isinstance(value, str):
                props.append(f".property('{safe_key}', '{_sanitize_gremlin(value)}')")
            elif isinstance(value, (int, float)):
                props.append(f".property('{safe_key}', {value})")

        prop_str = "".join(props)
        return (
            f"g.V().has('id', '{source}')"
            f".outE('{relationship}').has('id', '{edge_id}')"
            f".fold()"
            f".coalesce("
            f"  unfold(),"
            f"  V().has('id', '{source}')"
            f"  .addE('{relationship}').to(V().has('id', '{target}'))"
            f"  .property('id', '{edge_id}')"
            f"){prop_str}"
        )

    def generate_delete_node(self, node_id: str) -> str:
        """Generate Gremlin query to delete a node and its edges."""
        return f"g.V().has('id', '{_sanitize_gremlin(node_id)}').drop()"

    def generate_delete_edge(self, edge_id: str) -> str:
        """Generate Gremlin query to delete an edge."""
        return f"g.E().has('id', '{_sanitize_gremlin(edge_id)}').drop()"

    def generate_team_query(self, team_id: str, entity_type: str | None = None) -> str:
        """Generate Gremlin query to get all nodes for a team."""
        safe_team = _sanitize_gremlin(team_id)
        if entity_type:
            return (
                f"g.V().has('team_id', '{safe_team}')"
                f".has('entity_type', '{_sanitize_gremlin(entity_type)}')"
                f".valueMap(true)"
            )
        return f"g.V().has('team_id', '{safe_team}').valueMap(true)"

    def generate_cross_repo_edges(self, team_id: str) -> str:
        """Generate Gremlin query to find cross-repo edges."""
        return (
            f"g.V().has('team_id', '{_sanitize_gremlin(team_id)}')"
            f".outE().has('cross_repo', true)"
            f".project('source', 'target', 'relationship', 'source_repo', 'target_repo')"
            f".by(outV().values('id'))"
            f".by(inV().values('id'))"
            f".by(label())"
            f".by(outV().values('repo'))"
            f".by(inV().values('repo'))"
        )

    # -- Batch operations (for sync) -----------------------------------------

    def generate_sync_push_queries(
        self,
        delta: dict[str, Any],
        team_id: str,
        developer_id: str = "",
    ) -> list[str]:
        """Generate all Gremlin queries needed to push a sync delta.

        Returns ordered list of queries to execute sequentially.
        """
        queries: list[str] = []

        # Add team_id and developer info to all nodes
        for node in delta.get("nodes_added", []):
            node["team_id"] = team_id
            if developer_id:
                node["updated_by"] = developer_id
            queries.append(self.generate_upsert_node(node))

        for node in delta.get("nodes_modified", []):
            node["team_id"] = team_id
            if developer_id:
                node["updated_by"] = developer_id
            queries.append(self.generate_upsert_node(node))

        for node_id in delta.get("nodes_deleted", []):
            queries.append(self.generate_delete_node(node_id))

        for edge in delta.get("edges_added", []):
            queries.append(self.generate_upsert_edge(edge))

        for edge in delta.get("edges_modified", []):
            queries.append(self.generate_upsert_edge(edge))

        for edge_id in delta.get("edges_deleted", []):
            queries.append(self.generate_delete_edge(edge_id))

        return queries

    # -- OpenCypher query generation ------------------------------------------

    def generate_cypher_upsert_node(self, node: dict[str, Any]) -> str:
        """Generate OpenCypher MERGE query for a node.

        All string values are sanitized to prevent Cypher injection.
        """
        node_id = _sanitize_cypher(node.get("id", ""))
        entity_type = _sanitize_cypher(node.get("entity_type", "Unknown"))

        props = {k: v for k, v in node.items() if k != "id"}
        set_clause = ", ".join(
            f"n.{_sanitize_cypher(k)} = {json.dumps(v)}" for k, v in props.items()
            if isinstance(v, (str, int, float, bool))
        )

        return (
            f"MERGE (n:{entity_type} {{id: '{node_id}'}}) "
            f"SET {set_clause}"
        )

    def generate_cypher_stats(self, team_id: str) -> str:
        """Generate OpenCypher query for team graph statistics."""
        safe_team = _sanitize_cypher(team_id)
        return (
            f"MATCH (n {{team_id: '{safe_team}'}}) "
            f"RETURN labels(n) AS type, count(n) AS count "
            f"ORDER BY count DESC"
        )


# ---------------------------------------------------------------------------
# Neptune availability check
# ---------------------------------------------------------------------------

def check_neptune_available() -> tuple[bool, str]:
    """Check if Neptune client dependencies are available.

    Phase 1: Always returns available since we only generate queries.
    Phase 3+: Will check for gremlinpython or neptune-python-utils.
    """
    return True, "Neptune adapter available (foundation mode — query generation only)"


def check_neptune_connection(config: NeptuneConfig) -> tuple[bool, str]:
    """Check if a Neptune cluster is reachable.

    Phase 1: Validates config format only.
    Phase 3+: Will attempt actual connection.
    """
    if not config.endpoint:
        return False, "Neptune endpoint not configured"
    if not config.region:
        return False, "AWS region not configured for Neptune"
    return True, f"Neptune config valid: {config.endpoint} in {config.region}"
