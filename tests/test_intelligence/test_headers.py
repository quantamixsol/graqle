"""Tests for graqle.intelligence.headers — Inline Intelligence Headers."""

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.intelligence.headers import (
    generate_header,
    inject_header,
    eject_header,
    has_header,
    MAX_HEADER_BYTES,
    _find_insert_position,
)
from graqle.intelligence.models import ModulePacket, ModuleConsumer, ModuleDependency


def _make_packet(
    module: str = "test_mod",
    consumers: int = 0,
    dependencies: int = 0,
    constraints: list[str] | None = None,
    incidents: list[str] | None = None,
) -> ModulePacket:
    return ModulePacket(
        module=module,
        files=["test_mod.py"],
        node_count=3,
        function_count=2,
        class_count=1,
        line_count=50,
        public_interfaces=[],
        consumers=[ModuleConsumer(module=f"client_{i}", via="IMPORTS") for i in range(consumers)],
        dependencies=[ModuleDependency(module=f"dep_{i}", type="internal") for i in range(dependencies)],
        risk_score=0.5,
        risk_level="MEDIUM",
        impact_radius=2,
        chunk_coverage=95.0,
        description_coverage=90.0,
        constraints=constraints or [],
        incidents=incidents or [],
    )


class TestGenerateHeader:
    """Tests for generate_header."""

    def test_python_header(self) -> None:
        header = generate_header(_make_packet(), ".py")
        assert header.startswith("# ── graqle:intelligence ──
# module: tests.test_intelligence.test_headers
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, headers, models
# constraints: none
# ── /graqle:intelligence ──\n\ndef hello():\n    pass\n",
            encoding="utf-8",
        )

        new_pkt = _make_packet(module="updated_mod")
        header = generate_header(new_pkt, ".py")
        assert inject_header(fpath, header) is True

        content = fpath.read_text(encoding="utf-8")
        assert "updated_mod" in content
        assert "old content" not in content

    def test_inject_idempotent(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text("def hello():\n    pass\n", encoding="utf-8")

        header = generate_header(_make_packet(), ".py")
        inject_header(fpath, header)
        content_after_first = fpath.read_text(encoding="utf-8")

        assert inject_header(fpath, header) is False
        content_after_second = fpath.read_text(encoding="utf-8")
        assert content_after_first == content_after_second

    def test_inject_empty_header_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text("pass\n", encoding="utf-8")
        assert inject_header(fpath, "") is False

    def test_inject_typescript(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.ts"
        fpath.write_text("export function hello() {}\n", encoding="utf-8")

        header = generate_header(_make_packet(), ".ts")
        assert inject_header(fpath, header) is True

        content = fpath.read_text(encoding="utf-8")
        assert "// ── graqle:intelligence ──" in content


class TestEjectHeader:
    """Tests for eject_header."""

    def test_eject_removes_header(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text("def hello():\n    pass\n", encoding="utf-8")

        header = generate_header(_make_packet(), ".py")
        inject_header(fpath, header)
        assert has_header(fpath) is True

        assert eject_header(fpath) is True
        assert has_header(fpath) is False

        content = fpath.read_text(encoding="utf-8")
        assert "graqle:intelligence" not in content
        assert "hello" in content

    def test_eject_no_header_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text("def hello():\n    pass\n", encoding="utf-8")
        assert eject_header(fpath) is False

    def test_eject_nonexistent_file_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "missing.py"
        assert eject_header(fpath) is False


class TestHasHeader:
    """Tests for has_header."""

    def test_has_header_true(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text(
            "# ── graqle:intelligence ──\n# stuff\n# ── /graqle:intelligence ──\n",
            encoding="utf-8",
        )
        assert has_header(fpath) is True

    def test_has_header_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "mod.py"
        fpath.write_text("def hello():\n    pass\n", encoding="utf-8")
        assert has_header(fpath) is False


class TestFindInsertPosition:
    """Tests for _find_insert_position."""

    def test_python_after_shebang(self) -> None:
        content = "#!/usr/bin/env python\n\nimport os\n"
        pos = _find_insert_position(content, ".py")
        assert pos > 0
        assert content[pos:].startswith("import")

    def test_python_after_multiline_docstring(self) -> None:
        content = '"""\nModule doc.\nMultiple lines.\n"""\n\nimport os\n'
        pos = _find_insert_position(content, ".py")
        assert content[pos:].startswith("import")

    def test_js_after_use_strict(self) -> None:
        content = "'use strict';\n\nconst x = 1;\n"
        pos = _find_insert_position(content, ".js")
        assert pos > 0
