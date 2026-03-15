"""Graqle Domain Detector -- Analyze ANY codebase and generate a domain-specific ontology.

Detects the domain/context of a codebase by analyzing project metadata files,
directory structure, file content, and documentation. Then uses an LLM (preferring
Claude Sonnet/Opus) to generate a comprehensive, domain-specific ontology of
node types and edge types. Falls back to a rich heuristic ontology when no LLM
is available.

This is a ONE-TIME operation during graph initialization. Cost is negligible
because it runs once per codebase.

Usage:
    from graqle.ontology.domain_detector import auto_ontology

    nodes, edges = auto_ontology(Path("/path/to/codebase"))
    # or with LLM:
    nodes, edges = auto_ontology(Path("/path/to/codebase"), api_key="sk-...")
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domain_detector
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, json, logging, os, re +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graqle.ontology.schema import (
    NodeShape,
    EdgeShape,
    PropertyConstraint,
    EdgeConstraint,
    register_node_shape,
    register_edge_shape,
    _prop,
    _edge,
)

logger = logging.getLogger("graqle.ontology.domain_detector")

# ---------------------------------------------------------------------------
# Domain Profile
# ---------------------------------------------------------------------------

@dataclass
class DomainProfile:
    """Profile of a detected codebase domain."""

    # Primary domain classification
    primary_domain: str  # e.g., "web_saas", "data_science", "mobile", "embedded"
    secondary_domains: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0

    # Project metadata
    project_name: str = ""
    language: str = ""  # primary language
    languages: list[str] = field(default_factory=list)
    framework: str = ""  # primary framework
    frameworks: list[str] = field(default_factory=list)
    build_system: str = ""

    # Detected patterns
    has_frontend: bool = False
    has_backend: bool = False
    has_api: bool = False
    has_database: bool = False
    has_ml: bool = False
    has_ci_cd: bool = False
    has_docker: bool = False
    has_kubernetes: bool = False
    has_serverless: bool = False
    has_monorepo: bool = False
    has_tests: bool = False
    has_docs: bool = False
    has_governance: bool = False  # .gcc / .gsm directories

    # Raw signals for LLM context
    dependencies: list[str] = field(default_factory=list)
    directory_patterns: list[str] = field(default_factory=list)
    file_samples: list[str] = field(default_factory=list)  # first N lines of key files
    readme_snippet: str = ""
    keywords: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary of the detected domain."""
        parts = [
            f"Domain: {self.primary_domain}",
            f"Language: {self.language}",
        ]
        if self.framework:
            parts.append(f"Framework: {self.framework}")
        if self.secondary_domains:
            parts.append(f"Also: {', '.join(self.secondary_domains)}")
        features = []
        for attr in ("has_frontend", "has_backend", "has_api", "has_database",
                      "has_ml", "has_ci_cd", "has_docker", "has_kubernetes",
                      "has_serverless", "has_monorepo", "has_tests", "has_docs",
                      "has_governance"):
            if getattr(self, attr):
                features.append(attr.replace("has_", ""))
        if features:
            parts.append(f"Features: {', '.join(features)}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Constants -- file patterns and domain signals
# ---------------------------------------------------------------------------

# Project metadata files and what they indicate
_METADATA_FILES = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "poetry.lock": "python",
    "package.json": "javascript",
    "yarn.lock": "javascript",
    "pnpm-lock.yaml": "javascript",
    "tsconfig.json": "typescript",
    "Cargo.toml": "rust",
    "Cargo.lock": "rust",
    "go.mod": "go",
    "go.sum": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "Gemfile": "ruby",
    "composer.json": "php",
    "pubspec.yaml": "dart",
    "Package.swift": "swift",
    "CMakeLists.txt": "cpp",
    "Makefile": "mixed",
    "mix.exs": "elixir",
    "build.sbt": "scala",
    "Project.toml": "julia",
    "stack.yaml": "haskell",
    "deno.json": "typescript",
    "bun.lockb": "typescript",
}

# Directory patterns that signal specific domains
_DIR_SIGNALS: dict[str, list[tuple[str, float]]] = {
    # (domain, weight)
    "src/components": [("frontend", 0.8)],
    "src/pages": [("frontend", 0.8)],
    "src/app": [("frontend", 0.7), ("web_saas", 0.3)],
    "src/views": [("frontend", 0.7)],
    "src/hooks": [("frontend", 0.6)],
    "src/stores": [("frontend", 0.5)],
    "src/routes": [("web_saas", 0.5)],
    "public": [("frontend", 0.4)],
    "static": [("frontend", 0.3)],
    "templates": [("web_saas", 0.4)],
    "api": [("api", 0.7)],
    "routes": [("api", 0.5)],
    "handlers": [("api", 0.5), ("serverless", 0.3)],
    "lambdas": [("serverless", 0.9)],
    "functions": [("serverless", 0.6)],
    "serverless": [("serverless", 0.8)],
    "models": [("database", 0.5), ("ml", 0.3)],
    "migrations": [("database", 0.8)],
    "schemas": [("database", 0.5), ("api", 0.3)],
    "prisma": [("database", 0.8)],
    "notebooks": [("data_science", 0.9)],
    "experiments": [("data_science", 0.6), ("ml", 0.5)],
    "training": [("ml", 0.8)],
    "inference": [("ml", 0.7)],
    "data": [("data_science", 0.3)],
    "datasets": [("data_science", 0.7)],
    "pipelines": [("data_engineering", 0.7)],
    "dags": [("data_engineering", 0.9)],
    "etl": [("data_engineering", 0.8)],
    "terraform": [("infrastructure", 0.9)],
    "infra": [("infrastructure", 0.7)],
    "cdk": [("infrastructure", 0.8)],
    "pulumi": [("infrastructure", 0.8)],
    "k8s": [("kubernetes", 0.9)],
    "kubernetes": [("kubernetes", 0.9)],
    "helm": [("kubernetes", 0.8)],
    "charts": [("kubernetes", 0.6)],
    "docker": [("containerized", 0.7)],
    ".github/workflows": [("ci_cd", 0.9)],
    ".gitlab-ci.yml": [("ci_cd", 0.8)],
    ".circleci": [("ci_cd", 0.8)],
    "ios": [("mobile", 0.9)],
    "android": [("mobile", 0.9)],
    "lib": [("mobile", 0.4)],  # Flutter
    "tests": [("tested", 0.5)],
    "test": [("tested", 0.5)],
    "__tests__": [("tested", 0.5)],
    "spec": [("tested", 0.5)],
    "e2e": [("tested", 0.6)],
    "cypress": [("tested", 0.7), ("frontend", 0.3)],
    "docs": [("documented", 0.5)],
    "documentation": [("documented", 0.6)],
    ".gcc": [("governance", 0.9)],
    ".gsm": [("governance", 0.7)],
    "plugins": [("extensible", 0.6)],
    "extensions": [("extensible", 0.6)],
    "addons": [("extensible", 0.5)],
    "proto": [("grpc", 0.8)],
    "protos": [("grpc", 0.8)],
    "pkg": [("library", 0.5)],
    "internal": [("library", 0.4)],
    "cmd": [("cli", 0.7)],
    "cli": [("cli", 0.7)],
    "bin": [("cli", 0.4)],
    "scripts": [("scripted", 0.3)],
    "game": [("gamedev", 0.8)],
    "scenes": [("gamedev", 0.7)],
    "assets": [("gamedev", 0.4), ("frontend", 0.3)],
    "shaders": [("gamedev", 0.8), ("graphics", 0.7)],
    "firmware": [("embedded", 0.9)],
    "drivers": [("embedded", 0.7)],
    "hal": [("embedded", 0.8)],
    "bsp": [("embedded", 0.9)],
    "security": [("security", 0.6)],
    "auth": [("security", 0.5), ("web_saas", 0.3)],
    "monitoring": [("observability", 0.7)],
    "observability": [("observability", 0.8)],
    "telemetry": [("observability", 0.7)],
}

# Dependency keywords that signal specific domains
_DEP_SIGNALS: dict[str, list[tuple[str, float]]] = {
    # Python
    "django": [("web_saas", 0.8), ("backend", 0.7)],
    "flask": [("web_saas", 0.7), ("backend", 0.6)],
    "fastapi": [("api", 0.8), ("backend", 0.7)],
    "uvicorn": [("api", 0.5)],
    "starlette": [("api", 0.5)],
    "sqlalchemy": [("database", 0.8)],
    "alembic": [("database", 0.7)],
    "prisma": [("database", 0.8)],
    "tortoise-orm": [("database", 0.7)],
    "celery": [("async_processing", 0.8)],
    "dramatiq": [("async_processing", 0.7)],
    "numpy": [("data_science", 0.5)],
    "pandas": [("data_science", 0.7)],
    "scipy": [("data_science", 0.6)],
    "scikit-learn": [("ml", 0.8)],
    "sklearn": [("ml", 0.8)],
    "tensorflow": [("ml", 0.9), ("deep_learning", 0.8)],
    "torch": [("ml", 0.9), ("deep_learning", 0.8)],
    "pytorch": [("ml", 0.9), ("deep_learning", 0.8)],
    "transformers": [("ml", 0.8), ("nlp", 0.7)],
    "langchain": [("llm_app", 0.9)],
    "llamaindex": [("llm_app", 0.8)],
    "openai": [("llm_app", 0.7)],
    "anthropic": [("llm_app", 0.7)],
    "boto3": [("aws", 0.7), ("cloud", 0.5)],
    "airflow": [("data_engineering", 0.9)],
    "prefect": [("data_engineering", 0.8)],
    "dagster": [("data_engineering", 0.8)],
    "dbt": [("data_engineering", 0.8)],
    "pyspark": [("data_engineering", 0.7)],
    "pytest": [("tested", 0.5)],
    "scrapy": [("scraping", 0.9)],
    "beautifulsoup4": [("scraping", 0.6)],
    "networkx": [("graph", 0.7)],
    "neo4j": [("graph", 0.8)],
    "pygame": [("gamedev", 0.8)],
    "micropython": [("embedded", 0.8)],
    "circuitpython": [("embedded", 0.8)],
    "robotics": [("robotics", 0.9)],
    "ros": [("robotics", 0.9)],
    "streamlit": [("data_science", 0.6), ("frontend", 0.4)],
    "gradio": [("ml", 0.5), ("frontend", 0.3)],
    "plotly": [("data_science", 0.5)],
    "matplotlib": [("data_science", 0.5)],
    # JavaScript / TypeScript
    "react": [("frontend", 0.9)],
    "next": [("frontend", 0.8), ("web_saas", 0.6)],
    "vue": [("frontend", 0.9)],
    "nuxt": [("frontend", 0.8), ("web_saas", 0.5)],
    "angular": [("frontend", 0.9)],
    "svelte": [("frontend", 0.9)],
    "express": [("backend", 0.8), ("api", 0.6)],
    "nestjs": [("backend", 0.8), ("api", 0.7)],
    "koa": [("backend", 0.7)],
    "hono": [("backend", 0.6), ("serverless", 0.4)],
    "prisma": [("database", 0.8)],
    "sequelize": [("database", 0.7)],
    "typeorm": [("database", 0.7)],
    "drizzle-orm": [("database", 0.7)],
    "jest": [("tested", 0.5)],
    "vitest": [("tested", 0.5)],
    "cypress": [("tested", 0.6), ("e2e", 0.7)],
    "playwright": [("tested", 0.6), ("e2e", 0.7)],
    "electron": [("desktop", 0.9)],
    "tauri": [("desktop", 0.8)],
    "react-native": [("mobile", 0.9)],
    "expo": [("mobile", 0.8)],
    "ionic": [("mobile", 0.7)],
    "three": [("3d", 0.8)],
    "phaser": [("gamedev", 0.9)],
    "pixi": [("gamedev", 0.7), ("graphics", 0.5)],
    "socket.io": [("realtime", 0.7)],
    "ws": [("realtime", 0.5)],
    "stripe": [("payments", 0.8)],
    "tailwindcss": [("frontend", 0.5)],
    "storybook": [("frontend", 0.5), ("design_system", 0.7)],
    # Rust
    "tokio": [("async", 0.6)],
    "actix-web": [("web_saas", 0.7), ("backend", 0.7)],
    "axum": [("web_saas", 0.7), ("backend", 0.7)],
    "wasm-bindgen": [("wasm", 0.9)],
    "bevy": [("gamedev", 0.9)],
    "embedded-hal": [("embedded", 0.9)],
    # Go
    "gin": [("api", 0.7), ("backend", 0.6)],
    "echo": [("api", 0.6)],
    "fiber": [("api", 0.6)],
    "cobra": [("cli", 0.8)],
    "urfave/cli": [("cli", 0.8)],
    "grpc": [("grpc", 0.8)],
    "protobuf": [("grpc", 0.6)],
}

