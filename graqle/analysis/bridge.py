"""R2 Bridge-Edge Detection module (ADR-133).

Detects candidate bridge edges between scanner entity types
(PythonModule, JavaScriptModule, Class, Function, TestFile) and
KG Entity nodes.  ReactComponent is optional/secondary via
scan_react_components.

Language-namespaced dedup keys prevent cross-language collisions
(e.g. utils.py vs utils.ts).
"""

# ── graqle:intelligence ──
# module: graqle.analysis.bridge
# risk: MEDIUM (impact radius: 3 modules)
# consumers: merge.pipeline, scan, mcp_dev_server
# dependencies: __future__, dataclasses, logging, re, typing
# constraints: ADR-133 R2 bridge validation protocol
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCANNER_ENTITY_TYPES: frozenset[str] = frozenset({
    "PythonModule",
    "JavaScriptModule",
    "Class",
    "Function",
    "TestFile",
})

SECONDARY_ENTITY_TYPES: frozenset[str] = frozenset({
    "ReactComponent",
})

_COMPATIBLE_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("PythonModule", "Entity"),
    ("PythonModule", "Module"),
    ("PythonModule", "Service"),
    ("PythonModule", "Component"),
    ("PythonModule", "Package"),
    ("JavaScriptModule", "Entity"),
    ("JavaScriptModule", "Module"),
    ("JavaScriptModule", "Service"),
    ("JavaScriptModule", "Component"),
    ("JavaScriptModule", "Package"),
    ("Class", "Entity"),
    ("Class", "Concept"),
    ("Class", "Service"),
    ("Class", "Component"),
    ("Function", "Entity"),
    ("Function", "Concept"),
    ("Function", "API"),
    ("Function", "Service"),
    ("TestFile", "Entity"),
    ("TestFile", "Module"),
    ("TestFile", "Service"),
    ("ReactComponent", "Entity"),
    ("ReactComponent", "Component"),
    ("ReactComponent", "Module"),
})

# Entity-type → language mapping (ADR-133 CRITICAL for dedup namespacing)
# NOTE: Class and Function are language-agnostic — derive_language uses
# file-path heuristic (step 3) for these types instead of a static map.
_ENTITY_TYPE_TO_LANGUAGE: dict[str, str] = {
    "PythonModule": "python",
    "JavaScriptModule": "javascript",
    "ReactComponent": "javascript",
}

# Normalisation patterns — mirrors linker.py convention
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_LOWER_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")

# Confidence constants
_DEFAULT_CONFIDENCE_THRESHOLD: float = 0.4
_EXACT_MATCH_CONFIDENCE: float = 0.95  # < 1.0: normalisation may conflate distinct names


