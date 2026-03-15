"""graq scan — auto-discover code-as-graph from a repository.

Production-quality repository scanner that discovers Python/JS/TS modules,
classes, functions, API endpoints, ORM models, tests, configs, Docker services,
CI pipelines, dependencies, and environment variables — then builds a rich
knowledge graph with typed nodes and edges.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.scan
# risk: HIGH (impact radius: 2 modules)
# consumers: main, test_scan
# dependencies: __future__, ast, json, logging, re +9 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import ast
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from graqle.cli.console import BRAND_NAME

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
        """Return imports, classes, functions, routes, env_vars, models, calls.

        Functions and classes include rich metadata: line ranges, parameters,
        docstrings, outgoing calls, and decorators — enabling function-level
        chunk inheritance and rich T1 descriptions.
        """
        empty: dict[str, Any] = {
            "imports": [],
            "classes": [],
            "functions": [],
            "function_details": {},
            "class_details": {},
            "routes": [],
            "env_vars": [],
            "models": [],
            "calls": [],
            "total_lines": 0,
        }
        try:
            source = path.read_text(errors="ignore")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return empty

        source_lines = source.splitlines()
        total_lines = len(source_lines)

        imports: list[str] = []
        classes: list[str] = []
        functions: list[str] = []
        function_details: dict[str, dict[str, Any]] = {}
        class_details: dict[str, dict[str, Any]] = {}
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
                end_line = getattr(node, "end_lineno", node.lineno + 10)
                class_details[node.name] = {
                    "start_line": node.lineno,
                    "end_line": end_line,
                    "line_count": end_line - node.lineno + 1,
                    "bases": [_attr_name(b) or "?" for b in node.bases],
                    "methods": [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                    "docstring": ast.get_docstring(node) or "",
                }
                # Detect ORM models by base class names
                for base in node.bases:
                    base_name = _attr_name(base)
                    if base_name and any(k in base_name for k in self._ORM_BASES):
                        models.append(node.name)
                        break

            # --- Functions & routes ----------------------------------------
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
                end_line = getattr(node, "end_lineno", node.lineno + 5)

                # Extract parameter names
                params = [a.arg for a in node.args.args if a.arg != "self"]

                # Extract calls made inside this function body
                fn_calls: list[str] = []
                fn_env_vars: list[str] = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        cn = _call_name(child)
                        if cn:
                            fn_calls.append(cn)
                            if "getenv" in cn or "environ" in cn:
                                for arg in child.args:
                                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                        fn_env_vars.append(arg.value)
                    elif isinstance(child, ast.Subscript):
                        val_name = _attr_name(child.value) if hasattr(child, "value") else ""
                        if val_name and "environ" in val_name:
                            if isinstance(child.slice, ast.Constant) and isinstance(child.slice.value, str):
                                fn_env_vars.append(child.slice.value)

                # Decorators
                decorators = [_decorator_name(d) or "" for d in node.decorator_list]

                function_details[node.name] = {
                    "start_line": node.lineno,
                    "end_line": end_line,
                    "line_count": end_line - node.lineno + 1,
                    "params": params,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": ast.get_docstring(node) or "",
                    "calls": list(dict.fromkeys(fn_calls)),  # dedupe, preserve order
                    "env_vars": list(set(fn_env_vars)),
                    "decorators": [d for d in decorators if d],
                }

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
            "function_details": function_details,
            "class_details": class_details,
            "routes": routes,
            "env_vars": list(set(env_vars)),
            "models": models,
            "calls": calls,
            "total_lines": total_lines,
        }


# ---------------------------------------------------------------------------
# JS / TS Analyzer (regex-based)
# ---------------------------------------------------------------------------

class JSAnalyzer:
    """Analyze JavaScript / TypeScript files using regex patterns.

    Enhanced to extract line ranges, parameters, JSDoc, and body-level calls
    for each function and class — enabling line-range chunk inheritance and
    rich descriptions identical to PythonAnalyzer.
    """

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

    # --- Detailed patterns for line-range extraction ---

    # Matches: function name(...), async function name(...),
    #          export function name(...), export default function name(...)
    _FN_DECL_RE = re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    # Matches: const/let/var name = (...) =>, const name = async (...) =>
    #          const name = function(...), export const name = ...
    _FN_ASSIGN_RE = re.compile(
        r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>",
        re.MULTILINE,
    )
    _FN_ASSIGN_EXPR_RE = re.compile(
        r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(",
        re.MULTILINE,
    )
    # Matches: class Name {, class Name extends Base {, interface Name {
    _CLASS_DECL_RE = re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:class|interface)\s+(\w+)"
        r"(?:\s+extends\s+(\w+))?(?:\s+implements\s+[\w,\s]+)?",
        re.MULTILINE,
    )
    # JSDoc: /** ... */
    _JSDOC_RE = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
    # Params from signature: (a, b, c) or (a: Type, b: Type)
    _PARAMS_RE = re.compile(r"\(\s*([^)]*)\)")
    # Function call: identifier( — but not keywords
    _CALL_RE = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
    _JS_KEYWORDS = frozenset({
        "if", "else", "for", "while", "do", "switch", "case", "return",
        "throw", "try", "catch", "finally", "new", "typeof", "instanceof",
        "void", "delete", "in", "of", "with", "yield", "await", "import",
        "export", "from", "as", "default", "class", "extends", "super",
        "this", "function", "async", "const", "let", "var",
    })

    @staticmethod
    def _offset_to_line(content: str, offset: int) -> int:
        """Convert a character offset to a 1-based line number."""
        return content.count("\n", 0, offset) + 1

    def _find_block_end(self, content: str, start_offset: int) -> int:
        """Find the end of a brace-delimited block starting near *start_offset*.

        Scans forward from *start_offset* to find the opening ``{``, then
        counts matching braces to locate the closing ``}``.  Returns the
        character offset of the character *after* the closing brace.

        If no opening brace is found within 500 chars (e.g. arrow fn without
        braces), heuristically finds the end of the statement.
        """
        # Find opening brace
        search_limit = min(start_offset + 500, len(content))
        brace_pos = content.find("{", start_offset, search_limit)
        if brace_pos == -1:
            # Arrow function without braces — find end of expression
            # Look for next top-level declaration or blank line
            newline_pos = content.find("\n\n", start_offset)
            if newline_pos == -1:
                return len(content)
            # Find end of the logical line (could be multiline expression)
            return newline_pos

        depth = 0
        i = brace_pos
        in_string: str | None = None
        in_template = False
        escape = False
        while i < len(content):
            ch = content[i]
            if escape:
                escape = False
                i += 1
                continue
            if ch == "\\":
                escape = True
                i += 1
                continue
            if in_string:
                if ch == in_string:
                    in_string = None
                i += 1
                continue
            if ch in ('"', "'"):
                in_string = ch
                i += 1
                continue
            if ch == "`":
                in_template = not in_template
                i += 1
                continue
            if in_template:
                i += 1
                continue
            if ch == "/" and i + 1 < len(content):
                nxt = content[i + 1]
                if nxt == "/":
                    # Line comment — skip to end of line
                    nl = content.find("\n", i + 2)
                    i = nl + 1 if nl != -1 else len(content)
                    continue
                if nxt == "*":
                    # Block comment — skip to */
                    end_c = content.find("*/", i + 2)
                    i = end_c + 2 if end_c != -1 else len(content)
                    continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return len(content)

    def _extract_jsdoc_before(self, content: str, decl_offset: int) -> str:
        """Extract JSDoc comment immediately before a declaration."""
        # Look backwards from decl_offset for /** ... */
        search_start = max(0, decl_offset - 2000)
        region = content[search_start:decl_offset]
        # Find the last JSDoc block
        matches = list(self._JSDOC_RE.finditer(region))
        if not matches:
            return ""
        last = matches[-1]
        # Must be right before the declaration (only whitespace between)
        between = region[last.end():]
        if between.strip():
            return ""  # Something else between JSDoc and declaration
        raw = last.group(1)
        # Clean JSDoc: remove leading * from each line
        lines = []
        for line in raw.splitlines():
            cleaned = line.strip().lstrip("*").strip()
            if cleaned and not cleaned.startswith("@"):
                lines.append(cleaned)
        return " ".join(lines)[:300]

    def _extract_params(self, content: str, decl_offset: int) -> list[str]:
        """Extract parameter names from the function signature near *decl_offset*."""
        # Search forward for the first (...) after the declaration
        search_end = min(decl_offset + 500, len(content))
        m = self._PARAMS_RE.search(content, decl_offset, search_end)
        if not m or not m.group(1).strip():
            return []
        raw_params = m.group(1)
        params = []
        for p in raw_params.split(","):
            p = p.strip()
            if not p:
                continue
            # Remove type annotations: "name: Type" -> "name", "name = default" -> "name"
            name = re.split(r"[=:?]", p)[0].strip()
            # Remove destructuring braces/brackets, rest/spread
            name = name.lstrip("{[").rstrip("}]").lstrip(".")
            if name and name not in ("", "..."):
                params.append(name)
        return params[:15]

    def _extract_calls_in_body(self, body: str) -> list[str]:
        """Extract unique function call names from a function body."""
        calls = set()
        for m in self._CALL_RE.finditer(body):
            name = m.group(1)
            if name not in self._JS_KEYWORDS and not name[0].isupper():
                # Exclude class instantiation (Capitalized names) and keywords
                calls.add(name)
        # Also include Capitalized calls (React components, constructors)
        for m in self._CALL_RE.finditer(body):
            name = m.group(1)
            if name not in self._JS_KEYWORDS and name[0].isupper():
                calls.add(name)
        return sorted(calls)[:30]

    def _extract_env_vars_in_body(self, body: str) -> list[str]:
        """Extract env var names from a function body."""
        env = set(self.ENV_PATTERN.findall(body))
        env |= set(self.ENV_PATTERN_VITE.findall(body))
        return sorted(env)

    def analyze_file(self, path: Path) -> dict[str, Any]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {
                "imports": [], "classes": [], "functions": [],
                "routes": [], "env_vars": [],
                "function_details": {}, "class_details": {},
            }

        # --- Collect all top-level declarations with positions ---
        declarations: list[tuple[str, str, int, re.Match[str]]] = []
        # (kind, name, offset, match)

        for m in self._FN_DECL_RE.finditer(content):
            declarations.append(("function", m.group(1), m.start(), m))
        for m in self._FN_ASSIGN_RE.finditer(content):
            declarations.append(("function", m.group(1), m.start(), m))
        for m in self._FN_ASSIGN_EXPR_RE.finditer(content):
            declarations.append(("function", m.group(1), m.start(), m))
        for m in self._CLASS_DECL_RE.finditer(content):
            declarations.append(("class", m.group(1), m.start(), m))

        # Sort by offset and deduplicate (same name at same position)
        declarations.sort(key=lambda d: d[2])
        seen: set[tuple[str, int]] = set()
        unique_decls: list[tuple[str, str, int, re.Match[str]]] = []
        for kind, name, offset, match in declarations:
            key = (name, offset)
            if key not in seen:
                seen.add(key)
                unique_decls.append((kind, name, offset, match))
        declarations = unique_decls

        # --- Build function_details and class_details with line ranges ---
        function_details: dict[str, dict[str, Any]] = {}
        class_details: dict[str, dict[str, Any]] = {}
        function_names: list[str] = []
        class_names: list[str] = []

        for kind, name, offset, match in declarations:
            start_line = self._offset_to_line(content, offset)
            block_end = self._find_block_end(content, match.end())
            end_line = self._offset_to_line(content, block_end)
            body = content[match.end():block_end]
            line_count = end_line - start_line + 1

            if kind == "function":
                is_async = "async" in match.group(0)
                jsdoc = self._extract_jsdoc_before(content, offset)
                params = self._extract_params(content, offset)
                calls = self._extract_calls_in_body(body)
                env_vars = self._extract_env_vars_in_body(body)

                # Detect decorators (TypeScript)
                decorator_line = max(0, offset - 200)
                region_before = content[decorator_line:offset]
                decorators = re.findall(r"@(\w+)", region_before)

                function_details[name] = {
                    "start_line": start_line,
                    "end_line": end_line,
                    "line_count": line_count,
                    "params": params,
                    "is_async": is_async,
                    "docstring": jsdoc,
                    "calls": calls,
                    "env_vars": env_vars,
                    "decorators": decorators[-3:] if decorators else [],
                }
                if name not in function_names:
                    function_names.append(name)

            elif kind == "class":
                jsdoc = self._extract_jsdoc_before(content, offset)
                bases = []
                if match.group(2):
                    bases.append(match.group(2))
                # Extract method names inside the class body
                method_names = re.findall(
                    r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*[:{]", body
                )
                # Filter out keywords
                methods = [
                    m for m in method_names
                    if m not in self._JS_KEYWORDS and m != name
                ][:20]

                class_details[name] = {
                    "start_line": start_line,
                    "end_line": end_line,
                    "line_count": line_count,
                    "bases": bases,
                    "methods": methods,
                    "docstring": jsdoc,
                }
                if name not in class_names:
                    class_names.append(name)

        # --- Legacy fields (backward compatible) ---
        raw_fns = self.FUNCTION_PATTERN.findall(content)
        legacy_functions = [g1 or g2 for g1, g2 in raw_fns if g1 or g2][:30]
        # Merge: prefer detailed names, fall back to legacy
        all_fn_names = list(dict.fromkeys(function_names + legacy_functions))

        legacy_classes = self.CLASS_PATTERN.findall(content)
        all_class_names = list(dict.fromkeys(class_names + legacy_classes))

        routes_raw = self.ROUTE_PATTERN.findall(content)
        routes = [{"method": m.upper(), "path": p} for m, p in routes_raw]

        env_vars = list(set(
            self.ENV_PATTERN.findall(content) + self.ENV_PATTERN_VITE.findall(content),
        ))

        return {
            "imports": self.IMPORT_PATTERN.findall(content),
            "classes": all_class_names,
            "functions": all_fn_names,
            "routes": routes,
            "env_vars": env_vars,
            "function_details": function_details,
            "class_details": class_details,
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
        follow_repos: bool = False,
        include_docs: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.max_depth = max_depth
        self.include_tests = include_tests
        self.verbose = verbose
        self.follow_repos = follow_repos
        self.include_docs = include_docs

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
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

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

    def coverage_report(self) -> dict[str, Any]:
        """Check KG coverage: how many nodes have chunks, descriptions, and edges.

        Returns a report dict with coverage percentages and lists of empty nodes.
        """
        total = len(self._nodes)
        code_types = {"Function", "Class", "PythonModule", "JavaScriptModule", "TestFile"}
        code_nodes = [n for n in self._nodes.values() if n.get("type") in code_types]

        nodes_with_chunks = sum(1 for n in code_nodes if n.get("chunks"))
        nodes_with_desc = sum(1 for n in code_nodes if len(n.get("description", "")) > 60)

        # Edge coverage: which nodes have > 1 edge (more than just DEFINES from parent)
        edge_count: dict[str, int] = {}
        for e in self._edges:
            edge_count[e["source"]] = edge_count.get(e["source"], 0) + 1
            edge_count[e["target"]] = edge_count.get(e["target"], 0) + 1
        nodes_with_edges = sum(1 for n in code_nodes if edge_count.get(n["id"], 0) > 1)

        # Empty function/class nodes (the critical gap)
        empty_code_nodes = [
            n["id"] for n in code_nodes
            if n.get("type") in ("Function", "Class") and not n.get("chunks")
        ]

        code_count = len(code_nodes) or 1  # avoid div by zero
        return {
            "total_nodes": total,
            "code_nodes": len(code_nodes),
            "chunk_coverage": round(nodes_with_chunks / code_count * 100, 1),
            "description_coverage": round(nodes_with_desc / code_count * 100, 1),
            "edge_coverage": round(nodes_with_edges / code_count * 100, 1),
            "empty_code_nodes": empty_code_nodes[:20],
            "empty_code_node_count": len(empty_code_nodes),
        }

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
                # In follow-repos mode, detect nested repos and load their .gitignore
                if self.follow_repos and (entry / ".git").is_dir():
                    # Load nested repo's .gitignore into our matcher
                    nested_gi = entry / ".gitignore"
                    if nested_gi.is_file():
                        self.gitignore._load_file(nested_gi)
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
        elif suffix == ".md" and self.include_docs:
            self._process_markdown(path)
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
        fn_details = info.get("function_details", {})
        cls_details = info.get("class_details", {})

        # Classes — with chunk inheritance and rich description
        for cls_name in info["classes"]:
            cls_id = f"{rel}::{cls_name}"
            detail = cls_details.get(cls_name, {})
            cls_desc = self._build_class_description(cls_name, rel, detail)
            cls_attrs: dict[str, Any] = {
                "label": cls_name,
                "type": "Class",
                "description": cls_desc,
                "file_path": str(path.resolve()),
            }
            # Inherit chunks from module by line range (with overlap + text fallback)
            if detail.get("start_line") and chunks:
                cls_chunks = self._inherit_chunks(
                    chunks, detail["start_line"],
                    detail.get("end_line", 999999), cls_name,
                )
                if cls_chunks:
                    cls_attrs["chunks"] = cls_chunks
                    cls_attrs["chunk_count"] = len(cls_chunks)
            self._add_node(cls_id, **cls_attrs)
            self._add_edge(node_id, cls_id, "DEFINES")

        # Functions — with chunk inheritance, rich description, and outgoing edges
        for fn_name in info["functions"]:
            if fn_name.startswith("_") and not any(r["handler"] == fn_name for r in info["routes"]):
                continue  # skip private helpers to reduce noise
            fn_id = f"{rel}::{fn_name}"
            detail = fn_details.get(fn_name, {})
            fn_desc = self._build_function_description(fn_name, rel, detail)
            fn_attrs: dict[str, Any] = {
                "label": fn_name,
                "type": "Function",
                "description": fn_desc,
                "file_path": str(path.resolve()),
            }
            # Inherit chunks from module by line range (with overlap + text fallback)
            if detail.get("start_line") and chunks:
                fn_chunks = self._inherit_chunks(
                    chunks, detail["start_line"],
                    detail.get("end_line", 999999), fn_name,
                )
                if fn_chunks:
                    fn_attrs["chunks"] = fn_chunks
                    fn_attrs["chunk_count"] = len(fn_chunks)
            self._add_node(fn_id, **fn_attrs)
            self._add_edge(node_id, fn_id, "DEFINES")

            # Function-level outgoing edges: CALLS, USES_ENVVAR
            for called in detail.get("calls", [])[:20]:
                # Create CALLS edges to other known functions in this file
                called_id = f"{rel}::{called}"
                if called_id != fn_id:  # no self-loops
                    self._add_edge(fn_id, called_id, "CALLS")
            for ev in detail.get("env_vars", []):
                ev_id = f"env::{ev}"
                self._add_node(ev_id, label=ev, type="EnvVar", description=f"Environment variable {ev}")
                self._add_edge(fn_id, ev_id, "USES_ENVVAR")

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

        # Env vars (module-level)
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

        # Enhanced analysis with line ranges
        info = self.js_analyzer.analyze_file(path)
        fn_details = info.get("function_details", {})
        cls_details = info.get("class_details", {})

        # Classes — with chunk inheritance and rich description
        for cls_name in info["classes"]:
            cls_id = f"{rel}::{cls_name}"
            detail = cls_details.get(cls_name, {})
            cls_desc = self._build_class_description(cls_name, rel, detail)
            cls_attrs: dict[str, Any] = {
                "label": cls_name,
                "type": "Class",
                "description": cls_desc,
                "file_path": str(path.resolve()),
            }
            # Inherit chunks by line range (with overlap + text fallback)
            if detail.get("start_line") and chunks:
                cls_chunks = self._inherit_chunks(
                    chunks, detail["start_line"],
                    detail.get("end_line", 999999), cls_name,
                )
                if cls_chunks:
                    cls_attrs["chunks"] = cls_chunks
                    cls_attrs["chunk_count"] = len(cls_chunks)
            self._add_node(cls_id, **cls_attrs)
            self._add_edge(node_id, cls_id, "DEFINES")

        # Functions — with chunk inheritance, rich description, and outgoing edges
        for fn_name in info["functions"][:30]:
            fn_id = f"{rel}::{fn_name}"
            detail = fn_details.get(fn_name, {})
            fn_desc = self._build_function_description(fn_name, rel, detail)
            fn_attrs: dict[str, Any] = {
                "label": fn_name,
                "type": "Function",
                "description": fn_desc,
                "file_path": str(path.resolve()),
            }
            # Inherit chunks by line range (with overlap + text fallback)
            if detail.get("start_line") and chunks:
                fn_chunks = self._inherit_chunks(
                    chunks, detail["start_line"],
                    detail.get("end_line", 999999), fn_name,
                )
                if fn_chunks:
                    fn_attrs["chunks"] = fn_chunks
                    fn_attrs["chunk_count"] = len(fn_chunks)
            self._add_node(fn_id, **fn_attrs)
            self._add_edge(node_id, fn_id, "DEFINES")

            # Function-level outgoing edges: CALLS, USES_ENVVAR
            for called in detail.get("calls", [])[:20]:
                called_id = f"{rel}::{called}"
                if called_id != fn_id:
                    self._add_edge(fn_id, called_id, "CALLS")
            for ev in detail.get("env_vars", []):
                ev_id = f"env::{ev}"
                self._add_node(ev_id, label=ev, type="EnvVar",
                               description=f"Environment variable {ev}")
                self._add_edge(fn_id, ev_id, "USES_ENVVAR")

        # Routes
        for route in info["routes"]:
            ep_id = f"endpoint::{route['path']}"
            self._add_node(
                ep_id, label=route["path"], type="APIEndpoint",
                description=f"API endpoint {route['method']} {route['path']}",
                method=route["method"],
            )
            self._add_edge(node_id, ep_id, "ROUTES_TO")

        # Module-level env vars
        for ev in info["env_vars"]:
            ev_id = f"env::{ev}"
            self._add_node(ev_id, label=ev, type="EnvVar",
                           description=f"Environment variable {ev}")
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

    # -- Markdown / documentation files ------------------------------------

    def _process_markdown(self, path: Path) -> None:
        """Create a Document node for non-README markdown files (ADRs, plans, docs)."""
        rel = self._rel(path)
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            content = ""

        # Extract title from first # heading
        title = path.stem
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()[:100]
                break

        # Detect document type from path or content
        rel_lower = rel.lower()
        if "adr" in rel_lower or "decision" in rel_lower:
            doc_type = "Decision"
        elif "plan" in rel_lower:
            doc_type = "Plan"
        elif "commit" in rel_lower or "log" in rel_lower or "changelog" in rel_lower:
            doc_type = "Log"
        else:
            doc_type = "Document"

        # Build description from content
        desc_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                desc_lines.append(stripped)
                if len(" ".join(desc_lines)) > 300:
                    break
        description = " ".join(desc_lines)[:400] or f"{doc_type}: {rel}"

        # Create chunks from markdown sections
        chunks: list[dict[str, Any]] = []
        current_section = ""
        current_lines: list[str] = []
        line_num = 0
        section_start = 1
        for i, line in enumerate(content.splitlines(), 1):
            if line.strip().startswith("#"):
                # Flush previous section
                if current_lines:
                    text = "\n".join(current_lines).strip()
                    if text and len(text) >= 30:
                        chunks.append({
                            "text": text[:1500],
                            "type": "markdown_section",
                            "start_line": section_start,
                            "end_line": i - 1,
                        })
                current_section = line.strip().lstrip("#").strip()
                current_lines = [line]
                section_start = i
            else:
                current_lines.append(line)
        # Flush last section
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text and len(text) >= 30:
                chunks.append({
                    "text": text[:1500],
                    "type": "markdown_section",
                    "start_line": section_start,
                    "end_line": len(content.splitlines()),
                })

        node_attrs: dict[str, Any] = {
            "label": title,
            "type": doc_type,
            "description": description,
            "file_path": str(path.resolve()),
        }
        if chunks:
            node_attrs["chunks"] = chunks
            node_attrs["chunk_count"] = len(chunks)

        self._add_node(rel, **node_attrs)
        self._add_contains_edge(path, rel)

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

    # -- Rich description builders ------------------------------------------

    @staticmethod
    def _build_function_description(
        name: str, rel: str, detail: dict[str, Any], max_len: int = 500
    ) -> str:
        """Generate a rich T1 description for a function node from AST data."""
        if not detail:
            return f"Function {name} in {rel}"

        parts: list[str] = []

        # Signature
        params = detail.get("params", [])
        is_async = detail.get("is_async", False)
        prefix = "async " if is_async else ""
        param_str = ", ".join(params[:8])
        if len(params) > 8:
            param_str += f", ... +{len(params) - 8} more"
        sig = f"{prefix}{name}({param_str})"
        parts.append(sig)

        # Docstring (first sentence)
        docstring = detail.get("docstring", "")
        if docstring:
            first_sentence = docstring.split("\n")[0].strip()
            if first_sentence:
                parts.append(first_sentence[:200])

        # Line count
        lc = detail.get("line_count", 0)
        if lc:
            parts.append(f"{lc} lines")

        # Calls made (deduplicated, top 10)
        fn_calls = detail.get("calls", [])
        if fn_calls:
            unique_calls = list(dict.fromkeys(fn_calls))[:10]
            parts.append("Calls: " + ", ".join(unique_calls))

        # Env vars used
        env_vars = detail.get("env_vars", [])
        if env_vars:
            parts.append("Env: " + ", ".join(env_vars[:5]))

        # Decorators
        decorators = detail.get("decorators", [])
        if decorators:
            parts.append("Decorators: " + ", ".join(decorators[:3]))

        desc = f"{rel}::{name}. " + ". ".join(parts)
        return desc[:max_len]

    @staticmethod
    def _build_class_description(
        name: str, rel: str, detail: dict[str, Any], max_len: int = 500
    ) -> str:
        """Generate a rich T1 description for a class node from AST data."""
        if not detail:
            return f"Class {name} in {rel}"

        parts: list[str] = []

        # Bases
        bases = detail.get("bases", [])
        if bases:
            parts.append(f"class {name}({', '.join(bases[:5])})")
        else:
            parts.append(f"class {name}")

        # Docstring
        docstring = detail.get("docstring", "")
        if docstring:
            first_sentence = docstring.split("\n")[0].strip()
            if first_sentence:
                parts.append(first_sentence[:200])

        # Methods
        methods = detail.get("methods", [])
        if methods:
            public_methods = [m for m in methods if not m.startswith("_")][:10]
            if public_methods:
                parts.append("Methods: " + ", ".join(public_methods))

        # Line count
        lc = detail.get("line_count", 0)
        if lc:
            parts.append(f"{lc} lines")

        desc = f"{rel}::{name}. " + ". ".join(parts)
        return desc[:max_len]

    @staticmethod
    def _inherit_chunks(
        chunks: list[dict[str, Any]],
        start_line: int,
        end_line: int,
        name: str,
    ) -> list[dict[str, Any]]:
        """Inherit chunks for a function/class by line range, with fallbacks.

        Strategy (in priority order):
        1. Strict containment: chunk entirely within [start_line, end_line]
        2. Overlap: chunk overlaps with [start_line, end_line] by >= 50%
        3. Text match: chunk text contains the entity name in first 300 chars
        """
        if not chunks:
            return []

        # 1. Strict containment
        result = [
            c for c in chunks
            if c.get("start_line", 0) >= start_line
            and c.get("end_line", 0) <= end_line
        ]
        if result:
            return result

        # 2. Overlap: chunk range overlaps with function range
        # A chunk "belongs" if overlap >= 30% of function size OR >= 50% of chunk size
        fn_size = end_line - start_line + 1
        for c in chunks:
            c_start = c.get("start_line", 0)
            c_end = c.get("end_line", 0)
            if c_start == 0 or c_end == 0:
                continue
            overlap_start = max(c_start, start_line)
            overlap_end = min(c_end, end_line)
            overlap = max(0, overlap_end - overlap_start + 1)
            chunk_size = c_end - c_start + 1
            if chunk_size > 0 and (
                overlap / chunk_size >= 0.5
                or (fn_size > 0 and overlap / fn_size >= 0.3)
            ):
                result.append(c)
        if result:
            return result

        # 3. Text match fallback
        result = [
            c for c in chunks
            if name in c.get("text", "")[:300]
        ]
        return result

    def _extract_content(
        self, path: Path, lang_prefix: str
    ) -> tuple[str, list[dict[str, Any]]]:
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
    ) -> list[dict[str, Any]]:
        """Split source code into semantic chunks at function/class boundaries.

        Returns a list of {"text": "...", "type": "...", "start_line": N, "end_line": N}.
        Line numbers enable function-level chunk inheritance.
        """
        lines = content.splitlines(keepends=True)
        if not lines:
            return []

        chunks: list[dict[str, Any]] = []

        boundary_patterns = (
            "def ", "class ", "async def ",
            "function ", "export ", "const ", "let ",
            "import ", "from ",
            "describe(", "it(", "test(",
        )

        current_block: list[str] = []
        block_type = "source_code"
        block_start_line = 1  # 1-indexed

        def _flush_block() -> None:
            nonlocal block_start_line
            text = "".join(current_block).strip()
            if not text or len(text) < 20:
                return
            end_line = block_start_line + len(current_block) - 1
            if len(text) > max_chunk_chars:
                sub_parts = re.split(r"\n\s*\n", text)
                accum = ""
                sub_start = block_start_line
                for part in sub_parts:
                    if len(accum) + len(part) > max_chunk_chars and accum:
                        sub_end = sub_start + accum.count("\n")
                        chunks.append({"text": accum.strip(), "type": block_type,
                                       "start_line": sub_start, "end_line": sub_end})
                        sub_start = sub_end + 1
                        accum = part
                    else:
                        accum = accum + "\n\n" + part if accum else part
                if accum.strip():
                    chunks.append({"text": accum.strip(), "type": block_type,
                                   "start_line": sub_start, "end_line": end_line})
            else:
                chunks.append({"text": text, "type": block_type,
                               "start_line": block_start_line, "end_line": end_line})

        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            is_boundary = (
                any(stripped.startswith(p) for p in boundary_patterns)
                and not line[0:1].isspace()
            )

            if is_boundary and current_block:
                _flush_block()
                current_block = [line]
                block_start_line = line_num
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
    exclude: list[str] | None = typer.Option(
        None, "--exclude", "-e",
        help="Gitignore-style patterns to exclude (repeatable, e.g. --exclude '*.log' --exclude 'tmp/')",
    ),
    config: str | None = typer.Option(
        None, "--config", "-c",
        help="Path to graqle.yaml config file (default: auto-detect in repo root)",
    ),
    follow_repos: bool = typer.Option(
        False, "--follow-repos",
        help="Traverse into subdirectories that are separate git repos",
    ),
    docs: bool = typer.Option(
        False, "--docs",
        help="Include .md documentation files (ADRs, plans, changelogs) as graph nodes",
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

    # Merge exclude patterns: graqle.yaml scan.exclude_patterns + CLI --exclude
    all_excludes: list[str] = list(exclude or [])
    config_path = Path(config) if config else None
    if config_path is None:
        # Auto-detect config: check repo root, then cwd
        for candidate in [repo / "graqle.yaml", Path("graqle.yaml")]:
            if candidate.exists():
                config_path = candidate
                break
    if config_path and config_path.exists():
        try:
            from graqle.config.settings import GraqleConfig
            cfg = GraqleConfig.from_yaml(str(config_path))
            if cfg.scan.exclude_patterns:
                all_excludes = cfg.scan.exclude_patterns + all_excludes
                if verbose:
                    console.print(f"[dim]Loaded config from {config_path}[/dim]")
                    console.print(f"[dim]Merged {len(cfg.scan.exclude_patterns)} exclude patterns from config[/dim]")
        except Exception as exc:
            if verbose:
                console.print(f"[yellow]Config load warning: {exc}[/yellow]")
    elif config:
        console.print(f"[yellow]Config file not found: {config}[/yellow]")

    extra_info = []
    if follow_repos:
        extra_info.append("follow-repos")
    if docs:
        extra_info.append("docs")
    flags_str = f" | Flags: {', '.join(extra_info)}" if extra_info else ""

    console.print(Panel(
        f"{BRAND_NAME} Repository Scanner\n"
        f"Path: {repo}\n"
        f"Depth: {depth} | Tests: {'yes' if include_tests else 'no'}{flags_str}",
        border_style="cyan",
    ))

    scanner = RepoScanner(
        repo,
        max_depth=depth,
        include_tests=include_tests,
        verbose=verbose,
        exclude_patterns=all_excludes or None,
        follow_repos=follow_repos,
        include_docs=docs,
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

    # Coverage report
    coverage = scanner.coverage_report()
    chunk_pct = coverage["chunk_coverage"]
    desc_pct = coverage["description_coverage"]
    edge_pct = coverage["edge_coverage"]
    chunk_color = "green" if chunk_pct >= 80 else "yellow" if chunk_pct >= 50 else "red"
    console.print(f"\n[bold]KG Coverage:[/bold] "
                  f"chunks [{chunk_color}]{chunk_pct}%[/{chunk_color}] | "
                  f"descriptions {desc_pct}% | "
                  f"edges {edge_pct}%")
    if coverage["empty_code_node_count"] > 0:
        console.print(f"  [yellow]{coverage['empty_code_node_count']} code nodes have no chunks "
                      f"(function/class without source text)[/yellow]")
        if verbose and coverage["empty_code_nodes"]:
            for nid in coverage["empty_code_nodes"][:10]:
                console.print(f"    [dim]- {nid}[/dim]")

    # Warn if embedding cache is stale or missing
    cache_path = Path(".graqle/chunk_embeddings.npz")
    if cache_path.exists():
        if cache_path.stat().st_mtime < out_path.stat().st_mtime:
            console.print(
                "\n[yellow]Embedding cache is stale — it was built before this scan.[/yellow]\n"
                "[yellow]Run [bold]graq rebuild --embeddings[/bold] to update for fast activation.[/yellow]"
            )
    else:
        console.print(
            "\n[dim]Tip: Run [bold]graq rebuild --embeddings[/bold] to build the embedding cache "
            "for fast query activation.[/dim]"
        )


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
    exclude: list[str] | None = typer.Option(
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
    import time as _time

    from graqle.scanner.background import BackgroundScanManager

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
    """Save nodes and edges back to graph JSON.

    Validates graph data before writing to prevent corruption (DF-005).
    """
    from graqle.core.graph import _validate_graph_data, _write_with_lock

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

    # Validate before saving (DF-005)
    _validate_graph_data(data, existing_path=str(graph_path))

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