# Domain classification rules (primary domain based on signal accumulation)
_DOMAIN_CLASSIFICATIONS = [
    # (domain_name, required_signals, min_score)
    ("llm_application", {"llm_app"}, 0.7),
    ("data_science", {"data_science", "ml"}, 0.6),
    ("machine_learning", {"ml", "deep_learning"}, 0.7),
    ("data_engineering", {"data_engineering"}, 0.7),
    ("mobile_app", {"mobile"}, 0.7),
    ("game_development", {"gamedev"}, 0.7),
    ("embedded_systems", {"embedded"}, 0.7),
    ("robotics", {"robotics"}, 0.8),
    ("web_saas", {"web_saas", "frontend", "backend"}, 0.5),
    ("fullstack_web", {"frontend", "backend"}, 0.6),
    ("frontend_app", {"frontend"}, 0.7),
    ("backend_api", {"api", "backend"}, 0.6),
    ("serverless", {"serverless"}, 0.7),
    ("infrastructure", {"infrastructure", "kubernetes"}, 0.6),
    ("cli_tool", {"cli"}, 0.7),
    ("library", {"library"}, 0.5),
    ("desktop_app", {"desktop"}, 0.7),
    ("scraping", {"scraping"}, 0.7),
    ("graph_application", {"graph"}, 0.7),
    ("realtime", {"realtime"}, 0.6),
    ("design_system", {"design_system", "frontend"}, 0.6),
    ("generic_software", set(), 0.0),  # fallback
]


# ---------------------------------------------------------------------------
# Codebase Analysis
# ---------------------------------------------------------------------------

