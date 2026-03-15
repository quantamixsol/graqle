"""graq learn — Teach the knowledge graph new concepts.

Adds business-level nodes, relationships, and context that code scanning
can't discover. The graph becomes self-discovering and self-evolving:
users seed high-level concepts, Graqle finds connections autonomously.

Uses a 3-tier intelligence stack:
  1. Semantic similarity (Bedrock Titan V2 / sentence-transformers / keyword fallback)
  2. Graph topology (link prediction, community detection via Neo4j GDS or NetworkX)
  3. Entity extraction (NLP-based entity linking for knowledge ingestion)

Examples:
    graq learn node "auth-service" --type SERVICE --desc "Handles JWT auth"
    graq learn node "revenue-goal" --type BUSINESS_OUTCOME --desc "Hit $1M ARR by Q3"
    graq learn edge "auth-service" "user-db" --relation DEPENDS_ON
    graq learn file notes.md --auto-connect
    graq learn discover --from "auth-service" --semantic --gds
    graq learn knowledge "TAMR+ means intelligent retrieval" --domain copy
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.learn
# risk: MEDIUM (impact radius: 2 modules)
# consumers: main, test_learn_entity_knowledge
# dependencies: __future__, json, re, pathlib, typer +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from graqle.cli.console import ARROW, CHECK

learn_app = typer.Typer(
    name="learn",
    help="Teach the knowledge graph new concepts, relationships, and business context.",
    no_args_is_help=True,
)

console = Console()


def _describe_connections(graph, node_id: str) -> list[str]:
    """Return a list of 'target_id (RELATION)' strings for a node's edges."""
    results: list[str] = []
    if not hasattr(graph, "get_neighbors"):
        return results
    neighbors = graph.get_neighbors(node_id)
    for nid in neighbors:
        edges = graph.get_edges_between(node_id, nid) if hasattr(graph, "get_edges_between") else []
        rel = edges[0].relationship if edges else "RELATES_TO"
        results.append(f"{nid} ({rel})")
    return results


def _load_graph(graph_path: str = "graqle.json"):
    """Load graph from Neo4j (if configured) or JSON file."""
    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

    config = GraqleConfig.default()
    config_file = Path("graqle.yaml")
    if config_file.exists():
        config = GraqleConfig.from_yaml(str(config_file))

    # Try Neo4j if configured
    connector = getattr(getattr(config, "graph", None), "connector", "networkx")
    if connector == "neo4j":
        try:
            graph_cfg = config.graph
            g = Graqle.from_neo4j(
                uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
                username=getattr(graph_cfg, "username", None) or "neo4j",
                password=getattr(graph_cfg, "password", None) or "",
                database=getattr(graph_cfg, "database", None) or "neo4j",
                config=config,
            )
            return g, f"neo4j://{getattr(graph_cfg, 'uri', 'localhost')}"
        except Exception as exc:
            console.print(f"[yellow]Neo4j load failed ({exc}), falling back to JSON[/yellow]")

    # Fallback: JSON file
    gpath = Path(graph_path)
    if not gpath.exists():
        console.print(f"[red]Graph file not found: {graph_path}[/red]")
        raise typer.Exit(1)

    return Graqle.from_json(str(gpath), config=config), str(gpath)


def _save_graph(graph, gpath: str) -> None:
    """Persist graph to Neo4j (if configured) or JSON file."""
    if gpath.startswith("neo4j://"):
        from graqle.config.settings import GraqleConfig
        config_file = Path("graqle.yaml")
        config = GraqleConfig.from_yaml(str(config_file)) if config_file.exists() else GraqleConfig.default()
        graph_cfg = config.graph
        graph.to_neo4j(
            uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
            username=getattr(graph_cfg, "username", None) or "neo4j",
            password=getattr(graph_cfg, "password", None) or "",
            database=getattr(graph_cfg, "database", None) or "neo4j",
        )
    else:
        graph.to_json(gpath)


