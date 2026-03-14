"""graq scan — auto-discover code-as-graph from a repository.

Production-quality repository scanner that discovers Python/JS/TS modules,
classes, functions, API endpoints, ORM models, tests, configs, Docker services,
CI pipelines, dependencies, and environment variables — then builds a rich
knowledge graph with typed nodes and edges.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from graqle.cli.console import BRAND_NAME
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()
logger = logging.getLogger("graqle.cli.scan")

# ---------------------------------------------------------------------------
# Node & Edge Type Registries
# ---------------------------------------------------------------------------

NODE_TYPES = {
    "PythonModule": "Python source file",
    "JavaScriptModule": "JavaScript/TypeScript source file",
    "Class": "Class definition",
    "Function": "Function/method definition",
    "APIEndpoint": "API route/endpoint",
    "DatabaseModel": "ORM model/schema",
    "TestFile": "Test file",
    "Config": "Configuration file",
    "EnvVar": "Environment variable",
    "Dependency": "External dependency",
    "Directory": "Directory/package",
    "DockerService": "Docker container/service",
    "CIPipeline": "CI/CD pipeline",
}

EDGE_TYPES = {
    "IMPORTS": "Code import dependency",
    "CONTAINS": "Directory contains file",
    "TESTS": "Test file tests source file",
    "CONFIGURES": "Config configures service",
    "DEPENDS_ON": "Depends on external package",
    "DEFINES": "File defines class/function",
    "CALLS": "Function calls another function",
    "ROUTES_TO": "API route maps to handler",
    "MODELS": "ORM model for database table",
    "USES_ENVVAR": "Uses environment variable",
}

# Directories to always skip (source code only — no build artifacts)
SKIP_DIRS = frozenset({
    # Python
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info", ".eggs",
    "site-packages",
    # JavaScript / Node
    "node_modules", ".next", ".turbo", ".vercel",
    # Build outputs (all languages)
    "dist", "build", "out", "_build", "target",
    # IDE / editor
    ".idea", ".vscode",
    # VCS
    ".git",
    # Caches / coverage
    ".cache", "coverage", ".coverage", ".nyc_output",
    # Misc build artifacts
    ".cargo", ".gradle", ".mvn",
})

# ---------------------------------------------------------------------------
# Python Analyzer (AST-based)
# ---------------------------------------------------------------------------

class PythonAnalyzer:
    """Analyze Python files using the ``ast`` module."""

    # Route-decorator keywords (FastAPI, Flask, Django-ninja, etc.)
    _ROUTE_KEYWORDS = {"route", "get", "post", "put", "delete", "patch", "api_view", "websocket"}

    # ORM base-class names
    _ORM_BASES = {"Model", "Base", "DeclarativeBase", "SQLModel", "Document"}

    def analyze_file(self, path: Path) -> dict[str, Any]:
        """Return imports, classes, functions, routes, env_vars, models, calls."""
        empty: dict[str, Any] = {
            "imports": [],
            "classes": [],
            "functions": [],
            "routes": [],
            "env_vars": [],
            "models": [],
            "calls": [],
        }
        try:
            source = path.read_text(errors="ignore")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return empty

        imports: list[str] = []
        classes: list[str] = []
        functions: list[str] = []
        routes: list[dict[str, str]] = []
        env_vars: list[str] = []
        models: list[str] = []
        calls: list[str] = []

        for node in ast.walk(tree):
            # --- Imports ---------------------------------------------------
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

            # --- Classes ---------------------------------------------------
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
                # Detect ORM models by base class names
                for base in node.bases:
                    base_name = _attr_name(base)
                    if base_name and any(k in base_name for k in self._ORM_BASES):
                        models.append(node.name)
                        break

            # --- Functions & routes ----------------------------------------
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)

                # Check decorators for route patterns
                for dec in node.decorator_list:
                    dec_name = _decorator_name(dec)
                    if dec_name and any(kw in dec_name.lower() for kw in self._ROUTE_KEYWORDS):
                        route_path = _decorator_first_arg(dec) or f"/{node.name}"
                        routes.append({"handler": node.name, "path": route_path, "method": dec_name})

            # --- Env vars & function calls ---------------------------------
            elif isinstance(node, ast.Call):
                func_name = _call_name(node)
                if func_name:
                    # Track outgoing calls (top-level only for sanity)
                    calls.append(func_name)

                    # os.environ.get / os.getenv / environ.get
                    if "getenv" in func_name or "environ" in func_name:
                        for arg in node.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                env_vars.append(arg.value)

            # --- os.environ["KEY"] subscript access ------------------------
            elif isinstance(node, ast.Subscript):
                val_name = _attr_name(node.value) if hasattr(node, "value") else ""
                if val_name and "environ" in val_name:
                    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        env_vars.append(node.slice.value)

        return {
            "imports": imports,
            "classes": classes,
            "functions": functions,
            "routes": routes,
            "env_vars": list(set(env_vars)),
            "models": models,
            "calls": calls,
        }


# ---------------------------------------------------------------------------
# JS / TS Analyzer (regex-based)
# ---------------------------------------------------------------------------

class JSAnalyzer:
    """Analyze JavaScript / TypeScript files using regex patterns."""

    IMPORT_PATTERN = re.compile(
        r"""(?:import\s+(?:.*?\s+from\s+)?|require\s*\(\s*)['\"]([^'"]+)['\"]""",
    )
    ROUTE_PATTERN = re.compile(
        r"""(?:app|router|server)\.(get|post|put|delete|patch|all)\s*\(\s*['\"]([^'"]+)""",
        re.IGNORECASE,
    )
    NEXT_PAGE_PATTERN = re.compile(
        r"""export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)""",
    )
    ENV_PATTERN = re.compile(r"process\.env\.(\w+)")
    ENV_PATTERN_VITE = re.compile(r"import\.meta\.env\.(\w+)")
    CLASS_PATTERN = re.compile(r"(?:class|interface)\s+(\w+)")
    FUNCTION_PATTERN = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
    )
    REACT_COMPONENT = re.compile(
        r"(?:export\s+)?(?:default\s+)?(?:const|function)\s+([A-Z]\w+)",
    )

    def analyze_file(self, path: Path) -> dict[str, Any]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {"imports": [], "classes": [], "functions": [], "routes": [], "env_vars": []}

        # Merge named groups from FUNCTION_PATTERN
        raw_fns = self.FUNCTION_PATTERN.findall(content)
        functions = [g1 or g2 for g1, g2 in raw_fns if g1 or g2][:30]

        routes_raw = self.ROUTE_PATTERN.findall(content)
        routes = [{"method": m.upper(), "path": p} for m, p in routes_raw]

        env_vars = list(set(
            self.ENV_PATTERN.findall(content) + self.ENV_PATTERN_VITE.findall(content),
        ))

        return {
            "imports": self.IMPORT_PATTERN.findall(content),
            "classes": self.CLASS_PATTERN.findall(content),
            "functions": functions,
            "routes": routes,
            "env_vars": env_vars,
        }


