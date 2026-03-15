"""Integration tests: scan → learn doc → query → verify document nodes surface.

Tests the full chain from document scanning through to graph querying,
ensuring document nodes integrate properly with existing code nodes.
"""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_doc_chain
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, typing, pytest +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graqle.scanner.docs import DocScanOptions, DocumentScanner, ScanResult
from graqle.scanner.linker import AutoLinker
from graqle.scanner.manifest import ScanManifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a realistic mini project with code + docs."""
    root = tmp_path / "myproject"
    root.mkdir()

    # Code-like nodes (simulate what graq scan repo would produce)
    # We represent these as pre-existing graph nodes

    # Documents
    docs = root / "docs"
    docs.mkdir()

    (docs / "architecture.md").write_text(
        "# Architecture\n\n"
        "## Auth Layer\n\n"
        "The auth_service handles JWT authentication via validate_token().\n"
        "All API requests pass through the auth middleware.\n\n"
        "## Database\n\n"
        "PostgreSQL is the primary store. The db_pool manages connections.\n\n"
        "## API Gateway\n\n"
        "Routes are defined in routes.py and handled by api_handler.\n",
        encoding="utf-8",
    )

    (docs / "adr-001-jwt.md").write_text(
        "---\n"
        "title: Use JWT for Authentication\n"
        "status: accepted\n"
        "date: 2026-01-15\n"
        "---\n\n"
        "# ADR-001: Use JWT for Authentication\n\n"
        "## Context\n\n"
        "We need stateless authentication for the API.\n\n"
        "## Decision\n\n"
        "Use JWT tokens with RS256 signing. The auth_service.py module\n"
        "implements token generation and validate_token() handles verification.\n\n"
        "## Consequences\n\n"
        "Stateless auth reduces database load but requires token rotation.\n",
        encoding="utf-8",
    )

    (docs / "runbook.txt").write_text(
        "Deployment Runbook\n\n"
        "Step 1: Run tests with pytest\n"
        "Step 2: Build Docker image\n"
        "Step 3: Deploy to staging via deploy_service\n"
        "Step 4: Run smoke tests against api_handler\n"
        "Step 5: Promote to production\n",
        encoding="utf-8",
    )

    (root / "README.md").write_text(
        "# MyProject\n\n"
        "A production API service.\n\n"
        "## Quick Start\n\n"
        "Run `pip install -e .` then `python -m myproject`.\n",
        encoding="utf-8",
    )

    return root


@pytest.fixture
def code_nodes() -> dict[str, dict[str, Any]]:
    """Pre-existing code nodes (simulating graq scan repo output)."""
    return {
        "auth_service.py": {
            "id": "auth_service.py",
            "label": "auth_service",
            "entity_type": "MODULE",
            "description": "Authentication service module",
        },
        "validate_token": {
            "id": "validate_token",
            "label": "validate_token",
            "entity_type": "FUNCTION",
            "description": "JWT token validation function",
        },
        "db_pool": {
            "id": "db_pool",
            "label": "db_pool",
            "entity_type": "SERVICE",
            "description": "Database connection pool",
        },
        "routes.py": {
            "id": "routes.py",
            "label": "routes",
            "entity_type": "MODULE",
            "description": "API route definitions",
        },
        "api_handler": {
            "id": "api_handler",
            "label": "api_handler",
            "entity_type": "FUNCTION",
            "description": "Main API request handler",
        },
        "deploy_service": {
            "id": "deploy_service",
            "label": "deploy_service",
            "entity_type": "SERVICE",
            "description": "Deployment orchestrator",
        },
    }


# ---------------------------------------------------------------------------
# Full chain: scan → link → verify
# ---------------------------------------------------------------------------


class TestFullChain:
    def test_scan_docs_links_to_code(
        self, project_dir: Path, code_nodes: dict
    ) -> None:
        """Core integration: scan documents, verify they link to code nodes."""
        edges: dict[str, Any] = {}
        nodes = dict(code_nodes)

        scanner = DocumentScanner(nodes, edges)
        result = scanner.scan_directory(project_dir)

        # Should have scanned multiple documents
        assert result.files_scanned >= 3

        # Should have created document nodes
        doc_nodes = [n for n in nodes.values() if n["entity_type"] == "DOCUMENT"]
        assert len(doc_nodes) >= 3

        # Should have created section nodes
        sec_nodes = [n for n in nodes.values() if n["entity_type"] == "SECTION"]
        assert len(sec_nodes) >= 3  # at least Auth Layer, Database, API Gateway

        # Should have REFERENCED_IN edges to code nodes
        ref_edges = [
            e for e in edges.values() if e["relationship"] == "REFERENCED_IN"
        ]
        assert len(ref_edges) >= 2  # auth_service.py, validate_token at minimum

        # Verify specific linkages
        ref_targets = {e["target"] for e in ref_edges}
        assert "auth_service.py" in ref_targets or "validate_token" in ref_targets

    def test_section_of_edges_connect_hierarchy(
        self, project_dir: Path, code_nodes: dict
    ) -> None:
        """Verify SECTION_OF edges form proper document hierarchy."""
        edges: dict[str, Any] = {}
        nodes = dict(code_nodes)

        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(project_dir)

        section_of_edges = [
            e for e in edges.values() if e["relationship"] == "SECTION_OF"
        ]
        # Each section should point to its parent document
        for edge in section_of_edges:
            assert edge["target"].startswith("doc::")
            assert edge["source"].startswith("sec::")

    def test_front_matter_extracted(
        self, project_dir: Path, code_nodes: dict
    ) -> None:
        """ADR with YAML front matter should have metadata in node properties."""
        edges: dict[str, Any] = {}
        nodes = dict(code_nodes)

        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(project_dir)

        # Find the ADR document node
        adr_nodes = [
            n for n in nodes.values()
            if n["entity_type"] == "DOCUMENT" and "adr" in n["id"].lower()
        ]
        assert len(adr_nodes) == 1
        adr = adr_nodes[0]

        # Front matter metadata should be in properties
        props = adr.get("properties", {})
        assert props.get("title") == "Use JWT for Authentication"
        assert props.get("status") == "accepted"


# ---------------------------------------------------------------------------
# Incremental: scan → modify → rescan
# ---------------------------------------------------------------------------


class TestIncrementalChain:
    def test_incremental_rescan(self, project_dir: Path) -> None:
        """Second scan should skip unchanged files, rescan modified."""
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}
        manifest_path = project_dir / ".graqle-doc-manifest.json"

        opts = DocScanOptions(incremental=True)
        scanner = DocumentScanner(
            nodes, edges, options=opts, manifest_path=manifest_path
        )

        # First scan
        r1 = scanner.scan_directory(project_dir)
        nodes_after_first = len(nodes)
        assert r1.files_scanned >= 3

        # Second scan — nothing changed
        r2 = scanner.scan_directory(project_dir)
        assert r2.files_skipped >= 3
        assert r2.files_scanned == 0

        # Modify a file
        import time
        time.sleep(0.05)
        arch = project_dir / "docs" / "architecture.md"
        arch.write_text(
            "# Architecture v2\n\n## New Section\n\nUpdated content.\n",
            encoding="utf-8",
        )

        # Third scan — only modified file rescanned
        r3 = scanner.scan_directory(project_dir)
        assert r3.files_scanned >= 1
        assert r3.files_skipped >= 2


# ---------------------------------------------------------------------------
# On-demand: graq learn doc equivalent
# ---------------------------------------------------------------------------


class TestOnDemandIngestion:
    def test_learn_single_file(self, project_dir: Path, code_nodes: dict) -> None:
        """Simulate graq learn doc <file>."""
        nodes = dict(code_nodes)
        edges: dict[str, Any] = {}

        opts = DocScanOptions(incremental=False)  # On-demand always re-processes
        scanner = DocumentScanner(nodes, edges, options=opts)

        result = scanner.scan_file(
            project_dir / "docs" / "architecture.md",
            base_dir=project_dir,
        )

        assert result.files_scanned == 1
        assert result.nodes_added > 0

        # Should have linked to code
        ref_edges = [
            e for e in edges.values() if e["relationship"] == "REFERENCED_IN"
        ]
        assert len(ref_edges) >= 1

    def test_learn_directory(self, project_dir: Path, code_nodes: dict) -> None:
        """Simulate graq learn doc <directory>."""
        nodes = dict(code_nodes)
        edges: dict[str, Any] = {}

        opts = DocScanOptions(incremental=False)
        scanner = DocumentScanner(nodes, edges, options=opts)

        result = scanner.scan_directory(project_dir / "docs")
        assert result.files_scanned >= 3


# ---------------------------------------------------------------------------
# Budget control
# ---------------------------------------------------------------------------


class TestBudgetChain:
    def test_max_files_stops_early(self, project_dir: Path) -> None:
        """Budget control stops scanning after max_files."""
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        opts = DocScanOptions(max_files=1)
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(project_dir)

        assert result.files_scanned <= 1

    def test_max_nodes_stops_early(self, project_dir: Path) -> None:
        """Budget control stops scanning after max_nodes."""
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        opts = DocScanOptions(max_nodes=3)
        scanner = DocumentScanner(nodes, edges, options=opts)
        result = scanner.scan_directory(project_dir)

        # Should have stopped relatively early
        assert result.nodes_added <= 15  # First file may create several nodes


# ---------------------------------------------------------------------------
# Privacy chain
# ---------------------------------------------------------------------------


class TestPrivacyChain:
    def test_secrets_redacted_in_nodes(self, tmp_path: Path) -> None:
        """Sensitive content should be redacted before entering the graph."""
        d = tmp_path / "proj"
        d.mkdir()
        (d / "secrets.md").write_text(
            "# Config\n\n"
            "Database: postgresql://user:p4ssw0rd@host:5432/db\n"
            "API Key: AKIAIOSFODNN7EXAMPLE\n"
            "Token: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123\n",
            encoding="utf-8",
        )

        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        scanner = DocumentScanner(nodes, edges)
        scanner.scan_directory(d)

        # Check that secrets are redacted in node descriptions
        for node in nodes.values():
            desc = node.get("description", "")
            assert "AKIAIOSFODNN7EXAMPLE" not in desc
            assert "p4ssw0rd" not in desc


# ---------------------------------------------------------------------------
# Stale cleanup chain
# ---------------------------------------------------------------------------


class TestStaleCleanupChain:
    def test_deleted_file_nodes_removed(self, project_dir: Path) -> None:
        """When a file is deleted, its nodes and edges are cleaned up."""
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}
        manifest_path = project_dir / ".graqle-doc-manifest.json"

        opts = DocScanOptions(incremental=True)
        scanner = DocumentScanner(
            nodes, edges, options=opts, manifest_path=manifest_path
        )

        # Scan everything
        scanner.scan_directory(project_dir)
        nodes_before = len(nodes)

        # Delete a document
        (project_dir / "docs" / "runbook.txt").unlink()

        # Rescan — stale nodes should be removed
        result = scanner.scan_directory(project_dir)
        assert result.stale_removed > 0
        assert len(nodes) < nodes_before