class _graph_lock:
    """Context manager for atomic graph read-modify-write (DF-006).

    Holds a file lock across the entire load → modify → save sequence
    to prevent concurrent processes from overwriting each other's changes.

    Usage::

        with _graph_lock(graph_path) as (graph, gpath):
            graph.add_node_simple(...)
            # Lock is held until save completes
        # Lock released, graph saved
    """

    def __init__(self, graph_path: str = "graqle.json"):
        self._graph_path = graph_path
        self._lock_path = graph_path + ".lock"
        self._fd = None

    def __enter__(self):
        from graqle.config.settings import GraqleConfig
        from graqle.core.graph import Graqle, _acquire_lock

        # Acquire lock BEFORE reading
        self._fd = _acquire_lock(self._lock_path)

        config = GraqleConfig.default()
        config_file = Path("graqle.yaml")
        if config_file.exists():
            config = GraqleConfig.from_yaml(str(config_file))

        gpath = Path(self._graph_path)
        if not gpath.exists():
            console.print(f"[red]Graph file not found: {self._graph_path}[/red]")
            raise typer.Exit(1)

        graph = Graqle.from_json(str(gpath), config=config)
        self._graph = graph
        self._gpath = str(gpath)
        return graph, self._gpath

    def __exit__(self, exc_type, exc_val, exc_tb):
        import json as _json

        from graqle.core.graph import _release_lock, _validate_graph_data

        try:
            if exc_type is None:
                # Save under the same lock (no race window)
                G = self._graph.to_networkx()
                import networkx as _nx
                data = _nx.node_link_data(G, edges="links")
                _validate_graph_data(data)
                content = _json.dumps(data, indent=2, default=str)
                with open(self._gpath, "w", encoding="utf-8") as f:
                    f.write(content)
        finally:
            _release_lock(self._fd, self._lock_path)
        return False