# ---------------------------------------------------------------------------
# Gitignore Matcher (lightweight)
# ---------------------------------------------------------------------------

class GitignoreMatcher:
    """Simple .gitignore pattern matching (covers most common patterns).

    Also reads ``.graqle-ignore`` if present, applying the same syntax.
    Extra patterns can be supplied via *extra_patterns* (e.g. from ``--exclude``).
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        extra_patterns: list[str] | None = None,
    ) -> None:
        self._patterns: list[re.Pattern[str]] = []
        for ignore_file in (".gitignore", ".graqle-ignore"):
            gi = repo_root / ignore_file
            if gi.is_file():
                self._load_file(gi)
        if extra_patterns:
            for pat in extra_patterns:
                pat = pat.strip()
                if pat and not pat.startswith("#"):
                    self._patterns.append(self._compile(pat))

    def _load_file(self, path: Path) -> None:
        """Load patterns from a gitignore-style file."""
        for raw_line in path.read_text(errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            self._patterns.append(self._compile(line))

    @staticmethod
    def _compile(pattern: str) -> re.Pattern[str]:
        """Convert a gitignore glob to a regex."""
        neg = False
        if pattern.startswith("!"):
            neg = True
            pattern = pattern[1:]
        pattern = pattern.rstrip("/")
        # Escape and convert globs
        regex = pattern.replace(".", r"\.")
        regex = regex.replace("**", "<<<GLOBSTAR>>>")
        regex = regex.replace("*", "[^/]*")
        regex = regex.replace("<<<GLOBSTAR>>>", ".*")
        regex = regex.replace("?", "[^/]")
        # Match at any directory level if no leading /
        if not regex.startswith("/"):
            regex = f"(?:^|.*/){regex}"
        else:
            regex = "^" + regex[1:]
        regex += "(?:/.*)?$"
        return re.compile(regex)

    def is_ignored(self, rel_path: str) -> bool:
        """Return True if *rel_path* matches any ignore pattern."""
        for pat in self._patterns:
            if pat.search(rel_path):
                return True
        return False


# ---------------------------------------------------------------------------
# Repository Scanner
# ---------------------------------------------------------------------------

class RepoScanner:
    """Walk a repository and build a rich knowledge graph."""

    def __init__(
        self,
        root: Path,
        *,
        max_depth: int = 5,
        include_tests: bool = True,
        verbose: bool = False,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.max_depth = max_depth
        self.include_tests = include_tests
        self.verbose = verbose

        self.py_analyzer = PythonAnalyzer()
        self.js_analyzer = JSAnalyzer()
        self.gitignore = GitignoreMatcher(self.root, extra_patterns=exclude_patterns)

        # Graph data (networkx-style node_link_data)
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []
        self._edge_id = 0

        # Bookkeeping
        self._py_files: dict[str, Path] = {}  # node_id -> Path
        self._js_files: dict[str, Path] = {}

    # -- Public API ---------------------------------------------------------

    def scan(self) -> dict[str, Any]:
        """Execute the full scan and return networkx node_link_data dict."""
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            # Phase 1: collect files
            task = progress.add_task("[cyan]Collecting files...", total=None)
            all_files = self._collect_files()
            progress.update(task, completed=100, total=100)

            total = len(all_files)
            task2 = progress.add_task("[cyan]Analyzing files...", total=total)

            for file_path in all_files:
                self._process_file(file_path)
                progress.advance(task2)

            # Phase 2: cross-file analysis
            task3 = progress.add_task("[cyan]Resolving cross-references...", total=4)
            self._resolve_imports()
            progress.advance(task3)
            self._discover_test_links()
            progress.advance(task3)
            self._discover_dependencies()
            progress.advance(task3)
            self._discover_infra()
            progress.advance(task3)

        return self._to_node_link_data()

    def summary(self) -> str:
        """Return a human-readable scan summary."""
        type_counts: Counter[str] = Counter()
        edge_counts: Counter[str] = Counter()
        for n in self._nodes.values():
            type_counts[n.get("type", "Unknown")] += 1
        for e in self._edges:
            edge_counts[e.get("relationship", "UNKNOWN")] += 1
        return _format_summary(self.root, type_counts, edge_counts, len(self._nodes), len(self._edges))

    # -- File collection ----------------------------------------------------

    def _collect_files(self) -> list[Path]:
        """Recursively collect files respecting depth, skip-dirs, and gitignore."""
        files: list[Path] = []
        for item in self._walk(self.root, depth=0):
            files.append(item)
        return files

    def _walk(self, directory: Path, depth: int) -> list[Path]:
        if depth > self.max_depth:
            return []
        results: list[Path] = []
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return results

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env", ".github", ".gitlab-ci.yml"}:
                if entry.name in {".github"}:
                    pass  # we want .github
                else:
                    continue

            if entry.is_dir():
                if entry.name in SKIP_DIRS:
                    continue
                rel = str(entry.relative_to(self.root)).replace("\\", "/")
                if self.gitignore.is_ignored(rel):
                    continue
                # Add directory node
                self._add_dir_node(entry)
                results.extend(self._walk(entry, depth + 1))
            else:
                rel = str(entry.relative_to(self.root)).replace("\\", "/")
                if self.gitignore.is_ignored(rel):
                    continue
                results.append(entry)
        return results

    # -- File processing (dispatch) -----------------------------------------

    def _process_file(self, path: Path) -> None:
        suffix = path.suffix.lower()
        name = path.name.lower()

        if suffix == ".py":
            self._process_python(path)
        elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            self._process_js(path)
        elif name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            self._process_docker(path)
        elif name in {"package.json", "requirements.txt", "pyproject.toml", "setup.cfg", "setup.py", "Pipfile", "poetry.lock"}:
            self._process_dependency_file(path)
        elif name == ".env" or (name.startswith(".env") and suffix in {"", ".local", ".example", ".sample"}):
            self._process_env_file(path)
        elif name == "readme.md":
            self._process_readme(path)
        elif suffix in {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}:
            self._process_config(path)

        # CI/CD detection (handled in _discover_infra for .github/workflows)

    # -- Python files -------------------------------------------------------

    def _process_python(self, path: Path) -> None:
        rel = self._rel(path)
        is_test = _is_test_file(path)
        if is_test and not self.include_tests:
            return

        node_type = "TestFile" if is_test else "PythonModule"
        node_id = rel

        # T1: Rich description + T2: Semantic chunks + T3: file_path
        description, chunks = self._extract_content(path, "Python")
        node_attrs: dict[str, Any] = {
            "label": path.stem,
            "type": node_type,
            "description": description,
            "file_path": str(path.resolve()),
        }
        if chunks:
            node_attrs["chunks"] = chunks
            node_attrs["chunk_count"] = len(chunks)

        self._add_node(node_id, **node_attrs)
        self._py_files[node_id] = path

        # Parent dir edge
        self._add_contains_edge(path, node_id)

        # AST analysis
        info = self.py_analyzer.analyze_file(path)

        # Classes
        for cls_name in info["classes"]:
            cls_id = f"{rel}::{cls_name}"
            self._add_node(cls_id, label=cls_name, type="Class", description=f"Class {cls_name} in {rel}")
            self._add_edge(node_id, cls_id, "DEFINES")

        # Functions (top-level only — skip dunder unless route)
        for fn_name in info["functions"]:
            if fn_name.startswith("_") and not any(r["handler"] == fn_name for r in info["routes"]):
                continue  # skip private helpers to reduce noise
            fn_id = f"{rel}::{fn_name}"
            self._add_node(fn_id, label=fn_name, type="Function", description=f"Function {fn_name} in {rel}")
            self._add_edge(node_id, fn_id, "DEFINES")

        # Routes
        for route in info["routes"]:
            ep_id = f"endpoint::{route['path']}"
            handler_id = f"{rel}::{route['handler']}"
            self._add_node(
                ep_id,
                label=route["path"],
                type="APIEndpoint",
                description=f"API endpoint {route.get('method', '')} {route['path']}",
                method=route.get("method", ""),
            )
            if handler_id in self._nodes:
                self._add_edge(ep_id, handler_id, "ROUTES_TO")

        # ORM models
        for model_name in info["models"]:
            model_id = f"model::{model_name}"
            self._add_node(model_id, label=model_name, type="DatabaseModel", description=f"ORM model {model_name}")
            cls_id = f"{rel}::{model_name}"
            if cls_id in self._nodes:
                self._add_edge(cls_id, model_id, "MODELS")

        # Env vars
        for ev in info["env_vars"]:
            ev_id = f"env::{ev}"
            self._add_node(ev_id, label=ev, type="EnvVar", description=f"Environment variable {ev}")
            self._add_edge(node_id, ev_id, "USES_ENVVAR")

    # -- JS/TS files --------------------------------------------------------

    def _process_js(self, path: Path) -> None:
        rel = self._rel(path)
        is_test = _is_test_file(path)
        if is_test and not self.include_tests:
            return

        node_type = "TestFile" if is_test else "JavaScriptModule"
        node_id = rel

        # T1: Rich description + T2: Semantic chunks + T3: file_path
        description, chunks = self._extract_content(path, "JS/TS")
        node_attrs: dict[str, Any] = {
            "label": path.stem,
            "type": node_type,
            "description": description,
            "file_path": str(path.resolve()),
        }
        if chunks:
            node_attrs["chunks"] = chunks
            node_attrs["chunk_count"] = len(chunks)

        self._add_node(node_id, **node_attrs)
        self._js_files[node_id] = path

        self._add_contains_edge(path, node_id)

        info = self.js_analyzer.analyze_file(path)

        for cls_name in info["classes"]:
            cls_id = f"{rel}::{cls_name}"
            self._add_node(cls_id, label=cls_name, type="Class", description=f"Class/Interface {cls_name} in {rel}")
            self._add_edge(node_id, cls_id, "DEFINES")

        for fn_name in info["functions"][:20]:
            fn_id = f"{rel}::{fn_name}"
            self._add_node(fn_id, label=fn_name, type="Function", description=f"Function {fn_name} in {rel}")
            self._add_edge(node_id, fn_id, "DEFINES")

        for route in info["routes"]:
            ep_id = f"endpoint::{route['path']}"
            self._add_node(
                ep_id, label=route["path"], type="APIEndpoint",
                description=f"API endpoint {route['method']} {route['path']}",
                method=route["method"],
            )
            self._add_edge(node_id, ep_id, "ROUTES_TO")

        for ev in info["env_vars"]:
            ev_id = f"env::{ev}"
            self._add_node(ev_id, label=ev, type="EnvVar", description=f"Environment variable {ev}")
            self._add_edge(node_id, ev_id, "USES_ENVVAR")

    # -- Config files -------------------------------------------------------

    def _process_config(self, path: Path) -> None:
        rel = self._rel(path)
        # Read config content for T2 chunks
        config_chunks: list[dict[str, str]] = []
        config_desc = f"Configuration: {rel}"
        try:
            config_content = path.read_text(encoding="utf-8", errors="ignore")
            if config_content.strip():
                config_chunks = [{"text": config_content[:3000], "type": "config"}]
                config_desc = f"Configuration: {path.name}. " + config_content[:200].replace("\n", " ")
        except Exception:
            pass

        node_attrs: dict[str, Any] = {
            "label": path.name,
            "type": "Config",
            "description": config_desc,
            "file_path": str(path.resolve()),
        }
        if config_chunks:
            node_attrs["chunks"] = config_chunks
            node_attrs["chunk_count"] = len(config_chunks)
        self._add_node(rel, **node_attrs)
        self._add_contains_edge(path, rel)

        # CI/CD pipelines
        rel_parts = rel.replace("\\", "/")
        if ".github/workflows" in rel_parts or "gitlab-ci" in path.name.lower():
            ci_id = f"ci::{path.stem}"
            self._add_node(ci_id, label=path.stem, type="CIPipeline", description=f"CI/CD pipeline: {path.name}")
            self._add_edge(rel, ci_id, "CONFIGURES")

    # -- Docker files -------------------------------------------------------

    def _process_docker(self, path: Path) -> None:
        rel = self._rel(path)
        self._add_node(rel, label=path.name, type="Config", description=f"Docker config: {rel}")
        self._add_contains_edge(path, rel)

        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return

        name_lower = path.name.lower()
        if name_lower == "dockerfile":
            svc_id = f"docker::{path.parent.name or 'main'}"
            self._add_node(svc_id, label=path.parent.name or "main", type="DockerService",
                           description=f"Docker service from {rel}")
            self._add_edge(rel, svc_id, "CONFIGURES")

            # Extract env vars from ENV directives
            for match in re.finditer(r"^ENV\s+(\w+)", content, re.MULTILINE):
                ev_id = f"env::{match.group(1)}"
                self._add_node(ev_id, label=match.group(1), type="EnvVar",
                               description=f"Environment variable {match.group(1)}")
                self._add_edge(svc_id, ev_id, "USES_ENVVAR")
        else:
            # docker-compose: extract service names
            for match in re.finditer(r"^\s{2}(\w[\w-]*):\s*$", content, re.MULTILINE):
                svc_name = match.group(1)
                if svc_name in {"version", "services", "volumes", "networks", "configs", "secrets"}:
                    continue
                svc_id = f"docker::{svc_name}"
                self._add_node(svc_id, label=svc_name, type="DockerService",
                               description=f"Docker Compose service: {svc_name}")
                self._add_edge(rel, svc_id, "CONFIGURES")

    # -- Dependency files ---------------------------------------------------

    def _process_dependency_file(self, path: Path) -> None:
        rel = self._rel(path)
        self._add_node(rel, label=path.name, type="Config", description=f"Dependency manifest: {rel}")
        self._add_contains_edge(path, rel)

    # -- .env files ---------------------------------------------------------

    def _process_env_file(self, path: Path) -> None:
        rel = self._rel(path)
        self._add_node(rel, label=path.name, type="Config", description=f"Environment config: {rel}")
        self._add_contains_edge(path, rel)

        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                var_name = line.split("=", 1)[0].strip()
                if var_name:
                    ev_id = f"env::{var_name}"
                    # names only, no values!
                    self._add_node(ev_id, label=var_name, type="EnvVar",
                                   description=f"Environment variable {var_name}")
                    self._add_edge(rel, ev_id, "CONFIGURES")

    # -- README -------------------------------------------------------------

    def _process_readme(self, path: Path) -> None:
        rel = self._rel(path)
        try:
            content = path.read_text(errors="ignore")[:2000]
        except Exception:
            content = ""
        # Extract first paragraph as description
        desc = ""
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                desc = line[:200]
                break
        self._add_node(rel, label="README", type="Config", description=desc or f"Project readme: {rel}")

    # -- Cross-file resolution (Phase 2) ------------------------------------

    def _resolve_imports(self) -> None:
        """Resolve import statements to actual file nodes."""
        # Build module-name -> node-id index for Python
        py_module_index: dict[str, str] = {}
        for node_id in self._py_files:
            # e.g., "graqle/core/graph.py" -> "graqle.core.graph"
            mod = node_id.replace("/", ".").replace("\\", ".")
            if mod.endswith(".py"):
                mod = mod[:-3]
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            py_module_index[mod] = node_id

        for node_id, path in self._py_files.items():
            info = self.py_analyzer.analyze_file(path)
            for imp in info["imports"]:
                # Try exact match then prefix match
                target = py_module_index.get(imp)
                if target is None:
                    # Try sub-module: "graqle.core" matches "graqle/core/__init__.py"
                    for mod_name, nid in py_module_index.items():
                        if mod_name.startswith(imp) or imp.startswith(mod_name):
                            target = nid
                            break
                if target and target != node_id:
                    self._add_edge(node_id, target, "IMPORTS")

        # JS/TS import resolution (relative imports)
        for node_id, path in self._js_files.items():
            info = self.js_analyzer.analyze_file(path)
            parent_dir = path.parent
            for imp in info["imports"]:
                if imp.startswith("."):
                    # Relative import — resolve to file
                    resolved = self._resolve_js_import(parent_dir, imp)
                    if resolved:
                        self._add_edge(node_id, resolved, "IMPORTS")

    def _resolve_js_import(self, from_dir: Path, import_path: str) -> str | None:
        """Resolve a relative JS import to a node id."""
        try:
            candidate = (from_dir / import_path).resolve()
        except (ValueError, OSError):
            return None

        suffixes = ["", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", "/index.tsx"]
        for suffix in suffixes:
            full = Path(str(candidate) + suffix)
            if full.is_file():
                try:
                    rel = str(full.relative_to(self.root)).replace("\\", "/")
                    if rel in self._nodes:
                        return rel
                except ValueError:
                    pass
        return None

    def _discover_test_links(self) -> None:
        """Link test files to their likely source files."""
        test_nodes = [nid for nid, n in self._nodes.items() if n.get("type") == "TestFile"]
        source_nodes = {
            nid for nid, n in self._nodes.items()
            if n.get("type") in ("PythonModule", "JavaScriptModule")
        }

        for test_id in test_nodes:
            # Heuristic: test_foo.py tests foo.py; foo.test.ts tests foo.ts
            test_name = Path(test_id).stem
            # Strip test_ prefix and _test / .test suffix
            source_stem = test_name
            for prefix in ("test_", "test-"):
                if source_stem.startswith(prefix):
                    source_stem = source_stem[len(prefix):]
            for suffix in ("_test", "-test", ".test", ".spec"):
                if source_stem.endswith(suffix):
                    source_stem = source_stem[: -len(suffix)]

            # Find matching source file
            for src_id in source_nodes:
                src_stem = Path(src_id).stem
                if src_stem == source_stem:
                    self._add_edge(test_id, src_id, "TESTS")
                    break

    def _discover_dependencies(self) -> None:
        """Parse dependency manifests into Dependency nodes."""
        for node_id, node in list(self._nodes.items()):
            if node.get("type") != "Config":
                continue
            name = Path(node_id).name.lower()
            path = self.root / node_id

            if name == "requirements.txt":
                self._parse_requirements_txt(path, node_id)
            elif name == "pyproject.toml":
                self._parse_pyproject_toml(path, node_id)
            elif name == "package.json":
                self._parse_package_json(path, node_id)

    def _parse_requirements_txt(self, path: Path, config_id: str) -> None:
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            pkg = re.split(r"[>=<!\[;]", line)[0].strip()
            if pkg:
                dep_id = f"dep::{pkg}"
                self._add_node(dep_id, label=pkg, type="Dependency", description=f"Python package: {pkg}")
                self._add_edge(config_id, dep_id, "DEPENDS_ON")

    def _parse_pyproject_toml(self, path: Path, config_id: str) -> None:
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return
        # Simple regex to find dependencies list
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in {"[project]", "[tool.poetry.dependencies]"} or "dependencies" in stripped:
                in_deps = "dependencies" in stripped or in_deps
            if in_deps and stripped.startswith('"'):
                pkg = re.split(r"[>=<!\[;]", stripped.strip('"').strip("'").strip(","))[0].strip()
                if pkg:
                    dep_id = f"dep::{pkg}"
                    self._add_node(dep_id, label=pkg, type="Dependency", description=f"Python package: {pkg}")
                    self._add_edge(config_id, dep_id, "DEPENDS_ON")
            elif in_deps and stripped.startswith("[") and "dependencies" not in stripped:
                in_deps = False

    def _parse_package_json(self, path: Path, config_id: str) -> None:
        try:
            data = json.loads(path.read_text(errors="ignore"))
        except Exception:
            return
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            deps = data.get(section, {})
            if isinstance(deps, dict):
                for pkg in deps:
                    dep_id = f"dep::{pkg}"
                    self._add_node(dep_id, label=pkg, type="Dependency", description=f"NPM package: {pkg}")
                    self._add_edge(config_id, dep_id, "DEPENDS_ON")

    def _discover_infra(self) -> None:
        """Discover CI/CD pipelines in .github/workflows."""
        workflows_dir = self.root / ".github" / "workflows"
        if workflows_dir.is_dir():
            for wf in workflows_dir.iterdir():
                if wf.suffix in {".yml", ".yaml"}:
                    rel = self._rel(wf)
                    if rel not in self._nodes:
                        self._add_node(rel, label=wf.name, type="Config", description=f"CI config: {wf.name}")
                    ci_id = f"ci::{wf.stem}"
                    self._add_node(ci_id, label=wf.stem, type="CIPipeline",
                                   description=f"GitHub Actions workflow: {wf.stem}")
                    self._add_edge(rel, ci_id, "CONFIGURES")

        # GitLab CI
        gl_ci = self.root / ".gitlab-ci.yml"
        if gl_ci.is_file():
            rel = self._rel(gl_ci)
            if rel not in self._nodes:
                self._add_node(rel, label=gl_ci.name, type="Config", description="GitLab CI config")
            ci_id = "ci::gitlab"
            self._add_node(ci_id, label="gitlab-ci", type="CIPipeline", description="GitLab CI/CD pipeline")
            self._add_edge(rel, ci_id, "CONFIGURES")

    # -- Content extraction (T1/T2/T3) -------------------------------------

    def _extract_content(
        self, path: Path, lang_prefix: str
    ) -> tuple[str, list[dict[str, str]]]:
        """Extract rich description (T1) and semantic chunks (T2) from a file.

        Returns (description, chunks). Falls back to generic description on error.
        """
        rel = self._rel(path)
        fallback_desc = f"{lang_prefix}: {rel}"
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return fallback_desc, []

        if not content.strip():
            return fallback_desc, []

        description = self._summarize_file(content, rel, lang_prefix)
        chunks = self._chunk_source_code(content)
        return description, chunks

    @staticmethod
    def _summarize_file(content: str, rel: str, lang_prefix: str, max_len: int = 400) -> str:
        """Generate a rich T1 description from file content (no LLM needed).

        Extracts docstrings, JSDoc, function/class signatures, exports, and
        React component names to create a meaningful description.
        """
        lines = content.splitlines()
        parts: list[str] = []

        # Extract module docstring / JSDoc (first doc block)
        for i, line in enumerate(lines[:30]):
            stripped = line.strip()
            if stripped.startswith(('"""', "'''", "/**", "/*")):
                doc_lines = []
                for j in range(i, min(i + 10, len(lines))):
                    dl = lines[j].strip().strip('"\'*/').strip()
                    if dl:
                        doc_lines.append(dl)
                    # End of doc block
                    if j > i and lines[j].strip().endswith(('"""', "'''", "*/", "*/")):
                        break
                doc = " ".join(doc_lines)[:250]
                if doc:
                    parts.append(doc)
                break

        # Extract function/class/export signatures
        signatures: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ", "class ")):
                sig = stripped.split(":", 1)[0].split("{", 1)[0].strip()
                if not sig.startswith(("def _", "async def _")):  # skip private
                    signatures.append(sig)
            elif stripped.startswith(("export function", "export const", "export default")):
                sig = stripped[:120].split("{", 1)[0].strip()
                signatures.append(sig)

        if signatures:
            parts.append("Defines: " + ", ".join(signatures[:12]))

        # Detect React components
        react_comps = re.findall(
            r"(?:export\s+)?(?:default\s+)?(?:const|function)\s+([A-Z]\w+)",
            content,
        )
        if react_comps:
            unique = list(dict.fromkeys(react_comps))[:8]
            parts.append("Components: " + ", ".join(unique))

        if not parts:
            # Fallback: first meaningful line
            for line in lines[:15]:
                stripped = line.strip()
                if stripped and not stripped.startswith(("#", "//", "/*", "*", "import ", "from ")):
                    parts.append(stripped[:120])
                    break

        summary = f"{rel}. " + ". ".join(parts) if parts else f"{lang_prefix}: {rel}"
        return summary[:max_len]

    @staticmethod
    def _chunk_source_code(
        content: str, max_chunk_chars: int = 1500
    ) -> list[dict[str, str]]:
        """Split source code into semantic chunks at function/class boundaries.

        Returns a list of {"text": "...", "type": "function|class|imports|..."}.
        """
        lines = content.splitlines(keepends=True)
        if not lines:
            return []

        chunks: list[dict[str, str]] = []

        boundary_patterns = (
            "def ", "class ", "async def ",
            "function ", "export ", "const ", "let ",
            "import ", "from ",
            "describe(", "it(", "test(",
        )

        current_block: list[str] = []
        block_type = "source_code"

        def _flush_block() -> None:
            text = "".join(current_block).strip()
            if not text or len(text) < 20:
                return
            if len(text) > max_chunk_chars:
                sub_parts = re.split(r"\n\s*\n", text)
                accum = ""
                for part in sub_parts:
                    if len(accum) + len(part) > max_chunk_chars and accum:
                        chunks.append({"text": accum.strip(), "type": block_type})
                        accum = part
                    else:
                        accum = accum + "\n\n" + part if accum else part
                if accum.strip():
                    chunks.append({"text": accum.strip(), "type": block_type})
            else:
                chunks.append({"text": text, "type": block_type})

        for line in lines:
            stripped = line.lstrip()
            is_boundary = (
                any(stripped.startswith(p) for p in boundary_patterns)
                and not line[0:1].isspace()
            )

            if is_boundary and current_block:
                _flush_block()
                current_block = [line]
                if stripped.startswith(("def ", "async def ")):
                    block_type = "function"
                elif stripped.startswith("class "):
                    block_type = "class"
                elif stripped.startswith(("import ", "from ")):
                    block_type = "imports"
                elif stripped.startswith(("export ",)):
                    block_type = "export"
                elif stripped.startswith(("describe(", "it(", "test(")):
                    block_type = "test"
                else:
                    block_type = "source_code"
            else:
                current_block.append(line)

        if current_block:
            _flush_block()

        return chunks

    # -- Graph helpers ------------------------------------------------------

    def _add_node(self, node_id: str, **attrs: Any) -> None:
        if node_id not in self._nodes:
            self._nodes[node_id] = {"id": node_id, **attrs}

    def _add_edge(self, source: str, target: str, relationship: str) -> None:
        # Deduplicate
        for e in self._edges:
            if e["source"] == source and e["target"] == target and e["relationship"] == relationship:
                return
        self._edges.append({
            "source": source,
            "target": target,
            "relationship": relationship,
        })
        self._edge_id += 1

    def _add_dir_node(self, dir_path: Path) -> None:
        rel = self._rel(dir_path)
        self._add_node(rel, label=dir_path.name, type="Directory", description=f"Directory: {rel}")
        # Link to parent dir
        parent_rel = self._rel(dir_path.parent)
        if parent_rel and parent_rel != rel and parent_rel in self._nodes:
            self._add_edge(parent_rel, rel, "CONTAINS")

    def _add_contains_edge(self, file_path: Path, node_id: str) -> None:
        parent_rel = self._rel(file_path.parent)
        if parent_rel and parent_rel in self._nodes:
            self._add_edge(parent_rel, node_id, "CONTAINS")

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _to_node_link_data(self) -> dict[str, Any]:
        """Produce networkx-compatible node_link_data format."""
        nodes = []
        for node_id, attrs in self._nodes.items():
            node_data = {"id": node_id}
            for k, v in attrs.items():
                if k != "id":
                    node_data[k] = v
            nodes.append(node_data)

        links = []
        for edge in self._edges:
            links.append({
                "source": edge["source"],
                "target": edge["target"],
                "relationship": edge["relationship"],
            })

        return {
            "directed": True,
            "multigraph": False,
            "graph": {},
            "nodes": nodes,
            "links": links,
        }


