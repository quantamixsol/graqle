"""Tests for graqle.intelligence.claude_section — CLAUDE.md Auto-Section Generator."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_claude_section
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, claude_section, models +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.intelligence.claude_section import (
    OPEN_MARKER,
    CLOSE_MARKER,
    generate_section,
    detect_ai_tools,
    inject_section,
    eject_section,
)
from graqle.intelligence.models import ModulePacket
from graqle.intelligence.scorecard import RunningScorecard


def _make_packet(
    module: str = "test_mod",
    risk_score: float = 0.5,
    risk_level: str = "MEDIUM",
    constraints: list[str] | None = None,
    incidents: list[str] | None = None,
) -> ModulePacket:
    return ModulePacket(
        module=module,
        files=[f"{module}.py"],
        node_count=3,
        function_count=2,
        class_count=1,
        line_count=50,
        public_interfaces=[],
        consumers=[],
        dependencies=[],
        risk_score=risk_score,
        risk_level=risk_level,
        impact_radius=2,
        chunk_coverage=95.0,
        description_coverage=90.0,
        constraints=constraints or [],
        incidents=incidents or [],
    )


class TestGenerateSection:
    """Tests for generate_section."""

    def test_has_markers(self) -> None:
        packets = [_make_packet()]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert section.startswith(OPEN_MARKER)
        assert section.endswith(CLOSE_MARKER)

    def test_has_module_risk_map(self) -> None:
        packets = [_make_packet("mod_a"), _make_packet("mod_b")]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Module Risk Map" in section
        assert "mod_a" in section
        assert "mod_b" in section

    def test_sorted_by_risk_descending(self) -> None:
        packets = [
            _make_packet("low_risk", risk_score=0.1),
            _make_packet("high_risk", risk_score=0.9),
        ]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        # high_risk should appear before low_risk in the table
        assert section.index("high_risk") < section.index("low_risk")

    def test_max_15_modules(self) -> None:
        packets = [_make_packet(f"mod_{i}", risk_score=i * 0.05) for i in range(20)]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        # Count table rows (lines starting with |, excluding header)
        table_rows = [l for l in section.split("\n") if l.startswith("| mod_")]
        assert len(table_rows) == 15

    def test_includes_incidents(self) -> None:
        packets = [_make_packet(incidents=["Auth broke in v0.22"])]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Recent Incidents" in section
        assert "Auth broke in v0.22" in section

    def test_includes_constraints(self) -> None:
        packets = [_make_packet(constraints=["DO NOT remove legacy endpoint"])]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Active Constraints" in section
        assert "DO NOT remove legacy endpoint" in section

    def test_includes_quality_gate_status(self) -> None:
        packets = [_make_packet()]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Quality Gate Status" in section
        assert "Coverage:" in section
        assert "Health:" in section

    def test_no_incidents_section_when_empty(self) -> None:
        packets = [_make_packet()]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Recent Incidents" not in section

    def test_no_constraints_section_when_empty(self) -> None:
        packets = [_make_packet()]
        scorecard = RunningScorecard()
        section = generate_section(packets, scorecard)
        assert "Active Constraints" not in section


class TestDetectAiTools:
    """Tests for detect_ai_tools."""

    def test_detects_claude_md(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Project", encoding="utf-8")
        tools = detect_ai_tools(tmp_path)
        assert "claude" in tools
        assert tools["claude"] == tmp_path / "CLAUDE.md"

    def test_detects_cursorrules(self, tmp_path: Path) -> None:
        (tmp_path / ".cursorrules").write_text("rules", encoding="utf-8")
        tools = detect_ai_tools(tmp_path)
        assert "cursor" in tools

    def test_detects_copilot(self, tmp_path: Path) -> None:
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("instructions", encoding="utf-8")
        tools = detect_ai_tools(tmp_path)
        assert "copilot" in tools

    def test_detects_windsurf(self, tmp_path: Path) -> None:
        (tmp_path / ".windsurfrules").write_text("rules", encoding="utf-8")
        tools = detect_ai_tools(tmp_path)
        assert "windsurf" in tools

    def test_detects_multiple(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Project", encoding="utf-8")
        (tmp_path / ".cursorrules").write_text("rules", encoding="utf-8")
        tools = detect_ai_tools(tmp_path)
        assert len(tools) == 2

    def test_empty_when_none(self, tmp_path: Path) -> None:
        tools = detect_ai_tools(tmp_path)
        assert tools == {}


class TestInjectSection:
    """Tests for inject_section."""

    def test_inject_appends_to_file(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        fpath.write_text("# My Project\n\nSome docs.\n", encoding="utf-8")

        section = f"{OPEN_MARKER}\ntest content\n{CLOSE_MARKER}"
        assert inject_section(fpath, section) is True

        content = fpath.read_text(encoding="utf-8")
        assert OPEN_MARKER in content
        assert "test content" in content
        assert "# My Project" in content

    def test_inject_replaces_existing(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        fpath.write_text(
            f"# Project\n\n{OPEN_MARKER}\nold content\n{CLOSE_MARKER}\n\nMore docs.\n",
            encoding="utf-8",
        )

        section = f"{OPEN_MARKER}\nnew content\n{CLOSE_MARKER}"
        assert inject_section(fpath, section) is True

        content = fpath.read_text(encoding="utf-8")
        assert "new content" in content
        assert "old content" not in content
        assert "# Project" in content
        assert "More docs." in content

    def test_inject_idempotent(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        section = f"{OPEN_MARKER}\ncontent\n{CLOSE_MARKER}"
        fpath.write_text(f"# Project\n\n{section}\n", encoding="utf-8")

        assert inject_section(fpath, section) is False

    def test_inject_creates_from_empty(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        fpath.write_text("", encoding="utf-8")

        section = f"{OPEN_MARKER}\ncontent\n{CLOSE_MARKER}"
        assert inject_section(fpath, section) is True

        content = fpath.read_text(encoding="utf-8")
        assert OPEN_MARKER in content


class TestEjectSection:
    """Tests for eject_section."""

    def test_eject_removes_section(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        fpath.write_text(
            f"# Project\n\n{OPEN_MARKER}\nstuff\n{CLOSE_MARKER}\n\nMore docs.\n",
            encoding="utf-8",
        )

        assert eject_section(fpath) is True

        content = fpath.read_text(encoding="utf-8")
        assert OPEN_MARKER not in content
        assert "stuff" not in content
        assert "# Project" in content
        assert "More docs." in content

    def test_eject_no_section_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "CLAUDE.md"
        fpath.write_text("# Clean file\n", encoding="utf-8")
        assert eject_section(fpath) is False

    def test_eject_nonexistent_file_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "missing.md"
        assert eject_section(fpath) is False


class TestDogfoodDetection:
    """Dogfooding: detect AI tools on real-ish SDK structure."""

    def test_detects_claude_md_in_sdk_like_structure(self, tmp_path: Path) -> None:
        """Simulate an SDK root with CLAUDE.md."""
        (tmp_path / "CLAUDE.md").write_text("# graqle-sdk\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'graqle'\n", encoding="utf-8")

        tools = detect_ai_tools(tmp_path)
        assert "claude" in tools
