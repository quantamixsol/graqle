"""Tests for the chunk pipeline — ensuring chunks flow from source files to reasoning agents.

This is the CRITICAL test suite that validates the full evidence chain:
  source_file → auto_load_chunks → node.properties["chunks"] → _build_evidence_text → prompt

Bug 14 (P0): Chunks missing at reasoning time — root cause was:
  1. source_file vs file_path key mismatch
  2. No auto-chunk loading for hand-built KGs
  3. to_networkx() returning stale cached graph without chunks
"""

# ── graqle:intelligence ──
# module: tests.test_core.test_chunk_pipeline
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, graph, node
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.core.graph import Graqle
from graqle.core.node import CogniNode


@pytest.fixture
def py_source(tmp_path: Path) -> Path:
    """Create a sample Python file for chunk testing."""
    f = tmp_path / "sample.py"
    f.write_text(
        '"""Sample module."""\n\n'
        "def hello():\n"
        '    """Say hello."""\n'
        '    return "hello"\n\n'
        "class Widget:\n"
        '    """A widget."""\n'
        "    def run(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def md_source(tmp_path: Path) -> Path:
    """Create a sample markdown file for chunk testing."""
    f = tmp_path / "notes.md"
    f.write_text("# Project Notes\n\nThis is the project context.\n", encoding="utf-8")
    return f


class TestAutoLoadChunks:
    """Verify that _auto_load_chunks fills in missing chunks from source files."""

    def test_loads_chunks_from_source_file(self, py_source: Path) -> None:
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source)},
        )
        graph = Graqle(nodes={"mod::sample": node})
        chunks = graph.nodes["mod::sample"].properties.get("chunks", [])
        assert len(chunks) > 0, "Auto-load should have created chunks"
        # Verify chunk content is from the file
        all_text = " ".join(c["text"] for c in chunks)
        assert "hello" in all_text

    def test_loads_chunks_from_file_path(self, py_source: Path) -> None:
        """file_path should also trigger auto-loading."""
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"file_path": str(py_source)},
        )
        graph = Graqle(nodes={"mod::sample": node})
        chunks = graph.nodes["mod::sample"].properties.get("chunks", [])
        assert len(chunks) > 0

    def test_skips_nodes_with_existing_chunks(self, py_source: Path) -> None:
        """If chunks already exist, auto-load should not overwrite them."""
        existing = [{"text": "existing evidence", "type": "manual"}]
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source), "chunks": existing},
        )
        graph = Graqle(nodes={"mod::sample": node})
        chunks = graph.nodes["mod::sample"].properties["chunks"]
        assert chunks == existing

    def test_handles_nonexistent_file(self) -> None:
        """Should not crash when source file doesn't exist."""
        node = CogniNode(
            id="mod::gone",
            label="gone.py",
            entity_type="Module",
            description="Missing file",
            properties={"source_file": "/nonexistent/path.py"},
        )
        graph = Graqle(nodes={"mod::gone": node})
        chunks = graph.nodes["mod::gone"].properties.get("chunks", [])
        assert chunks == []

    def test_markdown_becomes_single_chunk(self, md_source: Path) -> None:
        node = CogniNode(
            id="doc::notes",
            label="notes.md",
            entity_type="Document",
            description="Project notes",
            properties={"source_file": str(md_source)},
        )
        graph = Graqle(nodes={"doc::notes": node})
        chunks = graph.nodes["doc::notes"].properties.get("chunks", [])
        assert len(chunks) == 1
        assert "Project Notes" in chunks[0]["text"]