# ---------------------------------------------------------------------------
# AST Helper Functions
# ---------------------------------------------------------------------------

def _attr_name(node: ast.expr) -> str:
    """Extract a dotted name from an AST node (e.g., ``os.environ``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _decorator_name(node: ast.expr) -> str:
    """Get the decorator function name from a decorator AST node."""
    if isinstance(node, ast.Call):
        return _attr_name(node.func)
    return _attr_name(node)


def _decorator_first_arg(node: ast.expr) -> str | None:
    """Extract the first string argument of a decorator call, e.g. @app.get('/foo')."""
    if isinstance(node, ast.Call) and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _call_name(node: ast.Call) -> str:
    """Extract the function name from a Call node."""
    return _attr_name(node.func)


def _is_test_file(path: Path) -> bool:
    """Heuristic: is this file a test file?"""
    name = path.name.lower()
    parts = [p.lower() for p in path.parts]
    if any(d in parts for d in ("tests", "test", "__tests__", "spec", "specs")):
        return True
    if name.startswith("test_") or name.startswith("test-"):
        return True
    for suffix in ("_test.py", ".test.py", ".spec.py", "_test.js", ".test.js",
                    ".spec.js", "_test.ts", ".test.ts", ".spec.ts",
                    "_test.tsx", ".test.tsx", ".spec.tsx",
                    "_test.jsx", ".test.jsx", ".spec.jsx"):
        if name.endswith(suffix):
            return True
    if name == "conftest.py":
        return True
    return False


# ---------------------------------------------------------------------------
# Summary Formatting
# ---------------------------------------------------------------------------

def _format_summary(
    root: Path,
    type_counts: Counter[str],
    edge_counts: Counter[str],
    total_nodes: int,
    total_edges: int,
) -> str:
    """Build a Rich-formatted summary string."""
    lines: list[str] = []
    lines.append(f"[bold cyan]Repository:[/bold cyan] {root.name}")
    lines.append(f"[bold]Total:[/bold] {total_nodes} nodes, {total_edges} edges\n")

    lines.append("[bold]Node Types:[/bold]")
    for ntype, count in type_counts.most_common():
        desc = NODE_TYPES.get(ntype, ntype)
        lines.append(f"  {ntype:20s} {count:5d}  ({desc})")

    lines.append("\n[bold]Edge Types:[/bold]")
    for etype, count in edge_counts.most_common():
        desc = EDGE_TYPES.get(etype, etype)
        lines.append(f"  {etype:20s} {count:5d}  ({desc})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

scan_app = typer.Typer(help="Scan a codebase to build a Graqle knowledge graph.")


@scan_app.command("repo")
def scan_repo(
    path: str = typer.Argument(".", help="Repository path to scan"),
    output: str = typer.Option("graqle.json", "--output", "-o", help="Output JSON file path"),
    depth: int = typer.Option(5, "--depth", "-d", help="Max directory depth"),
    include_tests: bool = typer.Option(True, "--tests/--no-tests", help="Include test files"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging output"),
    exclude: Optional[list[str]] = typer.Option(
        None, "--exclude", "-e",
        help="Gitignore-style patterns to exclude (repeatable, e.g. --exclude '*.log' --exclude 'tmp/')",
    ),
) -> None:
    """Scan a code repository and build a knowledge graph.

    Discovers Python & JS/TS modules, classes, functions, API endpoints,
    ORM models, tests, configs, dependencies, Docker services, CI pipelines,
    and environment variable usage.

    Output is networkx JSON format, compatible with ``Graqle.from_json()``.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    repo = Path(path).resolve()
    if not repo.exists():
        console.print(f"[red]Path not found:[/red] {repo}")
        raise typer.Exit(1)

    console.print(Panel(
        f"{BRAND_NAME} Repository Scanner\n"
        f"Path: {repo}\n"
        f"Depth: {depth} | Tests: {'yes' if include_tests else 'no'}",
        border_style="cyan",
    ))

    scanner = RepoScanner(
        repo,
        max_depth=depth,
        include_tests=include_tests,
        verbose=verbose,
        exclude_patterns=exclude,
    )

    data = scanner.scan()

    # Write JSON
    out_path = Path(output)
    out_path.write_text(json.dumps(data, indent=2, default=str))

    # Print summary
    console.print()
    console.print(scanner.summary())
    console.print()
    console.print(f"[green bold]Scan complete.[/green bold] "
                  f"{len(data['nodes'])} nodes, {len(data['links'])} edges")
    console.print(f"[dim]Saved to:[/dim] {out_path.resolve()}")


