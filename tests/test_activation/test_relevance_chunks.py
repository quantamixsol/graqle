"""Tests for chunk-aware scoring enhancement (Bug 1 fix).

Verifies that _build_embedding_text() prioritizes function/class chunks
and uses 500 chars from top 5 chunks (was 200 chars from top 3).
"""

from unittest.mock import MagicMock

import pytest

from graqle.activation.relevance import RelevanceScorer


def _make_node(label: str, entity_type: str, description: str, chunks=None):
    """Create a mock node with optional chunks."""
    node = MagicMock()
    node.label = label
    node.entity_type = entity_type
    node.description = description
    node.properties = {"chunks": chunks or []}
    return node


class TestChunkAwareEmbeddingText:
    """Tests for _build_embedding_text with chunk prioritization."""

    def test_function_chunks_prioritized_over_generic(self):
        """Function/class chunks should appear before generic chunks."""
        scorer = RelevanceScorer(chunk_aware=True)
        node = _make_node("Products.tsx", "FILE", "React component", chunks=[
            {"type": "header", "text": "// Header comment about the file"},
            {"type": "function", "text": "export function ProductList({ items }) { return items.map(i => <Card key={i.id} />); }"},
            {"type": "import", "text": "import React from 'react';"},
            {"type": "class", "text": "class ProductService { async fetchAll() { return await api.get('/products'); } }"},
        ])
        text = scorer._build_embedding_text(node)
        # Function and class chunks should appear before header/import
        func_pos = text.find("ProductList")
        class_pos = text.find("ProductService")
        header_pos = text.find("Header comment")
        assert func_pos < header_pos, "Function chunk should come before header"
        assert class_pos < header_pos, "Class chunk should come before header"

    def test_uses_500_chars_per_chunk(self):
        """Each chunk should use up to 500 characters (was 200)."""
        scorer = RelevanceScorer(chunk_aware=True)
        long_text = "x" * 600  # Longer than 500
        node = _make_node("file.py", "FILE", "desc", chunks=[
            {"type": "function", "text": long_text},
        ])
        text = scorer._build_embedding_text(node)
        # Should contain exactly 500 x's from the chunk (truncated)
        assert "x" * 500 in text
        assert "x" * 501 not in text

    def test_uses_up_to_5_chunks(self):
        """Should use top 5 chunks (was 3)."""
        scorer = RelevanceScorer(chunk_aware=True)
        chunks = [
            {"type": "function", "text": f"function_{i}"} for i in range(7)
        ]
        node = _make_node("file.py", "FILE", "desc", chunks=chunks)
        text = scorer._build_embedding_text(node)
        # First 5 should be included
        for i in range(5):
            assert f"function_{i}" in text
        # 6th and 7th should NOT be included
        assert "function_5" not in text
        assert "function_6" not in text

    def test_method_and_export_chunks_prioritized(self):
        """method and export types should also be prioritized."""
        scorer = RelevanceScorer(chunk_aware=True)
        node = _make_node("api.ts", "FILE", "API module", chunks=[
            {"type": "comment", "text": "generic comment"},
            {"type": "method", "text": "async handleRequest(req) {}"},
            {"type": "export", "text": "export default router"},
        ])
        text = scorer._build_embedding_text(node)
        method_pos = text.find("handleRequest")
        export_pos = text.find("export default")
        comment_pos = text.find("generic comment")
        assert method_pos < comment_pos
        assert export_pos < comment_pos

    def test_string_chunks_handled(self):
        """Plain string chunks (non-dict) should still work."""
        scorer = RelevanceScorer(chunk_aware=True)
        node = _make_node("file.py", "FILE", "desc", chunks=[
            "plain string chunk one",
            "plain string chunk two",
        ])
        text = scorer._build_embedding_text(node)
        assert "plain string chunk one" in text
        assert "plain string chunk two" in text

    def test_empty_chunks_skipped(self):
        """Empty or whitespace-only chunks should be skipped."""
        scorer = RelevanceScorer(chunk_aware=True)
        node = _make_node("file.py", "FILE", "desc", chunks=[
            {"type": "function", "text": ""},
            {"type": "function", "text": "real content"},
            "",
        ])
        text = scorer._build_embedding_text(node)
        assert "real content" in text

    def test_chunk_aware_false_ignores_chunks(self):
        """When chunk_aware=False, chunks should not appear."""
        scorer = RelevanceScorer(chunk_aware=False)
        node = _make_node("file.py", "FILE", "description only", chunks=[
            {"type": "function", "text": "should not appear"},
        ])
        text = scorer._build_embedding_text(node)
        assert "should not appear" not in text
        assert "description only" in text

    def test_function_node_scores_higher_for_function_query(self):
        """A node with function chunks should produce text containing
        the function name, making it more relevant for function queries."""
        scorer = RelevanceScorer(chunk_aware=True)

        # Node with function chunks
        func_node = _make_node("Products.tsx", "FILE", "Product components", chunks=[
            {"type": "function", "text": "export function ProductList({ items }) { return <div>{items.map(...)}</div> }"},
            {"type": "function", "text": "export function ProductCard({ product }) { return <Card>{product.name}</Card> }"},
        ])

        # Node with only config/description
        config_node = _make_node("tailwind.config.ts", "FILE", "Tailwind CSS configuration", chunks=[
            {"type": "config", "text": "module.exports = { content: ['./src/**/*.tsx'], theme: { extend: {} } }"},
        ])

        func_text = scorer._build_embedding_text(func_node)
        config_text = scorer._build_embedding_text(config_node)

        # The function node's text should contain ProductList
        assert "ProductList" in func_text
        assert "ProductList" not in config_text
