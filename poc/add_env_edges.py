"""
add_env_edges.py — Add env-var -> Lambda REQUIRED_BY edges and svc -> svc INVOKES edges
to cognigraph.json.

Sources:
  1. .gcc/departments/engineering-kg.md (ENVVAR REQUIREMENTS + INVOCATION CHAIN)
  2. .gcc/project-kg.md (ENVVAR REQUIREMENTS table)
  3. crawlq-athena-eu-backend/SemanticGraphEU/**/handler.py (os.environ.get scans)
  4. crawlq-athena-eu-backend/SemanticGraphEU/shared/eu_config.py (centralized env vars)
"""

import json
import os
import re
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(r"c:\Users\haris\CrawlQ")
COGNIGRAPH = ROOT / "cognigraph.json"
BACKEND = ROOT / "crawlq-athena-eu-backend" / "SemanticGraphEU"

# ── 1. Env-var requirements from project-kg.md (ground truth) ───────────────
# Transcribed from the ENVVAR REQUIREMENTS table in project-kg.md
KG_ENVVAR_REQUIREMENTS: dict[str, dict[str, bool]] = {
    "l01": {"s3_bucket": True},
    "l02": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True, "s3_bucket": True},
    "l03": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True, "s3_bucket": True},
    "l04": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True, "s3_bucket": True},
    "l05": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True},
    "l06": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True},
    "l07": {"neo4j_password": True, "neo4j_uri": True},
    "l08": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True},
    "l09": {"neo4j_password": True, "neo4j_uri": True},
    "l10": {"bedrock_model": True, "s3_bucket": True},
    "l11": {"bedrock_model": True, "s3_bucket": True},
    "l12": {"neo4j_password": True, "neo4j_uri": True},
    "l13": {"neo4j_password": True, "neo4j_uri": True, "bedrock_model": True, "s3_bucket": True},
    "l14": {"neo4j_password": True, "neo4j_uri": True},
}

# ── 2. Invocation chain from engineering-kg.md / project-kg.md ──────────────
INVOCATION_CHAIN: list[dict] = [
    {"source": "svc::l01", "target": "svc::l03", "trigger": "Always on upload", "call_type": "async"},
    {"source": "svc::l01", "target": "svc::l04", "trigger": "Conditional: skip_insights=false", "call_type": "async"},
    {"source": "svc::l02", "target": "svc::l03", "trigger": "Manual reprocess", "call_type": "async"},
    {"source": "svc::l03", "target": "svc::l08", "trigger": "If governance frameworks active", "call_type": "async"},
    {"source": "svc::l05", "target": "svc::l17", "trigger": "Save/load chat history", "call_type": "sync"},
    {"source": "svc::l06", "target": "svc::l17", "trigger": "Save/load chat history", "call_type": "sync"},
    {"source": "svc::l10", "target": "svc::l03", "trigger": "Compliance re-eval", "call_type": "async"},
    {"source": "svc::l18", "target": "svc::l03", "trigger": "Research pipeline", "call_type": "async"},
    {"source": "svc::l18", "target": "svc::l16", "trigger": "Web augmentation", "call_type": "sync"},
]

# ── 3. Scan handler files for os.environ / os.getenv calls ──────────────────
#    Maps env-var name patterns to canonical env node IDs

ENV_VAR_PATTERNS = {
    r"NEO4J_PASSWORD": "neo4j_password",
    r"NEO4J_URI": "neo4j_uri",
    r"S3_BUCKET": "s3_bucket",
    r"BEDROCK_MODEL|EU_BEDROCK_MODEL_ID": "bedrock_model",
    r"EU_GRAPH_EXTRACTION_MODEL": "graph_extraction_model",
    r"EU_GRAPH_FALLBACK_MODEL": "graph_fallback_model",
    r"CHUNK_CONCURRENCY": "chunk_concurrency",
    r"PERPLEXITY_API_KEY": "perplexity_api_key",
    r"COGNITO_USER_POOL_ID": "cognito_user_pool_id",
    r"SQS_QUEUE_URL": "sqs_queue_url",
    r"DYNAMODB_TABLE": "dynamodb_table",
    r"CONVERSATION_MEMORY_FUNCTION": "conversation_memory_function",
}

