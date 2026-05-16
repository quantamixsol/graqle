"""Neo4j connector — production graph database integration.

Supports both read (load) and write (save) operations, plus vector search
on chunk embeddings for CypherActivation .
"""

# ── graqle:intelligence ──
# module: graqle.connectors.neo4j
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, logging, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from graqle.connectors.base import BaseConnector

logger = logging.getLogger("graqle.connectors.neo4j")


_VALID_REL_TYPE_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _sanitise_rel_type(name: Any) -> str:
    """Coerce an edge relationship label into a Cypher-identifier-safe rel type.

    CR-006b: Neo4j relationship types are interpolated directly into the Cypher
    string at save time so parallel typed edges (CALLS, DEFINES, IMPORTS, ...)
    are stored as distinct native relationships instead of all collapsing to
    ``:RELATED_TO``. To keep the interpolation safe:

    1. Coerce to ``str`` then upper-case.
    2. Replace spaces and hyphens with underscores.
    3. If the result still doesn't match ``[A-Z_][A-Z0-9_]*``, fall back to
       ``RELATED_TO`` — never trust untrusted input as a Cypher identifier.

    Empty / None / unknown shapes all sink to ``RELATED_TO`` so the migration
    never crashes and Cypher injection is impossible by construction.
    """
    if name is None:
        return "RELATED_TO"
    raw = str(name).strip().upper().replace(" ", "_").replace("-", "_")
    if not raw or not _VALID_REL_TYPE_RE.match(raw):
        # CR-006b security review MINOR: debug-log fallback so unexpected
        # shapes (Cypher-unsafe identifiers, injection payloads) are
        # observable in audit logs. The raw value is *not* logged at info
        # level to avoid leaking potentially adversarial content into
        # higher-priority log sinks.
        logger.debug(
            "rel-type fallback: %r -> RELATED_TO (not a Cypher identifier)",
            name,
        )
        return "RELATED_TO"
    return raw


