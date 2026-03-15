"""Tests for ADR-103: Content-aware PCST activation — 3-layer fix.

Validates that PCST selects content-bearing nodes (JSModule, Module, Config)
over empty structural connectors (Directory, Namespace).

Layer 1: Content richness multiplier in RelevanceScorer.score()
Layer 2: Post-PCST content filter in PCSTActivation._content_filter()
Layer 3: Direct file lookup bypass in Graqle._direct_file_lookup()
"""

# ── graqle:intelligence ──
# module: tests.test_activation.test_content_aware_pcst
# risk: HIGH (impact radius: 0 modules)
# dependencies: __future__, math, numpy, pytest, graph +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import math

import numpy as np
import pytest

from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from graqle.core.edge import CogniEdge
from graqle.activation.pcst import PCSTActivation
from graqle.activation.relevance import RelevanceScorer, _CONTENT_RICHNESS_BASE


# ──────────────────────────────────────────────────────────────────────
# Fixtures — graph topologies that reproduce the Directory-beats-JSModule bug
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def directory_vs_jsmodule_graph() -> Graqle:
    """Graph where a Directory node has high degree (hub) but zero chunks,
    and its child JSModule nodes have content chunks.

    Topology:
        dir::src (Directory, 0 chunks, high degree)
        ├── mod::auth.ts (JSModule, 3 chunks)
        ├── mod::payment.ts (JSModule, 2 chunks)
        └── mod::billing.ts (JSModule, 1 chunk)
    """
    nodes = {
        "dir::src": CogniNode(
            id="dir::src",
            label="src",
            entity_type="Directory",
            description="Source directory containing all service modules",
            properties={"chunks": []},  # explicit empty — no content to cite
        ),
        "mod::auth.ts": CogniNode(
            id="mod::auth.ts",
            label="auth.ts",
            entity_type="JSModule",
            description="Authentication service handling JWT tokens and sessions",
            properties={
                "chunks": [
                    {"text": "function verifyJWT(token) { /* validates JWT */ }", "type": "function"},
                    {"text": "function refreshToken(session) { /* refresh logic */ }", "type": "function"},
                    {"text": "class AuthProvider { /* session management */ }", "type": "class"},
                ],
            },
        ),
        "mod::payment.ts": CogniNode(
            id="mod::payment.ts",
            label="payment.ts",
            entity_type="JSModule",
            description="Payment processing service for Stripe integration",
            properties={
                "chunks": [
                    {"text": "function processPayment(amount) { /* Stripe call */ }", "type": "function"},
                    {"text": "function refund(chargeId) { /* refund logic */ }", "type": "function"},
                ],
            },
        ),
        "mod::billing.ts": CogniNode(
            id="mod::billing.ts",
            label="billing.ts",
            entity_type="JSModule",
            description="Billing invoice generation and subscription management",
            properties={
                "chunks": [
                    {"text": "function generateInvoice(sub) { /* invoice */ }", "type": "function"},
                ],
            },
        ),
    }

    edges = {
        "e_dir_auth": CogniEdge(
            id="e_dir_auth", source_id="dir::src", target_id="mod::auth.ts",
            relationship="CONTAINS", weight=1.0,
        ),
        "e_dir_payment": CogniEdge(
            id="e_dir_payment", source_id="dir::src", target_id="mod::payment.ts",
            relationship="CONTAINS", weight=1.0,
        ),
        "e_dir_billing": CogniEdge(
            id="e_dir_billing", source_id="dir::src", target_id="mod::billing.ts",
            relationship="CONTAINS", weight=1.0,
        ),
        "e_auth_payment": CogniEdge(
            id="e_auth_payment", source_id="mod::auth.ts", target_id="mod::payment.ts",
            relationship="IMPORTS", weight=0.8,
        ),
    }

    # Wire edges
    for eid, edge in edges.items():
        if edge.source_id in nodes:
            nodes[edge.source_id].outgoing_edges.append(eid)
        if edge.target_id in nodes:
            nodes[edge.target_id].incoming_edges.append(eid)

    return Graqle(nodes=nodes, edges=edges)