@learn_app.command("node")
def learn_node(
    node_id: str = typer.Argument(..., help="Unique node ID"),
    node_type: str = typer.Option("CONCEPT", "--type", "-t", help="Entity type (e.g. SERVICE, PRODUCT, BUSINESS_OUTCOME, CLIENT)"),
    description: str = typer.Option("", "--desc", "-d", help="Node description"),
    label: str = typer.Option(None, "--label", "-l", help="Display label (defaults to node_id)"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    auto_connect: bool = typer.Option(True, "--auto-connect/--no-auto-connect", help="Auto-discover edges"),
    semantic: bool = typer.Option(True, "--semantic/--no-semantic", help="Use semantic similarity (Bedrock/transformers/keyword fallback)"),
    threshold: float = typer.Option(0.7, "--threshold", help="Semantic similarity threshold (0.0-1.0)"),
) -> None:
    """Add a new node to the knowledge graph.

    Business-level nodes like PRODUCT, BUSINESS_OUTCOME, CLIENT, TEAM
    give Graqle cross-cutting reasoning that pure code scanning misses.

    Uses semantic auto-connect by default (Bedrock Titan V2 -> sentence-transformers -> keyword).
    """
    graph, gpath = _load_graph(graph_path)

    if node_id in graph.nodes:
        console.print(f"[yellow]Node '{node_id}' already exists — updating.[/yellow]")

    graph.add_node_simple(
        node_id,
        label=label or node_id,
        entity_type=node_type.upper(),
        description=description,
        properties={"source": "graq_learn", "manual": True},
    )

    auto_edges = 0
    if auto_connect and hasattr(graph, "semantic_auto_connect"):
        method = "auto" if semantic else "keyword"
        auto_edges = graph.semantic_auto_connect(
            [node_id], threshold=threshold, method=method,
        )

    _save_graph(graph, gpath)

    console.print(f"[green]{CHECK} Added node:[/green] {node_id} ({node_type})")
    if description:
        console.print(f"  Description: {description}")
    if auto_edges:
        connections = _describe_connections(graph, node_id)
        console.print(f"  [cyan]Auto-connected to: {', '.join(connections)}[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("edge")
def learn_edge(
    source: str = typer.Argument(..., help="Source node ID"),
    target: str = typer.Argument(..., help="Target node ID"),
    relation: str = typer.Option("RELATES_TO", "--relation", "-r", help="Edge relation type"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a relationship between two nodes."""
    graph, gpath = _load_graph(graph_path)

    for nid in [source, target]:
        if nid not in graph.nodes:
            console.print(f"[red]Node '{nid}' not found in graph[/red]")
            raise typer.Exit(1)

    graph.add_edge_simple(source, target, relation=relation.upper())
    _save_graph(graph, gpath)

    console.print(f"[green]{CHECK} Added edge:[/green] {source} --[{relation}]{ARROW} {target}")


@learn_app.command("file")
def learn_file(
    file_path: str = typer.Argument(..., help="Path to a markdown/text file with knowledge"),
    node_type: str = typer.Option("DOCUMENT", "--type", "-t", help="Entity type for file node"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    auto_connect: bool = typer.Option(True, "--auto-connect/--no-auto-connect", help="Auto-discover edges"),
) -> None:
    """Learn from a file — extract concepts and add to graph.

    Reads markdown, text, or JSON files and creates nodes from their content.
    """
    fpath = Path(file_path)
    if not fpath.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    graph, gpath = _load_graph(graph_path)
    content = fpath.read_text(encoding="utf-8", errors="ignore")

    # Add the file as a node
    node_id = fpath.stem.replace(" ", "_").lower()
    graph.add_node_simple(
        node_id,
        label=fpath.name,
        entity_type=node_type.upper(),
        description=content[:500],  # First 500 chars as description
        properties={
            "source": "graq_learn",
            "file_path": str(fpath),
            "content_length": len(content),
        },
    )

    auto_edges = 0
    if auto_connect and hasattr(graph, "semantic_auto_connect"):
        auto_edges = graph.semantic_auto_connect([node_id])

    _save_graph(graph, gpath)

    console.print(f"[green]{CHECK} Learned from file:[/green] {fpath.name}")
    console.print(f"  Node: {node_id} ({node_type})")
    if auto_edges:
        console.print(f"  [cyan]Semantically connected {auto_edges} edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("entity")
def learn_entity(
    entity_id: str = typer.Argument(..., help="Unique entity ID (e.g. 'CrawlQ', 'Philips')"),
    entity_type: str = typer.Option("PRODUCT", "--type", "-t", help="Entity type: PRODUCT, CLIENT, BUSINESS_OUTCOME, TEAM, SYNERGY, MARKET"),
    description: str = typer.Option("", "--desc", "-d", help="Business description"),
    connects: str = typer.Option(None, "--connects", help="Comma-separated node IDs to connect to"),
    relation: str = typer.Option("RELATES_TO", "--relation", "-r", help="Edge relation for --connects"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Add a business-level entity to the knowledge graph.

    Code scanning discovers modules and files. This command adds the
    business context that code scanning can't: products, clients,
    outcomes, teams, synergies, and market segments.

    \b
    Examples:
        graq learn entity "CrawlQ" --type PRODUCT --desc "Content ERP for enterprise"
        graq learn entity "Philips" --type CLIENT --desc "75% content time reduction"
        graq learn entity "content_compliance" --type SYNERGY --connects "CrawlQ,TracGov"
    """
    graph, gpath = _load_graph(graph_path)

    # Business types get special properties
    business_types = {"PRODUCT", "CLIENT", "BUSINESS_OUTCOME", "TEAM", "SYNERGY", "MARKET", "COMPETITOR", "METRIC"}
    etype = entity_type.upper()
    if etype not in business_types:
        console.print(f"[yellow]Note: '{etype}' is not a standard business type. Standard types: {', '.join(sorted(business_types))}[/yellow]")

    if entity_id in graph.nodes:
        console.print(f"[yellow]Entity '{entity_id}' already exists — updating.[/yellow]")

    graph.add_node_simple(
        entity_id,
        label=entity_id.replace("_", " ").title(),
        entity_type=etype,
        description=description,
        properties={
            "source": "graq_learn_entity",
            "manual": True,
            "business_entity": True,
        },
    )

    edges_added = 0
    if connects:
        # Support multiple delimiters: comma, semicolon, " and ", " + "
        import re
        raw_targets = re.split(r'[,;]\s*|\s+and\s+|\s*\+\s*', connects)
        targets = [t.strip() for t in raw_targets if t.strip()]
        for target in targets:
            if target not in graph.nodes:
                # Fuzzy match
                matches = [nid for nid in graph.nodes if target.lower() in nid.lower()]
                if matches:
                    target = matches[0]
                    console.print(f"  [dim]Fuzzy matched {ARROW} {target}[/dim]")
                else:
                    console.print(f"  [yellow]Skipping '{target}' — not found in graph[/yellow]")
                    continue
            graph.add_edge_simple(entity_id, target, relation=relation.upper())
            edges_added += 1

    auto_edges = 0
    if hasattr(graph, "semantic_auto_connect"):
        auto_edges = graph.semantic_auto_connect([entity_id])

    _save_graph(graph, gpath)

    console.print(f"[green]{CHECK} Business entity added:[/green] {entity_id} ({etype})")
    if description:
        console.print(f"  Description: {description}")
    if edges_added or auto_edges:
        connections = _describe_connections(graph, entity_id)
        if connections:
            console.print(f"  [cyan]Auto-connected to: {', '.join(connections)}[/cyan]")
        else:
            if edges_added:
                console.print(f"  [cyan]Connected to {edges_added} nodes via {relation}[/cyan]")
            if auto_edges:
                console.print(f"  [cyan]Semantically discovered {auto_edges} additional edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("knowledge")
def learn_knowledge(
    fact: str = typer.Argument(..., help="The knowledge to teach (e.g. 'Target audience is C-suite')"),
    domain: str = typer.Option("general", "--domain", "-d", help="Knowledge domain: brand, copy, product, market, technical"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags for retrieval"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    semantic: bool = typer.Option(True, "--semantic/--no-semantic", help="Use semantic similarity for auto-connect"),
    threshold: float = typer.Option(0.65, "--threshold", help="Semantic similarity threshold"),
    extract_entities: bool = typer.Option(True, "--extract/--no-extract", help="Extract entities from fact text"),
) -> None:
    """Teach domain knowledge that can't be extracted from code.

    Unlike 'graq learn node' which adds generic nodes, this creates
    KNOWLEDGE nodes with domain tagging for smarter retrieval during
    reasoning and preflight checks.

    Entity extraction automatically finds proper nouns, quoted terms,
    and capitalized phrases in the fact text, then links them to
    existing graph nodes via semantic similarity.

    \b
    Examples:
        graq learn knowledge "Target audience is C-suite in regulated industries" --domain brand
        graq learn knowledge "TAMR+ means intelligent document retrieval" --domain copy
        graq learn knowledge "Free tier: 500 nodes, 3 queries/month" --domain product
    """
    from datetime import datetime, timezone

    # Use _graph_lock for atomic read-modify-write (DF-006)
    with _graph_lock(graph_path) as (graph, gpath):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        node_id = f"knowledge_{domain}_{ts}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        # Extract entities from the fact text
        extracted_entities: list[str] = []
        if extract_entities:
            extracted_entities = _extract_entities(fact)

        graph.add_node_simple(
            node_id,
            label=fact[:80],
            entity_type="KNOWLEDGE",
            description=fact,
            properties={
                "source": "graq_learn_knowledge",
                "domain": domain,
                "tags": tag_list,
                "created": ts,
                "manual": True,
                "extracted_entities": extracted_entities,
            },
        )

        # Semantic auto-connect to existing nodes
        auto_edges = 0
        if hasattr(graph, "semantic_auto_connect"):
            method = "auto" if semantic else "keyword"
            auto_edges = graph.semantic_auto_connect(
                [node_id], threshold=threshold, method=method,
            )

        # Entity-based connections: link extracted entities to matching nodes
        entity_edges = 0
        if extracted_entities:
            entity_edges = _connect_extracted_entities(
                graph, node_id, extracted_entities, domain,
            )

    # Lock released, graph saved — now print results
    console.print(f"[green]{CHECK} Knowledge taught:[/green] {fact[:60]}...")
    console.print(f"  Domain: {domain} | Node: {node_id}")
    if tag_list:
        console.print(f"  Tags: {', '.join(tag_list)}")
    if extracted_entities:
        console.print(f"  [magenta]Entities extracted: {', '.join(extracted_entities[:10])}[/magenta]")
    if auto_edges or entity_edges:
        connections = _describe_connections(graph, node_id)
        if connections:
            console.print(f"  [cyan]Auto-connected to: {', '.join(connections)}[/cyan]")
        else:
            if auto_edges:
                console.print(f"  [cyan]Semantically connected {auto_edges} edges[/cyan]")
            if entity_edges:
                console.print(f"  [cyan]Entity-linked {entity_edges} edges[/cyan]")
    console.print(f"  Graph: {len(graph)} nodes total")


def _extract_entities(text: str) -> list[str]:
    """Extract entities from text using lightweight NLP heuristics.

    Finds:
    - Quoted terms ("TAMR+", 'CrawlQ')
    - Capitalized multi-word phrases (C-suite, Neo4j, TraceGov)
    - ALL-CAPS acronyms (JWT, API, CORS)
    - CamelCase terms (DeepSeek, GraphLearner)

    Returns deduplicated list of entity strings.
    """
    entities: set[str] = set()

    # 1. Quoted terms (single or double quotes)
    quoted = re.findall(r'''["']([^"']{2,50})["']''', text)
    entities.update(quoted)

    # 2. ALL-CAPS acronyms (2+ chars, may contain digits)
    acronyms = re.findall(r'\b([A-Z][A-Z0-9]{1,10})\b', text)
    # Filter out common words that happen to be caps
    caps_stopwords = {"THE", "AND", "FOR", "BUT", "NOT", "ALL", "ARE", "WAS",
                      "HAS", "HAD", "CAN", "DID", "GET", "SET", "PUT", "USE"}
    entities.update(a for a in acronyms if a not in caps_stopwords)

    # 3. Capitalized phrases (1-4 words starting with uppercase)
    cap_phrases = re.findall(
        r'\b([A-Z][a-zA-Z0-9+#-]*(?:\s+[A-Z][a-zA-Z0-9+#-]*){0,3})\b',
        text,
    )
    # Filter single-char and sentence starters
    for phrase in cap_phrases:
        words = phrase.split()
        # Skip if it's just the start of a sentence (single common word)
        if len(words) == 1 and words[0].lower() in {
            "the", "a", "an", "is", "in", "to", "of", "and", "for",
            "it", "on", "with", "as", "at", "by", "this", "that",
            "we", "our", "they", "their", "its", "are", "was", "has",
            "target", "free", "key", "main", "new", "all", "any",
        }:
            continue
        if len(phrase) >= 2:
            entities.add(phrase)

    # 4. CamelCase terms
    camel = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', text)
    entities.update(camel)

    # 5. Terms with special chars that indicate names (TAMR+, Neo4j, etc.)
    special = re.findall(r'\b([A-Z][a-zA-Z0-9]*[+#@])\b', text)
    entities.update(special)

    return sorted(entities)


def _connect_extracted_entities(
    graph, knowledge_node_id: str, entities: list[str], domain: str,
) -> int:
    """Connect a knowledge node to existing graph nodes that match extracted entities.

    Uses fuzzy matching: entity text is compared against node IDs, labels,
    and entity_type. Domain-aware: brand knowledge preferentially connects
    to PRODUCT nodes, etc.
    """
    # Domain -> preferred node types mapping
    domain_types = {
        "brand": {"PRODUCT", "CLIENT", "MARKET", "BUSINESS_OUTCOME"},
        "copy": {"PRODUCT", "KNOWLEDGE", "CONCEPT"},
        "product": {"PRODUCT", "SERVICE", "METRIC", "BUSINESS_OUTCOME"},
        "market": {"MARKET", "COMPETITOR", "CLIENT", "METRIC"},
        "technical": {"SERVICE", "MODULE", "LAMBDA", "CONFIG"},
    }
    preferred = domain_types.get(domain, set())

    edges_added = 0
    for entity_text in entities:
        entity_lower = entity_text.lower()
        best_match: str | None = None
        best_score = 0.0

        for nid, node in graph.nodes.items():
            if nid == knowledge_node_id:
                continue
            # Already connected?
            if graph.get_edges_between(knowledge_node_id, nid):
                continue

            score = 0.0
            # Exact ID match
            if entity_lower == nid.lower():
                score = 1.0
            # ID contains entity
            elif entity_lower in nid.lower():
                score = 0.8
            # Label match
            elif node.label and entity_lower == node.label.lower():
                score = 0.95
            elif node.label and entity_lower in node.label.lower():
                score = 0.7
            # Description contains entity
            elif node.description and entity_lower in node.description.lower():
                score = 0.5

            # Boost for domain-preferred types
            if score > 0 and preferred and node.entity_type in preferred:
                score = min(score * 1.2, 1.0)

            if score > best_score:
                best_score = score
                best_match = nid

        if best_match and best_score >= 0.5:
            # Determine relation based on domain
            relation = "INFORMS" if domain in ("brand", "copy", "market") else "RELATED_TO"
            graph.add_edge_simple(knowledge_node_id, best_match, relation=relation)
            edges_added += 1
            if edges_added >= 10:  # Cap entity connections
                break

    return edges_added


@learn_app.command("discover")
def learn_discover(
    from_node: str = typer.Option(None, "--from", "-f", help="Start discovery from this node"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    depth: int = typer.Option(2, "--depth", help="Discovery depth (hops)"),
    semantic: bool = typer.Option(True, "--semantic/--no-semantic", help="Use semantic similarity for suggestions"),
    gds: bool = typer.Option(False, "--gds/--no-gds", help="Run GDS topology analysis (link prediction, communities)"),
    threshold: float = typer.Option(0.6, "--threshold", help="Semantic similarity threshold"),
    top_k: int = typer.Option(15, "--top-k", help="Number of suggestions to show"),
) -> None:
    """Auto-discover new connections and concepts in the graph.

    This is the self-evolving feature: Graqle analyzes existing nodes
    and suggests new edges that users haven't thought of.

    \b
    Intelligence tiers:
      --semantic (default):  Bedrock Titan V2 / sentence-transformers / keyword
      --gds:                 Link prediction (Adamic Adar, Common Neighbors, PA)
                             + community detection (Louvain) via Neo4j GDS or NetworkX
    """
    graph, gpath = _load_graph(graph_path)

    # Find nodes with few connections (potential discovery targets)
    isolated = []
    for nid, node in graph.nodes.items():
        if node.degree <= 1:
            isolated.append((nid, node.entity_type, node.label))

    focus_nodes = [from_node] if from_node else None

    if from_node:
        if from_node not in graph.nodes:
            console.print(f"[red]Node '{from_node}' not found[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]Discovery from: {from_node}[/bold]")
        neighbors = graph.get_neighbors(from_node)
        console.print(f"  Current connections: {len(neighbors)}")

    # ---- Semantic Similarity Suggestions ----
    if semantic:
        console.print(Panel("[bold]Semantic Similarity Analysis[/bold]", style="blue"))
        _show_semantic_suggestions(graph, from_node, threshold=threshold, top_k=top_k)

    # ---- GDS Topology Analysis ----
    if gds:
        console.print(Panel("[bold]Graph Topology Intelligence (GDS)[/bold]", style="green"))
        _show_gds_analysis(graph, focus_nodes=focus_nodes, top_k=top_k)

    # ---- Fallback: type-based + keyword suggestions (when no semantic/gds) ----
    if not semantic and not gds and from_node:
        node = graph.nodes[from_node]
        neighbors = graph.get_neighbors(from_node)
        suggestions = []
        for nid, n in graph.nodes.items():
            if nid == from_node or nid in neighbors:
                continue
            if n.entity_type == node.entity_type:
                suggestions.append((nid, "SAME_TYPE", n.label, 0.0))
            if node.description and n.description:
                node_words = set(node.description.lower().split())
                n_words = set(n.description.lower().split())
                overlap = node_words & n_words - {"the", "a", "an", "is", "in", "to", "of", "and", "for"}
                if len(overlap) >= 3:
                    suggestions.append((nid, "KEYWORD_OVERLAP", f"{len(overlap)} shared terms", 0.0))

        if suggestions[:10]:
            table = Table(title="Suggested Connections (keyword)")
            table.add_column("Node ID", style="cyan")
            table.add_column("Reason", style="yellow")
            table.add_column("Detail")
            for nid, reason, detail, _ in suggestions[:10]:
                table.add_row(nid, reason, detail)
            console.print(table)
        else:
            console.print("  [dim]No new connections suggested[/dim]")

    if isolated:
        console.print(f"\n[bold yellow]Isolated nodes ({len(isolated)} with 1 or fewer connections):[/bold yellow]")
        for nid, ntype, label in isolated[:15]:
            console.print(f"  {nid} ({ntype})")
        if len(isolated) > 15:
            console.print(f"  ... and {len(isolated) - 15} more")

    console.print(f"\n[dim]Graph: {len(graph)} nodes, use 'graq learn edge' to add connections[/dim]")


def _show_semantic_suggestions(graph, from_node: str | None, *, threshold: float, top_k: int) -> None:
    """Display semantic similarity suggestions for the discover command."""
    import numpy as np

    engine = graph._get_embedding_engine("auto")

    if engine is None:
        console.print("  [yellow]No embedding engine available. Using keyword fallback.[/yellow]")
        if from_node:
            _show_keyword_suggestions(graph, from_node, top_k=top_k)
        return

    engine_name = type(engine).__name__
    console.print(f"  Engine: [cyan]{engine_name}[/cyan] | Threshold: {threshold}")

    # Determine which nodes to analyze
    if from_node:
        source_ids = [from_node]
    else:
        # Analyze all nodes with few connections
        source_ids = [
            nid for nid, node in graph.nodes.items()
            if node.degree <= 2 and node.description
        ][:20]  # Cap for performance

    if not source_ids:
        console.print("  [dim]No candidates for semantic analysis[/dim]")
        return

    # Get all node embeddings
    all_ids = list(graph.nodes.keys())
    all_ids_with_desc = [nid for nid in all_ids if graph.nodes[nid].description]
    all_embeddings = graph._get_or_compute_embeddings(all_ids_with_desc, engine)

    # Build embedding index
    emb_index: dict[str, np.ndarray] = {}
    for idx, nid in enumerate(all_ids_with_desc):
        if all_embeddings[idx] is not None:
            emb_index[nid] = all_embeddings[idx]

    suggestions: list[tuple[str, str, float]] = []  # (source, target, score)

    for src_id in source_ids:
        if src_id not in emb_index:
            continue
        src_emb = emb_index[src_id]
        neighbors = set(graph.get_neighbors(src_id))

        for tgt_id, tgt_emb in emb_index.items():
            if tgt_id == src_id or tgt_id in neighbors:
                continue
            sim = float(np.dot(src_emb, tgt_emb) / (
                np.linalg.norm(src_emb) * np.linalg.norm(tgt_emb) + 1e-9
            ))
            if sim >= threshold:
                suggestions.append((src_id, tgt_id, sim))

    suggestions.sort(key=lambda x: x[2], reverse=True)
    suggestions = suggestions[:top_k]

    if suggestions:
        table = Table(title=f"Semantic Suggestions (top {len(suggestions)})")
        table.add_column("Source", style="cyan")
        table.add_column("Target", style="cyan")
        table.add_column("Similarity", style="green", justify="right")
        table.add_column("Target Type", style="dim")
        for src, tgt, score in suggestions:
            tgt_type = graph.nodes[tgt].entity_type if tgt in graph.nodes else "?"
            table.add_row(src, tgt, f"{score:.4f}", tgt_type)
        console.print(table)
    else:
        console.print("  [dim]No semantic matches above threshold[/dim]")


def _show_keyword_suggestions(graph, from_node: str, *, top_k: int) -> None:
    """Fallback keyword-based suggestions when no embeddings available."""
    stopwords = {"the", "a", "an", "is", "in", "to", "of", "and", "for",
                  "it", "on", "with", "as", "at", "by", "this", "that"}
    node = graph.nodes[from_node]
    neighbors = set(graph.get_neighbors(from_node))
    suggestions = []

    if not node.description:
        return

    node_words = set(node.description.lower().split()) - stopwords
    for nid, n in graph.nodes.items():
        if nid == from_node or nid in neighbors or not n.description:
            continue
        n_words = set(n.description.lower().split()) - stopwords
        overlap = node_words & n_words
        if len(overlap) >= 3:
            suggestions.append((nid, len(overlap), n.entity_type))

    suggestions.sort(key=lambda x: x[1], reverse=True)
    if suggestions[:top_k]:
        table = Table(title="Keyword Overlap Suggestions")
        table.add_column("Node ID", style="cyan")
        table.add_column("Shared Terms", justify="right")
        table.add_column("Type", style="dim")
        for nid, count, ntype in suggestions[:top_k]:
            table.add_row(nid, str(count), ntype)
        console.print(table)


def _show_gds_analysis(graph, *, focus_nodes: list[str] | None, top_k: int) -> None:
    """Display GDS topology analysis (link prediction + communities)."""
    from graqle.learning.gds_intelligence import GDSIntelligence

    neo4j_conn = getattr(graph, "_neo4j_connector", None)
    gds = GDSIntelligence(graph, neo4j_connector=neo4j_conn)
    console.print(f"  Engine: [cyan]{gds.method}[/cyan]")

    report = gds.discover_missing_links(
        focus_nodes=focus_nodes, top_k=top_k,
    )

    # Link Predictions
    if report.link_predictions:
        table = Table(title=f"Link Predictions ({len(report.link_predictions)} found)")
        table.add_column("Source", style="cyan")
        table.add_column("Target", style="cyan")
        table.add_column("Score", style="green", justify="right")
        table.add_column("Algorithm", style="yellow")
        table.add_column("Reason", style="dim")
        for pred in report.link_predictions[:top_k]:
            table.add_row(
                pred.source, pred.target,
                f"{pred.score:.4f}", pred.algorithm,
                pred.reason[:60],
            )
        console.print(table)
    else:
        console.print("  [dim]No link predictions found[/dim]")

    # Communities
    if report.communities:
        console.print(f"\n  [bold]Communities detected: {len(report.communities)}[/bold]")
        for comm in report.communities[:10]:
            members_preview = ", ".join(comm.members[:5])
            if len(comm.members) > 5:
                members_preview += f", ... (+{len(comm.members) - 5})"
            console.print(f"    Cluster {comm.id}: {comm.label}")
            console.print(f"      Members: {members_preview}")

    # Node Similarities
    if report.similarities:
        table = Table(title=f"Node Similarities ({len(report.similarities)} pairs)")
        table.add_column("Node A", style="cyan")
        table.add_column("Node B", style="cyan")
        table.add_column("Jaccard", style="green", justify="right")
        table.add_column("Shared Neighbors", style="dim")
        for sim in report.similarities[:top_k]:
            shared = ", ".join(sim.shared_neighbors[:3])
            if len(sim.shared_neighbors) > 3:
                shared += f" +{len(sim.shared_neighbors) - 3}"
            table.add_row(sim.node_a, sim.node_b, f"{sim.score:.4f}", shared)
        console.print(table)

    # Stats
    console.print(f"\n  [dim]Stats: {report.stats}[/dim]")


@learn_app.command("batch")
def learn_batch(
    file_path: str = typer.Argument(..., help="JSON file with nodes and edges to add"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
) -> None:
    """Batch learn from a JSON file.

    File format:
    {
        "nodes": [{"id": "...", "type": "...", "label": "...", "description": "..."}],
        "edges": [{"source": "...", "target": "...", "relation": "..."}]
    }
    """
    fpath = Path(file_path)
    if not fpath.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(fpath.read_text())
    graph, gpath = _load_graph(graph_path)

    nodes_added = 0
    for node_data in data.get("nodes", []):
        nid = node_data.get("id")
        if not nid:
            continue
        graph.add_node_simple(
            nid,
            label=node_data.get("label", nid),
            entity_type=node_data.get("type", "CONCEPT").upper(),
            description=node_data.get("description", ""),
            properties=node_data.get("properties", {}),
        )
        nodes_added += 1

    edges_added = 0
    for edge_data in data.get("edges", []):
        src = edge_data.get("source")
        tgt = edge_data.get("target")
        if src and tgt and src in graph.nodes and tgt in graph.nodes:
            graph.add_edge_simple(src, tgt, relation=edge_data.get("relation", "RELATES_TO").upper())
            edges_added += 1

    _save_graph(graph, gpath)

    console.print(f"[green]{CHECK} Batch learned:[/green] {nodes_added} nodes, {edges_added} edges")
    console.print(f"  Graph: {len(graph)} nodes total")


@learn_app.command("doc")
def learn_doc(
    paths: list[str] = typer.Argument(..., help="Document file(s) or directory(ies) to ingest"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g", help="Graph file path"),
    no_link: bool = typer.Option(False, "--no-link", help="Skip auto-linking to code nodes"),
    no_redact: bool = typer.Option(False, "--no-redact", help="Skip privacy redaction"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without modifying graph"),
) -> None:
    """On-demand document ingestion into the knowledge graph.

    Parses documents (or all supported documents in directories),
    creates Document and Section nodes, auto-links to existing code
    nodes, and saves the graph immediately.

    Accepts one or more file/directory paths.

    Examples:
        graq learn doc architecture.pdf
        graq learn doc file1.md file2.md file3.md
        graq learn doc ./compliance-docs/
        graq learn doc spec.md --no-link --dry-run
    """
    from graqle.cli.commands.scan import _load_graph_data, _print_doc_scan_summary, _save_graph_data
    from graqle.scanner.docs import DocScanOptions, DocumentScanner, ScanResult

    # Resolve and validate all paths
    targets: list[Path] = []
    for p in paths:
        t = Path(p).resolve()
        if not t.exists():
            console.print(f"[red]Path not found:[/red] {t}")
            raise typer.Exit(1)
        targets.append(t)

    gp = Path(graph_path)
    nodes, edges = _load_graph_data(gp)
    manifest_path = gp.parent / ".graqle-doc-manifest.json"

    opts = DocScanOptions(
        link_exact=not no_link,
        link_fuzzy=not no_link,
        redaction_enabled=not no_redact,
        incremental=False,  # On-demand always re-processes
    )

    scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

    from rich.progress import Progress

    # Accumulate results across all paths
    combined = ScanResult()

    with Progress(console=console) as progress:
        task = progress.add_task("[cyan]Ingesting documents...", total=0)

        def progress_cb(fp, idx, total):
            progress.update(task, total=total, completed=idx,
                            description=f"[cyan]{fp.name}")

        for target in targets:
            if target.is_file():
                result = scanner.scan_file(target, base_dir=target.parent)
            else:
                result = scanner.scan_directory(target, progress_callback=progress_cb)

            # Merge into combined result
            combined.files_scanned += result.files_scanned
            combined.files_skipped += result.files_skipped
            combined.files_errored += result.files_errored
            combined.nodes_added += result.nodes_added
            combined.edges_added += result.edges_added
            combined.file_results.extend(result.file_results)
            combined.duration_seconds += result.duration_seconds
            combined.stale_removed += result.stale_removed

        progress.update(task, completed=combined.files_total)

    if dry_run:
        console.print("[yellow]Dry run — no changes saved.[/yellow]")
        _print_doc_scan_summary(combined)
        return

    _save_graph_data(gp, nodes, edges)
    _print_doc_scan_summary(combined)
    console.print(f"[green]{CHECK} Documents ingested into graph.[/green]")