def _safe_read_text(path: Path, max_chars: int = 10000) -> str:
    """Read a file's text content safely, returning empty string on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except (OSError, PermissionError):
        return ""


def _parse_pyproject(root: Path) -> dict[str, Any]:
    """Extract metadata from pyproject.toml."""
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    result: dict[str, Any] = {"deps": [], "keywords": [], "name": ""}

    # Project name
    m = re.search(r'name\s*=\s*"([^"]+)"', text)
    if m:
        result["name"] = m.group(1)

    # Dependencies
    for m in re.finditer(r'^\s*"?([a-zA-Z0-9_-]+)', text, re.MULTILINE):
        dep = m.group(1).lower().strip()
        if dep and len(dep) > 1 and dep not in ("python", "version", "name", "description"):
            result["deps"].append(dep)

    # Keywords
    kw_match = re.search(r'keywords\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if kw_match:
        result["keywords"] = re.findall(r'"([^"]+)"', kw_match.group(1))

    return result


def _parse_package_json(root: Path) -> dict[str, Any]:
    """Extract metadata from package.json."""
    path = root / "package.json"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}

    deps = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if key in data and isinstance(data[key], dict):
            deps.extend(data[key].keys())

    return {
        "name": data.get("name", ""),
        "deps": [d.lower().replace("@", "").split("/")[-1] for d in deps],
        "keywords": data.get("keywords", []),
    }


def _parse_cargo_toml(root: Path) -> dict[str, Any]:
    """Extract metadata from Cargo.toml."""
    path = root / "Cargo.toml"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    result: dict[str, Any] = {"deps": [], "keywords": [], "name": ""}

    m = re.search(r'name\s*=\s*"([^"]+)"', text)
    if m:
        result["name"] = m.group(1)

    # Dependencies section
    in_deps = False
    for line in text.splitlines():
        if re.match(r'\[.*dependencies.*\]', line):
            in_deps = True
            continue
        if line.startswith("[") and in_deps:
            in_deps = False
        if in_deps:
            m = re.match(r'(\w[\w-]*)\s*=', line)
            if m:
                result["deps"].append(m.group(1).lower())

    kw_match = re.search(r'keywords\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if kw_match:
        result["keywords"] = re.findall(r'"([^"]+)"', kw_match.group(1))

    return result


def _parse_go_mod(root: Path) -> dict[str, Any]:
    """Extract metadata from go.mod."""
    path = root / "go.mod"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    result: dict[str, Any] = {"deps": [], "keywords": [], "name": ""}

    m = re.search(r'module\s+(\S+)', text)
    if m:
        result["name"] = m.group(1).split("/")[-1]

    for m in re.finditer(r'^\s+(\S+)\s+v', text, re.MULTILINE):
        dep = m.group(1).split("/")[-1].lower()
        result["deps"].append(dep)

    return result


def _parse_setup_py(root: Path) -> dict[str, Any]:
    """Extract metadata from setup.py."""
    path = root / "setup.py"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    result: dict[str, Any] = {"deps": [], "keywords": [], "name": ""}

    m = re.search(r'name\s*=\s*["\']([^"\']+)', text)
    if m:
        result["name"] = m.group(1)

    for m in re.finditer(r'["\']([a-zA-Z0-9_-]+)(?:[><=!]|["\'])', text):
        dep = m.group(1).lower()
        if dep and len(dep) > 1:
            result["deps"].append(dep)

    return result


def _parse_requirements_txt(root: Path) -> dict[str, Any]:
    """Extract deps from requirements.txt."""
    path = root / "requirements.txt"
    if not path.exists():
        return {}
    text = _safe_read_text(path)
    if not text:
        return {}

    deps = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            dep = re.split(r'[><=!~\[]', line)[0].strip().lower()
            if dep:
                deps.append(dep)
    return {"deps": deps, "keywords": [], "name": ""}


def _scan_directories(root: Path, max_depth: int = 3) -> list[str]:
    """Scan directory structure up to max_depth, return relative paths."""
    dirs: list[str] = []
    try:
        for item in root.rglob("*"):
            if item.is_dir():
                rel = item.relative_to(root)
                parts = rel.parts
                if len(parts) > max_depth:
                    continue
                # Skip hidden dirs (except .gcc, .gsm, .github)
                if any(p.startswith(".") and p not in (".gcc", ".gsm", ".github") for p in parts):
                    continue
                # Skip common non-informative dirs
                if any(p in ("node_modules", "__pycache__", ".git", "venv", "env",
                             ".venv", ".env", "dist", "build", ".next", ".nuxt",
                             "target", ".tox", ".mypy_cache", ".pytest_cache",
                             "coverage", ".coverage", "htmlcov") for p in parts):
                    continue
                dirs.append(str(rel).replace("\\", "/"))
                if len(dirs) > 200:
                    break
    except (OSError, PermissionError):
        pass
    return dirs


def _sample_source_files(root: Path, max_files: int = 20, max_lines: int = 50) -> list[str]:
    """Sample content from representative source files."""
    # Priority extensions
    extensions = [".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go",
                  ".java", ".kt", ".rb", ".php", ".swift", ".dart",
                  ".ex", ".exs", ".scala", ".jl", ".hs", ".c", ".cpp", ".h"]

    samples: list[str] = []
    seen_dirs: set[str] = set()

    try:
        for ext in extensions:
            for fpath in root.rglob(f"*{ext}"):
                # Skip vendor / generated dirs
                parts_str = str(fpath.relative_to(root)).replace("\\", "/")
                skip_patterns = ("node_modules/", "__pycache__/", ".git/",
                                 "venv/", ".venv/", "dist/", "build/",
                                 "target/", ".next/", "vendor/")
                if any(p in parts_str for p in skip_patterns):
                    continue

                # One file per directory for diversity
                parent = str(fpath.parent)
                if parent in seen_dirs:
                    continue
                seen_dirs.add(parent)

                text = _safe_read_text(fpath, max_chars=5000)
                if text:
                    lines = text.splitlines()[:max_lines]
                    header = f"--- {parts_str} ---"
                    samples.append(header + "\n" + "\n".join(lines))

                if len(samples) >= max_files:
                    return samples
    except (OSError, PermissionError):
        pass

    return samples


def _read_readme(root: Path) -> str:
    """Read first 2000 chars of README or CLAUDE.md."""
    for name in ("README.md", "README.rst", "README.txt", "README",
                 "CLAUDE.md", "readme.md"):
        path = root / name
        if path.exists():
            return _safe_read_text(path, max_chars=2000)
    return ""


def _compute_domain_scores(
    dirs: list[str],
    deps: list[str],
) -> dict[str, float]:
    """Compute weighted domain signal scores from directories and dependencies."""
    scores: dict[str, float] = {}

    # Score from directory patterns
    for d in dirs:
        d_lower = d.lower()
        for pattern, signals in _DIR_SIGNALS.items():
            if d_lower == pattern.lower() or d_lower.endswith("/" + pattern.lower()):
                for domain, weight in signals:
                    scores[domain] = scores.get(domain, 0.0) + weight

    # Score from dependencies
    for dep in deps:
        dep_lower = dep.lower().replace("-", "").replace("_", "")
        for pattern, signals in _DEP_SIGNALS.items():
            pattern_normalized = pattern.lower().replace("-", "").replace("_", "")
            if dep_lower == pattern_normalized or pattern_normalized in dep_lower:
                for domain, weight in signals:
                    scores[domain] = scores.get(domain, 0.0) + weight

    return scores


# ---------------------------------------------------------------------------
# Public: detect_domain
# ---------------------------------------------------------------------------

def detect_domain(root: Path) -> DomainProfile:
    """Analyze a codebase root and return a DomainProfile.

    Inspects project metadata files, directory structure, file content samples,
    and documentation to classify the codebase domain.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    profile = DomainProfile(primary_domain="generic_software")

    # 1. Parse project metadata
    all_deps: list[str] = []
    all_keywords: list[str] = []

    for parser in (_parse_pyproject, _parse_package_json, _parse_cargo_toml,
                   _parse_go_mod, _parse_setup_py, _parse_requirements_txt):
        meta = parser(root)
        if meta:
            if meta.get("name") and not profile.project_name:
                profile.project_name = meta["name"]
            all_deps.extend(meta.get("deps", []))
            all_keywords.extend(meta.get("keywords", []))

    # Detect languages from metadata files
    detected_languages: list[str] = []
    for fname, lang in _METADATA_FILES.items():
        if (root / fname).exists():
            if lang not in detected_languages:
                detected_languages.append(lang)

    if detected_languages:
        profile.language = detected_languages[0]
        profile.languages = detected_languages

    # Detect frameworks from deps
    framework_deps = {
        "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
        "react": "React", "next": "Next.js", "vue": "Vue",
        "nuxt": "Nuxt", "angular": "Angular", "svelte": "Svelte",
        "express": "Express", "nestjs": "NestJS",
        "actix-web": "Actix", "axum": "Axum",
        "gin": "Gin", "echo": "Echo", "fiber": "Fiber",
        "bevy": "Bevy", "pygame": "Pygame",
        "tensorflow": "TensorFlow", "torch": "PyTorch",
        "langchain": "LangChain",
        "electron": "Electron", "tauri": "Tauri",
        "react-native": "React Native", "expo": "Expo",
        "flutter": "Flutter",
    }
    frameworks: list[str] = []
    for dep in all_deps:
        dep_lower = dep.lower().replace("-", "").replace("_", "")
        for key, name in framework_deps.items():
            key_normalized = key.lower().replace("-", "").replace("_", "")
            if dep_lower == key_normalized and name not in frameworks:
                frameworks.append(name)
    if frameworks:
        profile.framework = frameworks[0]
        profile.frameworks = frameworks

    profile.dependencies = list(set(all_deps))
    profile.keywords = list(set(all_keywords))

    # 2. Scan directory structure
    dirs = _scan_directories(root)
    profile.directory_patterns = dirs

    # 3. Sample source files
    samples = _sample_source_files(root)
    profile.file_samples = samples

    # 4. Read README/CLAUDE.md
    profile.readme_snippet = _read_readme(root)

    # 5. Compute domain scores
    scores = _compute_domain_scores(dirs, all_deps)

    # Set boolean feature flags
    profile.has_frontend = scores.get("frontend", 0) > 0.5
    profile.has_backend = scores.get("backend", 0) > 0.3 or scores.get("api", 0) > 0.5
    profile.has_api = scores.get("api", 0) > 0.4
    profile.has_database = scores.get("database", 0) > 0.5
    profile.has_ml = scores.get("ml", 0) > 0.5 or scores.get("deep_learning", 0) > 0.5
    profile.has_ci_cd = scores.get("ci_cd", 0) > 0.5
    profile.has_docker = (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists()
    profile.has_kubernetes = scores.get("kubernetes", 0) > 0.5
    profile.has_serverless = scores.get("serverless", 0) > 0.5
    profile.has_tests = scores.get("tested", 0) > 0.3
    profile.has_docs = scores.get("documented", 0) > 0.3
    profile.has_governance = (root / ".gcc").is_dir() or (root / ".gsm").is_dir()
    profile.has_monorepo = sum(1 for d in dirs if "/" not in d and d not in
                                ("src", "lib", "pkg", "docs", "tests", "test",
                                 "scripts", "public", "static", "assets")) > 5

    # 6. Classify primary domain
    for domain_name, required_signals, min_score in _DOMAIN_CLASSIFICATIONS:
        if not required_signals:
            # Fallback
            profile.primary_domain = domain_name
            profile.confidence = 0.3
            break
        signal_score = sum(scores.get(s, 0) for s in required_signals)
        if signal_score >= min_score:
            profile.primary_domain = domain_name
            profile.confidence = min(1.0, signal_score / (len(required_signals) * 1.0))
            break

    # Collect secondary domains
    secondary = []
    for domain_name, required_signals, min_score in _DOMAIN_CLASSIFICATIONS:
        if domain_name == profile.primary_domain or not required_signals:
            continue
        signal_score = sum(scores.get(s, 0) for s in required_signals)
        if signal_score >= min_score * 0.7:
            secondary.append(domain_name)
    profile.secondary_domains = secondary[:5]

    # Detect build system
    build_systems = {
        "pyproject.toml": "poetry/setuptools",
        "Cargo.toml": "cargo",
        "go.mod": "go modules",
        "pom.xml": "maven",
        "build.gradle": "gradle",
        "CMakeLists.txt": "cmake",
        "Makefile": "make",
        "mix.exs": "mix",
        "build.sbt": "sbt",
    }
    for fname, bs in build_systems.items():
        if (root / fname).exists():
            profile.build_system = bs
            break
    if not profile.build_system and (root / "package.json").exists():
        # Check for specific JS build tools
        for dep in all_deps:
            if dep in ("vite", "webpack", "esbuild", "rollup", "turbo", "nx"):
                profile.build_system = dep
                break
        if not profile.build_system:
            profile.build_system = "npm"

    logger.info(f"Detected domain: {profile.summary()}")
    return profile


# ---------------------------------------------------------------------------
# LLM-based Ontology Generation
# ---------------------------------------------------------------------------

_LLM_ONTOLOGY_PROMPT = """You are an expert software ontology engineer. You are analyzing a codebase to generate
a comprehensive knowledge graph ontology (node types and edge/relationship types) that captures
ALL aspects of this specific software domain.

## CODEBASE ANALYSIS

**Project Name:** {project_name}
**Primary Domain:** {primary_domain}
**Secondary Domains:** {secondary_domains}
**Language(s):** {languages}
**Framework(s):** {frameworks}
**Build System:** {build_system}

**Feature Flags:**
- Frontend: {has_frontend}
- Backend: {has_backend}
- API: {has_api}
- Database: {has_database}
- ML/AI: {has_ml}
- CI/CD: {has_ci_cd}
- Docker: {has_docker}
- Kubernetes: {has_kubernetes}
- Serverless: {has_serverless}
- Tests: {has_tests}
- Documentation: {has_docs}
- Governance (.gcc/.gsm): {has_governance}
- Monorepo: {has_monorepo}

**Dependencies (sample):** {dependencies}

**Directory Structure (sample):**
{directory_patterns}

**README/Docs Snippet:**
{readme_snippet}

**Source File Samples:**
{file_samples}

## YOUR TASK

Generate an EXTENSIVE, domain-specific ontology for this codebase. The ontology must be comprehensive
enough to model every aspect of the project's architecture, codebase, infrastructure, processes,
and team workflows.

### Requirements:
1. **At minimum 30 node types** -- cover ALL of these categories:
   - Code structure (modules, classes, functions, components, hooks, routes, controllers, models)
   - Data layer (database tables, schemas, migrations, ORMs, queries, indexes)
   - API layer (endpoints, routes, handlers, middleware, serializers, validators)
   - Infrastructure (servers, containers, clusters, load balancers, CDNs, DNS, certificates)
   - Cloud resources (specific to detected cloud: Lambda, S3, EC2, RDS, DynamoDB, etc.)
   - Configuration (env vars, config files, feature flags, secrets)
   - Testing (test suites, test cases, fixtures, mocks, coverage reports)
   - CI/CD (pipelines, stages, jobs, artifacts, deployments, releases)
   - Security (auth providers, IAM roles, API keys, certificates, vulnerabilities, policies)
   - Documentation (docs, READMEs, ADRs, changelogs, API specs, tutorials)
   - Monitoring/Observability (metrics, alerts, dashboards, log streams, traces)
   - Team/Process (team members, sprints, tasks, PRs, code reviews, incidents)
   - Dependencies (packages, libraries, version constraints)
   - Domain-specific types based on the detected domain

2. **At minimum 40 edge types** -- cover ALL relationship patterns:
   - Code relationships (imports, extends, implements, calls, returns, throws, wraps)
   - Data flow (reads_from, writes_to, transforms, maps_to, validates, serializes)
   - Dependency (depends_on, required_by, conflicts_with, replaces, extends)
   - Infrastructure (deployed_on, routes_to, load_balances, caches, proxies)
   - Ownership (owned_by, maintained_by, reviewed_by, created_by, assigned_to)
   - Lifecycle (triggers, blocks, follows, precedes, enables, disables)
   - Testing (tests, covers, mocks, stubs, asserts_about)
   - Security (authenticates, authorizes, encrypts, exposes, restricts)
   - Monitoring (monitors, alerts_on, logs_to, traces, reports_to)
   - Documentation (documents, references, links_to, supersedes)
   - Version control (branched_from, merged_into, cherry_picked_from, reverts)
   - Domain-specific edges based on the detected domain

3. **Property schemas** for each node type -- include:
   - An `id` property (required, str)
   - A `label` property (required, str)
   - Domain-relevant properties with appropriate types (str, int, float, bool, list, dict)
   - Use `allowed_values` for enum-like properties (e.g., status fields)

### Output Format (JSON):

```json
{{
  "node_types": [
    {{
      "node_type": "UPPERCASE_TYPE_NAME",
      "description": "Clear description of what this node represents",
      "properties": [
        {{"name": "id", "required": true, "prop_type": "str"}},
        {{"name": "label", "required": true, "prop_type": "str"}},
        {{"name": "example_prop", "required": false, "prop_type": "str", "allowed_values": ["a", "b"]}},
        {{"name": "count", "required": false, "prop_type": "int"}}
      ],
      "expected_edges": [
        {{"edge_type": "EDGE_NAME", "target_types": ["TARGET_TYPE"], "min_count": 0}}
      ]
    }}
  ],
  "edge_types": [
    {{
      "edge_type": "UPPERCASE_EDGE_NAME",
      "description": "What this relationship means",
      "valid_source_types": ["SOURCE1", "SOURCE2"],
      "valid_target_types": ["TARGET1", "TARGET2"],
      "allow_any_source": false,
      "allow_any_target": false
    }}
  ]
}}
```

IMPORTANT:
- ALL type names must be UPPERCASE_WITH_UNDERSCORES
- Every node type MUST have `id` (required) and `label` (required) properties
- Include types specific to the detected domain ({primary_domain})
- Be exhaustive -- this ontology will be used to model the ENTIRE codebase
- Edge types with `allow_any_source: true` or `allow_any_target: true` are wildcards
- Output ONLY valid JSON, no markdown fences or explanation text
"""


def _call_anthropic_api(
    prompt: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Call the Anthropic Messages API directly via HTTP to avoid SDK dependency."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "max_tokens": 8192,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    })

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Extract text from content blocks
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"]
            return ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error(f"Anthropic API error {e.code}: {body[:500]}")
        raise
    except urllib.error.URLError as e:
        logger.error(f"Anthropic API connection error: {e.reason}")
        raise


def _parse_llm_ontology(
    response_text: str,
) -> tuple[list[NodeShape], list[EdgeShape]]:
    """Parse LLM JSON response into NodeShape and EdgeShape lists."""
    # Strip markdown fences if present
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # Try to find JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Attempt repair: strip trailing commas, fix common LLM JSON issues
        import re
        repaired = re.sub(r',\s*([}\]])', r'', text)  # trailing commas
        repaired = repaired.replace("'", '"')  # single quotes
        try:
            data = json.loads(repaired)
            logger.info('LLM ontology JSON repaired successfully')
        except json.JSONDecodeError:
            logger.warning('LLM ontology JSON could not be parsed even after repair')
            raise

    node_shapes: list[NodeShape] = []
    edge_shapes: list[EdgeShape] = []

    # Parse node types
    for nt in data.get("node_types", []):
        props = []
        for p in nt.get("properties", []):
            props.append(PropertyConstraint(
                name=p["name"],
                required=p.get("required", False),
                prop_type=p.get("prop_type", "str"),
                allowed_values=p.get("allowed_values"),
                pattern=p.get("pattern"),
                min_value=p.get("min_value"),
                max_value=p.get("max_value"),
            ))

        edges = []
        for e in nt.get("expected_edges", []):
            edges.append(EdgeConstraint(
                edge_type=e["edge_type"],
                target_types=e.get("target_types", []),
                min_count=e.get("min_count", 0),
                max_count=e.get("max_count"),
            ))

        node_shapes.append(NodeShape(
            node_type=nt["node_type"],
            description=nt.get("description", ""),
            properties=props,
            expected_edges=edges,
            allow_extra_properties=True,
        ))

    # Parse edge types
    for et in data.get("edge_types", []):
        edge_shapes.append(EdgeShape(
            edge_type=et["edge_type"],
            description=et.get("description", ""),
            valid_source_types=et.get("valid_source_types", []),
            valid_target_types=et.get("valid_target_types", []),
            allow_any_source=et.get("allow_any_source", False),
            allow_any_target=et.get("allow_any_target", False),
        ))

    return node_shapes, edge_shapes


def _build_llm_prompt(profile: DomainProfile) -> str:
    """Build the LLM prompt from the domain profile."""
    dir_sample = "\n".join(f"  {d}" for d in profile.directory_patterns[:60])
    dep_sample = ", ".join(profile.dependencies[:50])
    file_sample = "\n".join(profile.file_samples[:10])  # Limit to avoid token overflow

    return _LLM_ONTOLOGY_PROMPT.format(
        project_name=profile.project_name or "(unknown)",
        primary_domain=profile.primary_domain,
        secondary_domains=", ".join(profile.secondary_domains) or "none",
        languages=", ".join(profile.languages) or profile.language or "unknown",
        frameworks=", ".join(profile.frameworks) or "none",
        build_system=profile.build_system or "unknown",
        has_frontend=profile.has_frontend,
        has_backend=profile.has_backend,
        has_api=profile.has_api,
        has_database=profile.has_database,
        has_ml=profile.has_ml,
        has_ci_cd=profile.has_ci_cd,
        has_docker=profile.has_docker,
        has_kubernetes=profile.has_kubernetes,
        has_serverless=profile.has_serverless,
        has_tests=profile.has_tests,
        has_docs=profile.has_docs,
        has_governance=profile.has_governance,
        has_monorepo=profile.has_monorepo,
        dependencies=dep_sample or "none detected",
        directory_patterns=dir_sample or "  (no directories scanned)",
        readme_snippet=profile.readme_snippet[:1500] or "(no README found)",
        file_samples=file_sample[:8000] or "(no source files sampled)",
    )


# ---------------------------------------------------------------------------
# Heuristic Fallback Ontology Generation
# ---------------------------------------------------------------------------

def _heuristic_base_nodes() -> list[NodeShape]:
    """Core node types applicable to virtually any codebase."""
    return [
        # --- Code Structure ---
        NodeShape("SOURCE_FILE", "A source code file",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("language"), _prop("line_count", prop_type="int"),
                   _prop("size_bytes", prop_type="int")],
                  [_edge("CONTAINS", ["CLASS", "FUNCTION", "CONSTANT"]),
                   _edge("IMPORTS", ["MODULE", "SOURCE_FILE"])]),
        NodeShape("MODULE", "A code module or package",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("language"),
                   _prop("exported_symbols", prop_type="list")],
                  [_edge("CONTAINS", ["SOURCE_FILE", "CLASS", "FUNCTION"]),
                   _edge("DEPENDS_ON", ["MODULE", "PACKAGE"])]),
        NodeShape("CLASS", "A class or type definition",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("line_number", prop_type="int"),
                   _prop("visibility", allowed_values=["public", "private", "protected", "internal"])],
                  [_edge("EXTENDS", ["CLASS"]), _edge("IMPLEMENTS", ["INTERFACE"]),
                   _edge("CONTAINS", ["FUNCTION", "PROPERTY"])]),
        NodeShape("FUNCTION", "A function, method, or callable",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("line_number", prop_type="int"),
                   _prop("parameters", prop_type="list"), _prop("return_type"),
                   _prop("async", prop_type="bool"), _prop("visibility")],
                  [_edge("CALLS", ["FUNCTION"]), _edge("RETURNS", ["CLASS"]),
                   _edge("RAISES", ["ERROR_TYPE"])]),
        NodeShape("INTERFACE", "An interface, trait, or protocol definition",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("methods", prop_type="list")],
                  [_edge("IMPLEMENTED_BY", ["CLASS"])]),
        NodeShape("CONSTANT", "A constant or enum value",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("value"), _prop("const_type")]),
        NodeShape("ERROR_TYPE", "An error, exception, or fault type",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("base_class"), _prop("severity")],
                  [_edge("RAISED_BY", ["FUNCTION", "SERVICE"])]),

        # --- Dependencies ---
        NodeShape("PACKAGE", "An external dependency / library",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("version"), _prop("registry"), _prop("license"),
                   _prop("dev_only", prop_type="bool")],
                  [_edge("USED_BY", ["MODULE", "SERVICE"]),
                   _edge("DEPENDS_ON", ["PACKAGE"])]),

        # --- Configuration ---
        NodeShape("CONFIG_FILE", "A configuration file",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("format",
                   allowed_values=["json", "yaml", "toml", "ini", "env", "xml"])]),
        NodeShape("ENVVAR", "An environment variable",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("default_value"), _prop("required", prop_type="bool"),
                   _prop("secret", prop_type="bool")],
                  [_edge("REQUIRED_BY", ["SERVICE", "MODULE"])]),
        NodeShape("FEATURE_FLAG", "A feature flag or toggle",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("enabled", prop_type="bool"), _prop("rollout_pct", prop_type="float")],
                  [_edge("CONTROLS", ["FUNCTION", "MODULE", "FRONTEND_COMPONENT"])]),
        NodeShape("SECRET", "A secret, API key, or credential reference",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("rotation_days", prop_type="int")],
                  [_edge("USED_BY", ["SERVICE"])]),

        # --- Testing ---
        NodeShape("TEST_SUITE", "A test suite or test file",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("runner"), _prop("test_count", prop_type="int"),
                   _prop("status", allowed_values=["passing", "failing", "skipped"])],
                  [_edge("TESTS", ["MODULE", "CLASS", "FUNCTION", "SERVICE"])]),
        NodeShape("TEST_CASE", "An individual test case",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("line_number", prop_type="int"),
                   _prop("status", allowed_values=["pass", "fail", "skip", "flaky"])],
                  [_edge("PART_OF", ["TEST_SUITE"]),
                   _edge("TESTS", ["FUNCTION", "CLASS"])]),
        NodeShape("TEST_FIXTURE", "Test fixture or factory",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("scope")],
                  [_edge("USED_BY", ["TEST_CASE", "TEST_SUITE"])]),

        # --- CI/CD ---
        NodeShape("CI_PIPELINE", "CI/CD pipeline definition",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider", allowed_values=[
                       "github_actions", "gitlab_ci", "circleci", "jenkins",
                       "buildkite", "azure_devops", "bitbucket", "other"]),
                   _prop("file_path"), _prop("trigger")],
                  [_edge("CONTAINS", ["CI_STAGE"]),
                   _edge("DEPLOYS", ["SERVICE", "DEPLOYMENT"])]),
        NodeShape("CI_STAGE", "A stage or job in a CI/CD pipeline",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("runner"), _prop("timeout")],
                  [_edge("FOLLOWS", ["CI_STAGE"]),
                   _edge("PRODUCES", ["ARTIFACT"])]),
        NodeShape("ARTIFACT", "A build artifact (binary, container image, package)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("artifact_type"), _prop("size_bytes", prop_type="int"),
                   _prop("version")],
                  [_edge("PRODUCED_BY", ["CI_STAGE"]),
                   _edge("DEPLOYED_TO", ["DEPLOYMENT"])]),

        # --- Documentation ---
        NodeShape("DOCUMENT", "Documentation file (README, guide, ADR)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("doc_type",
                   allowed_values=["readme", "adr", "api_spec", "tutorial",
                                   "changelog", "contributing", "design_doc", "runbook"]),
                   _prop("format", allowed_values=["markdown", "rst", "asciidoc", "html"])],
                  [_edge("DOCUMENTS", ["MODULE", "SERVICE", "CLASS", "FUNCTION"]),
                   _edge("REFERENCES", ["DOCUMENT"])]),
        NodeShape("ADR", "Architecture Decision Record",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("number", prop_type="int"),
                   _prop("status", allowed_values=["PROPOSED", "ACCEPTED", "DEPRECATED", "SUPERSEDED"]),
                   _prop("date")],
                  [_edge("GOVERNS", ["MODULE", "SERVICE"]),
                   _edge("SUPERSEDES", ["ADR"])]),

        # --- Security ---
        NodeShape("AUTH_PROVIDER", "Authentication provider or identity service",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider_type",
                   allowed_values=["oauth2", "saml", "oidc", "api_key", "jwt", "cognito",
                                   "auth0", "firebase_auth", "custom"]),
                   _prop("endpoint")],
                  [_edge("AUTHENTICATES", ["SERVICE", "FRONTEND_COMPONENT"])]),
        NodeShape("IAM_ROLE", "IAM role or permission set",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("policies", prop_type="list"), _prop("arn")],
                  [_edge("ASSUMED_BY", ["SERVICE"]),
                   _edge("GRANTS_ACCESS_TO", ["CLOUD_RESOURCE"])]),
        NodeShape("SECURITY_POLICY", "Security policy or compliance rule",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("severity",
                   allowed_values=["critical", "high", "medium", "low"]),
                   _prop("standard")],
                  [_edge("CONSTRAINS", ["SERVICE", "MODULE", "DEPLOYMENT"])]),

        # --- Monitoring ---
        NodeShape("METRIC", "An observable metric or KPI",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("unit"), _prop("aggregation"), _prop("source")],
                  [_edge("MEASURES", ["SERVICE", "FUNCTION"])]),
        NodeShape("ALERT_RULE", "A monitoring alert or alarm",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("threshold"), _prop("severity"), _prop("channel")],
                  [_edge("MONITORS", ["METRIC"]),
                   _edge("NOTIFIES", ["TEAM_MEMBER"])]),
        NodeShape("DASHBOARD", "A monitoring or analytics dashboard",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("url")],
                  [_edge("DISPLAYS", ["METRIC"])]),

        # --- Team / Process ---
        NodeShape("TEAM_MEMBER", "A team member or contributor",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("role"), _prop("email")],
                  [_edge("OWNS", ["MODULE", "SERVICE"]),
                   _edge("REVIEWS", ["PULL_REQUEST"])]),
        NodeShape("PULL_REQUEST", "A pull/merge request",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("status", allowed_values=["open", "merged", "closed"]),
                   _prop("branch"), _prop("target_branch")],
                  [_edge("MODIFIES", ["SOURCE_FILE", "MODULE"]),
                   _edge("CREATED_BY", ["TEAM_MEMBER"]),
                   _edge("REVIEWED_BY", ["TEAM_MEMBER"])]),
        NodeShape("INCIDENT", "A production incident or outage",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("severity",
                   allowed_values=["critical", "major", "minor", "informational"]),
                   _prop("status", allowed_values=["open", "investigating", "resolved", "postmortem"]),
                   _prop("root_cause"), _prop("duration_minutes", prop_type="int")],
                  [_edge("AFFECTED", ["SERVICE"]),
                   _edge("RESOLVED_BY", ["TEAM_MEMBER"]),
                   _edge("CAUSED_BY", ["DEPLOYMENT", "FUNCTION"])]),
        NodeShape("TASK", "A task, story, or issue",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("status", allowed_values=["todo", "in_progress", "done", "blocked"]),
                   _prop("priority", allowed_values=["critical", "high", "medium", "low"]),
                   _prop("assignee")],
                  [_edge("ASSIGNED_TO", ["TEAM_MEMBER"]),
                   _edge("BLOCKS", ["TASK"]),
                   _edge("RELATES_TO", ["MODULE", "SERVICE"])]),

        # --- Governance (.gcc/.gsm) ---
        NodeShape("LESSON", "An operational lesson learned",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("severity", allowed_values=["CRITICAL", "HIGH", "MEDIUM", "LOW"]),
                   _prop("domain"), _prop("hit_count", prop_type="int")],
                  [_edge("APPLIES_TO", ["SERVICE", "MODULE"])]),
        NodeShape("MISTAKE", "A documented production mistake",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("component"), _prop("root_cause"), _prop("fix"),
                   _prop("severity")],
                  [_edge("OCCURRED_IN", ["SERVICE", "MODULE"])]),
        NodeShape("SAFETY_RULE", "A safety boundary or constraint",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("rule")],
                  [_edge("CONSTRAINS", ["SERVICE", "MODULE", "DEPLOYMENT"])]),
    ]


