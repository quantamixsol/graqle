"""Tests for graqle.scanner.docs — DocumentScanner orchestrator."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_docs
# risk: HIGH (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, typing, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graqle.scanner.docs import DocScanOptions, DocumentScanner, ScanResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample documents."""
    d = tmp_path / "project"
    d.mkdir()

    # Markdown file
    (d / "README.md").write_text(
        "# My Project\n\nThis uses auth_service.py for authentication.\n\n"
        "## Features\n\nFast and reliable.\n",
        encoding="utf-8",
    )

    # Text file
    (d / "notes.txt").write_text(
        "Design notes\n\nThe payment handler processes transactions.\n"
        "We use validate_token for JWT verification.\n",
        encoding="utf-8",
    )

    # Sub-directory
    sub = d / "docs"
    sub.mkdir()
    (sub / "guide.md").write_text(
        "# User Guide\n\n## Getting Started\n\nInstall with pip.\n\n"
        "## Configuration\n\nEdit config.yaml to set up.\n",
        encoding="utf-8",
    )

    return d


@pytest.fixture
def empty_graph() -> tuple[dict, dict]:
    """Return empty node and edge dicts."""
    return {}, {}


@pytest.fixture
def graph_with_code() -> tuple[dict, dict]:
    """Return graph with pre-existing code nodes."""
    nodes = {
        "auth_service.py": {
            "id": "auth_service.py",
            "label": "AuthService",
            "entity_type": "MODULE",
            "description": "Authentication module",
        },
        "validate_token": {
            "id": "validate_token",
            "label": "validate_token",
            "entity_type": "FUNCTION",
            "description": "JWT token validation",
        },
        "config.yaml": {
            "id": "config.yaml",
            "label": "config.yaml",
            "entity_type": "FILE",
            "description": "App config",
        },
    }
    edges: dict[str, Any] = {}
    return nodes, edges


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / ".graqle-doc-manifest.json"


# ---------------------------------------------------------------------------
# Basic scanning
# ---------------------------------------------------------------------------