# Handler directory -> Lambda ID mapping
HANDLER_DIR_TO_LAMBDA = {
    "EUUploadDeepDocument": "l01",
    "EUProcessDeepDocument": "l02",
    "EUGraphBuilder": "l03",
    "EUGenerateDeepInsights": "l04",  # aka EUGenerateInsights
    "EUChatAthenaBot": "l05",
    "EUChatJobWorker": "l06",
    "EUKGQueryService": "l07",
    "EUGovernanceEvaluator": "l08",
    "EUGovernanceLibrary": "l09",
    "EUComplianceEngine": "l10",
    "EUConsentManager": "l11",
    "EUResponseKGExtractor": "l12",
    "EUTraceExplainer": "l13",
    "EUGetDeepInsights": "l14",
    "EUGetDeepDocuments": "l15",
    "EUWebSearch": "l16",
    "EUConversationMemory": "l17",
    "EUDeepResearch": "l18",
    "EUAuditTrailStore": "l19",
}


def scan_handler_env_vars() -> dict[str, set[str]]:
    """Scan all handler.py files and return {lambda_id: {env_node_id, ...}}."""
    results: dict[str, set[str]] = {}
    for handler_dir, lambda_id in HANDLER_DIR_TO_LAMBDA.items():
        handler_file = BACKEND / handler_dir / "handler.py"
        if not handler_file.exists():
            continue
        text = handler_file.read_text(encoding="utf-8", errors="ignore")
        found_envs: set[str] = set()
        for pattern, env_id in ENV_VAR_PATTERNS.items():
            if re.search(pattern, text):
                found_envs.add(env_id)
        if found_envs:
            results[lambda_id] = found_envs
    return results