def _heuristic_base_edges() -> list[EdgeShape]:
    """Core edge types applicable to virtually any codebase."""
    return [
        # Code relationships
        EdgeShape("IMPORTS", "Module/file imports another",
                  ["SOURCE_FILE", "MODULE"], ["SOURCE_FILE", "MODULE"]),
        EdgeShape("EXTENDS", "Class extends/inherits from another",
                  ["CLASS"], ["CLASS"]),
        EdgeShape("IMPLEMENTS", "Class implements interface",
                  ["CLASS"], ["INTERFACE"]),
        EdgeShape("CALLS", "Function calls another function",
                  ["FUNCTION", "SERVICE"], ["FUNCTION", "SERVICE"]),
        EdgeShape("RETURNS", "Function returns a type",
                  ["FUNCTION"], ["CLASS"]),
        EdgeShape("RAISES", "Function raises an error",
                  ["FUNCTION"], ["ERROR_TYPE"]),
        EdgeShape("CONTAINS", "Parent contains child",
                  allow_any_source=True, allow_any_target=True),
        EdgeShape("WRAPS", "Decorator/wrapper wraps a function",
                  ["FUNCTION"], ["FUNCTION"]),

        # Dependency
        EdgeShape("DEPENDS_ON", "Component depends on another",
                  allow_any_source=True, allow_any_target=True),
        EdgeShape("REQUIRED_BY", "Required by a component",
                  ["ENVVAR", "PACKAGE", "SECRET"], ["SERVICE", "MODULE"]),
        EdgeShape("USED_BY", "Used by a component",
                  allow_any_source=True, allow_any_target=True),
        EdgeShape("CONFLICTS_WITH", "Version or dependency conflict",
                  ["PACKAGE"], ["PACKAGE"]),
        EdgeShape("REPLACES", "Supersedes or replaces another",
                  allow_any_source=True, allow_any_target=True),

        # Data flow
        EdgeShape("READS_FROM", "Reads data from a source",
                  ["SERVICE", "FUNCTION"], ["DATABASE_TABLE", "CLOUD_RESOURCE", "CONFIG_FILE"]),
        EdgeShape("WRITES_TO", "Writes data to a target",
                  ["SERVICE", "FUNCTION"], ["DATABASE_TABLE", "CLOUD_RESOURCE"]),
        EdgeShape("TRANSFORMS", "Transforms data from one form to another",
                  ["FUNCTION", "SERVICE"], ["FUNCTION", "SERVICE"]),
        EdgeShape("VALIDATES", "Validates data or input",
                  ["FUNCTION", "MODULE"], ["CLASS", "FUNCTION"]),
        EdgeShape("SERIALIZES", "Serializes/deserializes data",
                  ["FUNCTION"], ["CLASS"]),

        # Testing
        EdgeShape("TESTS", "Tests a component",
                  ["TEST_SUITE", "TEST_CASE"], ["MODULE", "CLASS", "FUNCTION", "SERVICE"]),
        EdgeShape("COVERS", "Test coverage of a component",
                  ["TEST_SUITE"], ["MODULE", "SOURCE_FILE"]),
        EdgeShape("MOCKS", "Mocks a dependency in tests",
                  ["TEST_CASE", "TEST_FIXTURE"], ["SERVICE", "MODULE", "FUNCTION"]),

        # CI/CD & Deployment
        EdgeShape("DEPLOYS", "Pipeline deploys a service",
                  ["CI_PIPELINE", "CI_STAGE"], ["SERVICE", "DEPLOYMENT"]),
        EdgeShape("PRODUCES", "Stage produces an artifact",
                  ["CI_STAGE"], ["ARTIFACT"]),
        EdgeShape("DEPLOYED_TO", "Artifact deployed to environment",
                  ["ARTIFACT", "SERVICE"], ["DEPLOYMENT"]),
        EdgeShape("FOLLOWS", "Stage follows another stage",
                  ["CI_STAGE"], ["CI_STAGE"]),
        EdgeShape("TRIGGERS", "Event triggers a pipeline/process",
                  allow_any_source=True, allow_any_target=True),

        # Infrastructure
        EdgeShape("DEPLOYED_ON", "Component deployed on infrastructure",
                  ["SERVICE"], ["CLOUD_RESOURCE", "DEPLOYMENT"]),
        EdgeShape("ROUTES_TO", "Network routing / proxy target",
                  ["CLOUD_RESOURCE", "SERVICE"], ["SERVICE"]),
        EdgeShape("LOAD_BALANCES", "Load balancer distributes to targets",
                  ["CLOUD_RESOURCE"], ["SERVICE"]),
        EdgeShape("CACHES", "Caching layer for a resource",
                  ["CLOUD_RESOURCE"], ["SERVICE"]),

        # Security
        EdgeShape("AUTHENTICATES", "Auth provider authenticates a component",
                  ["AUTH_PROVIDER"], ["SERVICE", "FRONTEND_COMPONENT"]),
        EdgeShape("AUTHORIZES", "Grants authorization to perform actions",
                  ["IAM_ROLE", "SECURITY_POLICY"], ["SERVICE", "FUNCTION"]),
        EdgeShape("GRANTS_ACCESS_TO", "Role grants access to a resource",
                  ["IAM_ROLE"], ["CLOUD_RESOURCE"]),
        EdgeShape("CONSTRAINS", "Policy constrains a component",
                  ["SECURITY_POLICY", "SAFETY_RULE"], ["SERVICE", "MODULE", "DEPLOYMENT"]),

        # Monitoring
        EdgeShape("MONITORS", "Alert monitors a metric",
                  ["ALERT_RULE"], ["METRIC"]),
        EdgeShape("MEASURES", "Metric measures a component",
                  ["METRIC"], ["SERVICE", "FUNCTION"]),
        EdgeShape("NOTIFIES", "Alert notifies a person/channel",
                  ["ALERT_RULE"], ["TEAM_MEMBER"]),
        EdgeShape("DISPLAYS", "Dashboard displays a metric",
                  ["DASHBOARD"], ["METRIC"]),

        # Documentation
        EdgeShape("DOCUMENTS", "Documentation covers a component",
                  ["DOCUMENT", "ADR"], ["MODULE", "SERVICE", "CLASS", "FUNCTION"]),
        EdgeShape("REFERENCES", "Document references another",
                  ["DOCUMENT", "ADR"], ["DOCUMENT", "ADR"]),
        EdgeShape("SUPERSEDES", "Newer version supersedes older",
                  ["ADR", "DOCUMENT"], ["ADR", "DOCUMENT"]),
        EdgeShape("GOVERNS", "ADR governs a component",
                  ["ADR"], ["MODULE", "SERVICE"]),

        # Ownership / Team
        EdgeShape("OWNS", "Team member owns a component",
                  ["TEAM_MEMBER"], ["MODULE", "SERVICE"]),
        EdgeShape("REVIEWS", "Team member reviews a PR",
                  ["TEAM_MEMBER"], ["PULL_REQUEST"]),
        EdgeShape("CREATED_BY", "Component created by team member",
                  ["PULL_REQUEST"], ["TEAM_MEMBER"]),
        EdgeShape("REVIEWED_BY", "PR reviewed by team member",
                  ["PULL_REQUEST"], ["TEAM_MEMBER"]),
        EdgeShape("ASSIGNED_TO", "Task assigned to team member",
                  ["TASK"], ["TEAM_MEMBER"]),
        EdgeShape("MODIFIES", "PR modifies files",
                  ["PULL_REQUEST"], ["SOURCE_FILE", "MODULE"]),
        EdgeShape("BLOCKS", "Task/issue blocks another",
                  ["TASK"], ["TASK"]),
        EdgeShape("RELATES_TO", "Generic relationship",
                  allow_any_source=True, allow_any_target=True),

        # Lifecycle
        EdgeShape("AFFECTED", "Incident affected a service",
                  ["INCIDENT"], ["SERVICE"]),
        EdgeShape("RESOLVED_BY", "Incident resolved by team member",
                  ["INCIDENT"], ["TEAM_MEMBER"]),
        EdgeShape("CAUSED_BY", "Incident caused by a deployment or function",
                  ["INCIDENT"], ["DEPLOYMENT", "FUNCTION"]),
        EdgeShape("CONTROLS", "Feature flag controls a component",
                  ["FEATURE_FLAG"], ["FUNCTION", "MODULE", "FRONTEND_COMPONENT"]),

        # Governance
        EdgeShape("APPLIES_TO", "Lesson applies to component",
                  ["LESSON", "SAFETY_RULE"], ["SERVICE", "MODULE"]),
        EdgeShape("OCCURRED_IN", "Mistake occurred in component",
                  ["MISTAKE"], ["SERVICE", "MODULE"]),

        # Part-of / composition
        EdgeShape("PART_OF", "Component is part of a larger component",
                  allow_any_source=True, allow_any_target=True),
        EdgeShape("ASSUMED_BY", "Role assumed by a service",
                  ["IAM_ROLE"], ["SERVICE"]),
        EdgeShape("RAISED_BY", "Error raised by a function",
                  ["ERROR_TYPE"], ["FUNCTION", "SERVICE"]),
        EdgeShape("IMPLEMENTED_BY", "Interface implemented by class",
                  ["INTERFACE"], ["CLASS"]),
        EdgeShape("PRODUCED_BY", "Artifact produced by a stage",
                  ["ARTIFACT"], ["CI_STAGE"]),
    ]


