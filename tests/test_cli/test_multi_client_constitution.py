"""P2 (ADR-222): the constitution renders into every supported client's
instruction file, and OpenAI Codex (AGENTS.md) is a first-class client.

Covers:
- `codex` is registered in SUPPORTED_IDES.
- `_get_instructions_path` maps each client to the correct file.
- `_detect_ide` recognises an AGENTS.md project as `codex`.
- `_write_claude_md` renders the FULL constitution (not the fallback) into
  every client's instruction file (claude/codex/cursor/windsurf).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graqle.cli.commands import init as init_mod
from graqle.cli.commands.init import (
    SUPPORTED_IDES,
    _detect_ide,
    _get_instructions_path,
    _write_claude_md,
)

CLIENTS = [
    ("claude", "CLAUDE.md"),
    ("codex", "AGENTS.md"),
    ("cursor", ".cursorrules"),
    ("windsurf", ".windsurfrules"),
]


def test_codex_is_supported() -> None:
    assert "codex" in SUPPORTED_IDES
    assert "AGENTS.md" in SUPPORTED_IDES["codex"]


@pytest.mark.parametrize("ide,filename", CLIENTS)
def test_instructions_path_mapping(ide: str, filename: str) -> None:
    p = _get_instructions_path(Path("/proj"), ide)
    assert p.name == filename


def test_detect_codex_from_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# existing", encoding="utf-8")
    assert _detect_ide(tmp_path) == "codex"


def test_detect_prefers_cursor_over_codex(tmp_path: Path) -> None:
    # Cursor markers take precedence (checked first); AGENTS.md alone -> codex.
    (tmp_path / ".cursorrules").write_text("x", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    assert _detect_ide(tmp_path) == "cursor"


@pytest.mark.parametrize("ide,filename", CLIENTS)
def test_full_constitution_rendered_per_client(ide: str, filename: str, tmp_path: Path) -> None:
    written = _write_claude_md(tmp_path, ide)
    assert written is True
    target = _get_instructions_path(tmp_path, ide)
    assert target.name == filename
    text = target.read_text(encoding="utf-8")
    # Full constitution, not the abridged fallback.
    assert text != init_mod._FALLBACK_INSTRUCTIONS
    assert len(text) > 8000
    for marker in ("senior developer", "tool inventory", "Governed workflows", "eu_ai_act:"):
        assert marker in text, f"{ide}: missing constitution section {marker!r}"
