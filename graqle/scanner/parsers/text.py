"""Plain-text document parser — zero external dependencies.

Parses ``.txt``, ``.rst``, and ``.adoc`` files by splitting on blank-line
boundaries and detecting header-like lines (ALL CAPS, underline-decorated).
"""

# ── graqle:intelligence ──
# module: graqle.scanner.parsers.text
# risk: LOW (impact radius: 2 modules)
# consumers: compile, test_text
# dependencies: __future__, re, pathlib, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from pathlib import Path

from graqle.scanner.parsers.base import (
    BaseDocParser,
    ParsedDocument,
    ParsedSection,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SECTION_CHARS = 1500
"""Soft cap on characters per section — consecutive paragraphs are grouped
until this limit is reached, then a new section is started."""

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_RE_ALLCAPS_LINE = re.compile(r"^[A-Z][A-Z0-9 _/&:,.\-]{2,}$")
"""Matches lines that are (mostly) upper-case and at least 3 chars — strong
signal for a header in plain text documents."""

_RE_UNDERLINE = re.compile(r"^[=\-~^]{3,}$")
"""RST / AsciiDoc style heading underline (===, ---, ~~~, ^^^)."""

_RE_BLANK_LINE = re.compile(r"\n[ \t]*\n")
"""Two consecutive newlines (possibly with whitespace between)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_header_like(line: str, next_line: str | None) -> bool:
    """Heuristic: is *line* likely a section header?

    A line is header-like if:
    * It is ALL CAPS (and not too short), **or**
    * The following line is an RST-style underline (``===`` / ``---``).
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _RE_ALLCAPS_LINE.match(stripped):
        return True
    if next_line is not None and _RE_UNDERLINE.match(next_line.strip()):
        return True
    return False


def _heading_level(line: str, next_line: str | None) -> int:
    """Return a heading level for *line* (1 or 2).

    * ALL-CAPS headings → level 1
    * ``===`` underline → level 1
    * ``---`` / ``~~~`` / ``^^^`` underline → level 2
    """
    if next_line is not None:
        stripped_next = next_line.strip()
        if _RE_UNDERLINE.match(stripped_next):
            if stripped_next[0] == "=":
                return 1
            return 2
    return 1  # ALL-CAPS default


def _split_paragraphs(text: str) -> list[str]:
    """Split *text* on blank lines and return non-empty paragraphs."""
    parts = _RE_BLANK_LINE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_long_section(
    section: ParsedSection,
    out: list[ParsedSection],
) -> None:
    """Split an oversized untitled section into chunks of ~_MAX_SECTION_CHARS.

    Splits prefer sentence boundaries (``". "``).  If no sentence boundary
    is found within the window, it falls back to the hard cap.
    """
    text = section.content
    while len(text) > _MAX_SECTION_CHARS:
        # Try to split at a sentence boundary near the cap
        split_at = text.rfind(". ", 0, _MAX_SECTION_CHARS)
        if split_at == -1 or split_at < _MAX_SECTION_CHARS // 2:
            split_at = _MAX_SECTION_CHARS
        else:
            split_at += 1  # include the period
        chunk = text[:split_at].strip()
        text = text[split_at:].strip()
        if chunk:
            out.append(
                ParsedSection(
                    title="",
                    content=chunk,
                    level=section.level,
                    section_type="paragraph",
                )
            )
    if text:
        out.append(
            ParsedSection(
                title="",
                content=text,
                level=section.level,
                section_type="paragraph",
            )
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PlainTextParser(BaseDocParser):
    """Parse plain-text files (``.txt``, ``.rst``, ``.adoc``).

    Uses only the standard library.  Paragraphs are grouped into sections
    capped at roughly :data:`_MAX_SECTION_CHARS` characters, with header-like
    lines starting new sections unconditionally.
    """

    def parse(self, path: Path) -> ParsedDocument:
        """Parse a plain-text file into a :class:`ParsedDocument`."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Text file not found: {path}")

        raw = path.read_text(encoding="utf-8", errors="replace")

        # -- Handle empty files --------------------------------------------
        if not raw.strip():
            return ParsedDocument(
                path=path,
                title=path.stem,
                format="text",
                sections=[],
                full_text="",
                metadata={"source": str(path)},
                parse_errors=[],
            )

        lines = raw.splitlines()
        paragraphs = _split_paragraphs(raw)

        # -- Detect document title -----------------------------------------
        title: str = ""
        # Scan the first few lines for a header-like line
        for i, line in enumerate(lines[:10]):
            next_line = lines[i + 1] if i + 1 < len(lines) else None
            if _is_header_like(line, next_line):
                title = line.strip()
                break
        if not title:
            title = path.stem

        # -- Build sections ------------------------------------------------
        sections: list[ParsedSection] = []
        current_title = ""
        current_chunks: list[str] = []
        current_len = 0

        current_level = 1

        def _flush() -> None:
            """Emit the accumulated chunks as a single section."""
            if not current_chunks:
                return
            content = "\n\n".join(current_chunks)
            sections.append(
                ParsedSection(
                    title=current_title,
                    content=content,
                    level=current_level,
                    section_type="heading" if current_title else "paragraph",
                )
            )

        for para in paragraphs:
            para_lines = para.splitlines()
            first_line = para_lines[0] if para_lines else ""
            second_line = para_lines[1] if len(para_lines) > 1 else None

            is_header = _is_header_like(first_line, second_line)

            if is_header:
                # Flush previous section
                _flush()
                current_chunks = []
                current_len = 0
                current_level = _heading_level(first_line, second_line)
                # If the paragraph is *only* a header (+ possible underline),
                # use it as the title for the *next* section.
                body_lines = para_lines[:]
                # Remove the header line itself
                body_lines.pop(0)
                # Remove underline if present
                if body_lines and _RE_UNDERLINE.match(body_lines[0].strip()):
                    body_lines.pop(0)
                current_title = first_line.strip()
                remaining = "\n".join(body_lines).strip()
                if remaining:
                    current_chunks.append(remaining)
                    current_len = len(remaining)
            else:
                # Would adding this paragraph exceed the soft cap?
                if current_len + len(para) > _MAX_SECTION_CHARS and current_chunks:
                    _flush()
                    current_chunks = []
                    current_len = 0
                    current_title = ""
                    current_level = 1
                current_chunks.append(para)
                current_len += len(para)

        # Flush any remaining content
        _flush()

        # Post-process: split oversized sections that consist of a single
        # long paragraph (no blank-line breaks to split on).
        final_sections: list[ParsedSection] = []
        for sec in sections:
            if len(sec.content) > _MAX_SECTION_CHARS and not sec.title:
                # Split on sentence boundaries at roughly _MAX_SECTION_CHARS
                _split_long_section(sec, final_sections)
            else:
                final_sections.append(sec)
        sections = final_sections

        # -- Full text -----------------------------------------------------
        full_text = "\n\n".join(
            (f"{s.title}\n{s.content}" if s.title else s.content) for s in sections
        ).strip()

        return ParsedDocument(
            path=path,
            title=title,
            format="text",
            sections=sections,
            full_text=full_text,
            metadata={"source": str(path)},
            parse_errors=[],
        )

    def is_available(self) -> bool:
        """Always available — uses only the standard library."""
        return True

    def missing_dependency_message(self) -> str:
        return "No additional dependencies required for plain-text parsing."

    @property
    def supported_extensions(self) -> list[str]:
        return [".txt", ".rst", ".adoc"]