# ---------------------------------------------------------------------------
# Document scan commands
# ---------------------------------------------------------------------------


@scan_app.command("docs")
def scan_docs(
    path: str = typer.Argument(".", help="Directory to scan for documents"),
    output: str = typer.Option("graqle.json", "--output", "-o", help="Graph file path"),
    background: bool = typer.Option(False, "--background", "-b", help="Run in background"),
    no_link: bool = typer.Option(False, "--no-link", help="Skip auto-linking to code"),
    no_redact: bool = typer.Option(False, "--no-redact", help="Skip privacy redaction"),
    max_files: int = typer.Option(0, "--max-files", help="Max files to scan (0=unlimited)"),
    max_nodes: int = typer.Option(0, "--max-nodes", help="Max nodes to create (0=unlimited)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Scan documents (MD, TXT, PDF, DOCX, ...) and add to the knowledge graph.

    Discovers documents recursively, parses them into sections, creates
    Document and Section nodes, and auto-links to existing code nodes.
    """
    from graqle.scanner.docs import DocScanOptions, DocumentScanner

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    root = Path(path).resolve()
    if not root.exists():
        console.print(f"[red]Path not found:[/red] {root}")
        raise typer.Exit(1)

    graph_path = Path(output)
    nodes, edges = _load_graph_data(graph_path)
    manifest_path = graph_path.parent / ".graqle-doc-manifest.json"

    opts = DocScanOptions(
        link_exact=not no_link,
        link_fuzzy=not no_link,
        redaction_enabled=not no_redact,
        max_files=max_files,
        max_nodes=max_nodes,
    )

    scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)

    if background:
        from graqle.scanner.background import BackgroundScanManager

        files = scanner._discover_files(root)
        mgr = BackgroundScanManager(graph_path.parent)

        def run_scan(progress_cb):
            return scanner.scan_files(files, root, progress_callback=progress_cb)

        mgr.start(run_scan, len(files))
        console.print(f"[cyan]Background doc scan started:[/cyan] {len(files)} files")
        console.print("[dim]Use 'graq scan status' to check progress.[/dim]")
        return

    # Foreground scan with progress
    from rich.progress import Progress

    with Progress(console=console) as progress:
        task = progress.add_task("[cyan]Scanning documents...", total=0)

        def progress_cb(fp, idx, total):
            progress.update(task, total=total, completed=idx,
                            description=f"[cyan]{fp.name}")

        result = scanner.scan_directory(root, progress_callback=progress_cb)
        progress.update(task, completed=result.files_total)

    _save_graph_data(graph_path, nodes, edges)
    _print_doc_scan_summary(result)


@scan_app.command("file")
def scan_file(
    path: str = typer.Argument(..., help="Path to a single document file"),
    output: str = typer.Option("graqle.json", "--output", "-o", help="Graph file path"),
    no_link: bool = typer.Option(False, "--no-link", help="Skip auto-linking"),
    no_redact: bool = typer.Option(False, "--no-redact", help="Skip redaction"),
) -> None:
    """Scan a single document file and add to the knowledge graph."""
    from graqle.scanner.docs import DocScanOptions, DocumentScanner

    fp = Path(path).resolve()
    if not fp.is_file():
        console.print(f"[red]File not found:[/red] {fp}")
        raise typer.Exit(1)

    graph_path = Path(output)
    nodes, edges = _load_graph_data(graph_path)
    manifest_path = graph_path.parent / ".graqle-doc-manifest.json"

    opts = DocScanOptions(
        link_exact=not no_link,
        link_fuzzy=not no_link,
        redaction_enabled=not no_redact,
    )
    scanner = DocumentScanner(nodes, edges, options=opts, manifest_path=manifest_path)
    result = scanner.scan_file(fp)

    _save_graph_data(graph_path, nodes, edges)
    _print_doc_scan_summary(result)


@scan_app.command("all")
def scan_all(
    path: str = typer.Argument(".", help="Repository path"),
    output: str = typer.Option("graqle.json", "--output", "-o", help="Output file"),
    depth: int = typer.Option(5, "--depth", "-d", help="Max directory depth for code"),
    include_tests: bool = typer.Option(True, "--tests/--no-tests", help="Include test files"),
    no_docs: bool = typer.Option(False, "--no-docs", help="Skip document scanning"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    exclude: Optional[list[str]] = typer.Option(
        None, "--exclude", "-e", help="Patterns to exclude"),
) -> None:
    """Scan code (foreground) + JSON (foreground) + documents (background).

    Scanning order: Code AST → JSON configs → Documents.
    JSON is scanned immediately after code because it's fast and produces
    bridge nodes that help document linking.
    """
    # Step 1: Code scan (foreground)
    scan_repo(path=path, output=output, depth=depth,
              include_tests=include_tests, verbose=verbose, exclude=exclude)

    # Step 2: JSON scan (foreground — fast, produces bridge nodes)
    console.print()
    console.print("[bold cyan]Phase 2:[/bold cyan] Scanning JSON configs...")
    try:
        from graqle.scanner.json_parser import JSONScanner

        root = Path(path).resolve()
        gp = Path(output)
        nodes, edges = _load_graph_data(gp)
        json_scanner = JSONScanner(nodes, edges)
        json_result = json_scanner.scan_directory(root)
        if json_result.nodes_added > 0:
            _save_graph_data(gp, nodes, edges)
            console.print(
                f"  [green]✓[/green] JSON: {json_result.files_scanned} files, "
                f"{json_result.nodes_added} nodes, {json_result.edges_added} edges "
                f"({json_result.duration_seconds:.1f}s)"
            )
        else:
            console.print("  [dim]No JSON knowledge files found.[/dim]")
    except Exception as exc:
        console.print(f"  [yellow]JSON scan skipped: {exc}[/yellow]")

    if no_docs:
        return

    # Step 3: Doc scan (background)
    console.print()
    scan_docs(path=path, output=output, background=True, no_link=False,
              no_redact=False, max_files=0, max_nodes=0, verbose=verbose)


@scan_app.command("status")
def scan_status() -> None:
    """Show background document scan progress."""
    from graqle.scanner.background import BackgroundScanManager

    mgr = BackgroundScanManager(".")
    progress = mgr.get_progress()

    if progress.status == "idle":
        console.print("[dim]No background scan in progress.[/dim]")
        return

    pct = (progress.processed / progress.total * 100) if progress.total > 0 else 0

    table = Table(title="Document Scan Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Status", f"[bold]{progress.status}[/bold]")
    table.add_row("Progress", f"{progress.processed}/{progress.total} ({pct:.0f}%)")
    table.add_row("Current File", progress.current_file or "-")
    table.add_row("Nodes Added", str(progress.nodes_added))
    table.add_row("Edges Added", str(progress.edges_added))
    table.add_row("Started", progress.started_at or "-")
    if progress.completed_at:
        table.add_row("Completed", progress.completed_at)
    if progress.duration_seconds > 0:
        table.add_row("Duration", f"{progress.duration_seconds:.1f}s")
    if progress.errors:
        table.add_row("Errors", str(len(progress.errors)))

    console.print(table)


@scan_app.command("wait")
def scan_wait(
    timeout: int = typer.Option(300, "--timeout", "-t", help="Max seconds to wait"),
) -> None:
    """Block until background document scan completes."""
    from graqle.scanner.background import BackgroundScanManager
    import time as _time

    mgr = BackgroundScanManager(".")
    progress = mgr.get_progress()

    if progress.status not in ("running",):
        console.print(f"[dim]No scan running (status: {progress.status}).[/dim]")
        return

    console.print("[cyan]Waiting for background scan to complete...[/cyan]")
    deadline = _time.time() + timeout

    while _time.time() < deadline:
        progress = mgr.get_progress()
        if progress.status != "running":
            break
        _time.sleep(1)

    progress = mgr.get_progress()
    console.print(f"[bold]Scan {progress.status}.[/bold] "
                  f"{progress.nodes_added} nodes, {progress.edges_added} edges.")


@scan_app.command("cancel")
def scan_cancel() -> None:
    """Cancel a running background document scan."""
    from graqle.scanner.background import BackgroundScanManager

    mgr = BackgroundScanManager(".")
    progress = mgr.get_progress()

    if progress.status != "running":
        console.print("[dim]No scan running to cancel.[/dim]")
        return

    mgr.cancel()
    console.print("[yellow]Background scan cancellation requested.[/yellow]")


@scan_app.command("json")
def scan_json(
    path: str = typer.Argument(".", help="Directory to scan for JSON files"),
    graph_path: str = typer.Option("graqle.json", "--graph", "-g"),
) -> None:
    """Scan JSON files (package.json, openapi.json, configs) for knowledge.

    JSON is the bridge layer between code and documents — small, fast,
    structured, and knowledge-dense. Extracts dependencies, API endpoints,
    infrastructure resources, tool rules, and app config values.

    Examples:
        graq scan json .
        graq scan json ./configs --graph my_graph.json
    """
    from graqle.scanner.json_parser import JSONScanner

    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Not a directory:[/red] {root}")
        raise typer.Exit(1)

    gp = Path(graph_path)
    nodes, edges = _load_graph_data(gp)

    scanner = JSONScanner(nodes, edges)

    from rich.progress import Progress

    with Progress(console=console) as progress:
        task = progress.add_task("[cyan]Scanning JSON files...", total=0)

        def progress_cb(fp, idx, total):
            progress.update(task, total=total, completed=idx,
                            description=f"[cyan]{fp.name}")

        result = scanner.scan_directory(root, progress_callback=progress_cb)
        progress.update(task, completed=result.files_scanned + result.files_skipped)

    _save_graph_data(gp, nodes, edges)
    _print_json_scan_summary(result)


# ---------------------------------------------------------------------------
# Helpers for doc scan CLI commands
# ---------------------------------------------------------------------------


def _load_graph_data(graph_path: Path) -> tuple[dict, dict]:
    """Load nodes and edges from an existing graph JSON file."""
    nodes: dict = {}
    edges: dict = {}
    if graph_path.is_file():
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            nid = node.get("id", "")
            nodes[nid] = {
                "id": nid,
                "label": node.get("label", nid),
                "entity_type": node.get("type", node.get("entity_type", "CONCEPT")),
                "description": node.get("description", ""),
                "properties": {k: v for k, v in node.items()
                               if k not in ("id", "label", "type", "entity_type", "description")},
            }
        for edge in data.get("links", data.get("edges", [])):
            eid = f"{edge.get('source', '')}___{edge.get('relationship', 'RELATES_TO')}___{edge.get('target', '')}"
            edges[eid] = {
                "id": eid,
                "source": edge.get("source", ""),
                "target": edge.get("target", ""),
                "relationship": edge.get("relationship", "RELATES_TO"),
            }
    return nodes, edges


def _save_graph_data(graph_path: Path, nodes: dict, edges: dict) -> None:
    """Save nodes and edges back to graph JSON."""
    from graqle.core.graph import _write_with_lock

    graph_nodes = []
    for n in nodes.values():
        node_data = {
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "type": n.get("entity_type", "CONCEPT"),
            "description": n.get("description", ""),
        }
        node_data.update(n.get("properties", {}))
        graph_nodes.append(node_data)

    graph_edges = []
    for e in edges.values():
        graph_edges.append({
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "relationship": e.get("relationship", "RELATES_TO"),
        })

    data = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": graph_nodes,
        "links": graph_edges,
    }

    content = json.dumps(data, indent=2, default=str)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    _write_with_lock(str(graph_path), content)
    console.print(f"[dim]Saved graph:[/dim] {graph_path} ({len(nodes)} nodes, {len(edges)} edges)")


def _print_json_scan_summary(result) -> None:
    """Print a summary table for a JSON scan result."""
    table = Table(title="JSON Scan Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Files Scanned", str(result.files_scanned))
    table.add_row("Files Skipped", str(result.files_skipped))
    table.add_row("Files Errored", str(result.files_errored))
    table.add_row("Nodes Added", str(result.nodes_added))
    table.add_row("Edges Added", str(result.edges_added))
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")
    if result.categories_found:
        table.add_row("", "")
        for cat, count in sorted(result.categories_found.items()):
            table.add_row(f"  {cat}", str(count))
    console.print(table)


def _print_doc_scan_summary(result) -> None:
    """Print a summary table for a document scan result."""
    table = Table(title="Document Scan Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Files Scanned", str(result.files_scanned))
    table.add_row("Files Skipped", str(result.files_skipped))
    table.add_row("Files Errored", str(result.files_errored))
    table.add_row("Nodes Added", str(result.nodes_added))
    table.add_row("Edges Added", str(result.edges_added))
    table.add_row("Stale Removed", str(result.stale_removed))
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")
    console.print(table)