class TestRebuildChunks:
    """Verify that rebuild_chunks can force-refresh chunks."""

    def test_rebuild_fills_missing(self, py_source: Path) -> None:
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source)},
        )
        graph = Graqle(nodes={"mod::sample": node})
        # Chunks should already exist from auto-load
        assert graph.nodes["mod::sample"].properties.get("chunks")

        # Clear chunks and rebuild
        graph.nodes["mod::sample"].properties.pop("chunks", None)
        updated = graph.rebuild_chunks()
        assert updated == 1
        assert graph.nodes["mod::sample"].properties.get("chunks")

    def test_rebuild_force_overwrites(self, py_source: Path) -> None:
        old_chunks = [{"text": "old", "type": "manual"}]
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source), "chunks": old_chunks},
        )
        graph = Graqle(nodes={"mod::sample": node})
        updated = graph.rebuild_chunks(force=True)
        assert updated == 1
        new_chunks = graph.nodes["mod::sample"].properties["chunks"]
        assert new_chunks != old_chunks
        assert any("hello" in c["text"] for c in new_chunks)


class TestChunkSourceCode:
    """Verify the static _chunk_source_code method."""

    def test_splits_on_functions(self) -> None:
        code = (
            '"""Module doc."""\n\n'
            "def foo():\n    pass\n\n"
            "def bar():\n    pass\n"
        )
        chunks = Graqle._chunk_source_code(code)
        assert len(chunks) >= 2
        types = [c["type"] for c in chunks]
        assert "function" in types

    def test_splits_on_classes(self) -> None:
        code = "class MyClass:\n    def method(self):\n        pass\n"
        chunks = Graqle._chunk_source_code(code)
        assert any(c["type"] == "class" for c in chunks)

    def test_respects_max_chunks(self) -> None:
        code = "\n\n".join(f"def func_{i}():\n    pass" for i in range(20))
        chunks = Graqle._chunk_source_code(code, max_chunks=3)
        assert len(chunks) <= 3

    def test_empty_content(self) -> None:
        chunks = Graqle._chunk_source_code("")
        assert chunks == []

    def test_no_definitions_returns_single_chunk(self) -> None:
        code = "x = 1\ny = 2\nprint(x + y)\n"
        chunks = Graqle._chunk_source_code(code)
        assert len(chunks) == 1
        assert chunks[0]["type"] in ("source", "module_header")


class TestToNetworkxFreshness:
    """Verify to_networkx() reflects runtime mutations (chunks, enrichment)."""

    def test_includes_auto_loaded_chunks(self, py_source: Path) -> None:
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source)},
        )
        graph = Graqle(nodes={"mod::sample": node})
        G = graph.to_networkx()
        nx_chunks = G.nodes["mod::sample"].get("chunks", [])
        assert len(nx_chunks) > 0, "to_networkx must include auto-loaded chunks"

    def test_reflects_rebuild(self, py_source: Path) -> None:
        node = CogniNode(
            id="mod::sample",
            label="sample.py",
            entity_type="Module",
            description="A sample module",
            properties={"source_file": str(py_source)},
        )
        graph = Graqle(nodes={"mod::sample": node})
        # Clear and rebuild
        graph.nodes["mod::sample"].properties.pop("chunks", None)
        graph.rebuild_chunks(force=True)
        G = graph.to_networkx()
        nx_chunks = G.nodes["mod::sample"].get("chunks", [])
        assert len(nx_chunks) > 0


class TestBuildEvidenceText:
    """Verify CogniNode._build_evidence_text finds chunks via all paths."""

    def test_from_chunks_property(self) -> None:
        node = CogniNode(
            id="n1", label="test", description="test node",
            properties={"chunks": [{"text": "evidence here", "type": "test"}]},
        )
        text = node._build_evidence_text("query")
        assert "evidence here" in text

    def test_from_source_file_fallback(self, py_source: Path) -> None:
        node = CogniNode(
            id="n1", label="test", description="test node",
            properties={"source_file": str(py_source)},
        )
        text = node._build_evidence_text("query")
        assert "hello" in text

    def test_from_file_path_fallback(self, py_source: Path) -> None:
        node = CogniNode(
            id="n1", label="test", description="test node",
            properties={"file_path": str(py_source)},
        )
        text = node._build_evidence_text("query")
        assert "hello" in text

    def test_empty_when_no_source(self) -> None:
        node = CogniNode(
            id="n1", label="test", description="test node",
            properties={},
        )
        text = node._build_evidence_text("query")
        assert text == ""
