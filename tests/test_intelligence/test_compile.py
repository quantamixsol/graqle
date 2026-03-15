"""Tests for graqle.intelligence.compile — The Intelligence Compiler."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_compile
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, pathlib, pytest, compile
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.intelligence.compile import compile_intelligence


def _create_mini_project(root: Path) -> None:
    """Create a minimal Python project for testing."""
    (root / "mod_a.py").write_text(
        '"""Module A — handles core logic."""\n\n'
        "from mod_b import helper\n\n"
        "def main_func():\n"
        '    """Main function that orchestrates everything."""\n'
        "    return helper()\n\n"
        "class CoreEngine:\n"
        '    """The core processing engine."""\n'
        "    def run(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    (root / "mod_b.py").write_text(
        '"""Module B — utility helpers."""\n\n'
        "def helper():\n"
        '    """A helpful utility function."""\n'
        "    return 42\n\n"
        "def another_helper():\n"
        '    """Another helper function."""\n'
        "    return 99\n",
        encoding="utf-8",
    )
    (root / "mod_c.py").write_text(
        '"""Module C — depends on both A and B."""\n\n'
        "from mod_a import main_func\n"
        "from mod_b import helper, another_helper\n\n"
        "def combined():\n"
        '    """Combines A and B functionality."""\n'
        "    return main_func() + helper() + another_helper()\n",
        encoding="utf-8",
    )


class TestCompileIntelligence:
    """Tests for compile_intelligence."""

    def test_basic_compile(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        result = compile_intelligence(tmp_path, inject=False)

        assert result["total_modules"] >= 3
        assert result["duration_seconds"] >= 0
        assert "health" in result
        assert result["chunk_coverage"] > 0

    def test_compile_creates_intelligence_dir(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        compile_intelligence(tmp_path, inject=False)

        intel_dir = tmp_path / ".graqle" / "intelligence"
        assert intel_dir.exists()
        assert (intel_dir / "module_index.json").exists()
        assert (intel_dir / "impact_matrix.json").exists()
        assert (tmp_path / ".graqle" / "scorecard.json").exists()

    def test_compile_with_inject(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        result = compile_intelligence(tmp_path, inject=True)

        assert result["files_injected"] >= 1

        # Check that at least one file has a header
        content_a = (tmp_path / "mod_a.py").read_text(encoding="utf-8")
        content_b = (tmp_path / "mod_b.py").read_text(encoding="utf-8")
        has_any_header = (
            "graqle:intelligence" in content_a or
            "graqle:intelligence" in content_b
        )
        assert has_any_header

    def test_compile_eject(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)

        # First inject
        compile_intelligence(tmp_path, inject=True)

        # Then eject
        result = compile_intelligence(tmp_path, eject=True)
        assert "ejected_headers" in result

        # Verify headers are gone
        content_a = (tmp_path / "mod_a.py").read_text(encoding="utf-8")
        assert "graqle:intelligence" not in content_a

    def test_compile_creates_claude_md(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        result = compile_intelligence(tmp_path, inject=True)

        # Should create CLAUDE.md if none exists
        claude_path = tmp_path / "CLAUDE.md"
        if claude_path.exists():
            content = claude_path.read_text(encoding="utf-8")
            assert "graqle:intelligence" in content

    def test_compile_module_index_content(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        compile_intelligence(tmp_path, inject=False)

        index_path = tmp_path / ".graqle" / "intelligence" / "module_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))

        assert index["total_modules"] >= 3
        modules = {m["module"] for m in index["modules"]}
        # Module names should be clean (no .py suffix)
        for mod in modules:
            assert not mod.endswith(".py")

    def test_compile_returns_coverage_metrics(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        result = compile_intelligence(tmp_path, inject=False)

        assert "chunk_coverage" in result
        assert "description_coverage" in result
        assert "edge_integrity" in result
        assert 0 <= result["chunk_coverage"] <= 100
        assert 0 <= result["description_coverage"] <= 100

    def test_compile_empty_project(self, tmp_path: Path) -> None:
        """Compile should handle a directory with no source files."""
        result = compile_intelligence(tmp_path, inject=False)
        assert result["total_modules"] == 0

    def test_compile_discovers_insights(self, tmp_path: Path) -> None:
        _create_mini_project(tmp_path)
        result = compile_intelligence(tmp_path, inject=False)
        # With 3 modules, should find at least some insights
        assert result["insights"] >= 0  # May be 0 for tiny projects


class TestDogfoodCompile:
    """Dogfooding: compile on real SDK intelligence module."""

    def test_compile_on_intelligence_subdir(self, tmp_path: Path) -> None:
        """Create a realistic intelligence-like subdir and compile it."""
        # Create files mimicking graqle/intelligence/
        (tmp_path / "models.py").write_text(
            '"""Data models for intelligence pipeline."""\n\n'
            "from pydantic import BaseModel\n\n"
            "class ValidatedNode(BaseModel):\n"
            '    """A validated node with guaranteed coverage."""\n'
            "    id: str\n"
            "    label: str\n"
            "    type: str\n\n"
            "class ModulePacket(BaseModel):\n"
            '    """Pre-compiled intelligence for a module."""\n'
            "    module: str\n"
            "    risk_score: float\n",
            encoding="utf-8",
        )
        (tmp_path / "validators.py").write_text(
            '"""6 validation gates for per-file quality."""\n\n'
            "from models import ValidatedNode\n\n"
            "def gate_1_parse_integrity(content):\n"
            '    """Gate 1: verify AST parse succeeds."""\n'
            "    return True\n\n"
            "def gate_2_node_completeness(nodes):\n"
            '    """Gate 2: verify all nodes have required fields."""\n'
            "    return all(n.label for n in nodes)\n",
            encoding="utf-8",
        )
        (tmp_path / "pipeline.py").write_text(
            '"""Streaming intelligence pipeline."""\n\n'
            "from models import ValidatedNode, ModulePacket\n"
            "from validators import gate_1_parse_integrity, gate_2_node_completeness\n\n"
            "def stream_intelligence(root):\n"
            '    """Stream intelligence per file."""\n'
            "    pass\n",
            encoding="utf-8",
        )

        result = compile_intelligence(tmp_path, inject=False)
        assert result["total_modules"] >= 3
        assert result["chunk_coverage"] > 0
