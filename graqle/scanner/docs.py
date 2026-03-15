"""DocumentScanner — main orchestrator for document-aware graph ingestion.

Coordinates parsing, chunking, redaction, node creation, auto-linking,
and incremental manifest tracking.  Designed for both foreground
(``graq scan docs``, ``graq learn doc``) and background usage.

Usage
-----
::

    scanner = DocumentScanner(graph, config)
    result = scanner.scan_directory(Path("."))
    result = scanner.scan_file(Path("docs/arch.pdf"))
    result = scanner.scan_files([Path("a.md"), Path("b.txt")])
"""

# ── graqle:intelligence ──
# module: graqle.scanner.docs
# risk: MEDIUM (impact radius: 2 modules)
# consumers: test_docs, test_doc_chain
# dependencies: __future__, logging, os, time, dataclasses +9 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graqle.scanner.chunker import DocumentChunker
from graqle.scanner.linker import AutoLinker, LinkingResult
from graqle.scanner.manifest import ScanManifest
from graqle.scanner.parsers import get_parser
from graqle.scanner.parsers.base import ParsedDocument
from graqle.scanner.privacy import RedactionEngine
from graqle.scanner.types import DOC_EXTENSIONS, SCAN_PRIORITY

logger = logging.getLogger("graqle.scanner.docs")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ScanFileResult:
    """Result of scanning a single file."""

    path: str
    success: bool
    node_ids: list[str] = field(default_factory=list)
    edge_count: int = 0
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    """Aggregate result of a scanning operation."""

    files_scanned: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    linking: LinkingResult | None = None
    file_results: list[ScanFileResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    stale_removed: int = 0

    @property
    def files_total(self) -> int:
        return self.files_scanned + self.files_skipped + self.files_errored


# ---------------------------------------------------------------------------
# Config DTO (thin — avoids importing Pydantic in the scanner)
# ---------------------------------------------------------------------------


@dataclass
class DocScanOptions:
    """Runtime options for a scan — mirrors the Pydantic config.

    This is a plain dataclass so the scanner module has zero dependency
    on Pydantic.  The CLI / config layer converts ``DocScanConfig`` →
    ``DocScanOptions`` before calling the scanner.
    """

    extensions: list[str] = field(
        default_factory=lambda: list(DOC_EXTENSIONS.keys())
    )
    exclude_extensions: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    max_file_size_mb: float = 50.0
    chunk_max_chars: int = 1500
    chunk_overlap_chars: int = 100
    chunk_min_chars: int = 100

    # Linking
    link_exact: bool = True
    link_fuzzy: bool = True
    link_semantic: bool = False
    link_llm: bool = False
    fuzzy_threshold: float = 0.60
    semantic_threshold: float = 0.70
    max_edges_per_doc: int = 50

    # Privacy
    redaction_enabled: bool = True
    redaction_extra_patterns: dict[str, str] = field(default_factory=dict)
    redaction_disabled_patterns: set[str] = field(default_factory=set)

    # Incremental
    incremental: bool = True

    # Budget
    max_nodes: int = 0  # 0 = unlimited
    max_files: int = 0  # 0 = unlimited


# ---------------------------------------------------------------------------
# DocumentScanner
# ---------------------------------------------------------------------------


class DocumentScanner:
    """Orchestrates document scanning, chunking, redaction, and linking.

    Parameters
    ----------
    graph_nodes:
        Dict of existing graph nodes ``{node_id: node_dict}``.
        Each dict must have ``"id"``, ``"label"``, ``"entity_type"``.
        The scanner adds new nodes in-place.
    graph_edges:
        Dict of existing graph edges ``{edge_id: edge_dict}``.
        The scanner adds new edges in-place.
    options:
        Scan configuration options.
    manifest_path:
        Path to the manifest JSON file.  If ``None``, incremental
        tracking is disabled.
    """

    def __init__(
        self,
        graph_nodes: dict[str, dict[str, Any]],
        graph_edges: dict[str, dict[str, Any]],
        options: DocScanOptions | None = None,
        manifest_path: str | Path | None = None,
    ) -> None:
        self._nodes = graph_nodes
        self._edges = graph_edges
        self._opts = options or DocScanOptions()

        # Sub-components
        self._chunker = DocumentChunker(
            max_chunk_chars=self._opts.chunk_max_chars,
            min_chunk_chars=self._opts.chunk_min_chars,
            overlap_chars=self._opts.chunk_overlap_chars,
        )
        self._redactor = RedactionEngine(
            enabled=self._opts.redaction_enabled,
            extra_patterns=self._opts.redaction_extra_patterns,
            disabled_patterns=self._opts.redaction_disabled_patterns,
        )
        self._linker = AutoLinker(
            exact=self._opts.link_exact,
            fuzzy=self._opts.link_fuzzy,
            semantic=self._opts.link_semantic,
            llm_assisted=self._opts.link_llm,
            fuzzy_threshold=self._opts.fuzzy_threshold,
            semantic_threshold=self._opts.semantic_threshold,
            max_edges_per_doc=self._opts.max_edges_per_doc,
        )
        self._manifest: ScanManifest | None = None
        if manifest_path and self._opts.incremental:
            self._manifest = ScanManifest(manifest_path)

    # -- public API ---------------------------------------------------------

    def scan_directory(
        self,
        root: Path,
        *,
        remove_stale: bool = True,
        progress_callback: Any = None,
    ) -> ScanResult:
        """Scan all supported documents under *root*.

        Parameters
        ----------
        root:
            Directory to scan recursively.
        remove_stale:
            If ``True``, remove manifest entries for deleted files and
            return orphaned node IDs.
        progress_callback:
            Optional ``callable(file_path, index, total)`` called before
            each file is processed.
        """
        root = Path(root).resolve()
        files = self._discover_files(root)

        # Sort by scan priority (cheap formats first)
        files.sort(key=lambda p: SCAN_PRIORITY.get(
            DOC_EXTENSIONS.get(p.suffix.lower(), ""), 99
        ))

        result = self._scan_file_list(files, root, progress_callback)

        # Clean up stale entries
        if remove_stale and self._manifest:
            stale = self._manifest.remove_stale(root)
            for rel_path, node_ids in stale.items():
                for nid in node_ids:
                    self._nodes.pop(nid, None)
                    # Remove edges referencing this node
                    self._remove_edges_for_node(nid)
                result.stale_removed += len(node_ids)
                logger.info("Removed stale: %s (%d nodes)", rel_path, len(node_ids))
            if stale:
                self._manifest.save()

        return result

    def scan_file(self, file_path: Path, base_dir: Path | None = None) -> ScanResult:
        """Scan a single file.

        Parameters
        ----------
        file_path:
            Path to the document file.
        base_dir:
            Base directory for relative path computation.  Defaults to
            the file's parent.
        """
        file_path = Path(file_path).resolve()
        base = Path(base_dir).resolve() if base_dir else file_path.parent
        return self._scan_file_list([file_path], base)

    def scan_files(
        self,
        files: list[Path],
        base_dir: Path,
        progress_callback: Any = None,
    ) -> ScanResult:
        """Scan a list of files."""
        resolved = [Path(f).resolve() for f in files]
        base = Path(base_dir).resolve()
        return self._scan_file_list(resolved, base, progress_callback)

    # -- discovery ----------------------------------------------------------

    def _discover_files(self, root: Path) -> list[Path]:
        """Recursively discover supported document files under *root*."""
        allowed_exts = set(self._opts.extensions) - set(self._opts.exclude_extensions)
        files: list[Path] = []

        for dirpath, _dirnames, filenames in os.walk(root):
            dp = Path(dirpath)
            # Skip hidden directories and common non-content dirs
            if any(part.startswith(".") for part in dp.relative_to(root).parts):
                continue
            if any(part in ("node_modules", "__pycache__", ".git", "venv", ".venv")
                   for part in dp.relative_to(root).parts):
                continue

            for fname in filenames:
                fp = dp / fname
                ext = fp.suffix.lower()
                if ext not in allowed_exts:
                    continue
                # Exclude patterns
                rel = str(fp.relative_to(root)).replace("\\", "/")
                if self._matches_exclude(rel):
                    continue
                # Size check
                try:
                    if fp.stat().st_size > self._opts.max_file_size_mb * 1024 * 1024:
                        continue
                except OSError:
                    continue
                files.append(fp)

        return files

    def _matches_exclude(self, rel_path: str) -> bool:
        """Check if *rel_path* matches any exclude pattern."""
        import fnmatch
        for pattern in self._opts.exclude_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    # -- core scan loop -----------------------------------------------------

    def _scan_file_list(
        self,
        files: list[Path],
        base_dir: Path,
        progress_callback: Any = None,
    ) -> ScanResult:
        """Process a list of files and return aggregate results."""
        t0 = time.time()
        result = ScanResult()
        total = len(files)
        nodes_before = len(self._nodes)

        for idx, fp in enumerate(files):
            # Budget check
            if self._opts.max_files > 0 and result.files_scanned >= self._opts.max_files:
                break
            if self._opts.max_nodes > 0 and result.nodes_added >= self._opts.max_nodes:
                break

            if progress_callback:
                progress_callback(fp, idx, total)

            rel_path = str(fp.relative_to(base_dir)).replace("\\", "/")

            # Incremental check
            if self._manifest and self._opts.incremental:
                if not self._manifest.needs_scan(rel_path, fp):
                    result.files_skipped += 1
                    result.file_results.append(ScanFileResult(
                        path=rel_path, success=True,
                        skipped=True, skip_reason="unchanged",
                    ))
                    continue

            # Parse
            file_result = self._process_file(fp, rel_path)
            result.file_results.append(file_result)

            if file_result.error:
                result.files_errored += 1
            elif file_result.skipped:
                result.files_skipped += 1
            else:
                result.files_scanned += 1
                result.nodes_added += len(file_result.node_ids)

                # Update manifest
                if self._manifest:
                    self._manifest.update(
                        rel_path, fp,
                        node_ids=file_result.node_ids,
                        fmt=DOC_EXTENSIONS.get(fp.suffix.lower(), ""),
                        parse_errors=file_result.parse_errors,
                    )

        # Auto-link all new document nodes to existing code nodes
        linking = self._run_linking()
        result.linking = linking
        result.edges_added = len(linking.accepted) if linking else 0

        # Save manifest
        if self._manifest:
            self._manifest.save()

        result.duration_seconds = time.time() - t0
        return result

    def _process_file(self, file_path: Path, rel_path: str) -> ScanFileResult:
        """Parse, chunk, redact, and create nodes for a single file."""
        ext = file_path.suffix.lower()

        # Get parser
        parser = get_parser(ext)
        if parser is None:
            return ScanFileResult(
                path=rel_path, success=False,
                error=f"No parser available for {ext}",
            )
        if not parser.is_available():
            return ScanFileResult(
                path=rel_path, success=False,
                skipped=True,
                skip_reason=parser.missing_dependency_message(),
            )

        # Parse
        try:
            doc = parser.parse(file_path)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return ScanFileResult(
                path=rel_path, success=False,
                error=str(exc),
            )

        # Chunk
        chunks = self._chunker.chunk_document(doc)

        # Create nodes
        node_ids = self._create_nodes(doc, chunks, rel_path)

        return ScanFileResult(
            path=rel_path,
            success=True,
            node_ids=node_ids,
            parse_errors=doc.parse_errors,
        )

    # -- node creation ------------------------------------------------------

    def _create_nodes(
        self,
        doc: ParsedDocument,
        chunks: list,
        rel_path: str,
    ) -> list[str]:
        """Create graph nodes from a parsed document and its chunks."""
        node_ids: list[str] = []

        # Document-level node
        doc_id = f"doc::{rel_path}"
        doc_text = self._redactor.redact(doc.full_text)
        title = doc.title or rel_path

        self._nodes[doc_id] = {
            "id": doc_id,
            "label": title,
            "entity_type": "DOCUMENT",
            "description": self._truncate(doc_text, 500),
            "properties": {
                "path": rel_path,
                "format": doc.format,
                "title": title,
                "section_count": len(doc.sections),
                "chunk_count": len(chunks),
                **{k: v for k, v in doc.metadata.items()
                   if k != "source" and isinstance(v, (str, int, float, bool))},
            },
        }
        node_ids.append(doc_id)

        # Section-level nodes
        for i, section in enumerate(doc.sections):
            if not section.title and not section.content.strip():
                continue

            sec_id = f"sec::{rel_path}::{section.title or f'section_{i}'}"
            sec_text = self._redactor.redact(section.content)

            self._nodes[sec_id] = {
                "id": sec_id,
                "label": section.title or f"Section {i + 1}",
                "entity_type": "SECTION",
                "description": self._truncate(sec_text, 300),
                "properties": {
                    "path": rel_path,
                    "level": section.level,
                    "section_type": section.section_type,
                    "has_tables": len(section.tables) > 0,
                    "has_code": len(section.code_blocks) > 0,
                    "link_count": len(section.links),
                },
            }
            node_ids.append(sec_id)

            # SECTION_OF edge
            edge_id = f"{sec_id}___SECTION_OF___{doc_id}"
            self._edges[edge_id] = {
                "id": edge_id,
                "source": sec_id,
                "target": doc_id,
                "relationship": "SECTION_OF",
            }

        return node_ids

    # -- linking ------------------------------------------------------------

    def _run_linking(self) -> LinkingResult:
        """Run auto-linking between document nodes and code nodes."""
        doc_nodes: list[dict[str, Any]] = []
        code_nodes: list[dict[str, Any]] = []
        doc_texts: dict[str, str] = {}

        for nid, node in self._nodes.items():
            etype = node.get("entity_type", "")
            if etype in ("DOCUMENT", "SECTION"):
                doc_nodes.append(node)
                doc_texts[nid] = node.get("description", "")
            elif etype not in ("DOCUMENT", "SECTION") and not nid.startswith("doc::") and not nid.startswith("sec::"):
                code_nodes.append(node)

        if not doc_nodes or not code_nodes:
            return LinkingResult()

        linking = self._linker.link(doc_nodes, code_nodes, doc_texts)

        # Apply accepted edges
        for edge in linking.accepted:
            edge_id = f"{edge.source_id}___{edge.relation}___{edge.target_id}"
            if edge_id not in self._edges:
                self._edges[edge_id] = {
                    "id": edge_id,
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "relationship": edge.relation,
                    "properties": {
                        "confidence": edge.confidence,
                        "method": edge.method,
                        "evidence": edge.evidence,
                    },
                }

        return linking

    # -- helpers ------------------------------------------------------------

    def _remove_edges_for_node(self, node_id: str) -> None:
        """Remove all edges connected to *node_id*."""
        to_remove = [
            eid for eid, e in self._edges.items()
            if e.get("source") == node_id or e.get("target") == node_id
        ]
        for eid in to_remove:
            del self._edges[eid]

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text to *max_len* chars, appending '...' if needed."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."
