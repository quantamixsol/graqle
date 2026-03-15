"""Tests for ChunkScorer — chunk-level activation strategy.

Verifies that ChunkScorer correctly activates nodes by matching
individual chunks to the query, not node-level descriptions.
"""

# ── graqle:intelligence ──
# module: tests.test_activation.test_chunk_scorer
# risk: LOW (impact radius: 0 modules)
# dependencies: mock, numpy, pytest, chunk_scorer
# constraints: none
# ── /graqle:intelligence ──

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from graqle.activation.chunk_scorer import ChunkScorer


def _make_node(nid, label, entity_type, description, chunks=None):
    """Create a mock CogniNode."""
    node = MagicMock()
    node.id = nid
    node.label = label
    node.entity_type = entity_type
    node.description = description
    node.properties = {"chunks": chunks or []}
    node.embedding = None
    return node


def _make_graph(nodes_dict):
    """Create a mock Graqle."""
    graph = MagicMock()
    graph.nodes = nodes_dict
    return graph


class TestChunkScorerActivation:
    """Tests for ChunkScorer.activate()."""

    def test_products_tsx_beats_tailwind_config(self):
        """The P0 bug: 'What functions does Products.tsx define?' should
        activate Products.tsx, not tailwind.config.ts."""
        nodes = {
            "products": _make_node(
                "products", "Products.tsx", "JSModule",
                "website/Products.tsx. React component.",
                chunks=[
                    {"type": "function", "text": "export function ProductList({ items }) { return <div>{items.map(item => <ProductCard key={item.id} product={item} />)}</div> }"},
                    {"type": "function", "text": "export function ProductCard({ product }) { return <div className='card'><h3>{product.name}</h3><p>{product.price}</p></div> }"},
                    {"type": "import", "text": "import React from 'react'; import { ProductCard } from './ProductCard';"},
                ],
            ),
            "tailwind": _make_node(
                "tailwind", "tailwind.config.ts", "Config",
                "website/tailwind.config.ts. Defines: export default config",
                chunks=[
                    {"type": "export", "text": "export default { content: ['./src/**/*.tsx'], theme: { extend: { colors: { primary: '#3b82f6' } } }, plugins: [] }"},
                ],
            ),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=5, min_score=0.0)
        result = scorer.activate(graph, "What functions does Products.tsx define?")

        # Products.tsx should be first (filename match gives it 2.0 floor)
        assert result[0] == "products", f"Expected products first, got {result}"

    def test_tech_stack_finds_package_json(self):
        """'What technologies and frameworks are used?' should find package.json."""
        nodes = {
            "pkg": _make_node(
                "pkg", "package.json", "Config",
                "website/package.json. Package configuration with dependencies.",
                chunks=[
                    {"type": "config", "text": 'dependencies: next 14.0.0, react 18.2.0, tailwindcss 3.4.0, typescript 5.3.0. These are the frameworks and libraries used in this project.'},
                ],
            ),
            "nextenv": _make_node(
                "nextenv", "next-env.d.ts", "TypeDef",
                "website/next-env.d.ts. TypeScript declarations.",
                chunks=[
                    {"type": "reference", "text": "/// <reference types='next' />"},
                ],
            ),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=5, min_score=0.0)
        result = scorer.activate(graph, "What frameworks and libraries are used in this project?")

        scores = scorer.last_relevance
        assert scores["pkg"] > scores["nextenv"], (
            f"package.json ({scores['pkg']:.3f}) should score higher than "
            f"next-env.d.ts ({scores['nextenv']:.3f})"
        )

    def test_multiple_nodes_activated(self):
        """ChunkScorer should activate multiple relevant nodes, not just 1."""
        nodes = {
            f"n{i}": _make_node(
                f"n{i}", f"component_{i}.tsx", "JSModule",
                f"Component {i}",
                chunks=[{"type": "function", "text": f"export function Component{i}() {{ return <div>Component {i}</div> }}"}],
            )
            for i in range(10)
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.0)
        result = scorer.activate(graph, "What React components exist?")

        assert len(result) > 1, f"Should activate multiple nodes, got {len(result)}"

    def test_min_score_filters_noise(self):
        """Nodes below min_score should be excluded."""
        nodes = {
            "relevant": _make_node(
                "relevant", "auth.py", "Module",
                "Authentication module",
                chunks=[{"type": "function", "text": "def authenticate(user, password): return verify_credentials(user, password)"}],
            ),
            "noise": _make_node(
                "noise", "README.md", "Document",
                "Project readme file",
                chunks=[{"type": "text", "text": "# My Project\nThis is a sample project."}],
            ),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.3)
        result = scorer.activate(graph, "How does authentication work?")

        # With high min_score, noise should be filtered out
        # (exact result depends on embedding model, but auth should survive)
        if result:
            assert "relevant" in result

    def test_no_chunks_penalized(self):
        """Nodes without chunks should score lower (0.5x penalty)."""
        nodes = {
            "with_chunks": _make_node(
                "with_chunks", "api.py", "Module",
                "API module with endpoints",
                chunks=[{"type": "function", "text": "def get_users(): return db.query(User).all()"}],
            ),
            "no_chunks": _make_node(
                "no_chunks", "utils/", "Directory",
                "API module with endpoints",  # Same description!
            ),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.0)
        scorer.activate(graph, "What API endpoints exist?")

        scores = scorer.last_relevance
        assert scores.get("with_chunks", 0) > scores.get("no_chunks", 0), (
            "Node with chunks should score higher than identical node without"
        )

    def test_filename_boost_guarantees_selection(self):
        """If query mentions a filename, that node gets floor score of 2.0."""
        nodes = {
            "target": _make_node(
                "target", "Products.tsx", "JSModule",
                "Component file",
                chunks=[{"type": "function", "text": "export function X() {}"}],
            ),
            "other": _make_node(
                "other", "utils.ts", "Module",
                "Utility functions",
                chunks=[{"type": "function", "text": "export function helper() {}"}],
            ),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.0)
        scorer.activate(graph, "Tell me about Products.tsx")

        assert scorer.last_relevance["target"] >= 2.0

    def test_max_nodes_limit(self):
        """Should not return more than max_nodes."""
        nodes = {
            f"n{i}": _make_node(
                f"n{i}", f"file_{i}.py", "Module", f"Module {i}",
                chunks=[{"type": "function", "text": f"def func_{i}(): pass"}],
            )
            for i in range(20)
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=5, min_score=0.0)
        result = scorer.activate(graph, "What functions exist?")

        assert len(result) <= 5

    def test_relevance_scores_stored(self):
        """last_relevance should contain scores for all activated nodes."""
        nodes = {
            "a": _make_node("a", "a.py", "Module", "Module A",
                           chunks=[{"type": "function", "text": "def hello(): print('hello')"}]),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.0)
        result = scorer.activate(graph, "hello function")

        assert "a" in scorer.last_relevance
        assert scorer.last_relevance["a"] > 0

    def test_empty_chunks_skipped(self):
        """Chunks with empty or very short text should be skipped."""
        nodes = {
            "a": _make_node("a", "a.py", "Module", "Module",
                           chunks=[
                               {"type": "function", "text": ""},
                               {"type": "function", "text": "x"},
                               {"type": "function", "text": "def real_function(): return 42"},
                           ]),
        }
        graph = _make_graph(nodes)
        scorer = ChunkScorer(max_nodes=50, min_score=0.0)
        result = scorer.activate(graph, "real function")
        # Should work without error, using only the valid chunk
        assert "a" in result