# ---------------------------------------------------------------------------
# Normalisation / tokenisation helpers (mirrors linker.py normalise pattern)
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip file extensions, split camelCase, collapse non-alnum."""
    # Handle consecutive-uppercase acronyms (XMLParser → XML_Parser)
    text = _CAMEL_SPLIT_RE.sub("_", text)
    # Handle lowercase→uppercase transitions (getUserName → get_User_Name)
    text = _CAMEL_LOWER_RE.sub("_", text).lower()
    for ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
        if text.endswith(ext):
            text = text[: -len(ext)]
            break
    return _NORMALISE_RE.sub("_", text).strip("_")


def _tokenise(text: str) -> set[str]:
    """Return the set of normalised tokens from *text*."""
    return {t for t in _normalise(text).split("_") if t and len(t) > 1}


# ---------------------------------------------------------------------------
# Node field extraction helper (DRY — single isinstance branch)
# ---------------------------------------------------------------------------

def _extract_node_fields(node: Any) -> tuple[dict, str, str, str, str]:
    """Extract (props, entity_type, node_id, label, source_file) from a node.

    Handles both dict and object representations with a single isinstance
    check, avoiding repeated branching in derive_language.
    """
    if isinstance(node, dict):
        props = node.get("properties", node)
        entity_type = node.get("entity_type", node.get("type", ""))
        node_id = node.get("id", "")
        label = node.get("label", node.get("name", ""))
        source_file = node.get("source_file", node.get("file_path", ""))
    else:
        props = getattr(node, "properties", {}) or {}
        entity_type = getattr(node, "entity_type", "") or ""
        node_id = getattr(node, "id", "") or ""
        label = getattr(node, "label", "") or ""
        source_file = (
            getattr(node, "source_file", "")
            or getattr(node, "file_path", "")
            or props.get("source_file", "")
            or props.get("file_path", "")
        )
    return props, entity_type, node_id, label, source_file


# ---------------------------------------------------------------------------
# Language derivation (ADR-133 §3 — CRITICAL for dedup key namespacing)
# ---------------------------------------------------------------------------

def derive_language(node: Any) -> str:
    """Map a node's ``entity_type`` to a canonical language string.

    ADR-133 CRITICAL — the language tag namespaces dedup keys so that
    ``python::utils`` and ``javascript::utils`` remain distinct.

    Resolution order:
    1. Explicit ``language`` property on the node.
    2. ``entity_type`` lookup in ``_ENTITY_TYPE_TO_LANGUAGE``.
    3. File-path / node-id heuristic (suffix-based).
    4. Fallback ``"unknown"``.
    """
    # Unify dict vs object field extraction at the top (single isinstance check)
    props, entity_type, node_id, label, source_file = _extract_node_fields(node)

    # 1. Explicit property
    explicit_lang = props.get("language", "")
    if explicit_lang:
        return str(explicit_lang).lower()

    # 2. Entity type lookup
    lang = _ENTITY_TYPE_TO_LANGUAGE.get(entity_type, "")
    if lang:
        return lang

    # 3. File-path / label heuristic

    for candidate in (node_id, label, source_file):
        if not candidate:
            continue
        # Strip symbol suffix (e.g. "src/models.py::User" → "src/models.py")
        path = candidate.split("::")[0] if "::" in candidate else candidate
        lower = path.lower()
        if lower.endswith(".py"):
            return "python"
        if lower.endswith((".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs")):
            return "javascript"

    # 4. Fallback
    return "unknown"


# ---------------------------------------------------------------------------
# Data classes (follows linker.py ProposedEdge pattern)
# ---------------------------------------------------------------------------

@dataclass
class BridgeCandidate:
    """A proposed bridge edge between a scanner entity and a KG entity.

    ``confidence`` defaults to 0.0, which is below ``_DEFAULT_CONFIDENCE_THRESHOLD``
    (0.4). Callers must set confidence explicitly before threshold filtering.
    """

    source_id: str
    target_id: str
    relationship: str = "BRIDGE_TO"
    confidence: float = 0.0
    method: Literal["exact_name", "token_overlap", "unknown"] = "unknown"
    language: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("source_id and target_id must be non-empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence {self.confidence} must be in [0, 1]")


def make_dedup_key(candidate: BridgeCandidate) -> str:
    """Language-namespaced dedup key for a bridge candidate.

    Format: ``{language}::{source_id}--{relationship}-->{target_id}``

    ADR-133: the language prefix prevents ``python::utils`` from
    colliding with ``javascript::utils``.
    """
    return (
        f"{candidate.language}::{candidate.source_id}"
        f"--{candidate.relationship}-->{candidate.target_id}"
    )


@dataclass
class BridgeDetectionReport:
    """Result of a bridge-detection run."""

    candidates: list[BridgeCandidate] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# R2 Bridge Validation Protocol — 6 checks (reordered per GraQle review)
# ---------------------------------------------------------------------------

def _validate_candidate(
    candidate: BridgeCandidate,
    all_node_ids: set[str],
    existing_edge_keys: set[str],
    seen_dedup_keys: set[str],
    source_type: str,
    target_type: str,
    confidence_threshold: float,
) -> str | None:
    """Run the 6-check R2 Bridge Validation Protocol.

    Returns ``None`` if valid, or a rejection reason string.

    Check order (per GraQle review): structural invariants first,
    then soft gates.
    """
    # 1. No self-loops
    if candidate.source_id == candidate.target_id:
        return "self_loop"

    # 2. Both endpoints exist (structural — before soft checks)
    if candidate.source_id not in all_node_ids:
        return f"source_missing:{candidate.source_id}"
    if candidate.target_id not in all_node_ids:
        return f"target_missing:{candidate.target_id}"

    # 3. Type compatibility
    if source_type and target_type:
        if (source_type, target_type) not in _COMPATIBLE_PAIRS:
            return f"type_incompatible:{source_type}->{target_type}"

    # 4. No duplicate edge (already in graph)
    edge_key = f"{candidate.source_id}--{candidate.relationship}-->{candidate.target_id}"
    if edge_key in existing_edge_keys:
        return "duplicate_edge"

    # 5. Dedup-key collision (language-namespaced)
    dedup_key = make_dedup_key(candidate)
    if dedup_key in seen_dedup_keys:
        return "duplicate_dedup_key"

    # 6. Confidence threshold (soft gate — last)
    if candidate.confidence < confidence_threshold:
        return f"below_confidence:{candidate.confidence}<{confidence_threshold}"

    return None


# ---------------------------------------------------------------------------
# BridgeDetector
# ---------------------------------------------------------------------------

class BridgeDetector:
    """Detect candidate bridge edges between scanner nodes and KG entities."""

    def __init__(
        self,
        *,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
        scan_react_components: bool = False,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self._allowed_types: set[str] = set(SCANNER_ENTITY_TYPES)
        if scan_react_components:
            self._allowed_types |= SECONDARY_ENTITY_TYPES

    # -- public API ---------------------------------------------------------

    def detect(
        self,
        scanner_nodes: list[dict[str, Any]],
        kg_nodes: list[dict[str, Any]],
        existing_edges: list[dict[str, Any]] | None = None,
    ) -> BridgeDetectionReport:
        """Run bridge detection and return a validated report."""
        report = BridgeDetectionReport()

        all_node_ids: set[str] = set()
        for n in scanner_nodes:
            nid = n.get("id", "")
            if nid:
                all_node_ids.add(nid)
        for n in kg_nodes:
            nid = n.get("id", "")
            if nid:
                all_node_ids.add(nid)

        # Build existing edge keys — normalise source/source_id and target/target_id
        existing_edge_keys: set[str] = set()
        if existing_edges:
            for e in existing_edges:
                src = e.get("source") or e.get("source_id", "")
                tgt = e.get("target") or e.get("target_id", "")
                rel = e.get("relationship", "")
                existing_edge_keys.add(f"{src}--{rel}-->{tgt}")

        # Pre-index KG nodes by normalised name for O(1) exact-match lookup
        kg_by_norm: dict[str, list[dict[str, Any]]] = {}
        kg_all: list[dict[str, Any]] = []
        for kg_node in kg_nodes:
            kg_id = kg_node.get("id", "")
            if not kg_id:
                continue
            kg_all.append(kg_node)
            norm_name = _normalise(kg_node.get("name", kg_id))
            if norm_name:
                kg_by_norm.setdefault(norm_name, []).append(kg_node)

        seen_dedup: set[str] = set()

        for s_node in scanner_nodes:
            s_type = s_node.get("entity_type", s_node.get("type", ""))
            if s_type not in self._allowed_types:
                continue

            s_id = s_node.get("id", "")
            if not s_id:
                logger.warning("Scanner node missing id, skipping: %s", s_node)
                continue

            s_name = s_node.get("name", s_id)
            s_lang = derive_language(s_node)
            norm_s = _normalise(s_name)

            # Phase 1: exact-match via index (O(1) lookup)
            exact_matches = kg_by_norm.get(norm_s, [])
            matched_exact = False
            for kg_node in exact_matches:
                kg_id = kg_node.get("id", "")
                kg_type = kg_node.get("entity_type", kg_node.get("type", ""))
                candidate = BridgeCandidate(
                    source_id=s_id,
                    target_id=kg_id,
                    relationship="BRIDGE_TO",
                    confidence=_EXACT_MATCH_CONFIDENCE,
                    method="exact_name",
                    language=s_lang,
                )
                reason = _validate_candidate(
                    candidate, all_node_ids, existing_edge_keys,
                    seen_dedup, s_type, kg_type, self.confidence_threshold,
                )
                if reason is None:
                    seen_dedup.add(make_dedup_key(candidate))
                    report.candidates.append(candidate)
                    matched_exact = True
                else:
                    report.rejected.append({
                        "source_id": candidate.source_id,
                        "target_id": candidate.target_id,
                        "relationship": candidate.relationship,
                        "reason": reason,
                    })

            # Phase 2: token-overlap for non-exact matches only
            if not matched_exact:
                s_tokens = _tokenise(s_name)
                if s_tokens:
                    for kg_node in kg_all:
                        kg_id = kg_node.get("id", "")
                        kg_name = kg_node.get("name", kg_id)
                        kg_type = kg_node.get("entity_type", kg_node.get("type", ""))
                        k_tokens = _tokenise(kg_name)
                        if not k_tokens:
                            continue
                        intersection = s_tokens & k_tokens
                        if not intersection:
                            continue
                        union = s_tokens | k_tokens
                        score = len(intersection) / len(union)
                        if score < self.confidence_threshold:
                            continue
                        candidate = BridgeCandidate(
                            source_id=s_id,
                            target_id=kg_id,
                            relationship="BRIDGE_TO",
                            confidence=round(score, 4),
                            method="token_overlap",
                            language=s_lang,
                        )
                        reason = _validate_candidate(
                            candidate, all_node_ids, existing_edge_keys,
                            seen_dedup, s_type, kg_type, self.confidence_threshold,
                        )
                        if reason is None:
                            seen_dedup.add(make_dedup_key(candidate))
                            report.candidates.append(candidate)
                        else:
                            report.rejected.append({
                                "source_id": candidate.source_id,
                                "target_id": candidate.target_id,
                                "relationship": candidate.relationship,
                                "reason": reason,
                            })

        logger.info(
            "Bridge detection complete: %d accepted, %d rejected",
            len(report.candidates), len(report.rejected),
        )
        return report