# Domain-specific node additions keyed by domain signals
_DOMAIN_EXTRA_NODES: dict[str, list[NodeShape]] = {
    "frontend": [
        NodeShape("FRONTEND_COMPONENT", "UI component (React, Vue, etc.)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("component_type",
                   allowed_values=["page", "layout", "widget", "modal", "form", "hook"]),
                   _prop("framework")],
                  [_edge("USES", ["SERVICE", "MODULE", "STORE"]),
                   _edge("RENDERS", ["FRONTEND_COMPONENT"]),
                   _edge("CONTAINS", ["FRONTEND_COMPONENT"])]),
        NodeShape("ROUTE", "A frontend or API route",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("path"), _prop("method",
                   allowed_values=["GET", "POST", "PUT", "PATCH", "DELETE"]),
                   _prop("auth_required", prop_type="bool")],
                  [_edge("HANDLED_BY", ["FRONTEND_COMPONENT", "FUNCTION"]),
                   _edge("PROTECTED_BY", ["AUTH_PROVIDER"])]),
        NodeShape("STORE", "Client-side state store (Redux, Zustand, Pinia, etc.)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("persisted", prop_type="bool")],
                  [_edge("USED_BY", ["FRONTEND_COMPONENT"])]),
        NodeShape("STYLE_SYSTEM", "CSS/design token system",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("framework"), _prop("file_path")],
                  [_edge("STYLES", ["FRONTEND_COMPONENT"])]),
    ],
    "backend": [
        NodeShape("SERVICE", "Backend service or microservice",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("handler"), _prop("runtime"), _prop("port", prop_type="int"),
                   _prop("protocol", allowed_values=["http", "grpc", "websocket", "graphql"])],
                  [_edge("CALLS", ["SERVICE"]), _edge("REQUIRES", ["ENVVAR"]),
                   _edge("READS_FROM", ["DATABASE_TABLE"]),
                   _edge("WRITES_TO", ["DATABASE_TABLE"])]),
        NodeShape("MIDDLEWARE", "HTTP middleware or interceptor",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("order", prop_type="int")],
                  [_edge("WRAPS", ["FUNCTION", "SERVICE"])]),
        NodeShape("QUEUE", "Message queue or event bus",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("topic")],
                  [_edge("CONSUMED_BY", ["SERVICE"]),
                   _edge("PRODUCED_BY_SERVICE", ["SERVICE"])]),
    ],
    "database": [
        NodeShape("DATABASE", "Database instance",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("engine",
                   allowed_values=["postgresql", "mysql", "sqlite", "mongodb",
                                   "dynamodb", "redis", "neo4j", "cassandra", "other"]),
                   _prop("endpoint"), _prop("region")]),
        NodeShape("DATABASE_TABLE", "Database table, collection, or index",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("table_name"), _prop("schema"), _prop("engine")],
                  [_edge("BELONGS_TO", ["DATABASE"]),
                   _edge("REFERENCES_TABLE", ["DATABASE_TABLE"])]),
        NodeShape("MIGRATION", "Database migration file",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("version"), _prop("direction",
                   allowed_values=["up", "down"]),
                   _prop("applied", prop_type="bool")],
                  [_edge("MODIFIES_TABLE", ["DATABASE_TABLE"]),
                   _edge("FOLLOWS", ["MIGRATION"])]),
        NodeShape("QUERY", "A named or complex database query",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("query_text"), _prop("performance_ms", prop_type="float")],
                  [_edge("QUERIES", ["DATABASE_TABLE"]),
                   _edge("CALLED_BY", ["FUNCTION"])]),
    ],
    "api": [
        NodeShape("API_ENDPOINT", "A REST/GraphQL/gRPC endpoint",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("path"), _prop("method",
                   allowed_values=["GET", "POST", "PUT", "PATCH", "DELETE", "QUERY", "MUTATION"]),
                   _prop("auth_required", prop_type="bool"),
                   _prop("rate_limit", prop_type="int"),
                   _prop("deprecated", prop_type="bool")],
                  [_edge("HANDLED_BY", ["FUNCTION", "SERVICE"]),
                   _edge("RETURNS_SCHEMA", ["DATA_SCHEMA"]),
                   _edge("ACCEPTS_SCHEMA", ["DATA_SCHEMA"]),
                   _edge("PROTECTED_BY", ["AUTH_PROVIDER"])]),
        NodeShape("DATA_SCHEMA", "API request/response schema (OpenAPI, GraphQL type, protobuf)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("format",
                   allowed_values=["openapi", "graphql", "protobuf", "json_schema", "pydantic"]),
                   _prop("file_path")],
                  [_edge("USED_BY", ["API_ENDPOINT"])]),
    ],
    "serverless": [
        NodeShape("LAMBDA_FUNCTION", "Serverless function (AWS Lambda, Vercel, Cloudflare Worker)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("handler"), _prop("runtime"), _prop("memory_mb", prop_type="int"),
                   _prop("timeout_seconds", prop_type="int"), _prop("function_url"),
                   _prop("region"), _prop("trigger_type",
                   allowed_values=["http", "event", "schedule", "queue", "stream"])],
                  [_edge("REQUIRES", ["ENVVAR"]), _edge("CALLS", ["SERVICE", "LAMBDA_FUNCTION"]),
                   _edge("READS_FROM", ["DATABASE_TABLE", "CLOUD_RESOURCE"]),
                   _edge("WRITES_TO", ["DATABASE_TABLE", "CLOUD_RESOURCE"])]),
        NodeShape("EVENT_SOURCE", "Event trigger for serverless function",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("source_type",
                   allowed_values=["api_gateway", "s3", "dynamodb_stream", "sqs",
                                   "sns", "eventbridge", "schedule", "cognito"])],
                  [_edge("TRIGGERS", ["LAMBDA_FUNCTION"])]),
    ],
    "cloud": [
        NodeShape("CLOUD_RESOURCE", "Cloud infrastructure resource",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("resource_type"), _prop("provider",
                   allowed_values=["aws", "gcp", "azure", "cloudflare", "vercel", "other"]),
                   _prop("region"), _prop("arn"), _prop("endpoint")],
                  [_edge("USED_BY", ["SERVICE", "LAMBDA_FUNCTION"])]),
        NodeShape("DOMAIN_NAME", "DNS domain or subdomain",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("fqdn"), _prop("registrar"), _prop("hosted_zone")],
                  [_edge("ROUTES_TO", ["SERVICE", "CLOUD_RESOURCE"]),
                   _edge("CERTIFIED_BY", ["CERTIFICATE"])]),
        NodeShape("CERTIFICATE", "TLS/SSL certificate",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("arn"), _prop("domains", prop_type="list"),
                   _prop("expiry_date")],
                  [_edge("SECURES", ["DOMAIN_NAME"])]),
    ],
    "infrastructure": [
        NodeShape("DEPLOYMENT", "Deployment configuration or environment",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("environment",
                   allowed_values=["development", "staging", "production", "preview"]),
                   _prop("provider"), _prop("region")],
                  [_edge("HOSTS", ["SERVICE"]),
                   _edge("MANAGED_BY", ["CI_PIPELINE"])]),
        NodeShape("CONTAINER", "Docker container or image",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("image"), _prop("tag"), _prop("registry"),
                   _prop("base_image")],
                  [_edge("RUNS", ["SERVICE"]),
                   _edge("BUILT_BY", ["CI_STAGE"])]),
    ],
    "kubernetes": [
        NodeShape("K8S_CLUSTER", "Kubernetes cluster",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("version"), _prop("node_count", prop_type="int")]),
        NodeShape("K8S_NAMESPACE", "Kubernetes namespace",
                  [_prop("id", required=True), _prop("label", required=True)],
                  [_edge("PART_OF", ["K8S_CLUSTER"])]),
        NodeShape("K8S_DEPLOYMENT", "Kubernetes Deployment/StatefulSet",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("replicas", prop_type="int"), _prop("image")],
                  [_edge("RUNS_IN", ["K8S_NAMESPACE"]),
                   _edge("RUNS", ["CONTAINER"])]),
        NodeShape("K8S_SERVICE", "Kubernetes Service",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("service_type", allowed_values=["ClusterIP", "NodePort", "LoadBalancer"]),
                   _prop("port", prop_type="int")],
                  [_edge("EXPOSES", ["K8S_DEPLOYMENT"])]),
        NodeShape("K8S_INGRESS", "Kubernetes Ingress",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("host"), _prop("tls", prop_type="bool")],
                  [_edge("ROUTES_TO", ["K8S_SERVICE"])]),
    ],
    "ml": [
        NodeShape("ML_MODEL", "Machine learning model",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("architecture"), _prop("framework",
                   allowed_values=["pytorch", "tensorflow", "sklearn", "xgboost",
                                   "huggingface", "onnx", "custom"]),
                   _prop("version"), _prop("metrics", prop_type="dict"),
                   _prop("parameters_count", prop_type="int")],
                  [_edge("TRAINED_ON", ["DATASET"]),
                   _edge("EVALUATED_BY", ["BENCHMARK"]),
                   _edge("SERVED_BY", ["SERVICE", "LAMBDA_FUNCTION"])]),
        NodeShape("DATASET", "Training/evaluation dataset",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("size"), _prop("format"), _prop("source"),
                   _prop("row_count", prop_type="int")],
                  [_edge("USED_BY", ["ML_MODEL"]),
                   _edge("STORED_IN", ["CLOUD_RESOURCE"])]),
        NodeShape("EXPERIMENT", "ML experiment or training run",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("status", allowed_values=["running", "completed", "failed"]),
                   _prop("metrics", prop_type="dict"), _prop("hyperparameters", prop_type="dict")],
                  [_edge("PRODUCES", ["ML_MODEL"]),
                   _edge("USES", ["DATASET"])]),
        NodeShape("BENCHMARK", "Evaluation benchmark",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("metric_name"), _prop("score", prop_type="float")],
                  [_edge("EVALUATES", ["ML_MODEL"])]),
        NodeShape("FEATURE_STORE", "Feature engineering store",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("feature_count", prop_type="int")],
                  [_edge("PROVIDES_FEATURES_TO", ["ML_MODEL"])]),
    ],
    "data_science": [
        NodeShape("NOTEBOOK", "Jupyter/Colab notebook",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path"), _prop("kernel"),
                   _prop("cell_count", prop_type="int")],
                  [_edge("USES", ["DATASET", "ML_MODEL"])]),
        NodeShape("VISUALIZATION", "Data visualization or chart",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("chart_type"), _prop("library")],
                  [_edge("DISPLAYS", ["DATASET", "METRIC"])]),
    ],
    "data_engineering": [
        NodeShape("DATA_PIPELINE", "ETL/ELT data pipeline",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("orchestrator",
                   allowed_values=["airflow", "prefect", "dagster", "dbt", "custom"]),
                   _prop("schedule"), _prop("status")],
                  [_edge("READS_FROM", ["DATABASE_TABLE", "CLOUD_RESOURCE"]),
                   _edge("WRITES_TO", ["DATABASE_TABLE", "CLOUD_RESOURCE"]),
                   _edge("CONTAINS", ["PIPELINE_STEP"])]),
        NodeShape("PIPELINE_STEP", "Step in a data pipeline",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("step_type", allowed_values=["extract", "transform", "load", "validate"]),
                   _prop("duration_seconds", prop_type="float")],
                  [_edge("FLOWS_TO", ["PIPELINE_STEP"]),
                   _edge("EXECUTED_BY", ["SERVICE"])]),
        NodeShape("DATA_WAREHOUSE", "Data warehouse or lake",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider"), _prop("schema_count", prop_type="int")],
                  [_edge("CONTAINS", ["DATABASE_TABLE"])]),
    ],
    "llm_app": [
        NodeShape("LLM_PROVIDER", "LLM API provider",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider",
                   allowed_values=["anthropic", "openai", "bedrock", "ollama",
                                   "huggingface", "cohere", "google", "custom"]),
                   _prop("model_id"), _prop("endpoint")],
                  [_edge("USED_BY", ["AGENT", "SERVICE"])]),
        NodeShape("AGENT", "LLM-powered agent or chain",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("framework"), _prop("system_prompt"),
                   _prop("tools", prop_type="list")],
                  [_edge("CALLS", ["LLM_PROVIDER"]),
                   _edge("USES_TOOL", ["FUNCTION", "SERVICE"]),
                   _edge("RETRIEVES_FROM", ["VECTOR_STORE"])]),
        NodeShape("VECTOR_STORE", "Vector database for embeddings",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider",
                   allowed_values=["pinecone", "weaviate", "qdrant", "chroma",
                                   "faiss", "pgvector", "opensearch"]),
                   _prop("dimension", prop_type="int"),
                   _prop("index_count", prop_type="int")],
                  [_edge("QUERIED_BY", ["AGENT", "SERVICE"])]),
        NodeShape("PROMPT_TEMPLATE", "A reusable prompt template",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("template_text"), _prop("variables", prop_type="list"),
                   _prop("version")],
                  [_edge("USED_BY", ["AGENT"])]),
        NodeShape("RAG_PIPELINE", "Retrieval-Augmented Generation pipeline",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("retriever"), _prop("generator"), _prop("reranker")],
                  [_edge("RETRIEVES_FROM", ["VECTOR_STORE"]),
                   _edge("GENERATES_WITH", ["LLM_PROVIDER"])]),
    ],
    "mobile": [
        NodeShape("SCREEN", "Mobile app screen or view",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("platform", allowed_values=["ios", "android", "cross_platform"]),
                   _prop("file_path")],
                  [_edge("NAVIGATES_TO", ["SCREEN"]),
                   _edge("USES", ["SERVICE"])]),
        NodeShape("NATIVE_MODULE", "Native code module (iOS/Android)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("platform"), _prop("language")],
                  [_edge("BRIDGES_TO", ["MODULE"])]),
    ],
    "gamedev": [
        NodeShape("GAME_SCENE", "Game scene or level",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("scene_type")]),
        NodeShape("GAME_ENTITY", "Game entity or actor",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("entity_type"), _prop("prefab")],
                  [_edge("BELONGS_TO", ["GAME_SCENE"])]),
        NodeShape("GAME_SYSTEM", "ECS system or game subsystem",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("update_phase")],
                  [_edge("PROCESSES", ["GAME_ENTITY"])]),
        NodeShape("ASSET", "Game asset (texture, model, sound, animation)",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("asset_type",
                   allowed_values=["texture", "model", "sound", "animation",
                                   "shader", "font", "tilemap"]),
                   _prop("file_path"), _prop("size_bytes", prop_type="int")],
                  [_edge("USED_BY", ["GAME_ENTITY", "GAME_SCENE"])]),
    ],
    "embedded": [
        NodeShape("MCU", "Microcontroller unit",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("family"), _prop("flash_kb", prop_type="int"),
                   _prop("ram_kb", prop_type="int")]),
        NodeShape("PERIPHERAL", "Hardware peripheral",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("peripheral_type"), _prop("bus",
                   allowed_values=["i2c", "spi", "uart", "gpio", "adc", "pwm", "can", "usb"])],
                  [_edge("CONNECTED_TO", ["MCU"])]),
        NodeShape("DRIVER", "Device driver",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("file_path")],
                  [_edge("CONTROLS", ["PERIPHERAL"])]),
        NodeShape("ISR", "Interrupt service routine",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("irq_number", prop_type="int"), _prop("priority", prop_type="int")],
                  [_edge("HANDLES", ["PERIPHERAL"])]),
    ],
    "graph": [
        NodeShape("GRAPH_DATABASE", "Graph database instance",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("engine",
                   allowed_values=["neo4j", "neptune", "arangodb", "dgraph", "tigergraph"]),
                   _prop("endpoint")]),
        NodeShape("GRAPH_LABEL", "Node label / type in graph DB",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("properties", prop_type="list"),
                   _prop("indexes", prop_type="list")],
                  [_edge("STORED_IN", ["GRAPH_DATABASE"])]),
        NodeShape("CYPHER_QUERY", "Named Cypher/GSQL/AQL query",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("query_text"), _prop("parameterized", prop_type="bool")],
                  [_edge("QUERIES", ["GRAPH_LABEL"])]),
    ],
    "payments": [
        NodeShape("PAYMENT_PROVIDER", "Payment processing provider",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("provider",
                   allowed_values=["stripe", "paypal", "braintree", "square", "adyen"]),
                   _prop("mode", allowed_values=["live", "test"])]),
        NodeShape("PRODUCT", "Billable product or subscription tier",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("product_id"), _prop("price_id"),
                   _prop("price_cents", prop_type="int"),
                   _prop("billing_interval", allowed_values=["monthly", "yearly", "one_time"])],
                  [_edge("MANAGED_BY", ["PAYMENT_PROVIDER"])]),
        NodeShape("WEBHOOK_HANDLER", "Payment webhook handler",
                  [_prop("id", required=True), _prop("label", required=True),
                   _prop("event_type"), _prop("endpoint")],
                  [_edge("LISTENS_TO", ["PAYMENT_PROVIDER"])]),
    ],
}

