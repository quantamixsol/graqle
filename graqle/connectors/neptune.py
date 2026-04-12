"""Amazon Neptune openCypher client for Graqle.

Production client for querying the graqle-kg Neptune Serverless cluster.
Uses HTTPS + openCypher via HTTP POST, with SigV4 IAM authentication.

Ported from the regulatory product Studio's neptune_client.py (studio-tamr-kg pattern).

Cluster: graqle-kg (eu-central-1, serverless v2)
Endpoint: graqle-kg.cluster-cfb3tqihxeti.eu-central-1.neptune.amazonaws.com:8182
"""

# ── graqle:intelligence ──
# module: graqle.connectors.neptune
# risk: MEDIUM (impact radius: 1 modules)
# consumers: lambda_handler, server.app
# dependencies: json, logging, os, requests, botocore
# constraints: must be in same VPC as Neptune cluster
# ── /graqle:intelligence ──

import json
import logging
import os
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger("graqle.connectors.neptune")

# Lazy imports — requests and botocore are only available on Lambda/production
# Not included in base SDK install to keep dependencies minimal
requests = None
botocore = None


def _ensure_deps():
    """Lazy-import requests and botocore on first use."""
    global requests, botocore
    if requests is None:
        import requests as _requests
        requests = _requests
    if botocore is None:
        import botocore as _botocore
        import botocore.session  # noqa: F811
        import botocore.auth  # noqa: F811
        import botocore.awsrequest  # noqa: F811
        botocore = _botocore

# ─── Config ─────────────────────────────────────────────────────────────────

NEPTUNE_ENDPOINT = os.environ.get(
    "NEPTUNE_ENDPOINT",
    "graqle-kg.cluster-cfb3tqihxeti.eu-central-1.neptune.amazonaws.com",
)
NEPTUNE_PORT = int(os.environ.get("NEPTUNE_PORT", "8182"))
NEPTUNE_REGION = os.environ.get("NEPTUNE_REGION", "eu-central-1")
NEPTUNE_IAM_AUTH = os.environ.get("NEPTUNE_IAM_AUTH", "true").lower() in ("true", "1")

_BASE_URL = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/openCypher"
_SESSION = None  # Lazy-initialized requests.Session
_NEPTUNE_TIMEOUT = 30  # 30s for cold Neptune cluster startup
_NEPTUNE_UNAVAILABLE = False  # Set True after first timeout — skip remaining calls


def _get_session():
    """Get or create the requests Session (lazy init)."""
    global _SESSION
    if _SESSION is None:
        _ensure_deps()
        _SESSION = requests.Session()
        _SESSION.headers.update({"Content-Type": "application/x-www-form-urlencoded"})
    return _SESSION


# ─── Core query execution ───────────────────────────────────────────────────

def execute_query(query: str, parameters: dict | None = None) -> list[dict]:
    """Execute an openCypher query against Neptune. Returns list of result rows."""
    global _NEPTUNE_UNAVAILABLE
    _ensure_deps()

    if _NEPTUNE_UNAVAILABLE:
        raise RuntimeError("Neptune unavailable for this invocation (previous timeout)")

    data = {"query": query}
    if parameters:
        data["parameters"] = json.dumps(parameters)

    session = _get_session()
    try:
        if NEPTUNE_IAM_AUTH:
            resp = _execute_with_iam(data)
        else:
            resp = session.post(_BASE_URL, data=data, timeout=_NEPTUNE_TIMEOUT)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        _NEPTUNE_UNAVAILABLE = True
        raise RuntimeError(f"Neptune timeout/connection error: {e}") from e

    if resp.status_code != 200:
        logger.error("Neptune query failed: %s — %s", resp.status_code, resp.text[:500])
        raise RuntimeError(f"Neptune query failed ({resp.status_code}): {resp.text[:500]}")

    return resp.json().get("results", [])