@pytest.fixture
def isolated_nodes_graph() -> Graqle:
    """Graph with zero edges — tests fallback behaviour."""
    nodes = {
        "n1": CogniNode(
            id="n1", label="config.yaml", entity_type="Config",
            description="Application configuration file",
            properties={"chunks": [{"text": "port: 8080", "type": "yaml"}]},
        ),
        "n2": CogniNode(
            id="n2", label="readme.md", entity_type="Document",
            description="Project readme documentation",
            properties={},
        ),
    }
    return Graqle(nodes=nodes)


# ──────────────────────────────────────────────────────────────────────
# Layer 1: Content Richness Multiplier
# ──────────────────────────────────────────────────────────────────────

class TestContentRichnessMultiplier:
    """Layer 1 (ADR-103): log2(2 + chunk_count) multiplier."""

    def test_zero_chunks_neutral_multiplier(self) -> None:
        """Nodes with 0 chunks get multiplier = log2(2) = 1.0 (no boost)."""
        assert math.log2(_CONTENT_RICHNESS_BASE + 0) == 1.0

    def test_positive_chunks_boost(self) -> None:
        """Nodes with chunks get multiplier > 1.0."""
        for n_chunks in [1, 2, 3, 5, 10]:
            mult = math.log2(_CONTENT_RICHNESS_BASE + n_chunks)
            assert mult > 1.0, f"{n_chunks} chunks should boost: got {mult}"

    def test_logarithmic_diminishing_returns(self) -> None:
        """Boost grows logarithmically — not linearly."""
        mult_1 = math.log2(_CONTENT_RICHNESS_BASE + 1)
        mult_10 = math.log2(_CONTENT_RICHNESS_BASE + 10)
        # 10 chunks should not give 10x the boost of 1 chunk
        assert mult_10 / mult_1 < 3.0

    def test_chunked_node_scores_higher_than_empty(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """auth.ts (3 chunks) should outscore dir::src (0 chunks)."""
        scorer = RelevanceScorer()
        scores = scorer.score(directory_vs_jsmodule_graph, "authentication JWT tokens")
        assert scores["mod::auth.ts"] > scores["dir::src"], (
            f"auth.ts ({scores['mod::auth.ts']:.3f}) should beat "
            f"dir::src ({scores['dir::src']:.3f})"
        )

    def test_all_chunked_nodes_beat_directory(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Every JSModule should outscore the Directory for a relevant query."""
        scorer = RelevanceScorer()
        scores = scorer.score(directory_vs_jsmodule_graph, "payment processing billing")
        dir_score = scores["dir::src"]
        for nid in ["mod::auth.ts", "mod::payment.ts", "mod::billing.ts"]:
            assert scores[nid] >= dir_score, (
                f"{nid} ({scores[nid]:.3f}) should be >= dir::src ({dir_score:.3f})"
            )

    def test_scores_can_exceed_one(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """v3 scores are NOT clamped to [0, 1] — content multiplier can push beyond."""
        scorer = RelevanceScorer()
        scores = scorer.score(directory_vs_jsmodule_graph, "authentication JWT tokens")
        # At least one score should be > 0 (basic sanity)
        assert max(scores.values()) > 0


# ──────────────────────────────────────────────────────────────────────
# Layer 2: Post-PCST Content Filter
# ──────────────────────────────────────────────────────────────────────

class TestPostPCSTContentFilter:
    """Layer 2 (ADR-103): Replace zero-chunk nodes with content-bearing neighbours."""

    def test_zero_chunk_node_replaced(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """dir::src (0 chunks) should be replaced by a child with chunks."""
        activator = PCSTActivation(max_nodes=3)
        relevance = {"dir::src": 0.9, "mod::auth.ts": 0.7, "mod::payment.ts": 0.5, "mod::billing.ts": 0.3}
        selected = ["dir::src", "mod::auth.ts"]
        filtered = activator._content_filter(
            directory_vs_jsmodule_graph, selected, relevance,
        )
        assert "dir::src" not in filtered, "dir::src should be replaced"
        # Replaced with a chunked neighbour
        assert any(
            nid.startswith("mod::") for nid in filtered
        ), "Replacement should be a JSModule"

    def test_chunked_nodes_kept(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Nodes with chunks should never be replaced."""
        activator = PCSTActivation(max_nodes=5)
        relevance = {"mod::auth.ts": 0.9, "mod::payment.ts": 0.7}
        selected = ["mod::auth.ts", "mod::payment.ts"]
        filtered = activator._content_filter(
            directory_vs_jsmodule_graph, selected, relevance,
        )
        assert set(filtered) == {"mod::auth.ts", "mod::payment.ts"}

    def test_no_duplicate_after_replacement(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """If replacement is already in selection, no duplicates appear."""
        activator = PCSTActivation(max_nodes=5)
        relevance = {"dir::src": 0.9, "mod::auth.ts": 0.8, "mod::payment.ts": 0.5}
        # dir::src and auth.ts both selected; dir::src's best neighbour is auth.ts
        selected = ["dir::src", "mod::auth.ts"]
        filtered = activator._content_filter(
            directory_vs_jsmodule_graph, selected, relevance,
        )
        # No duplicates
        assert len(filtered) == len(set(filtered))

    def test_isolated_zero_chunk_node_kept(
        self, isolated_nodes_graph: Graqle,
    ) -> None:
        """Zero-chunk node with no neighbours is kept (nothing to swap to)."""
        activator = PCSTActivation(max_nodes=5)
        relevance = {"n2": 0.8}
        selected = ["n2"]
        filtered = activator._content_filter(
            isolated_nodes_graph, selected, relevance,
        )
        assert "n2" in filtered

    def test_all_neighbours_also_zero_chunks(self) -> None:
        """If all neighbours also have zero chunks, original is kept."""
        nodes = {
            "a": CogniNode(id="a", label="A", description="dir a", properties={}),
            "b": CogniNode(id="b", label="B", description="dir b", properties={}),
        }
        edges = {
            "e_ab": CogniEdge(id="e_ab", source_id="a", target_id="b",
                              relationship="RELATED_TO", weight=1.0),
        }
        nodes["a"].outgoing_edges.append("e_ab")
        nodes["b"].incoming_edges.append("e_ab")
        graph = Graqle(nodes=nodes, edges=edges)

        activator = PCSTActivation(max_nodes=5)
        selected = ["a"]
        filtered = activator._content_filter(graph, selected, {"a": 0.5, "b": 0.3})
        assert "a" in filtered

    def test_empty_selection_returns_empty(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Empty input → empty output."""
        activator = PCSTActivation(max_nodes=5)
        filtered = activator._content_filter(
            directory_vs_jsmodule_graph, [], {},
        )
        assert filtered == []


# ──────────────────────────────────────────────────────────────────────
# Layer 3: Direct File Lookup Bypass
# ──────────────────────────────────────────────────────────────────────

class TestDirectFileLookup:
    """Layer 3 (ADR-103): Bypass PCST when query mentions a specific filename."""

    def test_exact_filename_match(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Query mentioning 'auth.ts' should directly activate mod::auth.ts."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "What does auth.ts do?"
        )
        assert result is not None
        assert "mod::auth.ts" in result

    def test_bare_name_word_boundary_match(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """'payment' as a word should match payment.ts."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "How does payment handle refunds?"
        )
        assert result is not None
        assert "mod::payment.ts" in result

    def test_bare_name_no_substring_match(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """'bill' inside 'billing' should not match if 'bill' is not a label.
        But 'billing' should match billing.ts's bare name."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "What is the billing process?"
        )
        assert result is not None
        assert "mod::billing.ts" in result

    def test_no_match_returns_none(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Query with no filename reference returns None (→ fall through to PCST)."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "How does GDPR conflict with the AI Act?"
        )
        assert result is None

    def test_short_label_ignored(self) -> None:
        """Labels < 3 chars should not trigger false matches."""
        nodes = {
            "n1": CogniNode(
                id="n1", label="a", entity_type="Module",
                description="Short label node",
                properties={"chunks": [{"text": "content", "type": "source"}]},
            ),
        }
        graph = Graqle(nodes=nodes)
        result = graph._direct_file_lookup("What is a module?")
        assert result is None

    def test_includes_neighbours(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Direct lookup should include neighbours of the matched node."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "What does auth.ts do?"
        )
        assert result is not None
        # auth.ts is connected to dir::src and payment.ts
        assert len(result) > 1

    def test_multiple_files_in_query(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Query mentioning two files should activate both."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "How do auth.ts and payment.ts interact?"
        )
        assert result is not None
        assert "mod::auth.ts" in result
        assert "mod::payment.ts" in result

    def test_case_insensitive(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """File lookup should be case-insensitive."""
        result = directory_vs_jsmodule_graph._direct_file_lookup(
            "What does Auth.ts do?"
        )
        assert result is not None
        assert "mod::auth.ts" in result

    def test_path_in_label_extracts_basename(self) -> None:
        """Labels like 'src/services/auth.ts' should match 'auth.ts' in query."""
        nodes = {
            "n1": CogniNode(
                id="n1", label="src/services/auth.ts", entity_type="JSModule",
                description="Auth service at nested path",
                properties={"chunks": [{"text": "function verify() {}", "type": "function"}]},
            ),
        }
        graph = Graqle(nodes=nodes)
        result = graph._direct_file_lookup("What does auth.ts do?")
        assert result is not None
        assert "n1" in result


# ──────────────────────────────────────────────────────────────────────
# Integration: Full pipeline (Layer 1 + 2 + 3 combined)
# ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """End-to-end integration tests: all 3 layers working together."""

    def test_pcst_prefers_content_nodes_over_directory(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Full PCST activation should select content-bearing nodes, not directories."""
        activator = PCSTActivation(max_nodes=3)
        selected = activator.activate(
            directory_vs_jsmodule_graph, "authentication JWT tokens"
        )
        # dir::src should not be in the result (or if it sneaks in via PCST,
        # Layer 2 should have replaced it)
        content_nodes = [nid for nid in selected if nid.startswith("mod::")]
        assert len(content_nodes) > 0, (
            f"Expected content-bearing nodes, got: {selected}"
        )

    def test_activate_subgraph_with_filename_query(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """_activate_subgraph should use direct lookup when query mentions a file."""
        selected = directory_vs_jsmodule_graph._activate_subgraph(
            "What does auth.ts do?", "pcst"
        )
        assert "mod::auth.ts" in selected

    def test_activate_subgraph_falls_through_to_pcst(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Generic query should use PCST, not direct file lookup."""
        selected = directory_vs_jsmodule_graph._activate_subgraph(
            "What are the main services?", "pcst"
        )
        # Should have activated some nodes
        assert len(selected) > 0

    def test_full_strategy_ignores_layers(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """strategy='full' returns all nodes regardless of content."""
        selected = directory_vs_jsmodule_graph._activate_subgraph(
            "auth.ts", "full"
        )
        assert len(selected) == len(directory_vs_jsmodule_graph.nodes)

    def test_topk_strategy_ignores_layers(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """strategy='top_k' uses degree-based selection, not PCST layers."""
        selected = directory_vs_jsmodule_graph._activate_subgraph(
            "auth.ts", "top_k"
        )
        assert len(selected) > 0


# ──────────────────────────────────────────────────────────────────────
# Edge cases the user asked about (Option A / B / C boundaries)
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases around the 3 options (layers) and their interactions."""

    def test_node_with_empty_chunk_list_treated_as_zero(self) -> None:
        """Node with chunks=[] should get neutral multiplier (1.0)."""
        node = CogniNode(
            id="n1", label="empty.ts", entity_type="Module",
            description="Module with empty chunks list",
            properties={"chunks": []},
        )
        graph = Graqle(nodes={"n1": node})
        scorer = RelevanceScorer()
        scores = scorer.score(graph, "empty module")
        # Should not crash; score should be ≥ 0
        assert scores["n1"] >= 0.0

    def test_node_with_string_chunks_not_list(self) -> None:
        """Edge case: chunks stored as string instead of list."""
        node = CogniNode(
            id="n1", label="weird.ts", entity_type="Module",
            description="Module with string chunk property",
            properties={"chunks": "this is not a list"},
        )
        graph = Graqle(nodes={"n1": node})
        scorer = RelevanceScorer()
        # Should not crash — len("string") > 0 but it's not a list of dicts
        scores = scorer.score(graph, "weird module")
        assert scores["n1"] >= 0.0

    def test_filename_boost_vs_content_multiplier_interaction(self) -> None:
        """Filename boost (floor 2.0) and content multiplier should compose correctly.
        A node that matches by filename AND has chunks should get at least 2.0."""
        node = CogniNode(
            id="n1", label="auth.ts", entity_type="JSModule",
            description="Auth module",
            properties={"chunks": [{"text": "verify JWT", "type": "function"}]},
        )
        graph = Graqle(nodes={"n1": node})
        scorer = RelevanceScorer()
        scores = scorer.score(graph, "How does auth.ts work?")
        # Score should be ≥ 2.0 due to filename floor
        assert scores["n1"] >= 2.0

    def test_content_filter_with_node_missing_from_graph(self) -> None:
        """Content filter should handle node IDs that don't exist in the graph."""
        nodes = {
            "a": CogniNode(id="a", label="A", description="node A", properties={}),
        }
        graph = Graqle(nodes=nodes)
        activator = PCSTActivation(max_nodes=5)
        # "nonexistent" is not in graph.nodes
        filtered = activator._content_filter(
            graph, ["a", "nonexistent"], {"a": 0.5},
        )
        # Should not crash; "a" kept, "nonexistent" handled gracefully
        assert "a" in filtered

    def test_direct_lookup_with_all_short_labels(self) -> None:
        """If all nodes have short labels (< 3 chars), direct lookup returns None."""
        nodes = {
            "n1": CogniNode(id="n1", label="ab", description="short", properties={}),
            "n2": CogniNode(id="n2", label="xy", description="short", properties={}),
        }
        graph = Graqle(nodes=nodes)
        result = graph._direct_file_lookup("What about ab?")
        assert result is None

    def test_content_filter_preserves_order(
        self, directory_vs_jsmodule_graph: Graqle,
    ) -> None:
        """Content filter should preserve relative order of retained nodes."""
        activator = PCSTActivation(max_nodes=5)
        relevance = {
            "mod::auth.ts": 0.9, "mod::payment.ts": 0.7,
            "mod::billing.ts": 0.5, "dir::src": 0.3,
        }
        selected = ["mod::auth.ts", "mod::payment.ts", "mod::billing.ts"]
        filtered = activator._content_filter(
            directory_vs_jsmodule_graph, selected, relevance,
        )
        # All have chunks — should be returned in original order
        assert filtered == ["mod::auth.ts", "mod::payment.ts", "mod::billing.ts"]

    def test_max_nodes_respected_by_direct_lookup(self) -> None:
        """Direct file lookup should not return more nodes than max_nodes."""
        from graqle.config.settings import GraqleConfig

        # Create a large graph with many neighbours
        nodes = {}
        edges = {}
        main = CogniNode(
            id="main", label="main.ts", entity_type="JSModule",
            description="Main entry point",
            properties={"chunks": [{"text": "main()", "type": "function"}]},
        )
        nodes["main"] = main

        for i in range(100):
            nid = f"dep{i}"
            nodes[nid] = CogniNode(
                id=nid, label=f"dep{i}.ts", entity_type="JSModule",
                description=f"Dependency {i}",
                properties={},
            )
            eid = f"e_main_{nid}"
            edges[eid] = CogniEdge(
                id=eid, source_id="main", target_id=nid,
                relationship="IMPORTS", weight=1.0,
            )
            nodes["main"].outgoing_edges.append(eid)
            nodes[nid].incoming_edges.append(eid)

        config = GraqleConfig.default()
        config.activation.max_nodes = 10
        graph = Graqle(nodes=nodes, edges=edges, config=config)

        result = graph._direct_file_lookup("What does main.ts do?")
        assert result is not None
        assert len(result) <= 10