# Extra edges for specific domain signals
_DOMAIN_EXTRA_EDGES: dict[str, list[EdgeShape]] = {
    "frontend": [
        EdgeShape("RENDERS", "Component renders another component",
                  ["FRONTEND_COMPONENT"], ["FRONTEND_COMPONENT"]),
        EdgeShape("HANDLED_BY", "Route handled by component/function",
                  ["ROUTE", "API_ENDPOINT"], ["FRONTEND_COMPONENT", "FUNCTION"]),
        EdgeShape("STYLES", "Style system styles a component",
                  ["STYLE_SYSTEM"], ["FRONTEND_COMPONENT"]),
        EdgeShape("NAVIGATES_TO", "Navigation between screens/pages",
                  ["FRONTEND_COMPONENT", "SCREEN"], ["FRONTEND_COMPONENT", "SCREEN"]),
        EdgeShape("PROTECTED_BY", "Route/endpoint protected by auth",
                  ["ROUTE", "API_ENDPOINT"], ["AUTH_PROVIDER"]),
    ],
    "database": [
        EdgeShape("BELONGS_TO", "Table belongs to database",
                  ["DATABASE_TABLE"], ["DATABASE"]),
        EdgeShape("REFERENCES_TABLE", "Foreign key reference",
                  ["DATABASE_TABLE"], ["DATABASE_TABLE"]),
        EdgeShape("MODIFIES_TABLE", "Migration modifies a table",
                  ["MIGRATION"], ["DATABASE_TABLE"]),
        EdgeShape("QUERIES", "Query accesses a table/label",
                  ["QUERY", "CYPHER_QUERY"], ["DATABASE_TABLE", "GRAPH_LABEL"]),
        EdgeShape("CALLED_BY", "Query called by a function",
                  ["QUERY"], ["FUNCTION"]),
    ],
    "api": [
        EdgeShape("RETURNS_SCHEMA", "Endpoint returns a data schema",
                  ["API_ENDPOINT"], ["DATA_SCHEMA"]),
        EdgeShape("ACCEPTS_SCHEMA", "Endpoint accepts a data schema",
                  ["API_ENDPOINT"], ["DATA_SCHEMA"]),
    ],
    "serverless": [
        EdgeShape("TRIGGERED_BY", "Function triggered by event source",
                  ["LAMBDA_FUNCTION"], ["EVENT_SOURCE"]),
    ],
    "ml": [
        EdgeShape("TRAINED_ON", "Model trained on dataset",
                  ["ML_MODEL"], ["DATASET"]),
        EdgeShape("EVALUATED_BY", "Model evaluated by benchmark",
                  ["ML_MODEL"], ["BENCHMARK"]),
        EdgeShape("SERVED_BY", "Model served by service",
                  ["ML_MODEL"], ["SERVICE", "LAMBDA_FUNCTION"]),
        EdgeShape("PROVIDES_FEATURES_TO", "Feature store provides to model",
                  ["FEATURE_STORE"], ["ML_MODEL"]),
        EdgeShape("STORED_IN", "Data stored in resource",
                  ["DATASET"], ["CLOUD_RESOURCE"]),
    ],
    "llm_app": [
        EdgeShape("USES_TOOL", "Agent uses a tool",
                  ["AGENT"], ["FUNCTION", "SERVICE"]),
        EdgeShape("RETRIEVES_FROM", "Agent retrieves from vector store",
                  ["AGENT", "RAG_PIPELINE"], ["VECTOR_STORE"]),
        EdgeShape("GENERATES_WITH", "Pipeline generates with LLM",
                  ["RAG_PIPELINE"], ["LLM_PROVIDER"]),
        EdgeShape("QUERIED_BY", "Store queried by agent/service",
                  ["VECTOR_STORE"], ["AGENT", "SERVICE"]),
    ],
    "infrastructure": [
        EdgeShape("HOSTS", "Deployment hosts a service",
                  ["DEPLOYMENT"], ["SERVICE"]),
        EdgeShape("MANAGED_BY", "Deployment managed by pipeline",
                  ["DEPLOYMENT"], ["CI_PIPELINE", "PAYMENT_PROVIDER"]),
        EdgeShape("RUNS", "Container runs a service",
                  ["CONTAINER", "K8S_DEPLOYMENT"], ["SERVICE", "CONTAINER"]),
        EdgeShape("BUILT_BY", "Container built by CI stage",
                  ["CONTAINER"], ["CI_STAGE"]),
    ],
    "kubernetes": [
        EdgeShape("RUNS_IN", "Deployment runs in namespace",
                  ["K8S_DEPLOYMENT"], ["K8S_NAMESPACE"]),
        EdgeShape("EXPOSES", "Service exposes deployment",
                  ["K8S_SERVICE"], ["K8S_DEPLOYMENT"]),
    ],
    "cloud": [
        EdgeShape("CERTIFIED_BY", "Domain certified by TLS cert",
                  ["DOMAIN_NAME"], ["CERTIFICATE"]),
        EdgeShape("SECURES", "Certificate secures a domain",
                  ["CERTIFICATE"], ["DOMAIN_NAME"]),
    ],
    "payments": [
        EdgeShape("LISTENS_TO", "Webhook listens to provider events",
                  ["WEBHOOK_HANDLER"], ["PAYMENT_PROVIDER"]),
    ],
    "gamedev": [
        EdgeShape("PROCESSES", "System processes entities",
                  ["GAME_SYSTEM"], ["GAME_ENTITY"]),
        EdgeShape("CONNECTED_TO", "Hardware connected to MCU",
                  ["PERIPHERAL"], ["MCU"]),
    ],
    "embedded": [
        EdgeShape("HANDLES", "ISR handles peripheral interrupt",
                  ["ISR"], ["PERIPHERAL"]),
    ],
    "graph": [
        EdgeShape("STORED_IN", "Label stored in graph database",
                  ["GRAPH_LABEL"], ["GRAPH_DATABASE"]),
    ],
    "mobile": [
        EdgeShape("BRIDGES_TO", "Native module bridges to JS/Dart module",
                  ["NATIVE_MODULE"], ["MODULE"]),
    ],
    "data_engineering": [
        EdgeShape("FLOWS_TO", "Pipeline step flows to next step",
                  ["PIPELINE_STEP"], ["PIPELINE_STEP"]),
        EdgeShape("EXECUTED_BY", "Step executed by service",
                  ["PIPELINE_STEP"], ["SERVICE"]),
    ],
}


