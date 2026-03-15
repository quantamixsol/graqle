"""Tests for graqle.scanner.manifest — incremental scan tracking."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_manifest
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, os, time, pathlib +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from graqle.scanner.manifest import FileEntry, ScanManifest, _sha256_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    """Return path to a non-existent manifest file in a temp dir."""
    return tmp_path / ".graqle-doc-manifest.json"


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    """Create a small sample file for testing."""
    p = tmp_path / "docs" / "readme.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Hello\n\nSome content.", encoding="utf-8")
    return p


@pytest.fixture
def sample_file_b(tmp_path: Path) -> Path:
    """Create a second sample file."""
    p = tmp_path / "docs" / "guide.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("Guide content here.", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Construction / loading
# ---------------------------------------------------------------------------


class TestManifestConstruction:
    def test_empty_manifest(self, tmp_manifest: Path) -> None:
        m = ScanManifest(tmp_manifest)
        assert m.file_count() == 0
        assert m.total_nodes() == 0
        assert m.entries == {}

    def test_load_existing(self, tmp_manifest: Path) -> None:
        # Pre-populate a manifest file
        data = {
            "docs/readme.md": {
                "mtime": 100.0,
                "size": 42,
                "sha256": "abc123",
                "scanned_at": 200.0,
                "node_ids": ["doc::docs/readme.md"],
                "format": "markdown",
                "parse_errors": [],
            }
        }
        tmp_manifest.write_text(json.dumps(data), encoding="utf-8")
        m = ScanManifest(tmp_manifest)
        assert m.file_count() == 1
        assert m.has_entry("docs/readme.md")

    def test_corrupt_manifest_resets(self, tmp_manifest: Path) -> None:
        tmp_manifest.write_text("not json!", encoding="utf-8")
        m = ScanManifest(tmp_manifest)
        assert m.file_count() == 0


# ---------------------------------------------------------------------------
# needs_scan
# ---------------------------------------------------------------------------


class TestNeedsScan:
    def test_new_file_needs_scan(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        assert m.needs_scan("docs/readme.md", sample_file) is True

    def test_unchanged_file_skipped(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["doc::docs/readme.md"])
        assert m.needs_scan("docs/readme.md", sample_file) is False

    def test_modified_file_needs_scan(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        # Modify file
        time.sleep(0.05)
        sample_file.write_text("# Changed content!", encoding="utf-8")
        assert m.needs_scan("docs/readme.md", sample_file) is True

    def test_deleted_file_needs_scan(self, tmp_manifest: Path, tmp_path: Path) -> None:
        m = ScanManifest(tmp_manifest)
        ghost = tmp_path / "ghost.md"
        assert m.needs_scan("ghost.md", ghost) is True


# ---------------------------------------------------------------------------
# update / get_entry
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_creates_entry(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        entry = m.update(
            "docs/readme.md", sample_file,
            node_ids=["doc::docs/readme.md", "sec::docs/readme.md::Hello"],
            fmt="markdown",
        )
        assert isinstance(entry, FileEntry)
        assert entry.format == "markdown"
        assert len(entry.node_ids) == 2
        assert entry.sha256  # non-empty
        assert entry.scanned_at > 0

    def test_update_overwrites(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        m.update("docs/readme.md", sample_file, node_ids=["n1", "n2", "n3"])
        entry = m.get_entry("docs/readme.md")
        assert entry is not None
        assert len(entry.node_ids) == 3

    def test_get_entry_missing(self, tmp_manifest: Path) -> None:
        m = ScanManifest(tmp_manifest)
        assert m.get_entry("nonexistent.md") is None


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_reload(self, tmp_manifest: Path, sample_file: Path) -> None:
        m1 = ScanManifest(tmp_manifest)
        m1.update("docs/readme.md", sample_file, node_ids=["n1", "n2"], fmt="markdown")
        m1.save()

        m2 = ScanManifest(tmp_manifest)
        assert m2.file_count() == 1
        entry = m2.get_entry("docs/readme.md")
        assert entry is not None
        assert entry.node_ids == ["n1", "n2"]
        assert entry.format == "markdown"

    def test_save_creates_parent_dirs(self, tmp_path: Path, sample_file: Path) -> None:
        deep = tmp_path / "a" / "b" / "manifest.json"
        m = ScanManifest(deep)
        m.update("x.md", sample_file, node_ids=["n1"])
        m.save()
        assert deep.is_file()


# ---------------------------------------------------------------------------
# remove / remove_stale
# ---------------------------------------------------------------------------


class TestRemoval:
    def test_remove_entry(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        removed = m.remove("docs/readme.md")
        assert removed is not None
        assert removed.node_ids == ["n1"]
        assert m.file_count() == 0

    def test_remove_missing(self, tmp_manifest: Path) -> None:
        m = ScanManifest(tmp_manifest)
        assert m.remove("nope") is None

    def test_remove_stale(self, tmp_path: Path, tmp_manifest: Path) -> None:
        # Create two files, scan them, then delete one
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text("A", encoding="utf-8")
        f2.write_text("B", encoding="utf-8")

        m = ScanManifest(tmp_manifest)
        m.update("a.md", f1, node_ids=["n1"])
        m.update("b.md", f2, node_ids=["n2", "n3"])

        # Delete b.md
        f2.unlink()

        stale = m.remove_stale(tmp_path)
        assert "b.md" in stale
        assert stale["b.md"] == ["n2", "n3"]
        assert m.file_count() == 1  # only a.md remains
        assert "a.md" not in stale

    def test_remove_stale_empty(self, tmp_path: Path, tmp_manifest: Path) -> None:
        m = ScanManifest(tmp_manifest)
        stale = m.remove_stale(tmp_path)
        assert stale == {}


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


class TestCounters:
    def test_file_count(self, tmp_manifest: Path, sample_file: Path, sample_file_b: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        m.update("docs/guide.txt", sample_file_b, node_ids=["n2", "n3"])
        assert m.file_count() == 2

    def test_total_nodes(self, tmp_manifest: Path, sample_file: Path, sample_file_b: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        m.update("docs/guide.txt", sample_file_b, node_ids=["n2", "n3"])
        assert m.total_nodes() == 3

    def test_clear(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update("docs/readme.md", sample_file, node_ids=["n1"])
        m.clear()
        assert m.file_count() == 0


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------


class TestSha256:
    def test_sha256_file(self, sample_file: Path) -> None:
        h = _sha256_file(sample_file)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_sha256_deterministic(self, sample_file: Path) -> None:
        assert _sha256_file(sample_file) == _sha256_file(sample_file)

    def test_sha256_changes_on_modify(self, sample_file: Path) -> None:
        h1 = _sha256_file(sample_file)
        sample_file.write_text("different content", encoding="utf-8")
        h2 = _sha256_file(sample_file)
        assert h1 != h2


# ---------------------------------------------------------------------------
# Parse errors tracking
# ---------------------------------------------------------------------------


class TestParseErrors:
    def test_parse_errors_stored(self, tmp_manifest: Path, sample_file: Path) -> None:
        m = ScanManifest(tmp_manifest)
        m.update(
            "docs/readme.md", sample_file,
            node_ids=["n1"],
            parse_errors=["warn1", "warn2"],
        )
        entry = m.get_entry("docs/readme.md")
        assert entry is not None
        assert entry.parse_errors == ["warn1", "warn2"]

    def test_parse_errors_persist(self, tmp_manifest: Path, sample_file: Path) -> None:
        m1 = ScanManifest(tmp_manifest)
        m1.update("x.md", sample_file, node_ids=[], parse_errors=["e1"])
        m1.save()

        m2 = ScanManifest(tmp_manifest)
        entry = m2.get_entry("x.md")
        assert entry is not None
        assert entry.parse_errors == ["e1"]