def merge_env_requirements(
    kg_reqs: dict[str, dict[str, bool]],
    scanned: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Merge KG-documented requirements with scanned handler results."""
    merged: dict[str, set[str]] = {}
    # Start with KG documented
    for lambda_id, envs in kg_reqs.items():
        merged[lambda_id] = set(envs.keys())
    # Add scanned discoveries
    for lambda_id, envs in scanned.items():
        if lambda_id not in merged:
            merged[lambda_id] = set()
        merged[lambda_id].update(envs)
    return merged


def build_env_nodes(all_env_ids: set[str]) -> list[dict]:
    """Create ENV_VAR nodes for all discovered environment variables."""
    descriptions = {
        "neo4j_password": "Neo4j graph database password (SEC-4: must be set via Lambda env config)",
        "neo4j_uri": "Neo4j Bolt connection URI (bolt://18.185.88.251:7687)",
        "s3_bucket": "S3 bucket for document storage (eu-deep-documents-680341090470)",
        "bedrock_model": "Primary Bedrock LLM model ID (eu.anthropic.claude-opus-4-6-v1)",
        "graph_extraction_model": "KG entity extraction model — Haiku primary (ADR-095)",
        "graph_fallback_model": "KG extraction fallback — Sonnet (ADR-095, never Opus)",
        "chunk_concurrency": "Parallel chunk processing limit — default 10 (ADR-095)",
        "perplexity_api_key": "Perplexity API key for web search (L16)",
        "cognito_user_pool_id": "EU Cognito User Pool ID (eu-central-1_Z0rehiDtA)",
        "sqs_queue_url": "SQS queue URL for chat job dispatch",
        "dynamodb_table": "DynamoDB table name for chat jobs (eu_chat_jobs)",
        "conversation_memory_function": "Lambda function name for conversation memory service",
    }
    nodes = []
    for env_id in sorted(all_env_ids):
        nodes.append({
            "id": f"env::{env_id}",
            "type": "ENV_VAR",
            "label": env_id.upper().replace("_", " "),
            "metadata": {
                "var_name": env_id.upper(),
                "source": "shared/eu_config.py + handler.py scans",
            },
            "source_file": "cognigraph/poc/add_env_edges.py",
            "confidence": 0.95,
            "description": descriptions.get(env_id, f"Environment variable: {env_id.upper()}"),
        })
    return nodes


def build_required_by_edges(
    merged: dict[str, set[str]],
) -> list[dict]:
    """Create env -> svc REQUIRED_BY edges."""
    edges = []
    for lambda_id, envs in sorted(merged.items()):
        for env_id in sorted(envs):
            edges.append({
                "source": f"env::{env_id}",
                "target": f"svc::{lambda_id}",
                "relationship": "REQUIRED_BY",
                "weight": 0.9,
            })
    return edges


def build_invokes_edges() -> list[dict]:
    """Create svc -> svc INVOKES edges from the invocation chain."""
    edges = []
    for chain in INVOCATION_CHAIN:
        edges.append({
            "source": chain["source"],
            "target": chain["target"],
            "relationship": "INVOKES",
            "weight": 0.95,
            "metadata": {
                "trigger": chain["trigger"],
                "call_type": chain["call_type"],
            },
        })
    return edges


def remove_old_env_and_call_edges(links: list[dict]) -> list[dict]:
    """Remove old svc->env REQUIRES and svc->svc CALLS edges (being replaced)."""
    cleaned = []
    removed_count = 0
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        link_type = link.get("type", "")
        # Remove old REQUIRES edges (svc -> env)
        if src.startswith("svc::") and tgt.startswith("env::") and link_type == "REQUIRES":
            removed_count += 1
            continue
        # Remove old CALLS edges (svc -> svc) -- will be replaced by INVOKES
        if src.startswith("svc::") and tgt.startswith("svc::") and link_type == "CALLS":
            removed_count += 1
            continue
        cleaned.append(link)
    return cleaned, removed_count


def main():
    # Load cognigraph.json
    with open(COGNIGRAPH, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    links = graph.get("links", [])

    edges_before = len(links)
    print(f"=== CogniGraph Env-Var Edge Enrichment ===")
    print(f"Nodes before:  {len(nodes)}")
    print(f"Edges before:  {edges_before}")

    # ── Step 1: Scan handler files ──
    scanned = scan_handler_env_vars()
    print(f"\nHandler scan found env-var usage in {len(scanned)} Lambdas:")
    for lid, envs in sorted(scanned.items()):
        print(f"  {lid}: {sorted(envs)}")

    # ── Step 2: Merge with KG-documented requirements ──
    merged = merge_env_requirements(KG_ENVVAR_REQUIREMENTS, scanned)
    all_env_ids: set[str] = set()
    for envs in merged.values():
        all_env_ids.update(envs)
    print(f"\nMerged env vars across {len(merged)} Lambdas: {sorted(all_env_ids)}")

    # ── Step 3: Remove old edges ──
    links, removed_count = remove_old_env_and_call_edges(links)
    print(f"\nRemoved {removed_count} old REQUIRES/CALLS edges")

    # ── Step 4: Create env-var nodes ──
    new_env_nodes = build_env_nodes(all_env_ids)
    # Check for existing env nodes to avoid duplicates
    existing_ids = {n["id"] for n in nodes}
    added_nodes = [n for n in new_env_nodes if n["id"] not in existing_ids]
    nodes.extend(added_nodes)
    print(f"Added {len(added_nodes)} new ENV_VAR nodes")

    # ── Step 5: Create REQUIRED_BY edges ──
    required_by_edges = build_required_by_edges(merged)
    links.extend(required_by_edges)
    print(f"Added {len(required_by_edges)} REQUIRED_BY edges (env -> svc)")

    # ── Step 6: Create INVOKES edges ──
    invokes_edges = build_invokes_edges()
    links.extend(invokes_edges)
    print(f"Added {len(invokes_edges)} INVOKES edges (svc -> svc)")

    # ── Step 7: Save ──
    graph["nodes"] = nodes
    graph["links"] = links

    edges_after = len(links)
    total_new = len(required_by_edges) + len(invokes_edges)

    with open(COGNIGRAPH, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    print(f"\n=== Summary ===")
    print(f"Edges before:     {edges_before}")
    print(f"Old edges removed: {removed_count}")
    print(f"New REQUIRED_BY:   {len(required_by_edges)}")
    print(f"New INVOKES:       {len(invokes_edges)}")
    print(f"Total new edges:   {total_new}")
    print(f"Edges after:       {edges_after}")
    print(f"Net change:        +{edges_after - edges_before}")
    print(f"New ENV_VAR nodes: {len(added_nodes)}")
    print(f"\nSaved to {COGNIGRAPH}")


if __name__ == "__main__":
    main()