def _build_heuristic_ontology(profile: DomainProfile) -> tuple[list[NodeShape], list[EdgeShape]]:
    """Build a comprehensive ontology using heuristic pattern matching."""
    node_shapes = _heuristic_base_nodes()
    edge_shapes = _heuristic_base_edges()

    # Collect which domain extras to include based on profile features
    active_domains: set[str] = set()

    if profile.has_frontend:
        active_domains.add("frontend")
    if profile.has_backend:
        active_domains.add("backend")
    if profile.has_database:
        active_domains.add("database")
    if profile.has_api:
        active_domains.add("api")
    if profile.has_serverless:
        active_domains.add("serverless")
    if profile.has_ml:
        active_domains.update(("ml", "data_science"))
    if profile.has_docker:
        active_domains.add("infrastructure")
    if profile.has_kubernetes:
        active_domains.add("kubernetes")

    # Check primary/secondary domains for additional signals
    all_domains = [profile.primary_domain] + profile.secondary_domains
    for d in all_domains:
        if "llm" in d or "ai" in d:
            active_domains.add("llm_app")
        if "data_eng" in d:
            active_domains.add("data_engineering")
        if "mobile" in d:
            active_domains.add("mobile")
        if "game" in d:
            active_domains.add("gamedev")
        if "embed" in d:
            active_domains.add("embedded")
        if "graph" in d:
            active_domains.add("graph")
        if "frontend" in d or "web" in d or "fullstack" in d or "saas" in d:
            active_domains.add("frontend")
        if "backend" in d or "api" in d or "fullstack" in d or "saas" in d:
            active_domains.add("backend")
            active_domains.add("api")
        if "serverless" in d:
            active_domains.add("serverless")
        if "infrastructure" in d:
            active_domains.add("infrastructure")

    # Check dependencies for cloud/payment signals
    dep_str = " ".join(profile.dependencies).lower()
    if "boto3" in dep_str or "aws" in dep_str:
        active_domains.add("cloud")
    if "stripe" in dep_str or "paypal" in dep_str:
        active_domains.add("payments")

    # Always include cloud if serverless or infrastructure
    if "serverless" in active_domains or "infrastructure" in active_domains:
        active_domains.add("cloud")

    # Add domain-specific nodes and edges
    existing_node_types = {ns.node_type for ns in node_shapes}
    existing_edge_types = {es.edge_type for es in edge_shapes}

    for domain in active_domains:
        for ns in _DOMAIN_EXTRA_NODES.get(domain, []):
            if ns.node_type not in existing_node_types:
                node_shapes.append(ns)
                existing_node_types.add(ns.node_type)

        for es in _DOMAIN_EXTRA_EDGES.get(domain, []):
            if es.edge_type not in existing_edge_types:
                edge_shapes.append(es)
                existing_edge_types.add(es.edge_type)

    logger.info(
        f"Heuristic ontology: {len(node_shapes)} node types, "
        f"{len(edge_shapes)} edge types (active domains: {sorted(active_domains)})"
    )
    return node_shapes, edge_shapes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ontology(
    profile: DomainProfile,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-6",
) -> tuple[list[NodeShape], list[EdgeShape]]:
    """Generate a domain-specific ontology from a DomainProfile.

    If an Anthropic API key is provided, uses Claude Sonnet (or specified model)
    to generate a comprehensive, tailored ontology. Otherwise, falls back to
    a rich heuristic ontology based on pattern matching.

    This is a ONE-TIME operation -- the result should be cached/persisted.

    Parameters
    ----------
    profile : DomainProfile
        The detected domain profile from detect_domain().
    api_key : str | None
        Anthropic API key. If None, falls back to heuristic generation.
        Also checks ANTHROPIC_API_KEY environment variable.
    model : str
        Model to use for ontology generation. Default: claude-sonnet-4-6.
        Always prefer Sonnet or Opus for ontology quality.

    Returns
    -------
    tuple[list[NodeShape], list[EdgeShape]]
        Generated node shapes and edge shapes.
    """
    # Resolve API key
    effective_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    if effective_key:
        try:
            logger.info(f"Generating ontology with LLM ({model})...")
            prompt = _build_llm_prompt(profile)
            response = _call_anthropic_api(prompt, effective_key, model)
            node_shapes, edge_shapes = _parse_llm_ontology(response)

            if len(node_shapes) >= 10 and len(edge_shapes) >= 10:
                logger.info(
                    f"LLM ontology: {len(node_shapes)} node types, "
                    f"{len(edge_shapes)} edge types"
                )
                return node_shapes, edge_shapes
            else:
                logger.warning(
                    f"LLM returned sparse ontology ({len(node_shapes)} nodes, "
                    f"{len(edge_shapes)} edges). Falling back to heuristic."
                )
        except Exception as e:
            logger.warning(f"LLM ontology generation failed: {e}. Falling back to heuristic.")

    # Fallback: heuristic ontology
    return _build_heuristic_ontology(profile)


def auto_ontology(
    root: Path,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-6",
    register: bool = True,
) -> tuple[list[NodeShape], list[EdgeShape]]:
    """Convenience wrapper: detect domain + generate ontology in one call.

    Parameters
    ----------
    root : Path
        Root directory of the codebase to analyze.
    api_key : str | None
        Anthropic API key (or set ANTHROPIC_API_KEY env var).
    model : str
        LLM model to use. Default: claude-sonnet-4-6.
    register : bool
        If True, auto-registers all generated shapes via register_node_shape()
        and register_edge_shape(). Default: True.

    Returns
    -------
    tuple[list[NodeShape], list[EdgeShape]]
        The generated ontology shapes.
    """
    profile = detect_domain(root)
    node_shapes, edge_shapes = generate_ontology(profile, api_key=api_key, model=model)

    if register:
        for ns in node_shapes:
            register_node_shape(ns)
        for es in edge_shapes:
            register_edge_shape(es)
        logger.info(
            f"Registered {len(node_shapes)} node shapes and "
            f"{len(edge_shapes)} edge shapes into global registry"
        )

    return node_shapes, edge_shapes


__all__ = [
    "DomainProfile",
    "detect_domain",
    "generate_ontology",
    "auto_ontology",
]
