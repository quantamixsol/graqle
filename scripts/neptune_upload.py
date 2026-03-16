"""Upload Graqle graph data to Neptune Serverless.

Reads the existing graqle.json and pushes all nodes + edges to Neptune
using the production neptune client (SigV4 IAM auth, openCypher HTTPS).

Usage:
    python scripts/neptune_upload.py [--graph-path graqle.json] [--project-id graqle-sdk]

Requires: Lambda role or local AWS credentials with neptune-db:* permissions,
and network access to Neptune (run from within VPC or via SSH tunnel).
"""

import argparse
import json
import logging
import os
import sys
import time

# Add parent to path so we can import graqle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from graqle.connectors.neptune import (
    execute_query,
    upsert_nodes,
    upsert_edges,
    neptune_health,
    get_graph_stats,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def load_graph_json(path: str) -> dict:
    """Load graqle.json graph file."""
    with open(path) as f:
        data = json.load(f)

    # Handle different JSON formats
    if 'nodes' in data and 'links' in data:
        # D3-compatible format (from visualization endpoint)
        return data
    elif 'nodes' in data and 'edges' in data:
        # NetworkX format
        return {'nodes': data['nodes'], 'links': data['edges']}
    else:
        raise ValueError(f"Unknown graph format. Keys: {list(data.keys())}")


def transform_nodes(raw_nodes: list, project_id: str) -> list[dict]:
    """Transform raw graph nodes into Neptune-compatible format."""
    nodes = []
    for n in raw_nodes:
        # Handle both dict-style and list-style nodes
        if isinstance(n, dict):
            node_id = n.get('id', '')
            if not node_id:
                continue
            nodes.append({
                'id': node_id,
                'label': n.get('label', node_id),
                'type': n.get('type', n.get('entity_type', 'Entity')),
                'description': (n.get('description', '') or '')[:500],
                'size': float(n.get('size', 12)),
                'degree': int(n.get('degree', 0)),
                'color': n.get('color', '#64748b'),
            })
    return nodes


def transform_edges(raw_links: list) -> list[dict]:
    """Transform raw graph links into Neptune-compatible format."""
    edges = []
    for e in raw_links:
        if isinstance(e, dict):
            src = e.get('source', '')
            tgt = e.get('target', '')
            if isinstance(src, dict):
                src = src.get('id', '')
            if isinstance(tgt, dict):
                tgt = tgt.get('id', '')
            if not src or not tgt:
                continue
            edges.append({
                'source': src,
                'target': tgt,
                'relationship': e.get('relationship', e.get('type', 'RELATED_TO')),
                'weight': float(e.get('weight', 1.0)),
            })
    return edges


def upload_in_batches(project_id: str, nodes: list[dict], edges: list[dict], batch_size: int = 50):
    """Upload nodes and edges to Neptune in batches with progress."""

    # Upload nodes
    total_nodes = len(nodes)
    uploaded_nodes = 0
    logger.info("Uploading %d nodes in batches of %d...", total_nodes, batch_size)

    for i in range(0, total_nodes, batch_size):
        batch = nodes[i:i + batch_size]
        count = upsert_nodes(project_id, batch)
        uploaded_nodes += count
        pct = (i + len(batch)) / total_nodes * 100
        logger.info("  Nodes: %d/%d (%.0f%%)", uploaded_nodes, total_nodes, pct)

    logger.info("Uploaded %d/%d nodes", uploaded_nodes, total_nodes)

    # Upload edges
    total_edges = len(edges)
    uploaded_edges = 0
    logger.info("Uploading %d edges in batches of %d...", total_edges, batch_size)

    for i in range(0, total_edges, batch_size):
        batch = edges[i:i + batch_size]
        count = upsert_edges(project_id, batch)
        uploaded_edges += count
        pct = (i + len(batch)) / total_edges * 100
        logger.info("  Edges: %d/%d (%.0f%%)", uploaded_edges, total_edges, pct)

    logger.info("Uploaded %d/%d edges", uploaded_edges, total_edges)

    return uploaded_nodes, uploaded_edges


def main():
    parser = argparse.ArgumentParser(description='Upload Graqle graph to Neptune')
    parser.add_argument('--graph-path', default='graqle.json', help='Path to graqle.json')
    parser.add_argument('--project-id', default='graqle-sdk', help='Project ID for Neptune isolation')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for uploads')
    parser.add_argument('--dry-run', action='store_true', help='Parse and count without uploading')
    args = parser.parse_args()

    # Check Neptune connectivity
    logger.info("Checking Neptune connectivity...")
    health = neptune_health()
    if health['status'] != 'connected':
        logger.error("Neptune not reachable: %s", health.get('error', 'unknown'))
        logger.error("Endpoint: %s", health.get('endpoint', '?'))
        logger.error("Make sure you're running from within the VPC or have a tunnel.")
        sys.exit(1)
    logger.info("Neptune connected: %s", health['endpoint'])

    # Load graph
    logger.info("Loading graph from %s...", args.graph_path)
    data = load_graph_json(args.graph_path)
    raw_nodes = data.get('nodes', [])
    raw_links = data.get('links', [])
    logger.info("Loaded %d raw nodes, %d raw links", len(raw_nodes), len(raw_links))

    # Transform
    nodes = transform_nodes(raw_nodes, args.project_id)
    edges = transform_edges(raw_links)
    logger.info("Transformed: %d nodes, %d edges", len(nodes), len(edges))

    if args.dry_run:
        logger.info("DRY RUN — not uploading. Would upload %d nodes and %d edges.", len(nodes), len(edges))
        return

    # Upload
    start = time.time()
    uploaded_nodes, uploaded_edges = upload_in_batches(
        args.project_id, nodes, edges, batch_size=args.batch_size
    )
    elapsed = time.time() - start

    # Verify
    logger.info("Verifying Neptune graph stats...")
    stats = get_graph_stats(args.project_id)
    logger.info("Neptune stats: %s", json.dumps(stats, indent=2))

    logger.info(
        "DONE: %d nodes, %d edges uploaded in %.1fs",
        uploaded_nodes, uploaded_edges, elapsed
    )


if __name__ == '__main__':
    main()