def _execute_with_iam(data: dict):
    """Execute query with SigV4 IAM auth signing."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = botocore.session.get_session()
    credentials = session.get_credentials().get_frozen_credentials()

    encoded_body = urlencode(data)
    request = AWSRequest(
        method="POST",
        url=_BASE_URL,
        data=encoded_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    SigV4Auth(credentials, "neptune-db", NEPTUNE_REGION).add_auth(request)

    return _get_session().post(
        _BASE_URL,
        data=encoded_body,
        headers=dict(request.headers),
        timeout=_NEPTUNE_TIMEOUT,
    )


# ─── Graph Query Functions (GraQle-specific) ─────────────────────────────────

def get_nodes(project_id: str) -> list[dict]:
    """Get all nodes for a project. Returns D3-compatible node dicts."""
    query = """
    MATCH (n:GraqleNode {project_id: $pid})
    RETURN n.id AS id, n.label AS label, n.type AS type,
           n.description AS description, n.size AS size,
           n.degree AS degree, n.color AS color,
           n.properties AS properties
    """
    return execute_query(query, {"pid": project_id})


def get_edges(project_id: str) -> list[dict]:
    """Get all edges for a project. Returns D3-compatible link dicts."""
    query = """
    MATCH (s:GraqleNode {project_id: $pid})-[r]->(t:GraqleNode {project_id: $pid})
    RETURN r.id AS id, s.id AS source, t.id AS target,
           type(r) AS relationship, r.weight AS weight
    """
    return execute_query(query, {"pid": project_id})


def get_graph_stats(project_id: str) -> dict:
    """Get node/edge counts and type distribution for a project."""
    node_query = """
    MATCH (n:GraqleNode {project_id: $pid})
    RETURN n.type AS type, count(n) AS cnt
    """
    edge_query = """
    MATCH (s:GraqleNode {project_id: $pid})-[r]->(t:GraqleNode {project_id: $pid})
    RETURN count(r) AS edge_count
    """

    type_results = execute_query(node_query, {"pid": project_id})
    edge_results = execute_query(edge_query, {"pid": project_id})

    type_counts = {}
    total_nodes = 0
    for r in type_results:
        t = r.get("type", "UNKNOWN")
        c = r.get("cnt", 0)
        type_counts[t] = c
        total_nodes += c

    edge_count = edge_results[0].get("edge_count", 0) if edge_results else 0

    return {
        "node_count": total_nodes,
        "edge_count": edge_count,
        "type_counts": type_counts,
    }


def get_visualization(project_id: str) -> dict:
    """Get full D3-compatible visualization data {nodes, links}.

    This is the primary endpoint for the Graph Explorer.
    Returns the same format as the current JSON-based visualization route.
    """
    nodes = get_nodes(project_id)
    edges = get_edges(project_id)

    # Format nodes for D3
    d3_nodes = []
    for n in nodes:
        d3_nodes.append({
            "id": n.get("id", ""),
            "label": n.get("label", n.get("id", "")),
            "type": n.get("type", "Entity"),
            "description": (n.get("description") or "")[:200],
            "size": n.get("size", 12),
            "degree": n.get("degree", 0),
            "color": n.get("color", "#64748b"),
        })

    # Format edges for D3
    d3_links = []
    for e in edges:
        d3_links.append({
            "id": e.get("id", ""),
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "relationship": e.get("relationship", "RELATED_TO"),
            "weight": e.get("weight", 1.0),
        })

    return {"nodes": d3_nodes, "links": d3_links}


def get_node_neighbors(project_id: str, node_id: str, max_hops: int = 2) -> list[dict]:
    """Multi-hop traversal from a node. Used for impact blast radius."""
    query = f"""
    MATCH path = (start:GraqleNode {{id: $nid, project_id: $pid}})-[*1..{max_hops}]->(target:GraqleNode)
    WHERE target.project_id = $pid AND target.id <> $nid
    WITH target, length(path) AS hops
    WITH target, hops,
         CASE hops WHEN 1 THEN 1.0 WHEN 2 THEN 0.5 WHEN 3 THEN 0.25 ELSE 0.1 END AS decay
    RETURN target.id AS id, target.label AS label, target.type AS type,
           hops, max(decay) AS score
    ORDER BY score DESC
    LIMIT 50
    """
    return execute_query(query, {"nid": node_id, "pid": project_id})


# ─── Write Functions (for graq cloud push) ──────────────────────────────────

def upsert_nodes(project_id: str, nodes: list[dict]) -> int:
    """MERGE nodes into Neptune. Returns count of upserted nodes."""
    if not nodes:
        return 0
    # Fast-exit: if Neptune already known unavailable, skip the whole batch silently
    if _NEPTUNE_UNAVAILABLE:
        logger.debug("Neptune unavailable — skipping upsert of %d nodes", len(nodes))
        return 0
    count = 0
    for node in nodes:
        nid = node.get("id", "")
        if not nid:
            continue
        query = """
        MERGE (n:GraqleNode {id: $nid, project_id: $pid})
        SET n.label = $label, n.type = $type, n.description = $description,
            n.size = $size, n.degree = $degree, n.color = $color
        """
        try:
            execute_query(query, {
                "nid": nid,
                "pid": project_id,
                "label": node.get("label", nid),
                "type": node.get("type", "Entity"),
                "description": (node.get("description") or "")[:500],
                "size": float(node.get("size", 12)),
                "degree": int(node.get("degree", 0)),
                "color": node.get("color", "#64748b"),
            })
            count += 1
        except RuntimeError:
            # Neptune unavailable (VPC-only in local dev) — abort batch silently
            logger.debug("Neptune unavailable — aborting node upsert batch after %d", count)
            break
        except Exception as e:
            logger.debug("Failed to upsert node %s: %s", nid, str(e)[:100])
    return count


def upsert_edges(project_id: str, edges: list[dict]) -> int:
    """MERGE edges into Neptune. Returns count of upserted edges."""
    if not edges:
        return 0
    # Fast-exit: if Neptune already known unavailable, skip the whole batch silently
    if _NEPTUNE_UNAVAILABLE:
        logger.debug("Neptune unavailable — skipping upsert of %d edges", len(edges))
        return 0
    count = 0
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        rtype = edge.get("relationship", "RELATED_TO").upper().replace(" ", "_")
        if not src or not tgt:
            continue
        weight = float(edge.get("weight", 1.0)) if edge.get("weight") else 1.0
        # Neptune requires dynamic relationship types via string interpolation
        query = f"""
        MATCH (s:GraqleNode {{id: $src, project_id: $pid}})
        MATCH (t:GraqleNode {{id: $tgt, project_id: $pid}})
        MERGE (s)-[r:{rtype}]->(t)
        SET r.weight = $weight
        """
        try:
            execute_query(query, {
                "src": src, "tgt": tgt, "pid": project_id,
                "weight": weight,
            })
            count += 1
        except RuntimeError:
            # Neptune unavailable (VPC-only in local dev) — abort batch silently
            logger.debug("Neptune unavailable — aborting edge upsert batch after %d", count)
            break
        except Exception as e:
            logger.debug("Failed to upsert edge %s->%s: %s", src[:8], tgt[:8], str(e)[:100])
    return count


# ─── Cross-Project Queries (Sprint 6) ──────────────────────────────────────

def cross_project_search(project_ids: list[str], query_text: str, limit: int = 50) -> list[dict]:
    """Search for nodes matching a text pattern across multiple projects.

    This is the cross-project reasoning query — answers questions like
    "what connects the regulatory product to graqle?" by finding shared node types,
    similar labels, and cross-boundary dependencies.
    """
    if not project_ids:
        return []
    query = """
    MATCH (n:GraqleNode)
    WHERE n.project_id IN $pids
      AND (toLower(n.label) CONTAINS toLower($q) OR toLower(n.description) CONTAINS toLower($q))
    RETURN n.id AS id, n.label AS label, n.type AS type,
           n.project_id AS project_id, n.description AS description,
           n.degree AS degree
    ORDER BY n.degree DESC
    LIMIT $lim
    """
    return execute_query(query, {"pids": project_ids, "q": query_text, "lim": limit})


def cross_project_shared_types(project_ids: list[str]) -> list[dict]:
    """Find entity types that appear in multiple projects.

    Useful for identifying shared patterns, common services,
    and architectural overlaps between codebases.
    """
    if len(project_ids) < 2:
        return []
    query = """
    MATCH (n:GraqleNode)
    WHERE n.project_id IN $pids
    WITH n.type AS type, n.project_id AS pid
    WITH type, collect(DISTINCT pid) AS projects, count(*) AS total
    WHERE size(projects) > 1
    RETURN type, projects, total
    ORDER BY total DESC
    """
    return execute_query(query, {"pids": project_ids})


def cross_project_connections(project_a: str, project_b: str, limit: int = 20) -> list[dict]:
    """Find potential connections between two projects.

    Looks for nodes with the same label or type across project boundaries.
    These represent shared abstractions, common services, or integration points.
    """
    query = """
    MATCH (a:GraqleNode {project_id: $pa}), (b:GraqleNode {project_id: $pb})
    WHERE a.label = b.label OR (a.type = b.type AND a.type <> 'MODULE')
    RETURN a.id AS source_id, a.label AS source_label, a.type AS source_type,
           a.project_id AS source_project,
           b.id AS target_id, b.label AS target_label, b.type AS target_type,
           b.project_id AS target_project,
           CASE WHEN a.label = b.label THEN 'SAME_NAME' ELSE 'SAME_TYPE' END AS connection_type
    ORDER BY connection_type, a.label
    LIMIT $lim
    """
    return execute_query(query, {"pa": project_a, "pb": project_b, "lim": limit})


def list_all_projects() -> list[dict]:
    """List all projects in Neptune with node/edge counts."""
    query = """
    MATCH (n:GraqleNode)
    WITH n.project_id AS project_id, count(n) AS node_count,
         collect(DISTINCT n.type) AS types
    RETURN project_id, node_count, size(types) AS type_count
    ORDER BY node_count DESC
    """
    return execute_query(query)


# ─── Health & Utility ───────────────────────────────────────────────────────

def neptune_health() -> dict:
    """Quick health check — returns status and basic info."""
    try:
        execute_query("RETURN 'ok' AS status, 1 AS connected")
        return {
            "status": "connected",
            "endpoint": NEPTUNE_ENDPOINT,
            "port": NEPTUNE_PORT,
            "region": NEPTUNE_REGION,
            "iam_auth": NEPTUNE_IAM_AUTH,
        }
    except Exception as e:
        return {
            "status": "error",
            "endpoint": NEPTUNE_ENDPOINT,
            "error": str(e)[:200],
        }


def reset_availability() -> None:
    """Reset the unavailability flag (e.g., for new Lambda invocations)."""
    global _NEPTUNE_UNAVAILABLE
    _NEPTUNE_UNAVAILABLE = False


# ─── Backwards compatibility ────────────────────────────────────────────────
# These keep existing tests and imports working.

def _sanitize_cypher(value: str) -> str:
    """Sanitize a string value for safe use in OpenCypher queries."""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def check_neptune_available() -> tuple[bool, str]:
    """Check if Neptune client dependencies are available."""
    try:
        import requests as _r
        import botocore as _b
        return True, "Neptune client available (production mode — HTTPS + SigV4)"
    except ImportError as e:
        return False, f"Missing dependency: {e}"


def check_neptune_connection() -> tuple[bool, str]:
    """Check if the Neptune cluster is reachable."""
    result = neptune_health()
    if result["status"] == "connected":
        return True, f"Connected to {NEPTUNE_ENDPOINT}"
    return False, result.get("error", "Unknown error")
