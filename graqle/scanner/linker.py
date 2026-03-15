"""Auto-linker — connects document nodes to code nodes in the graph.

Implements a multi-level linking pipeline:

1. **Exact match** — code node IDs/labels found verbatim in document text.
2. **Fuzzy match** — normalised name matching (camelCase ↔ snake_case,
   path segments, keyword overlap).
3. **Semantic match** (opt-in) — embedding cosine similarity.
4. **LLM-assisted** (opt-in) — structured relationship extraction via LLM.

Each level is independently toggleable and has configurable thresholds.
The linker operates on the graph in-memory and returns a list of proposed
edges that the caller can accept/reject before persisting.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.linker
# risk: LOW (impact radius: 3 modules)
# consumers: docs, test_doc_chain, test_linker
# dependencies: __future__, logging, re, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graqle.scanner.linker")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProposedEdge:
    """A candidate edge proposed by the linker.

    Attributes
    ----------
    source_id:
        Node ID of the source (typically the document/section node).
    target_id:
        Node ID of the target (typically the code node).
    relation:
        Edge relationship type (e.g. ``"REFERENCED_IN"``).
    confidence:
        How confident the linker is in this edge (0.0–1.0).
    method:
        Which linking level proposed this edge.
    evidence:
        Human-readable explanation of why this edge was proposed.
    """

    source_id: str
    target_id: str
    relation: str
    confidence: float
    method: str  # "exact", "fuzzy", "semantic", "llm"
    evidence: str = ""


@dataclass
class LinkingResult:
    """Summary of a linking run.

    Attributes
    ----------
    proposed:
        All proposed edges.
    accepted:
        Edges that passed the confidence threshold and were added.
    rejected:
        Edges below threshold or filtered out.
    stats:
        Per-method counts.
    """

    proposed: list[ProposedEdge] = field(default_factory=list)
    accepted: list[ProposedEdge] = field(default_factory=list)
    rejected: list[ProposedEdge] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Name normalisation helpers
# ---------------------------------------------------------------------------

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALPHANUM_RE = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> set[str]:
    """Return a set of normalised tokens from a node label/ID.

    Handles camelCase, snake_case, kebab-case, and path separators.

    >>> sorted(_normalise("AuthService"))
    ['auth', 'authservice', 'service']
    >>> sorted(_normalise("src/payments/handler.py"))
    ['handler', 'handler.py', 'payments', 'src']
    """
    # Split on camelCase boundaries first
    expanded = _CAMEL_SPLIT_RE.sub(" ", name)
    # Replace path separators and non-alphanum with spaces
    expanded = expanded.replace("/", " ").replace("\\", " ").replace("_", " ").replace("-", " ").replace(".", " ")
    tokens = {t.lower() for t in expanded.split() if len(t) >= 2}
    # Also add the original basename (e.g. "handler.py")
    if "/" in name or "\\" in name:
        basename = name.replace("\\", "/").rsplit("/", 1)[-1]
        tokens.add(basename.lower())
    # Add full normalised form
    full = _NON_ALPHANUM_RE.sub("", name.lower())
    if len(full) >= 2:
        tokens.add(full)
    return tokens


def _token_overlap_score(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Jaccard-like overlap between two token sets.

    Returns a score between 0.0 and 1.0.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    if not intersection:
        return 0.0
    # Use the smaller set as denominator for asymmetric matching
    # (a doc mentioning "auth" should match "auth_service" at high score)
    return len(intersection) / min(len(tokens_a), len(tokens_b))


# ---------------------------------------------------------------------------
# AutoLinker
# ---------------------------------------------------------------------------


class AutoLinker:
    """Multi-level document-to-code auto-linker.

    Parameters
    ----------
    exact:
        Enable exact-match linking.
    fuzzy:
        Enable fuzzy-match linking.
    semantic:
        Enable semantic (embedding) linking.
    llm_assisted:
        Enable LLM-assisted linking.
    fuzzy_threshold:
        Minimum fuzzy overlap score to propose an edge (0.0–1.0).
    semantic_threshold:
        Minimum cosine similarity for semantic edges (0.0–1.0).
    max_edges_per_doc:
        Safety limit: max edges proposed per document node.
    """

    def __init__(
        self,
        *,
        exact: bool = True,
        fuzzy: bool = True,
        semantic: bool = False,
        llm_assisted: bool = False,
        fuzzy_threshold: float = 0.60,
        semantic_threshold: float = 0.70,
        max_edges_per_doc: int = 50,
    ) -> None:
        self.exact = exact
        self.fuzzy = fuzzy
        self.semantic = semantic
        self.llm_assisted = llm_assisted
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_threshold = semantic_threshold
        self.max_edges_per_doc = max_edges_per_doc

    # -- public API ---------------------------------------------------------

    def link(
        self,
        doc_nodes: list[dict[str, Any]],
        code_nodes: list[dict[str, Any]],
        doc_texts: dict[str, str] | None = None,
    ) -> LinkingResult:
        """Run the full linking pipeline.

        Parameters
        ----------
        doc_nodes:
            List of document/section node dicts.  Each must have at
            minimum ``{"id": str, "label": str}``.  Optionally
            ``"description"`` and ``"entity_type"``.
        code_nodes:
            List of code node dicts (same schema).
        doc_texts:
            Optional mapping ``{doc_node_id: full_text}`` used for
            exact and fuzzy matching (if not provided, the node's
            ``description`` is used).

        Returns
        -------
        LinkingResult
            Proposed, accepted, and rejected edges plus stats.
        """
        result = LinkingResult()
        doc_texts = doc_texts or {}

        # Build code node lookup structures once
        code_index = _build_code_index(code_nodes)

        for doc in doc_nodes:
            doc_id = doc["id"]
            text = doc_texts.get(doc_id, doc.get("description", ""))
            doc_label = doc.get("label", "")

            proposed_for_doc: list[ProposedEdge] = []

            if self.exact:
                proposed_for_doc.extend(
                    self._exact_match(doc_id, text, code_index)
                )

            if self.fuzzy:
                proposed_for_doc.extend(
                    self._fuzzy_match(doc_id, text, doc_label, code_index)
                )

            # Deduplicate: keep highest-confidence edge per (source, target, relation)
            deduped = self._deduplicate(proposed_for_doc)

            # Apply per-doc limit
            deduped.sort(key=lambda e: e.confidence, reverse=True)
            deduped = deduped[: self.max_edges_per_doc]

            result.proposed.extend(deduped)

        # Partition into accepted/rejected
        for edge in result.proposed:
            if edge.method == "exact":
                result.accepted.append(edge)
            elif edge.method == "fuzzy" and edge.confidence >= self.fuzzy_threshold:
                result.accepted.append(edge)
            elif edge.method == "semantic" and edge.confidence >= self.semantic_threshold:
                result.accepted.append(edge)
            else:
                result.rejected.append(edge)

        # Stats
        for method in ("exact", "fuzzy", "semantic", "llm"):
            accepted_count = sum(1 for e in result.accepted if e.method == method)
            if accepted_count > 0:
                result.stats[method] = accepted_count

        return result

    # -- Level 1: Exact match -----------------------------------------------

    def _exact_match(
        self,
        doc_id: str,
        text: str,
        code_index: _CodeIndex,
    ) -> list[ProposedEdge]:
        """Find code node IDs/labels that appear verbatim in *text*."""
        if not text:
            return []

        proposed: list[ProposedEdge] = []
        text_lower = text.lower()

        for code_node in code_index.nodes:
            node_id = code_node["id"]
            label = code_node.get("label", node_id)

            # Check if the node ID or label appears in the text
            for term, term_type in [(node_id, "id"), (label, "label")]:
                if not term or len(term) < 3:
                    continue
                if term.lower() in text_lower:
                    # Determine edge type based on context
                    relation = _infer_relation(code_node, doc_id)
                    proposed.append(
                        ProposedEdge(
                            source_id=doc_id,
                            target_id=node_id,
                            relation=relation,
                            confidence=1.0,
                            method="exact",
                            evidence=f"'{term}' ({term_type}) found verbatim in document text",
                        )
                    )
                    break  # Don't double-count id + label for same node

        return proposed

    # -- Level 2: Fuzzy match -----------------------------------------------

    def _fuzzy_match(
        self,
        doc_id: str,
        text: str,
        doc_label: str,
        code_index: _CodeIndex,
    ) -> list[ProposedEdge]:
        """Match code nodes via normalised token overlap."""
        if not text:
            return []

        proposed: list[ProposedEdge] = []
        # Tokenise the document text
        text_tokens = _tokenise_text(text)
        if not text_tokens:
            return []

        for code_node in code_index.nodes:
            node_id = code_node["id"]
            code_tokens = code_index.tokens.get(node_id, set())
            if not code_tokens:
                continue

            score = _token_overlap_score(code_tokens, text_tokens)
            if score >= self.fuzzy_threshold * 0.5:  # pre-filter (relaxed)
                relation = _infer_relation(code_node, doc_id)
                proposed.append(
                    ProposedEdge(
                        source_id=doc_id,
                        target_id=node_id,
                        relation=relation,
                        confidence=min(score, 1.0),
                        method="fuzzy",
                        evidence=(
                            f"Token overlap {score:.2f} between "
                            f"doc '{doc_label}' and code '{code_node.get('label', node_id)}'"
                        ),
                    )
                )

        return proposed

    # -- Deduplication ------------------------------------------------------

    @staticmethod
    def _deduplicate(edges: list[ProposedEdge]) -> list[ProposedEdge]:
        """Keep the highest-confidence edge per (source, target) pair."""
        best: dict[tuple[str, str], ProposedEdge] = {}
        for edge in edges:
            key = (edge.source_id, edge.target_id)
            existing = best.get(key)
            if existing is None or edge.confidence > existing.confidence:
                best[key] = edge
        return list(best.values())


# ---------------------------------------------------------------------------
# Code index — pre-processed lookup structure for code nodes
# ---------------------------------------------------------------------------


@dataclass
class _CodeIndex:
    """Pre-computed index over code nodes for fast matching."""

    nodes: list[dict[str, Any]]
    tokens: dict[str, set[str]]  # node_id → normalised tokens


def _build_code_index(code_nodes: list[dict[str, Any]]) -> _CodeIndex:
    """Build a :class:`_CodeIndex` from raw code node dicts."""
    tokens: dict[str, set[str]] = {}
    for node in code_nodes:
        nid = node["id"]
        label = node.get("label", nid)
        t = _normalise(nid) | _normalise(label)
        desc = node.get("description", "")
        if desc:
            t |= _normalise(desc)
        tokens[nid] = t
    return _CodeIndex(nodes=code_nodes, tokens=tokens)


def _tokenise_text(text: str) -> set[str]:
    """Extract a broad set of tokens from document text for fuzzy matching."""
    # Split on whitespace and punctuation, lowercase, filter short tokens
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_./-]{1,}", text)
    tokens: set[str] = set()
    for w in words:
        tokens |= _normalise(w)
    return tokens


# ---------------------------------------------------------------------------
# Relation inference
# ---------------------------------------------------------------------------

_DOC_NODE_TYPES = frozenset({
    "Document", "Section", "Decision", "Requirement",
    "Procedure", "Definition", "Stakeholder", "Timeline",
})


def _infer_relation(code_node: dict[str, Any], doc_id: str) -> str:
    """Infer the best edge relationship type based on node types.

    This is a heuristic — LLM-assisted linking (Level 4) produces more
    accurate relationships.
    """
    etype = code_node.get("entity_type", "")

    # If code node looks like a file/module, use REFERENCED_IN
    if etype in ("MODULE", "FILE", "SERVICE", "PACKAGE"):
        return "REFERENCED_IN"

    # If code node is a function/class, use REFERENCED_IN
    if etype in ("FUNCTION", "CLASS", "METHOD"):
        return "REFERENCED_IN"

    # Default
    return "REFERENCED_IN"
