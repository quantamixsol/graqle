"""JSON parser — classify JSON files and dispatch to category extractors.

Scanning order: Code AST (immediate) → JSON (background phase 1) →
Documents (background phase 2).  JSON is the bridge layer between code
and documents: it's small, fast, structured, and knowledge-dense.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.json_parser
# risk: MEDIUM (impact radius: 1 modules)
# consumers: test_json_parser
# dependencies: __future__, json, logging, os, time +5 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graqle.scanner.extractors import get_extractor
from graqle.scanner.extractors.base import ExtractionResult

logger = logging.getLogger("graqle.scanner.json_parser")

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Known filenames → category (highest priority)
_KNOWN_FILES: dict[str, str] = {
    "package.json": "DEPENDENCY_MANIFEST",
    "composer.json": "DEPENDENCY_MANIFEST",
    "pipfile": "DEPENDENCY_MANIFEST",
    "pipfile.lock": "SKIP",
    "package-lock.json": "SKIP",
    "yarn.lock": "SKIP",
    "pnpm-lock.yaml": "SKIP",
    "openapi.json": "API_SPEC",
    "swagger.json": "API_SPEC",
    "tsconfig.json": "TOOL_CONFIG",
    "jsconfig.json": "TOOL_CONFIG",
    ".eslintrc.json": "TOOL_CONFIG",
    ".prettierrc.json": "TOOL_CONFIG",
    ".prettierrc": "TOOL_CONFIG",
    ".stylelintrc.json": "TOOL_CONFIG",
    ".babelrc.json": "TOOL_CONFIG",
    "cdk.json": "INFRA_CONFIG",
    "samconfig.json": "INFRA_CONFIG",
    "template.json": "INFRA_CONFIG",
    "serverless.json": "INFRA_CONFIG",
}

# Default skip patterns
DEFAULT_SKIP_PATTERNS: list[str] = [
    "package-lock.json",
    "yarn.lock",
    "*.min.json",
    "node_modules/",
    ".git/",
    "__pycache__/",
    "dist/",
    ".next/",
]

# Maximum file size for JSON scanning (default 10MB)
DEFAULT_MAX_SIZE_MB = 10.0


@dataclass
class JSONClassification:
    """Result of classifying a JSON file."""

    category: str  # DEPENDENCY_MANIFEST, API_SPEC, etc. or SKIP/DATA_FILE
    confidence: float  # 0.0 - 1.0
    reason: str  # why this classification


def classify_json(file_path: str | Path, data: dict | None = None) -> JSONClassification:
    """Classify a JSON file into a knowledge category.

    Parameters
    ----------
    file_path:
        Path to the JSON file (used for filename matching).
    data:
        Pre-parsed JSON content.  If ``None``, the file is not read
        (filename-only classification).
    """
    fp = Path(file_path)
    fname = fp.name.lower()

    # 1. Known filename → known category
    if fname in _KNOWN_FILES:
        cat = _KNOWN_FILES[fname]
        return JSONClassification(cat, 1.0, f"known filename: {fname}")

    # Filename patterns
    if fname.endswith(".schema.json"):
        return JSONClassification("SCHEMA_FILE", 0.95, "*.schema.json pattern")
    if fname.startswith(".") and fname.endswith("rc.json"):
        return JSONClassification("TOOL_CONFIG", 0.9, ".*rc.json pattern")

    if data is None:
        return JSONClassification("UNKNOWN", 0.0, "no data provided")

    # 2. Content-based detection
    keys = set(data.keys()) if isinstance(data, dict) else set()

    if "openapi" in keys or "swagger" in keys:
        return JSONClassification("API_SPEC", 0.95, "openapi/swagger key found")

    if "dependencies" in keys and ("scripts" in keys or "devDependencies" in keys):
        return JSONClassification("DEPENDENCY_MANIFEST", 0.9, "npm manifest structure")

    if "packages" in keys or "dev-packages" in keys:
        return JSONClassification("DEPENDENCY_MANIFEST", 0.85, "Pipfile structure")

    if "require" in keys and "autoload" in keys:
        return JSONClassification("DEPENDENCY_MANIFEST", 0.85, "Composer structure")

    if "compilerOptions" in keys:
        return JSONClassification("TOOL_CONFIG", 0.95, "TypeScript config")

    if "AWSTemplateFormatVersion" in keys or "Resources" in keys:
        return JSONClassification("INFRA_CONFIG", 0.95, "CloudFormation template")

    if "service" in keys and "functions" in keys and "provider" in keys:
        return JSONClassification("INFRA_CONFIG", 0.9, "Serverless Framework")

    if "$schema" in keys:
        return JSONClassification("SCHEMA_FILE", 0.8, "$schema key present")

    if "rules" in keys:
        return JSONClassification("TOOL_CONFIG", 0.7, "has 'rules' key")

    # 3. Size heuristic — large files are likely data, not config
    try:
        size = fp.stat().st_size
        if size > 50 * 1024:  # >50KB
            return JSONClassification("DATA_FILE", 0.6, f"large file ({size / 1024:.0f}KB)")
    except OSError:
        pass

    # Default: treat as app config
    return JSONClassification("APP_CONFIG", 0.5, "default classification")


# ---------------------------------------------------------------------------
# JSONScanner — orchestrates classification + extraction
# ---------------------------------------------------------------------------


@dataclass
class JSONScanOptions:
    """Configuration for JSON scanning."""

    enabled: bool = True
    auto_detect: bool = True
    max_file_size_mb: float = DEFAULT_MAX_SIZE_MB
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_PATTERNS))
    categories: dict[str, bool] = field(default_factory=lambda: {
        "DEPENDENCY_MANIFEST": True,
        "API_SPEC": True,
        "TOOL_CONFIG": True,
        "APP_CONFIG": True,
        "INFRA_CONFIG": True,
        "SCHEMA_FILE": True,
        "DATA_FILE": False,
    })


@dataclass
class JSONScanResult:
    """Aggregate result of scanning JSON files."""

    files_scanned: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    duration_seconds: float = 0.0
    categories_found: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class JSONScanner:
    """Scan JSON files in a directory and extract knowledge.

    Parameters
    ----------
    graph_nodes:
        Dict of existing graph nodes (mutated in-place).
    graph_edges:
        Dict of existing graph edges (mutated in-place).
    options:
        Scanning configuration.
    """

    def __init__(
        self,
        graph_nodes: dict[str, dict[str, Any]],
        graph_edges: dict[str, dict[str, Any]],
        options: JSONScanOptions | None = None,
    ) -> None:
        self._nodes = graph_nodes
        self._edges = graph_edges
        self._opts = options or JSONScanOptions()

    def scan_directory(
        self,
        root: Path,
        *,
        progress_callback: Any = None,
    ) -> JSONScanResult:
        """Scan all JSON files under *root*."""
        root = Path(root).resolve()
        files = self._discover_files(root)
        return self._scan_files(files, root, progress_callback)

    def scan_file(
        self,
        file_path: Path,
        base_dir: Path | None = None,
    ) -> JSONScanResult:
        """Scan a single JSON file."""
        fp = Path(file_path).resolve()
        base = Path(base_dir).resolve() if base_dir else fp.parent
        return self._scan_files([fp], base)

    def _discover_files(self, root: Path) -> list[Path]:
        """Find JSON files to scan."""
        import fnmatch

        files: list[Path] = []
        max_bytes = int(self._opts.max_file_size_mb * 1024 * 1024)

        for dirpath, _dirnames, filenames in os.walk(root):
            dp = Path(dirpath)

            # Skip hidden dirs and common noise
            try:
                rel_dir = dp.relative_to(root)
            except ValueError:
                continue
            parts = rel_dir.parts
            if any(p.startswith(".") or p in (
                "node_modules", "__pycache__", "dist", ".next", "venv", ".venv",
            ) for p in parts):
                continue

            for fname in filenames:
                if not fname.lower().endswith(".json"):
                    continue

                fp = dp / fname
                rel = str(fp.relative_to(root)).replace("\\", "/")

                # Check exclude patterns
                skip = False
                for pattern in self._opts.exclude_patterns:
                    if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fname, pattern):
                        skip = True
                        break
                    if pattern.endswith("/") and rel.startswith(pattern):
                        skip = True
                        break
                if skip:
                    continue

                # Size check
                try:
                    if fp.stat().st_size > max_bytes:
                        continue
                except OSError:
                    continue

                files.append(fp)

        return files

    def _scan_files(
        self,
        files: list[Path],
        base_dir: Path,
        progress_callback: Any = None,
    ) -> JSONScanResult:
        t0 = time.time()
        result = JSONScanResult()
        total = len(files)

        for idx, fp in enumerate(files):
            if progress_callback:
                progress_callback(fp, idx, total)

            rel_path = str(fp.relative_to(base_dir)).replace("\\", "/")

            try:
                raw = fp.read_text(encoding="utf-8", errors="ignore")
                data = json.loads(raw)
            except (json.JSONDecodeError, OSError) as exc:
                result.files_errored += 1
                result.errors.append(f"{rel_path}: {exc}")
                continue

            if not isinstance(data, dict):
                result.files_skipped += 1
                continue

            # Classify
            classification = classify_json(fp, data)

            # Skip unwanted categories
            if classification.category in ("SKIP", "UNKNOWN"):
                result.files_skipped += 1
                continue
            if not self._opts.categories.get(classification.category, False):
                result.files_skipped += 1
                continue

            # Create a manifest node for the JSON file itself
            json_file_id = f"json::{rel_path}"
            self._nodes[json_file_id] = {
                "id": json_file_id,
                "label": fp.name,
                "entity_type": "CONFIG",
                "description": f"JSON file: {rel_path} (category: {classification.category})",
                "properties": {
                    "path": rel_path,
                    "category": classification.category,
                    "classification_confidence": classification.confidence,
                    "classification_reason": classification.reason,
                },
            }
            result.nodes_added += 1

            # Dispatch to extractor
            extractor = get_extractor(classification.category)
            if extractor is None:
                result.files_scanned += 1
                result.categories_found[classification.category] = (
                    result.categories_found.get(classification.category, 0) + 1
                )
                continue

            extraction = extractor.extract(data, str(fp), rel_path=rel_path)
            self._apply_extraction(extraction, result)
            result.files_scanned += 1
            result.categories_found[classification.category] = (
                result.categories_found.get(classification.category, 0) + 1
            )

        result.duration_seconds = time.time() - t0
        return result

    def _apply_extraction(
        self, extraction: ExtractionResult, result: JSONScanResult
    ) -> None:
        """Apply extracted nodes and edges to the graph."""
        for node in extraction.nodes:
            self._nodes[node.id] = {
                "id": node.id,
                "label": node.label,
                "entity_type": node.entity_type,
                "description": node.description,
                "properties": node.properties,
            }
            result.nodes_added += 1

        for edge in extraction.edges:
            edge_id = f"{edge.source_id}___{edge.relationship}___{edge.target_id}"
            self._edges[edge_id] = {
                "id": edge_id,
                "source": edge.source_id,
                "target": edge.target_id,
                "relationship": edge.relationship,
                "properties": edge.properties,
            }
            result.edges_added += 1
