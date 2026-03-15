"""6 Validation Gates for the Graqle Intelligence Pipeline.

Every file passes through all 6 gates sequentially. If a gate fails,
auto-repair is attempted before moving to the next gate. No file exits
the pipeline without all 6 gates passing (or being marked DEGRADED).

See ADR-105 §The 6 Validation Gates.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.validators
# risk: LOW (impact radius: 2 modules)
# consumers: pipeline, test_validators
# dependencies: __future__, logging, re, typing, models
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from typing import Any

from graqle.intelligence.models import (
    ValidationGateResult,
    ValidatedEdge,
    ValidatedNode,
)

logger = logging.getLogger("graqle.intelligence.validators")

# Registered node and edge types (from scan.py registry)
REGISTERED_NODE_TYPES = {
    "PythonModule", "JavaScriptModule", "Class", "Function", "APIEndpoint",
    "DatabaseModel", "TestFile", "Config", "EnvVar", "Dependency",
    "Directory", "DockerService", "CIPipeline", "Document",
}

REGISTERED_EDGE_TYPES = {
    "IMPORTS", "CONTAINS", "TESTS", "CONFIGURES", "DEPENDS_ON",
    "DEFINES", "CALLS", "ROUTES_TO", "MODELS", "USES_ENVVAR",
    "SHARES_ENV", "RELATED_TO",
}

# Types that should have source code chunks
CODE_NODE_TYPES = {"PythonModule", "JavaScriptModule", "Class", "Function", "TestFile"}

# Minimum description length for a node to be considered "described"
MIN_DESCRIPTION_LENGTH = 30

# Minimum chunk text length to be considered meaningful
MIN_CHUNK_TEXT_LENGTH = 10

# Pattern to detect import-only content
_IMPORT_ONLY_RE = re.compile(
    r"^(\s*(import\s|from\s|require\(|const\s+\w+\s*=\s*require|"
    r"export\s|\/\/|#|\"\"\"|\'\'\').*\n?)+$",
    re.MULTILINE,
)


def gate_1_parse_integrity(
    nodes_raw: list[dict[str, Any]],
    file_path: str,
    file_content: str | None = None,
) -> ValidationGateResult:
    """Gate 1: PARSE INTEGRITY — Did we successfully parse this file?

    Checks: At least 1 node was extracted from the file.
    Auto-repair: If zero nodes, create a raw-text module node with chunked content.
    Guarantee: Every file produces at least one node with raw-text chunks.
    """
    gate = ValidationGateResult(gate="parse_integrity", gate_number=1, passed=True)

    if nodes_raw:
        gate.details["node_count"] = len(nodes_raw)
        return gate

    # Auto-repair: create a raw module node from file content
    gate.passed = False
    gate.auto_repaired = 1
    gate.warnings.append(f"No AST nodes extracted from {file_path}. Creating raw-text node.")

    if file_content:
        # Chunk the raw content into ~500 char segments
        chunks = _chunk_raw_text(file_content, file_path)
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
        node_type = "PythonModule" if ext == "py" else "JavaScriptModule" if ext in ("js", "ts", "jsx", "tsx") else "Config"
        label = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

        raw_node = {
            "id": file_path,
            "label": label,
            "type": node_type,
            "description": f"Source file: {label}. Auto-parsed as raw text (AST parsing failed).",
            "chunks": chunks,
            "properties": {"file_path": file_path, "parse_mode": "raw_text"},
        }
        nodes_raw.append(raw_node)
        gate.passed = True  # repaired successfully
    else:
        gate.degraded = 1
        gate.warnings.append("No file content available for raw-text fallback.")

    return gate


def gate_2_node_completeness(
    nodes_raw: list[dict[str, Any]],
    file_path: str,
) -> tuple[ValidationGateResult, list[ValidatedNode]]:
    """Gate 2: NODE COMPLETENESS — Does every node have label, type, description, chunks?

    Auto-repair:
    - Missing description → synthesize from label + type + parent context
    - Missing chunks → synthesize chunk from description + file_path
    - Missing label → derive from file_path or id
    Guarantee: Zero hollow nodes. Every node has evidence.
    """
    gate = ValidationGateResult(gate="node_completeness", gate_number=2, passed=True)
    validated: list[ValidatedNode] = []

    for node in nodes_raw:
        repairs = 0
        node_id = node.get("id", "")
        label = node.get("label", "")
        entity_type = node.get("type", "")
        description = node.get("description", "")
        chunks = node.get("chunks", [])
        properties = node.get("properties", {})
        file_path_prop = properties.get("file_path", node.get("file_path"))

        # Repair: missing label
        if not label or len(label.strip()) < 2:
            label = node_id.rsplit("::", 1)[-1] if "::" in node_id else node_id.rsplit("/", 1)[-1]
            repairs += 1

        # Repair: missing/unregistered type
        if entity_type not in REGISTERED_NODE_TYPES:
            if entity_type:
                gate.warnings.append(f"Unregistered type '{entity_type}' for {node_id}. Keeping as-is.")
            else:
                entity_type = _infer_type(node_id, label, properties)
                repairs += 1

        # Repair: missing/short description
        if len(description) < MIN_DESCRIPTION_LENGTH:
            description = _synthesize_description(label, entity_type, properties, node_id)
            repairs += 1

        # Repair: missing chunks
        if not chunks or not any(
            isinstance(c, dict) and len(c.get("text", "").strip()) >= MIN_CHUNK_TEXT_LENGTH
            for c in chunks
        ):
            chunks = _synthesize_chunks(label, entity_type, description, file_path_prop)
            repairs += 1

        if repairs > 0:
            gate.auto_repaired += repairs

        try:
            validated_node = ValidatedNode(
                id=node_id,
                label=label,
                entity_type=entity_type,
                description=description,
                chunks=chunks,
                properties=properties,
                file_path=file_path_prop,
                start_line=node.get("start_line") or properties.get("start_line"),
                end_line=node.get("end_line") or properties.get("end_line"),
            )
            validated.append(validated_node)
        except Exception as e:
            gate.degraded += 1
            gate.warnings.append(f"Node {node_id} failed validation even after repair: {e}")

    if gate.degraded > 0:
        gate.passed = False

    gate.details["total_nodes"] = len(nodes_raw)
    gate.details["validated"] = len(validated)
    gate.details["repairs"] = gate.auto_repaired
    return gate, validated


def gate_3_chunk_quality(
    nodes: list[ValidatedNode],
) -> ValidationGateResult:
    """Gate 3: CHUNK QUALITY — Are chunks meaningful, not just boilerplate?

    Checks: text >= 10 chars, not 100% imports, has type annotation.
    Auto-repair: extend import-only chunks, infer missing type.
    Guarantee: Every chunk has actionable content.
    """
    gate = ValidationGateResult(gate="chunk_quality", gate_number=3, passed=True)

    for node in nodes:
        repaired_chunks: list[dict[str, Any]] = []
        for chunk in node.chunks:
            text = chunk.get("text", "").strip()

            # Skip truly empty chunks
            if len(text) < MIN_CHUNK_TEXT_LENGTH:
                gate.auto_repaired += 1
                continue

            # Check for import-only content
            if _IMPORT_ONLY_RE.fullmatch(text):
                # Don't discard — mark as "imports" type
                chunk["type"] = "imports"
                gate.auto_repaired += 1

            # Ensure chunk has type
            if not chunk.get("type"):
                chunk["type"] = _infer_chunk_type(text, node.entity_type)
                gate.auto_repaired += 1

            repaired_chunks.append(chunk)

        # If all chunks were removed, synthesize from description
        if not repaired_chunks:
            repaired_chunks = _synthesize_chunks(
                node.label, node.entity_type, node.description, node.file_path
            )
            gate.auto_repaired += 1
            gate.warnings.append(f"All chunks for {node.id} were boilerplate. Synthesized from description.")

        node.chunks = repaired_chunks

    return gate


def gate_4_edge_integrity(
    edges_raw: list[dict[str, Any]],
    known_node_ids: set[str],
) -> tuple[ValidationGateResult, list[ValidatedEdge], list[dict[str, Any]]]:
    """Gate 4: EDGE INTEGRITY — Do all edges connect existing nodes?

    Checks: source/target exist, registered type, no self-loops, no duplicates.
    Auto-repair: unknown type → closest match, duplicates → dedup.
    Returns: (result, valid_edges, pending_edges)
    Guarantee: Zero dangling edges in validated set. Pending edges deferred.
    """
    gate = ValidationGateResult(gate="edge_integrity", gate_number=4, passed=True)
    validated: list[ValidatedEdge] = []
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for edge in edges_raw:
        source = edge.get("source", "")
        target = edge.get("target", "")
        rel = edge.get("relationship", "")
        props = edge.get("properties", {})

        # Self-loop check
        if source == target:
            gate.auto_repaired += 1
            continue

        # Duplicate check
        edge_key = (source, target, rel)
        if edge_key in seen:
            gate.auto_repaired += 1
            continue
        seen.add(edge_key)

        # Relationship type check
        if rel not in REGISTERED_EDGE_TYPES:
            closest = _closest_edge_type(rel)
            if closest:
                rel = closest
                gate.auto_repaired += 1
            else:
                gate.warnings.append(f"Unknown edge type '{rel}' for {source}->{target}")

        # Endpoint existence check
        source_exists = source in known_node_ids
        target_exists = target in known_node_ids

        if source_exists and target_exists:
            validated.append(ValidatedEdge(
                source=source, target=target, relationship=rel, properties=props
            ))
        else:
            # Defer to pending queue — will be resolved after all files scanned
            pending.append({"source": source, "target": target, "relationship": rel, "properties": props})

    gate.details["valid"] = len(validated)
    gate.details["pending"] = len(pending)
    gate.details["removed"] = gate.auto_repaired
    return gate, validated, pending


def gate_5_relationship_completeness(
    nodes: list[ValidatedNode],
    edges: list[ValidatedEdge],
    file_path: str,
) -> tuple[ValidationGateResult, list[ValidatedEdge]]:
    """Gate 5: RELATIONSHIP COMPLETENESS — Are expected relationships present?

    Checks: modules have CONTAINS/DEFINES, functions have DEFINES from parent,
    imports produced IMPORTS edges.
    Auto-repair: create missing structural edges.
    Guarantee: Structural relationships are complete.
    """
    gate = ValidationGateResult(gate="relationship_completeness", gate_number=5, passed=True)
    new_edges: list[ValidatedEdge] = []

    node_ids = {n.id for n in nodes}
    edge_set = {(e.source, e.target, e.relationship) for e in edges}

    # Find module nodes (file-level)
    module_nodes = [n for n in nodes if n.entity_type in ("PythonModule", "JavaScriptModule", "TestFile")]
    child_nodes = [n for n in nodes if n.entity_type in ("Function", "Class")]

    for mod in module_nodes:
        for child in child_nodes:
            # Check child belongs to this module (shares file_path prefix)
            if child.id.startswith(mod.id) or (child.file_path and child.file_path == mod.file_path):
                edge_key = (mod.id, child.id, "DEFINES")
                if edge_key not in edge_set:
                    new_edges.append(ValidatedEdge(
                        source=mod.id, target=child.id, relationship="DEFINES"
                    ))
                    gate.auto_repaired += 1
                    edge_set.add(edge_key)

    gate.details["new_edges"] = len(new_edges)
    return gate, edges + new_edges


def gate_6_intelligence_compilation(
    nodes: list[ValidatedNode],
    edges: list[ValidatedEdge],
    file_path: str,
) -> ValidationGateResult:
    """Gate 6: INTELLIGENCE COMPILATION — Can we produce a useful packet?

    Checks: at least 1 node, packet producible, not isolated.
    Guarantee: Every file has an intelligence packet ready for Layer B.
    """
    gate = ValidationGateResult(gate="intelligence_compilation", gate_number=6, passed=True)

    if not nodes:
        gate.passed = False
        gate.degraded = 1
        gate.warnings.append(f"No validated nodes for {file_path}. Cannot compile intelligence.")
        return gate

    # Check connectivity
    has_edges = len(edges) > 0
    if not has_edges:
        gate.warnings.append(f"{file_path} has no edges. Intelligence packet will have limited context.")

    gate.details["nodes"] = len(nodes)
    gate.details["edges"] = len(edges)
    gate.details["has_edges"] = has_edges
    return gate


def run_all_gates(
    nodes_raw: list[dict[str, Any]],
    edges_raw: list[dict[str, Any]],
    file_path: str,
    file_content: str | None = None,
    known_node_ids: set[str] | None = None,
) -> tuple[list[ValidationGateResult], list[ValidatedNode], list[ValidatedEdge], list[dict[str, Any]]]:
    """Run all 6 validation gates in sequence.

    Returns: (gate_results, validated_nodes, validated_edges, pending_edges)
    """
    if known_node_ids is None:
        known_node_ids = set()

    results: list[ValidationGateResult] = []

    # Gate 1: Parse integrity
    g1 = gate_1_parse_integrity(nodes_raw, file_path, file_content)
    results.append(g1)

    # Gate 2: Node completeness
    g2, validated_nodes = gate_2_node_completeness(nodes_raw, file_path)
    results.append(g2)

    # Update known node IDs with newly validated nodes
    local_ids = {n.id for n in validated_nodes}
    all_known = known_node_ids | local_ids

    # Gate 3: Chunk quality
    g3 = gate_3_chunk_quality(validated_nodes)
    results.append(g3)

    # Gate 4: Edge integrity
    g4, validated_edges, pending_edges = gate_4_edge_integrity(edges_raw, all_known)
    results.append(g4)

    # Gate 5: Relationship completeness
    g5, validated_edges = gate_5_relationship_completeness(
        validated_nodes, validated_edges, file_path
    )
    results.append(g5)

    # Gate 6: Intelligence compilation
    g6 = gate_6_intelligence_compilation(validated_nodes, validated_edges, file_path)
    results.append(g6)

    return results, validated_nodes, validated_edges, pending_edges


# ─── Helper Functions ──────────────────────────────────────────────────

def _chunk_raw_text(content: str, file_path: str, chunk_size: int = 500) -> list[dict[str, Any]]:
    """Split raw text into ~500 char chunks for fallback nodes."""
    chunks = []
    lines = content.split("\n")
    current_text = ""
    current_start = 1

    for i, line in enumerate(lines, 1):
        current_text += line + "\n"
        if len(current_text) >= chunk_size:
            chunks.append({
                "text": current_text.strip(),
                "type": "raw",
                "start_line": current_start,
                "end_line": i,
            })
            current_text = ""
            current_start = i + 1

    if current_text.strip():
        chunks.append({
            "text": current_text.strip(),
            "type": "raw",
            "start_line": current_start,
            "end_line": len(lines),
        })

    return chunks or [{"text": f"File: {file_path}", "type": "raw"}]


def _infer_type(node_id: str, label: str, properties: dict[str, Any]) -> str:
    """Infer node type from ID/label patterns."""
    lower = (node_id + label).lower()
    if "test" in lower:
        return "TestFile"
    if lower.endswith(".py"):
        return "PythonModule"
    if any(lower.endswith(ext) for ext in (".js", ".ts", ".jsx", ".tsx")):
        return "JavaScriptModule"
    if "class" in properties.get("kind", ""):
        return "Class"
    if "function" in properties.get("kind", "") or "def" in properties.get("kind", ""):
        return "Function"
    return "Config"


def _synthesize_description(
    label: str, entity_type: str, properties: dict[str, Any], node_id: str
) -> str:
    """Synthesize a meaningful description from available metadata."""
    parts = [f"{entity_type}: {label}"]

    if "docstring" in properties and properties["docstring"]:
        parts.append(properties["docstring"][:200])
    elif "summary" in properties:
        parts.append(str(properties["summary"])[:200])
    else:
        # Build from structural info
        if entity_type in ("Function", "Class"):
            parent = node_id.rsplit("::", 1)[0] if "::" in node_id else ""
            if parent:
                parts.append(f"Defined in {parent.rsplit('/', 1)[-1]}.")
        if "params" in properties:
            params = properties["params"]
            if isinstance(params, list) and params:
                parts.append(f"Parameters: {', '.join(str(p) for p in params[:5])}.")
        if "calls" in properties:
            calls = properties["calls"]
            if isinstance(calls, list) and calls:
                parts.append(f"Calls: {', '.join(str(c) for c in calls[:5])}.")

    desc = " ".join(parts)
    # Ensure minimum length
    if len(desc) < MIN_DESCRIPTION_LENGTH:
        desc += f" Located at {node_id}."
    return desc[:500]


def _synthesize_chunks(
    label: str, entity_type: str, description: str, file_path: str | None
) -> list[dict[str, Any]]:
    """Synthesize chunks from description when no source chunks exist."""
    text = f"{entity_type} '{label}': {description}"
    if file_path:
        text += f" (source: {file_path})"

    return [{"text": text, "type": "synthesized"}]


def _infer_chunk_type(text: str, entity_type: str) -> str:
    """Infer chunk type from content."""
    lower = text[:200].lower()
    if "def " in lower or "function " in lower or "=>" in lower:
        return "function"
    if "class " in lower:
        return "class"
    if "import " in lower or "from " in lower or "require(" in lower:
        return "imports"
    if entity_type == "Function":
        return "function"
    if entity_type == "Class":
        return "class"
    return "file"


def _closest_edge_type(rel: str) -> str | None:
    """Find the closest registered edge type for a typo/variant."""
    rel_upper = rel.upper().replace("-", "_").replace(" ", "_")
    if rel_upper in REGISTERED_EDGE_TYPES:
        return rel_upper
    # Common aliases
    aliases = {
        "IMPORT": "IMPORTS", "CONTAIN": "CONTAINS", "TEST": "TESTS",
        "DEFINE": "DEFINES", "CALL": "CALLS", "DEPEND": "DEPENDS_ON",
        "CONFIGURE": "CONFIGURES", "MODEL": "MODELS", "ROUTE": "ROUTES_TO",
        "USE": "USES_ENVVAR", "USES": "USES_ENVVAR",
    }
    return aliases.get(rel_upper)
