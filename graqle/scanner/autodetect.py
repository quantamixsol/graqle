"""Environment auto-detection — DETECT don't ASK."""

# ── graqle:intelligence ──
# module: graqle.scanner.autodetect
# risk: LOW (impact radius: 1 modules)
# consumers: test_autodetect
# dependencies: __future__, os, logging, dataclasses, pathlib
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("graqle.scanner.autodetect")


@dataclass
class DetectedEnvironment:
    """Auto-detected project environment."""

    # Backend
    backend: str = "local"  # "bedrock", "anthropic", "openai", "local"
    region: str | None = None

    # Project
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    has_git: bool = False

    # IDE
    ide: str | None = None  # "vscode", "cursor", "jetbrains", None

    # Machine
    capacity: str = "standard"  # "minimal", "standard", "capable", "powerful"
    cpu_count: int = 1
    ram_gb: float = 4.0

    # Exclusions (auto-detected)
    smart_excludes: list[str] = field(default_factory=list)


def detect_environment(project_root: Path | str) -> DetectedEnvironment:
    """Auto-detect everything about the project environment.

    Follows the DETECT don't ASK principle — check env vars,
    file patterns, and system state rather than prompting the user.
    """
    root = Path(project_root).resolve()
    env = DetectedEnvironment()

    # Detect backend from env vars
    env.backend, env.region = _detect_backend()

    # Detect languages
    env.languages = _detect_languages(root)

    # Detect frameworks
    env.frameworks = _detect_frameworks(root)

    # Detect git
    env.has_git = (root / ".git").is_dir()

    # Detect IDE
    env.ide = _detect_ide(root)

    # Detect machine capacity
    env.capacity, env.cpu_count, env.ram_gb = _detect_machine()

    # Build smart excludes
    env.smart_excludes = _build_smart_excludes(root, env.languages)

    return env


def _detect_backend() -> tuple[str, str | None]:
    """Detect model backend from environment variables."""
    # AWS Bedrock
    if any(os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_DEFAULT_REGION")):
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
        return "bedrock", region

    # Anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", None

    # OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", None

    return "local", None


def _detect_languages(root: Path) -> list[str]:
    """Detect programming languages from file extensions in root."""
    lang_signals: dict[str, list[str]] = {
        "python": ["*.py", "pyproject.toml", "setup.py", "Pipfile", "requirements.txt"],
        "typescript": ["tsconfig.json", "*.ts", "*.tsx"],
        "javascript": ["*.js", "*.jsx", "package.json"],
        "go": ["go.mod", "*.go"],
        "rust": ["Cargo.toml", "*.rs"],
        "java": ["pom.xml", "build.gradle", "*.java"],
        "csharp": ["*.csproj", "*.cs", "*.sln"],
        "ruby": ["Gemfile", "*.rb"],
    }

    detected = []
    for lang, patterns in lang_signals.items():
        for pattern in patterns:
            # Check config files in root
            if not pattern.startswith("*"):
                if (root / pattern).exists():
                    detected.append(lang)
                    break
            else:
                # Quick scan: check root + 1 level deep
                if list(root.glob(pattern))[:1] or list(root.glob(f"*/{pattern}"))[:1]:
                    detected.append(lang)
                    break

    return detected


def _detect_frameworks(root: Path) -> list[str]:
    """Detect frameworks from config files."""
    frameworks = []

    framework_signals = {
        "next.js": "next.config.js",
        "react": None,  # detected from package.json
        "django": "manage.py",
        "flask": None,  # detected from imports
        "fastapi": None,
        "express": None,
        "cdk": "cdk.json",
        "serverless": "serverless.yml",
        "terraform": "main.tf",
    }

    for fw, config_file in framework_signals.items():
        if config_file and (root / config_file).exists():
            frameworks.append(fw)

    # Check next.config variants
    for variant in ("next.config.mjs", "next.config.ts"):
        if (root / variant).exists() and "next.js" not in frameworks:
            frameworks.append("next.js")

    # Check package.json for React/Express/etc
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "react" in deps and "react" not in frameworks:
                frameworks.append("react")
            if "express" in deps and "express" not in frameworks:
                frameworks.append("express")
            if "fastify" in deps:
                frameworks.append("fastify")
            if "vue" in deps:
                frameworks.append("vue")
            if "angular" in deps or "@angular/core" in deps:
                frameworks.append("angular")
        except Exception:
            pass

    return frameworks


def _detect_ide(root: Path) -> str | None:
    """Detect active IDE from project files and running processes."""
    if (root / ".cursor").is_dir():
        return "cursor"
    if (root / ".vscode").is_dir():
        return "vscode"
    if (root / ".idea").is_dir():
        return "jetbrains"
    return None


def _detect_machine() -> tuple[str, int, float]:
    """Detect machine capacity."""
    cpu_count = os.cpu_count() or 1

    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        # Fallback: assume 8GB if psutil not available
        ram_gb = 8.0

    if ram_gb < 4:
        capacity = "minimal"
    elif ram_gb < 8:
        capacity = "standard"
    elif ram_gb < 16:
        capacity = "capable"
    else:
        capacity = "powerful"

    return capacity, cpu_count, round(ram_gb, 1)


def _build_smart_excludes(root: Path, languages: list[str]) -> list[str]:
    """Build smart exclude patterns based on detected languages."""
    excludes = [
        "node_modules/", ".git/", "__pycache__/", "dist/", ".next/",
        "venv/", ".venv/", ".tox/", "*.pyc", "*.pyo",
        ".mypy_cache/", ".pytest_cache/", ".ruff_cache/",
        "build/", "target/", "bin/", "obj/",
        "*.min.js", "*.min.css", "*.map",
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "*.egg-info/", ".eggs/",
    ]

    if "rust" in languages:
        excludes.append("target/")
    if "java" in languages:
        excludes.extend([".gradle/", ".m2/"])
    if "csharp" in languages:
        excludes.extend(["bin/", "obj/", "packages/"])

    return excludes


def suggest_mcp_config(ide: str | None, project_root: Path) -> dict | None:
    """Generate MCP config suggestion for detected IDE."""
    if ide not in ("vscode", "cursor"):
        return None

    return {
        "mcpServers": {
            "graqle": {
                "command": "graq",
                "args": ["serve", "--mcp", "--port", "8077"],
                "cwd": str(project_root),
            }
        }
    }