class Neo4jConnector(BaseConnector):
    """Load/save graph data from/to a Neo4j database.

    Requires: pip install graqle[neo4j]

    Supports:
    - Custom Cypher queries for flexible graph extraction
    - Batch write via UNWIND (nodes + edges)
    - Chunk storage with :HAS_CHUNK relationships
    - Vector index creation and cosine similarity search
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
        node_query: str | None = None,
        edge_query: str | None = None,
        vector_index_name: str = "cogni_chunk_embedding_index",
        embedding_dimension: int = 1024,
    ) -> None:
        self._uri = uri
        self._username = username
        self._password = password
        self._database = database
        self._driver = None
        self._vector_index_name = vector_index_name
        self._embedding_dimension = embedding_dimension

        # Custom Cypher queries (or defaults)
        self._node_query = node_query or (
            "MATCH (n:CogniNode) RETURN "
            "n.id AS id, "
            "n.entity_type AS type, "
            "n.label AS label, "
            "n.description AS description, "
            "properties(n) AS properties"
        )
        self._edge_query = edge_query or (
            "MATCH (a:CogniNode)-[r]->(b:CogniNode) RETURN "
            "r.id AS id, "
            "a.id AS source, "
            "b.id AS target, "
            "type(r) AS relationship, "
            "properties(r) AS properties"
        )

    @property
    def uri(self) -> str:
        return self._uri

    def _get_driver(self):
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(
                    self._uri, auth=(self._username, self._password)
                )
            except ImportError:
                raise ImportError(
                    "Neo4j connector requires 'neo4j'. "
                    "Install with: pip install graqle[neo4j]"
                )
        return self._driver

    # --- Read operations ---

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load graph from Neo4j."""
        driver = self._get_driver()
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        with driver.session(database=self._database) as session:
            # Load nodes
            result = session.run(self._node_query)
            for record in result:
                nid = str(record["id"])
                props = dict(record.get("properties", {}))
                # Remove keys already extracted to avoid duplication
                for k in ("id", "label", "entity_type", "description"):
                    props.pop(k, None)
                nodes[nid] = {
                    "label": record.get("label") or nid,
                    "type": record.get("type") or "Entity",
                    "description": record.get("description") or "",
                    "properties": props,
                }

            # Load edges — CR-006a: when r.id is NULL (typed-edge writers that
            # don't set it), build a unique synthetic eid that includes the
            # relationship type and a per-result counter so parallel edges
            # between the same (source, target) pair don't collide in the
            # raw_edges dict and disappear at load time.
            result = session.run(self._edge_query)
            for idx, record in enumerate(result):
                raw_id = record.get("id")
                rel = record.get("relationship") or "RELATED_TO"
                raw_src = record.get("source")
                raw_tgt = record.get("target")
                if raw_src is None or raw_tgt is None:
                    logger.warning(
                        "Skipping malformed edge record at idx=%d "
                        "(missing source or target; raw_id=%s rel=%s)",
                        idx, "yes" if raw_id else "no", rel,
                    )
                    continue
                src = str(raw_src)
                tgt = str(raw_tgt)
                if raw_id:
                    eid = str(raw_id)
                else:
                    eid = f"e_{src}_{tgt}_{rel}_{idx}"
                props = dict(record.get("properties", {}))
                edges[eid] = {
                    "source": src,
                    "target": tgt,
                    "relationship": rel,
                    "weight": props.pop("weight", 1.0),
                    "properties": props,
                }

        logger.info("Loaded %d nodes, %d edges from Neo4j", len(nodes), len(edges))
        return nodes, edges

    def load_chunks(self) -> dict[str, list[dict]]:
        """Load chunks for all nodes. Returns {node_id: [chunk_dicts]}."""
        driver = self._get_driver()
        chunks_by_node: dict[str, list[dict]] = {}

        with driver.session(database=self._database) as session:
            result = session.run(
                "MATCH (n:CogniNode)-[:HAS_CHUNK]->(c:Chunk) "
                "RETURN n.id AS node_id, c.id AS chunk_id, "
                "c.text AS text, c.type AS type, c.index AS idx "
                "ORDER BY n.id, c.index"
            )
            for record in result:
                nid = str(record["node_id"])
                chunk = {
                    "text": record.get("text", ""),
                    "type": record.get("type", "text"),
                }
                chunks_by_node.setdefault(nid, []).append(chunk)

        logger.info(
            "Loaded chunks for %d nodes (%d total chunks)",
            len(chunks_by_node),
            sum(len(c) for c in chunks_by_node.values()),
        )
        return chunks_by_node

    # --- Write operations ---

    def save(self, nodes: dict[str, Any], edges: dict[str, Any]) -> None:
        """Batch write nodes and edges to Neo4j using UNWIND."""
        driver = self._get_driver()

        # Prepare node data
        node_rows = []
        for nid, data in nodes.items():
            row: dict[str, Any] = {
                "id": nid,
                "label": data.get("label", nid),
                "entity_type": data.get("type", data.get("entity_type", "Entity")),
                "description": data.get("description", ""),
            }
            # Flatten simple properties (strings/numbers only)
            props = data.get("properties", {})
            for k, v in props.items():
                if k not in ("id", "label", "entity_type", "description", "chunks"):
                    if isinstance(v, (str, int, float, bool)):
                        row[k] = v
            node_rows.append(row)

        # Prepare edge data
        edge_rows = []
        for eid, data in edges.items():
            edge_rows.append({
                "id": eid,
                "source": str(data["source"]),
                "target": str(data["target"]),
                "relationship": data.get("relationship", "RELATED_TO"),
                "weight": data.get("weight", 1.0),
            })

        with driver.session(database=self._database) as session:
            # Batch UNWIND nodes
            if node_rows:
                session.run(
                    "UNWIND $rows AS row "
                    "MERGE (n:CogniNode {id: row.id}) "
                    "SET n += row",
                    rows=node_rows,
                )

            # Batch UNWIND edges — CR-006b: group by sanitised relationship
            # type and run one UNWIND per type so parallel typed edges (CALLS,
            # DEFINES, IMPORTS, USES_ENVVAR, ...) are stored as distinct native
            # Neo4j relationships instead of all collapsing to :RELATED_TO.
            # Rel type is interpolated into the Cypher string after passing
            # through _sanitise_rel_type so injection is impossible — any
            # non-identifier shape falls back to :RELATED_TO.
            rel_type_count = 0
            if edge_rows:
                by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in edge_rows:
                    rtype = _sanitise_rel_type(row.get("relationship"))
                    by_type[rtype].append(row)
                rel_type_count = len(by_type)
                for rtype, rows in by_type.items():
                    session.run(
                        f"UNWIND $rows AS row "
                        f"MATCH (a:CogniNode {{id: row.source}}) "
                        f"MATCH (b:CogniNode {{id: row.target}}) "
                        f"MERGE (a)-[r:{rtype} {{id: row.id}}]->(b) "
                        f"SET r.relationship = row.relationship, "
                        f"    r.weight = row.weight",
                        rows=rows,
                    )

        logger.info(
            "Saved %d nodes, %d edges to Neo4j (across %d rel types)",
            len(node_rows), len(edge_rows), rel_type_count,
        )

    def save_chunks(
        self,
        chunks_by_node: dict[str, list[dict]],
        embed_fn: Any | None = None,
    ) -> int:
        """Create :Chunk nodes with :HAS_CHUNK relationships and optional embeddings.

        Args:
            chunks_by_node: {node_id: [{text, type, ...}, ...]}
            embed_fn: Optional callable(text) -> list[float] for generating embeddings.

        Returns:
            Total number of chunks written.
        """
        driver = self._get_driver()
        total = 0

        chunk_rows: list[dict[str, Any]] = []
        for nid, chunks in chunks_by_node.items():
            for idx, chunk in enumerate(chunks):
                text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                if not text:
                    continue
                row: dict[str, Any] = {
                    "chunk_id": f"{nid}_chunk_{idx}",
                    "node_id": nid,
                    "text": text,
                    "type": chunk.get("type", "text") if isinstance(chunk, dict) else "text",
                    "index": idx,
                }
                if embed_fn is not None:
                    try:
                        row["embedding"] = embed_fn(text)
                    except Exception as exc:
                        logger.warning("Embedding failed for %s chunk %d: %s", nid, idx, exc)
                chunk_rows.append(row)
                total += 1

        if not chunk_rows:
            return 0

        with driver.session(database=self._database) as session:
            # Write chunks in batches of 500
            batch_size = 500
            for i in range(0, len(chunk_rows), batch_size):
                batch = chunk_rows[i : i + batch_size]
                has_embeddings = "embedding" in batch[0]

                if has_embeddings:
                    session.run(
                        "UNWIND $rows AS row "
                        "MATCH (n:CogniNode {id: row.node_id}) "
                        "MERGE (c:Chunk {id: row.chunk_id}) "
                        "SET c.text = row.text, c.type = row.type, "
                        "    c.index = row.index, c.embedding = row.embedding "
                        "MERGE (n)-[:HAS_CHUNK]->(c)",
                        rows=batch,
                    )
                else:
                    session.run(
                        "UNWIND $rows AS row "
                        "MATCH (n:CogniNode {id: row.node_id}) "
                        "MERGE (c:Chunk {id: row.chunk_id}) "
                        "SET c.text = row.text, c.type = row.type, "
                        "    c.index = row.index "
                        "MERGE (n)-[:HAS_CHUNK]->(c)",
                        rows=batch,
                    )

        logger.info("Saved %d chunks for %d nodes to Neo4j", total, len(chunks_by_node))
        return total

    # --- Schema management ---

    def create_schema(self) -> None:
        """Create constraints and vector index for GraQle schema."""
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            # Uniqueness constraints
            session.run(
                "CREATE CONSTRAINT cogninode_id IF NOT EXISTS "
                "FOR (n:CogniNode) REQUIRE n.id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
                "FOR (c:Chunk) REQUIRE c.id IS UNIQUE"
            )

            # Vector index on chunk embeddings
            session.run(
                "CREATE VECTOR INDEX $index_name IF NOT EXISTS "
                "FOR (c:Chunk) ON (c.embedding) "
                "OPTIONS {indexConfig: {"
                "  `vector.dimensions`: $dimensions, "
                "  `vector.similarity_function`: 'cosine'"
                "}}",
                index_name=self._vector_index_name,
                dimensions=self._embedding_dimension,
            )

        logger.info(
            "Schema created: CogniNode/Chunk constraints + vector index '%s' (%d-dim)",
            self._vector_index_name,
            self._embedding_dimension,
        )

    # --- Vector search ---

    def vector_search(
        self,
        query_embedding: list[float],
        k: int = 20,
        max_nodes: int | None = None,
    ) -> list[tuple[str, float]]:
        """Cypher vector search on chunk embeddings → parent node IDs + scores.

        Returns list of (node_id, relevance_score) sorted by relevance desc.
        """
        driver = self._get_driver()
        max_nodes = max_nodes or k

        with driver.session(database=self._database) as session:
            result = session.run(
                "CALL db.index.vector.queryNodes($index_name, $k, $query_embedding) "
                "YIELD node AS chunk, score AS vec_score "
                "MATCH (chunk)<-[:HAS_CHUNK]-(n:CogniNode) "
                "RETURN DISTINCT n.id AS node_id, max(vec_score) AS relevance "
                "ORDER BY relevance DESC LIMIT $max_nodes",
                index_name=self._vector_index_name,
                k=k,
                query_embedding=query_embedding,
                max_nodes=max_nodes,
            )
            hits = [(str(record["node_id"]), float(record["relevance"])) for record in result]

        logger.debug("Vector search returned %d nodes (k=%d)", len(hits), k)
        return hits

    # --- Health checks ---

    def validate(self) -> bool:
        try:
            driver = self._get_driver()
            driver.verify_connectivity()
            return True
        except Exception:
            return False

    def health_check(self) -> dict[str, Any]:
        """Detailed health check for `graq doctor`."""
        info: dict[str, Any] = {"connected": False}
        try:
            driver = self._get_driver()
            driver.verify_connectivity()
            info["connected"] = True
        except Exception as exc:
            info["error"] = str(exc)
            return info

        try:
            with driver.session(database=self._database) as session:
                # Node count
                result = session.run("MATCH (n:CogniNode) RETURN count(n) AS cnt")
                info["node_count"] = result.single()["cnt"]

                # Chunk count
                result = session.run("MATCH (c:Chunk) RETURN count(c) AS cnt")
                info["chunk_count"] = result.single()["cnt"]

                # Vector index status
                result = session.run(
                    "SHOW INDEXES YIELD name, state "
                    "WHERE name = $idx RETURN state",
                    idx=self._vector_index_name,
                )
                rec = result.single()
                info["vector_index_state"] = rec["state"] if rec else "NOT_FOUND"
        except Exception as exc:
            info["detail_error"] = str(exc)

        return info

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