class TestBasicScanning:
    def test_scan_directory(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        assert result.files_scanned >= 3
        assert result.nodes_added > 0
        assert result.files_errored == 0

    def test_scan_creates_document_nodes(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        doc_nodes = [n for n in nodes.values() if n["entity_type"] == "DOCUMENT"]
        assert len(doc_nodes) >= 3  # README.md, notes.txt, guide.md

    def test_scan_creates_section_nodes(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        sec_nodes = [n for n in nodes.values() if n["entity_type"] == "SECTION"]
        assert len(sec_nodes) > 0

    def test_scan_creates_section_of_edges(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        section_of_edges = [
            e for e in edges.values() if e["relationship"] == "SECTION_OF"
        ]
        assert len(section_of_edges) > 0

    def test_scan_single_file(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_file(docs_dir / "README.md")

        assert result.files_scanned == 1
        assert result.nodes_added > 0

    def test_scan_result_duration(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)
        assert result.duration_seconds >= 0

    def test_scan_result_total(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)
        assert result.files_total == result.files_scanned + result.files_skipped + result.files_errored


# ---------------------------------------------------------------------------
# Auto-linking
# ---------------------------------------------------------------------------


class TestAutoLinking:
    def test_links_to_code_nodes(self, docs_dir: Path, graph_with_code: tuple) -> None:
        nodes, edges = graph_with_code
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        # Should create REFERENCED_IN edges to code nodes
        ref_edges = [
            e for e in edges.values() if e["relationship"] == "REFERENCED_IN"
        ]
        assert len(ref_edges) > 0

    def test_linking_result_in_scan_result(self, docs_dir: Path, graph_with_code: tuple) -> None:
        nodes, edges = graph_with_code
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        assert result.linking is not None
        assert result.edges_added > 0

    def test_no_links_without_code(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        # No code nodes → no cross-links (only SECTION_OF edges)
        ref_edges = [
            e for e in edges.values() if e["relationship"] == "REFERENCED_IN"
        ]
        assert len(ref_edges) == 0

    def test_linking_disabled(self, docs_dir: Path, graph_with_code: tuple) -> None:
        nodes, edges = graph_with_code
        opts = DocScanOptions(link_exact=False, link_fuzzy=False)
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)

        ref_edges = [
            e for e in edges.values() if e["relationship"] == "REFERENCED_IN"
        ]
        assert len(ref_edges) == 0


# ---------------------------------------------------------------------------
# Incremental scanning
# ---------------------------------------------------------------------------


class TestIncremental:
    def test_second_scan_skips_unchanged(
        self, docs_dir: Path, empty_graph: tuple, manifest_path: Path
    ) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(incremental=True)
        scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

        r1 = scanner.scan_directory(docs_dir)
        assert r1.files_scanned >= 3

        # Second scan: nothing changed
        r2 = scanner.scan_directory(docs_dir)
        assert r2.files_skipped >= 3
        assert r2.files_scanned == 0

    def test_modified_file_rescanned(
        self, docs_dir: Path, empty_graph: tuple, manifest_path: Path
    ) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(incremental=True)
        scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

        scanner.scan_directory(docs_dir)

        # Modify a file
        import time
        time.sleep(0.05)
        (docs_dir / "README.md").write_text("# Updated\n\nNew content.", encoding="utf-8")

        r2 = scanner.scan_directory(docs_dir)
        assert r2.files_scanned >= 1

    def test_stale_files_cleaned(
        self, docs_dir: Path, empty_graph: tuple, manifest_path: Path
    ) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(incremental=True)
        scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

        scanner.scan_directory(docs_dir)
        nodes_before = len(nodes)

        # Delete a file
        (docs_dir / "notes.txt").unlink()

        r2 = scanner.scan_directory(docs_dir)
        assert r2.stale_removed > 0
        assert len(nodes) < nodes_before

    def test_incremental_disabled(
        self, docs_dir: Path, empty_graph: tuple, manifest_path: Path
    ) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(incremental=False)
        scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

        r1 = scanner.scan_directory(docs_dir)
        r2 = scanner.scan_directory(docs_dir)
        # Without incremental, all files are re-scanned
        assert r2.files_scanned >= 3


# ---------------------------------------------------------------------------
# File discovery & filtering
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_skips_hidden_dirs(self, docs_dir: Path, empty_graph: tuple) -> None:
        hidden = docs_dir / ".hidden"
        hidden.mkdir()
        (hidden / "secret.md").write_text("# Secret", encoding="utf-8")

        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        # Should not have scanned the hidden dir
        assert not any("secret.md" in r.path for r in result.file_results)

    def test_skips_node_modules(self, docs_dir: Path, empty_graph: tuple) -> None:
        nm = docs_dir / "node_modules"
        nm.mkdir()
        (nm / "package.md").write_text("# Package", encoding="utf-8")

        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)
        assert not any("package.md" in r.path for r in result.file_results)

    def test_exclude_extensions(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(exclude_extensions=[".txt"])
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)

        txt_results = [r for r in result.file_results if r.path.endswith(".txt")]
        assert len(txt_results) == 0

    def test_exclude_patterns(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(exclude_patterns=["docs/*"])
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)

        guide_results = [r for r in result.file_results if "guide" in r.path]
        assert len(guide_results) == 0

    def test_max_file_size(self, docs_dir: Path, empty_graph: tuple) -> None:
        # Create a file larger than the limit
        big = docs_dir / "big.md"
        big.write_text("x" * 1000, encoding="utf-8")

        nodes, edges = empty_graph
        opts = DocScanOptions(max_file_size_mb=0.0001)  # ~100 bytes
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)

        big_results = [r for r in result.file_results if "big" in r.path]
        assert len(big_results) == 0

    def test_unsupported_extension_ignored(self, docs_dir: Path, empty_graph: tuple) -> None:
        (docs_dir / "image.png").write_bytes(b"\x89PNG")
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(docs_dir)

        png_results = [r for r in result.file_results if "image.png" in r.path]
        assert len(png_results) == 0


# ---------------------------------------------------------------------------
# Budget controls
# ---------------------------------------------------------------------------


class TestBudget:
    def test_max_files_limit(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(max_files=1)
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)
        assert result.files_scanned <= 1

    def test_max_nodes_limit(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        opts = DocScanOptions(max_nodes=2)
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(docs_dir)
        # After the first file creates > 2 nodes, scanning stops
        assert result.nodes_added <= 10  # relaxed — budget is checked between files


# ---------------------------------------------------------------------------
# Redaction integration
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redacts_secrets(self, tmp_path: Path, empty_graph: tuple) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        (d / "config.md").write_text(
            "# Config\n\nAPI_KEY=AKIAIOSFODNN7EXAMPLE\npassword=hunter2\n",
            encoding="utf-8",
        )

        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(d)

        # Find the document node
        doc_nodes = [n for n in nodes.values() if n["entity_type"] == "DOCUMENT"]
        assert len(doc_nodes) == 1
        desc = doc_nodes[0]["description"]
        assert "AKIAIOSFODNN7EXAMPLE" not in desc
        assert "hunter2" not in desc

    def test_redaction_disabled(self, tmp_path: Path, empty_graph: tuple) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        (d / "config.md").write_text(
            "# Config\n\npassword=hunter2\n",
            encoding="utf-8",
        )

        nodes, edges = empty_graph
        opts = DocScanOptions(redaction_enabled=False)
        scanner = DocumentScanner(nodes, edges, options=opts)
        scanner.scan_directory(d)

        doc_nodes = [n for n in nodes.values() if n["entity_type"] == "DOCUMENT"]
        assert len(doc_nodes) == 1
        desc = doc_nodes[0]["description"]
        assert "hunter2" in desc


# ---------------------------------------------------------------------------
# Node structure validation
# ---------------------------------------------------------------------------


class TestNodeStructure:
    def test_document_node_properties(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        doc_nodes = [n for n in nodes.values() if n["entity_type"] == "DOCUMENT"]
        for node in doc_nodes:
            assert "id" in node
            assert "label" in node
            assert "entity_type" in node
            assert "description" in node
            assert "properties" in node
            props = node["properties"]
            assert "path" in props
            assert "format" in props
            assert "title" in props

    def test_section_node_properties(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        sec_nodes = [n for n in nodes.values() if n["entity_type"] == "SECTION"]
        for node in sec_nodes:
            assert "id" in node
            props = node["properties"]
            assert "level" in props
            assert "section_type" in props

    def test_doc_id_format(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(docs_dir)

        for nid in nodes:
            if nodes[nid]["entity_type"] == "DOCUMENT":
                assert nid.startswith("doc::")
            elif nodes[nid]["entity_type"] == "SECTION":
                assert nid.startswith("sec::")


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


class TestProgressCallback:
    def test_callback_called(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)

        calls: list[tuple] = []
        def cb(path: Path, idx: int, total: int) -> None:
            calls.append((str(path), idx, total))

        scanner.scan_directory(docs_dir, progress_callback=cb)
        assert len(calls) >= 3
        for _, idx, total in calls:
            assert 0 <= idx < total

    def test_callback_with_scan_files(self, docs_dir: Path, empty_graph: tuple) -> None:
        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)

        calls: list = []
        scanner.scan_files(
            [docs_dir / "README.md"],
            docs_dir,
            progress_callback=lambda p, i, t: calls.append(i),
        )
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_unsupported_format_error(self, tmp_path: Path, empty_graph: tuple) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        (d / "data.csv").write_text("a,b,c\n1,2,3", encoding="utf-8")

        nodes, edges = empty_graph
        # Force .csv into extensions
        opts = DocScanOptions(extensions=[".csv"])
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(d)

        assert result.files_errored >= 1 or result.files_skipped >= 1

    def test_empty_directory(self, tmp_path: Path, empty_graph: tuple) -> None:
        d = tmp_path / "empty"
        d.mkdir()

        nodes, edges = empty_graph
        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(d)

        assert result.files_scanned == 0
        assert result.nodes_added == 0


# ---------------------------------------------------------------------------
# DocScanOptions defaults
# ---------------------------------------------------------------------------


class TestDocScanOptions:
    def test_defaults(self) -> None:
        opts = DocScanOptions()
        assert opts.max_file_size_mb == 50.0
        assert opts.chunk_max_chars == 1500
        assert opts.link_exact is True
        assert opts.link_fuzzy is True
        assert opts.link_semantic is False
        assert opts.redaction_enabled is True
        assert opts.incremental is True
        assert opts.max_nodes == 0
        assert opts.max_files == 0

    def test_custom_options(self) -> None:
        opts = DocScanOptions(
            max_file_size_mb=10.0,
            link_fuzzy=False,
            max_files=5,
        )
        assert opts.max_file_size_mb == 10.0
        assert opts.link_fuzzy is False
        assert opts.max_files == 5
