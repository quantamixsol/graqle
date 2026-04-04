# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ──────────────────────────────────────────────────────────────────

"""Streaming Intelligence Pipeline — the heart of GraQle's Quality Gate.

Processes files one at a time, streaming validated intelligence as it goes.
Each file produces a FileIntelligenceUnit with guaranteed coverage, and
emits curiosity-peak insights to keep the user engaged.

Three phases:
1. Structural pass (instant — file listing + project shape)
2. Import graph pass (fast — regex on imports, dependency map)
3. Deep scan (streaming — full AST + chunks + validation per file)

See ADR-105 §Streaming Intelligence Pipeline.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.pipeline
# risk: MEDIUM (impact radius: 3 modules)
# consumers: sdk_self_audit, compile, test_pipeline
# dependencies: __future__, logging, os, re, time +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from graqle.intelligence.models import (
    CoverageReport,
    CuriosityInsight,
    FileIntelligenceUnit,
    ModuleConsumer,
    ModuleDependency,
    ModulePacket,
    PublicInterface,
    ValidatedEdge,
    ValidatedNode,
    ValidationStatus,
)
from graqle.intelligence.scorecard import RunningScorecard
from graqle.intelligence.validators import run_all_gates
from graqle.utils.gitignore import GitignoreMatcher

logger = logging.getLogger("graqle.intelligence.pipeline")

# Directories to skip (aligned with scan.py SKIP_DIRS)
SKIP_DIRS = frozenset({
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info", ".eggs", "site-packages",
    "node_modules", ".next", ".turbo", ".vercel",
    "dist", "build", "out", "_build", "target",
    ".idea", ".vscode", ".git",
    ".cache", "coverage", ".coverage", ".nyc_output",
    ".cargo", ".gradle", ".mvn",
})

# File extensions we scan
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}
CONFIG_EXTENSIONS = {".yaml", ".yml", ".toml", ".json", ".cfg", ".ini"}

# Import patterns
_PY_IMPORT_RE = re.compile(r"^(?:from\s+([\w.]+)|import\s+([\w.]+))", re.MULTILINE)
_JS_IMPORT_RE = re.compile(
    r"(?:import\s+.*?from\s+['\"]([^'\"]+)['\"]|"
    r"require\(['\"]([^'\"]+)['\"]\))",
    re.MULTILINE,
)

# Function/class patterns for quick counting
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.MULTILINE)
_PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)
_JS_FUNC_RE = re.compile(
    r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(|"
    r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\w+\s*)?\s*=>)",
    re.MULTILINE,
)
_JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE)


class ProjectShape:
    """Result of the fast structural pass (Phase 1 — <3 seconds)."""

    def __init__(self) -> None:
        self.root: Path = Path(".")
        self.total_files: int = 0
        self.code_files: list[Path] = []
        self.config_files: list[Path] = []
        self.test_files: list[Path] = []
        self.extension_counts: Counter[str] = Counter()
        self.dir_count: int = 0
        self.estimated_lines: int = 0

        # Detection
        self.has_python: bool = False
        self.has_javascript: bool = False
        self.has_typescript: bool = False
        self.framework_hints: list[str] = []
        self.ai_tools: list[str] = []

    @property
    def all_scannable_files(self) -> list[Path]:
        return self.code_files + self.config_files


class ImportGraph:
    """Result of the import graph pass (Phase 2 — <10 seconds)."""

    def __init__(self) -> None:
        self.imports: dict[str, list[str]] = {}        # file → [imported modules]
        self.import_counts: dict[str, int] = {}        # file → number of times imported
        self.dependency_map: dict[str, set[str]] = {}  # file → set of files it imports

    def get_priority_order(self, files: list[Path], root: Path) -> list[Path]:
        """Sort files by import count descending — most imported first."""
        def sort_key(f: Path) -> tuple[int, str]:
            rel = str(f.relative_to(root)).replace("\\", "/")
            return (-self.import_counts.get(rel, 0), rel)
        return sorted(files, key=sort_key)

    def consumers_of(self, file_path: str) -> list[str]:
        """Get all files that import the given file."""
        return [
            f for f, imports in self.imports.items()
            if file_path in imports or self._module_match(file_path, imports)
        ]

    def dependencies_of(self, file_path: str) -> list[str]:
        """Get all files imported by the given file."""
        return self.imports.get(file_path, [])

    @staticmethod
    def _module_match(file_path: str, imports: list[str]) -> bool:
        """Check if file_path matches any import as a module path.

        Guards against single-character module names (e.g. ``d``, ``e``)
        that would false-positive-match almost every import via endswith.
        """
        module = file_path.replace("/", ".").replace("\\", ".")
        for suffix in (".py", ".js", ".ts", ".jsx", ".tsx"):
            if module.endswith(suffix):
                module = module[:-len(suffix)]
                break
        last_part = module.rsplit(".", 1)[-1]
        # Skip matching if the module's last segment is too short (minified/bundled)
        if len(last_part) <= 2:
            return False
        return any(
            module.endswith(imp) or imp.endswith(f".{last_part}") or imp == last_part
            for imp in imports
        )


def structural_pass(root: Path) -> ProjectShape:
    """Phase 1: Fast structural analysis (<3 seconds for 1000 files).

    No code parsing. Just file listing + size + extension counting.
    Produces project shape and detects frameworks/AI tools.
    """
    shape = ProjectShape()
    shape.root = root

    ai_tool_markers = {
        "claude": [Path("CLAUDE.md"), Path(".claude")],
        "cursor": [Path(".cursorrules"), Path(".cursor")],
        "copilot": [Path(".github/copilot-instructions.md")],
        "windsurf": [Path(".windsurfrules")],
    }

    # Detect AI tools
    for tool, markers in ai_tool_markers.items():
        if any((root / m).exists() for m in markers):
            shape.ai_tools.append(tool)

    # .gitignore filtering (v0.42.2 hotfix B1 — aligns compile with scan)
    gitignore = GitignoreMatcher(root)

    # Walk directory tree
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        # Single combined filter: SKIP_DIRS (fast) + hidden dirs + .gitignore patterns
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not (d.startswith(".") and d not in {".github"})
            and not gitignore.is_ignored(f"{rel_dir}/{d}" if rel_dir != "." else d)
        ]
        shape.dir_count += 1

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            shape.extension_counts[ext] += 1
            shape.total_files += 1

            if ext in CODE_EXTENSIONS:
                shape.code_files.append(fpath)
                try:
                    shape.estimated_lines += fpath.stat().st_size // 40  # rough estimate
                except OSError:
                    pass

                if ext == ".py":
                    shape.has_python = True
                elif ext in (".ts", ".tsx"):
                    shape.has_typescript = True
                elif ext in (".js", ".jsx"):
                    shape.has_javascript = True

                # Check if test file
                if "test" in fname.lower() or str(fpath).replace("\\", "/").find("/tests/") >= 0:
                    shape.test_files.append(fpath)

            elif ext in CONFIG_EXTENSIONS:
                shape.config_files.append(fpath)

    # Detect frameworks
    marker_files = {f.name for f in (root.iterdir() if root.is_dir() else [])}
    if "pyproject.toml" in marker_files or "setup.py" in marker_files:
        shape.framework_hints.append("python-package")
    if "package.json" in marker_files:
        shape.framework_hints.append("node")
    if "Dockerfile" in marker_files or "docker-compose.yml" in marker_files:
        shape.framework_hints.append("docker")
    if any(f.name == "conftest.py" for f in shape.code_files):
        shape.framework_hints.append("pytest")

    return shape


def import_graph_pass(files: list[Path], root: Path) -> ImportGraph:
    """Phase 2: Build import graph from regex scan (<10 seconds for 50 files).

    No AST parsing. Just regex on import/from/require lines.
    Produces dependency map and import counts for priority ordering.
    """
    graph = ImportGraph()
    file_set = {str(f.relative_to(root)).replace("\\", "/") for f in files}

    for fpath in files:
        rel = str(fpath.relative_to(root)).replace("\\", "/")
        ext = fpath.suffix.lower()

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        imports: list[str] = []
        if ext == ".py":
            for match in _PY_IMPORT_RE.finditer(content):
                mod = match.group(1) or match.group(2)
                if mod:
                    imports.append(mod)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for match in _JS_IMPORT_RE.finditer(content):
                mod = match.group(1) or match.group(2)
                if mod and not mod.startswith("."):
                    imports.append(mod)
                elif mod:
                    imports.append(mod)

        graph.imports[rel] = imports

    # Compute import counts: how many files import each file
    for file_path, imports in graph.imports.items():
        for imp in imports:
            # Try to resolve import to a file in the project
            resolved = _resolve_import(imp, file_set)
            if resolved:
                graph.import_counts[resolved] = graph.import_counts.get(resolved, 0) + 1

    return graph


def compile_module_packet(
    file_path: str,
    nodes: list[ValidatedNode],
    edges: list[ValidatedEdge],
    import_graph: ImportGraph | None = None,
    root: Path | None = None,
) -> ModulePacket:
    """Compile a ModulePacket from validated nodes and edges.

    This is the intelligence unit served by graq_gate and injected into Layer B headers.
    """
    # Count functions and classes
    functions = [n for n in nodes if n.entity_type == "Function"]
    classes = [n for n in nodes if n.entity_type == "Class"]

    # Estimate line count
    line_count = 0
    for n in nodes:
        if n.start_line and n.end_line:
            line_count = max(line_count, n.end_line)

    # Public interfaces (top-level functions and classes)
    public_interfaces = []
    for n in functions + classes:
        if not n.label.startswith("_"):
            public_interfaces.append(PublicInterface(
                name=n.label, type=n.entity_type,
                line=n.start_line,
            ))

    # Consumers and dependencies from import graph
    consumers: list[ModuleConsumer] = []
    dependencies: list[ModuleDependency] = []

    if import_graph:
        consumer_files = import_graph.consumers_of(file_path)
        for cf in consumer_files:
            mod_name = cf.replace("/", ".").replace("\\", ".")
            if mod_name.endswith(".py"):
                mod_name = mod_name[:-3]
            consumers.append(ModuleConsumer(module=mod_name))

        dep_imports = import_graph.dependencies_of(file_path)
        for dep in dep_imports:
            dep_type = "internal" if _is_internal_import(dep, root) else "external"
            dependencies.append(ModuleDependency(module=dep, type=dep_type))

    # Risk scoring
    consumer_count = len(consumers)
    dep_count = len(dependencies)
    fn_count = len(functions)
    impact_radius = consumer_count

    # Risk formula: weighted combination of connectivity and size
    risk_score = min(1.0, (
        0.4 * min(consumer_count / 15, 1.0) +    # import weight
        0.3 * min(fn_count / 40, 1.0) +            # size weight
        0.2 * min(dep_count / 10, 1.0) +            # dependency weight
        0.1 * min(len(edges) / 50, 1.0)             # edge density weight
    ))

    if risk_score >= 0.7:
        risk_level = "CRITICAL"
    elif risk_score >= 0.5:
        risk_level = "HIGH"
    elif risk_score >= 0.3:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Coverage
    nodes_with_chunks = sum(1 for n in nodes if n.chunks)
    nodes_with_desc = sum(1 for n in nodes if len(n.description) >= 30)
    total = len(nodes) or 1

    module_name = file_path.replace("/", ".").replace("\\", ".")
    if module_name.endswith(".py"):
        module_name = module_name[:-3]
    elif module_name.endswith((".js", ".ts")):
        module_name = module_name[:-3]
    elif module_name.endswith((".jsx", ".tsx")):
        module_name = module_name[:-4]

    return ModulePacket(
        module=module_name,
        files=[file_path],
        node_count=len(nodes),
        function_count=len(functions),
        class_count=len(classes),
        line_count=line_count,
        public_interfaces=public_interfaces,
        consumers=consumers,
        dependencies=dependencies,
        risk_score=round(risk_score, 3),
        risk_level=risk_level,
        impact_radius=impact_radius,
        chunk_coverage=round(nodes_with_chunks / total * 100, 1),
        description_coverage=round(nodes_with_desc / total * 100, 1),
    )


def process_file_lightweight(
    file_path: Path,
    root: Path,
    import_graph: ImportGraph | None = None,
    known_node_ids: set[str] | None = None,
) -> FileIntelligenceUnit:
    """Process a single file through the full intelligence pipeline.

    This is the lightweight version that uses regex-based extraction
    (not the full RepoScanner AST). Suitable for the streaming pipeline
    where speed matters more than AST-level detail.

    The full RepoScanner results can be layered on top later.
    """
    start = time.perf_counter()
    rel_path = str(file_path.relative_to(root)).replace("\\", "/")
    ext = file_path.suffix.lower()

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = ""

    # Extract nodes from content
    nodes_raw: list[dict[str, Any]] = []
    edges_raw: list[dict[str, Any]] = []

    if ext == ".py":
        nodes_raw, edges_raw = _extract_python_nodes(rel_path, content)
    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        nodes_raw, edges_raw = _extract_js_nodes(rel_path, content)
    else:
        # Config or unknown — create single file node
        nodes_raw = [{
            "id": rel_path,
            "label": file_path.name,
            "type": "Config",
            "description": f"Configuration file: {file_path.name}",
            "chunks": [{"text": content[:500], "type": "file"}] if content else [],
            "properties": {"file_path": rel_path},
        }]

    # Run all 6 validation gates
    gate_results, validated_nodes, validated_edges, pending_edges = run_all_gates(
        nodes_raw, edges_raw, rel_path,
        file_content=content,
        known_node_ids=known_node_ids,
    )

    # Compile module packet
    packet = compile_module_packet(
        rel_path, validated_nodes, validated_edges,
        import_graph=import_graph, root=root,
    )

    # Build coverage report
    coverage = CoverageReport(
        total_nodes=len(validated_nodes),
        nodes_with_chunks=sum(1 for n in validated_nodes if n.chunks),
        nodes_with_descriptions=sum(1 for n in validated_nodes if len(n.description) >= 30),
        total_edges=len(validated_edges) + len(pending_edges),
        valid_edges=len(validated_edges),
        pending_edges=len(pending_edges),
        auto_repairs=sum(g.auto_repaired for g in gate_results),
        degraded_nodes=sum(g.degraded for g in gate_results),
        parse_success=gate_results[0].passed if gate_results else True,
    )

    # Determine validation status
    if any(g.degraded > 0 for g in gate_results):
        status = ValidationStatus.DEGRADED
    elif any(g.auto_repaired > 0 for g in gate_results):
        status = ValidationStatus.REPAIRED
    else:
        status = ValidationStatus.PASS

    duration_ms = (time.perf_counter() - start) * 1000

    unit = FileIntelligenceUnit(
        file_path=rel_path,
        nodes=validated_nodes,
        edges=validated_edges,
        module_packet=packet,
        coverage=coverage,
        validation_status=status,
        gate_results=gate_results,
        scan_duration_ms=round(duration_ms, 1),
    )
    # Stash pending edges for second-pass resolution
    unit._pending_edges = pending_edges  # type: ignore[attr-defined]
    return unit


def stream_intelligence(
    root: Path,
    shape: ProjectShape | None = None,
    import_graph: ImportGraph | None = None,
) -> Iterator[tuple[FileIntelligenceUnit, list[CuriosityInsight]]]:
    """Stream intelligence units one file at a time.

    Yields (FileIntelligenceUnit, new_insights) for each file.
    Files are processed in priority order (most-imported first).
    """
    if shape is None:
        shape = structural_pass(root)
    if import_graph is None:
        import_graph = import_graph_pass(shape.code_files, root)

    # Priority order: most-imported files first
    ordered_files = import_graph.get_priority_order(shape.code_files, root)

    scorecard = RunningScorecard()
    scorecard.total_files = len(ordered_files)
    known_node_ids: set[str] = set()

    for fpath in ordered_files:
        unit = process_file_lightweight(fpath, root, import_graph, known_node_ids)

        # Update known node IDs for subsequent files
        for node in unit.nodes:
            known_node_ids.add(node.id)

        # Ingest into scorecard for insights
        new_insights = scorecard.ingest(unit)

        yield unit, new_insights


# ─── Internal extraction helpers ──────────────────────────────────────

def _extract_python_nodes(
    rel_path: str, content: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract Python nodes using regex (fast, not full AST)."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    lines = content.split("\n")

    # Module node
    mod_desc = _extract_module_docstring(content, rel_path)
    mod_chunks = _chunk_content(content, rel_path, "file")
    nodes.append({
        "id": rel_path,
        "label": Path(rel_path).name,
        "type": "PythonModule",
        "description": mod_desc,
        "chunks": mod_chunks,
        "properties": {"file_path": rel_path, "line_count": len(lines)},
    })

    # Functions
    for match in _PY_DEF_RE.finditer(content):
        name = match.group(1)
        line_no = content[:match.start()].count("\n") + 1
        func_id = f"{rel_path}::{name}"
        # Extract function body for chunk
        func_text = _extract_block(lines, line_no - 1, indent_based=True)
        nodes.append({
            "id": func_id,
            "label": name,
            "type": "Function",
            "description": f"Function {name} defined in {Path(rel_path).name}.",
            "chunks": [{"text": func_text[:500], "type": "function", "start_line": line_no}] if func_text else [],
            "properties": {"file_path": rel_path, "start_line": line_no},
        })
        edges.append({"source": rel_path, "target": func_id, "relationship": "DEFINES"})

    # Classes
    for match in _PY_CLASS_RE.finditer(content):
        name = match.group(1)
        line_no = content[:match.start()].count("\n") + 1
        class_id = f"{rel_path}::{name}"
        class_text = _extract_block(lines, line_no - 1, indent_based=True)
        nodes.append({
            "id": class_id,
            "label": name,
            "type": "Class",
            "description": f"Class {name} defined in {Path(rel_path).name}.",
            "chunks": [{"text": class_text[:500], "type": "class", "start_line": line_no}] if class_text else [],
            "properties": {"file_path": rel_path, "start_line": line_no},
        })
        edges.append({"source": rel_path, "target": class_id, "relationship": "DEFINES"})

    # Import edges
    for match in _PY_IMPORT_RE.finditer(content):
        mod = match.group(1) or match.group(2)
        if mod:
            edges.append({"source": rel_path, "target": mod, "relationship": "IMPORTS"})

    return nodes, edges


def _extract_js_nodes(
    rel_path: str, content: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract JS/TS nodes using regex (fast, not full AST)."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    lines = content.split("\n")

    # Module node
    nodes.append({
        "id": rel_path,
        "label": Path(rel_path).name,
        "type": "JavaScriptModule",
        "description": f"JavaScript/TypeScript module: {Path(rel_path).name}",
        "chunks": _chunk_content(content, rel_path, "file"),
        "properties": {"file_path": rel_path, "line_count": len(lines)},
    })

    # Functions
    for match in _JS_FUNC_RE.finditer(content):
        name = match.group(1) or match.group(2) or match.group(3)
        if name:
            line_no = content[:match.start()].count("\n") + 1
            func_id = f"{rel_path}::{name}"
            nodes.append({
                "id": func_id,
                "label": name,
                "type": "Function",
                "description": f"Function {name} defined in {Path(rel_path).name}.",
                "chunks": [{"text": content[match.start():match.start()+500], "type": "function", "start_line": line_no}],
                "properties": {"file_path": rel_path, "start_line": line_no},
            })
            edges.append({"source": rel_path, "target": func_id, "relationship": "DEFINES"})

    # Classes
    for match in _JS_CLASS_RE.finditer(content):
        name = match.group(1)
        line_no = content[:match.start()].count("\n") + 1
        class_id = f"{rel_path}::{name}"
        nodes.append({
            "id": class_id,
            "label": name,
            "type": "Class",
            "description": f"Class {name} defined in {Path(rel_path).name}.",
            "chunks": [{"text": content[match.start():match.start()+500], "type": "class", "start_line": line_no}],
            "properties": {"file_path": rel_path, "start_line": line_no},
        })
        edges.append({"source": rel_path, "target": class_id, "relationship": "DEFINES"})

    # Import edges
    for match in _JS_IMPORT_RE.finditer(content):
        mod = match.group(1) or match.group(2)
        if mod:
            edges.append({"source": rel_path, "target": mod, "relationship": "IMPORTS"})

    return nodes, edges


def _extract_module_docstring(content: str, rel_path: str) -> str:
    """Extract module-level docstring or first comment block."""
    # Python triple-quote docstring
    match = re.match(r'^(?:\s*#[^\n]*\n)*\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', content, re.DOTALL)
    if match:
        doc = (match.group(1) or match.group(2) or "").strip()
        if len(doc) >= 30:
            return doc[:300]

    # Fall back to first comment block
    comment_lines = []
    for line in content.split("\n")[:20]:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            comment_lines.append(stripped.lstrip("#/ "))
        elif comment_lines:
            break

    if comment_lines:
        desc = " ".join(comment_lines)
        if len(desc) >= 30:
            return desc[:300]

    return f"Source module: {Path(rel_path).name}. Contains Python/JS code."


def _chunk_content(content: str, rel_path: str, chunk_type: str, max_chunks: int = 5) -> list[dict[str, Any]]:
    """Split content into chunks for a module-level node."""
    chunks = []
    lines = content.split("\n")
    chunk_size = max(len(lines) // max_chunks, 20)

    for i in range(0, len(lines), chunk_size):
        chunk_lines = lines[i:i + chunk_size]
        text = "\n".join(chunk_lines).strip()
        if len(text) >= 10:
            chunks.append({
                "text": text[:500],
                "type": chunk_type,
                "start_line": i + 1,
                "end_line": min(i + chunk_size, len(lines)),
            })
        if len(chunks) >= max_chunks:
            break

    return chunks or [{"text": f"File: {rel_path}", "type": chunk_type}]


def _extract_block(lines: list[str], start_idx: int, indent_based: bool = True) -> str:
    """Extract a code block starting at start_idx."""
    if start_idx >= len(lines):
        return ""

    result = [lines[start_idx]]
    if indent_based:
        # Python: collect lines with greater indentation
        base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
        for i in range(start_idx + 1, min(start_idx + 50, len(lines))):
            line = lines[i]
            if line.strip() == "":
                result.append(line)
                continue
            indent = len(line) - len(line.lstrip())
            if indent > base_indent:
                result.append(line)
            else:
                break

    return "\n".join(result)


def _resolve_import(imp: str, file_set: set[str]) -> str | None:
    """Try to resolve an import name to a file in the project.

    Skips partial matching when the last component is <=2 chars to avoid
    false positives from minified/bundled single-letter module names.
    """
    # Convert module path to file path
    candidates = [
        imp.replace(".", "/") + ".py",
        imp.replace(".", "/") + "/__init__.py",
        imp.replace(".", "/") + ".ts",
        imp.replace(".", "/") + ".js",
    ]
    for candidate in candidates:
        if candidate in file_set:
            return candidate

    # Try partial match (last component) — but only if it's long enough
    # to avoid false positives (e.g. "d" matching everything ending in /d.py)
    last = imp.rsplit(".", 1)[-1]
    if len(last) > 2:
        for f in file_set:
            if f.endswith(f"/{last}.py") or f.endswith(f"/{last}.ts") or f.endswith(f"/{last}.js"):
                return f

    return None


def resolve_pending_edges(
    all_units: list[FileIntelligenceUnit],
) -> tuple[int, int]:
    """Second pass: resolve pending edges against the complete node set.

    After streaming, all node IDs are known. IMPORT edges that were deferred
    because their target wasn't scanned yet can now be resolved.

    Unresolvable edges (external imports like 'pydantic', 'typer') are removed
    from the edge count since they're external dependencies, not dangling edges.

    Returns: (resolved_count, external_count)
    """
    # Build complete node ID set and module→file_path mapping
    all_node_ids: set[str] = set()
    module_to_file: dict[str, str] = {}  # "graqle.intelligence.models" → "graqle/intelligence/models.py"

    for unit in all_units:
        file_path = unit.file_path
        for node in unit.nodes:
            all_node_ids.add(node.id)
        # Map module name variants to file path
        mod = file_path.replace("/", ".").replace("\\", ".")
        for suffix in (".py", ".js", ".ts", ".jsx", ".tsx"):
            if mod.endswith(suffix):
                mod = mod[:-len(suffix)]
                break
        module_to_file[mod] = file_path
        # Also map last component: "models" → file path
        # Skip single/double-char names to avoid minified module false positives
        last_part = mod.rsplit(".", 1)[-1]
        if len(last_part) > 2 and last_part not in module_to_file:
            module_to_file[last_part] = file_path

    resolved_total = 0
    external_total = 0

    for unit in all_units:
        if not hasattr(unit, "_pending_edges") or not unit._pending_edges:
            continue

        newly_resolved = []
        external_edges = []

        for edge_dict in unit._pending_edges:
            source = edge_dict["source"]
            target = edge_dict["target"]
            rel = edge_dict.get("relationship", "IMPORTS")
            props = edge_dict.get("properties", {})

            # Try to resolve target
            resolved_target = _resolve_edge_target(target, all_node_ids, module_to_file)
            resolved_source = source if source in all_node_ids else _resolve_edge_target(source, all_node_ids, module_to_file)

            if resolved_source and resolved_target and resolved_source != resolved_target:
                newly_resolved.append(ValidatedEdge(
                    source=resolved_source,
                    target=resolved_target,
                    relationship=rel,
                    properties=props,
                ))
            else:
                # Unresolvable = external dependency (not a quality issue)
                external_edges.append(edge_dict)

        # Add resolved edges to the unit
        if newly_resolved:
            unit.edges = list(unit.edges) + newly_resolved
            unit.coverage.valid_edges += len(newly_resolved)
            unit.coverage.pending_edges = max(0, unit.coverage.pending_edges - len(newly_resolved))

        # Remove external edges from total count (they're not dangling, just external)
        if external_edges:
            unit.coverage.total_edges = max(0, unit.coverage.total_edges - len(external_edges))
            unit.coverage.pending_edges = max(0, unit.coverage.pending_edges - len(external_edges))

        resolved_total += len(newly_resolved)
        external_total += len(external_edges)

    return resolved_total, external_total


def _resolve_edge_target(
    target: str, all_node_ids: set[str], module_to_file: dict[str, str]
) -> str | None:
    """Try to resolve an edge target to a known node ID."""
    # Direct match
    if target in all_node_ids:
        return target

    # Module name → file path
    if target in module_to_file:
        file_path = module_to_file[target]
        if file_path in all_node_ids:
            return file_path

    # Dotted module → file path conversion
    file_candidates = [
        target.replace(".", "/") + ".py",
        target.replace(".", "/") + "/__init__.py",
        target.replace(".", "/") + ".ts",
        target.replace(".", "/") + ".js",
    ]
    for candidate in file_candidates:
        if candidate in all_node_ids:
            return candidate

    # Last component match
    last_part = target.rsplit(".", 1)[-1]
    if last_part in module_to_file:
        file_path = module_to_file[last_part]
        if file_path in all_node_ids:
            return file_path

    return None


def _is_internal_import(imp: str, root: Path | None) -> bool:
    """Check if an import is internal (project module) vs external (pip package)."""
    if root is None:
        return False
    # If the import path starts with a known project directory, it's internal
    first_part = imp.split(".")[0]
    return (root / first_part).exists()
