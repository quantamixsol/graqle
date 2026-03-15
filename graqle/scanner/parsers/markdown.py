"""Markdown document parser — zero external dependencies.

Parses Markdown files using only the Python standard library (``re``).
Handles ATX headings, fenced code blocks, inline links, pipe tables,
and YAML front matter.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.parsers.markdown
# risk: LOW (impact radius: 2 modules)
# consumers: setup_guide, test_markdown
# dependencies: __future__, re, pathlib, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from graqle.scanner.parsers.base import (
    BaseDocParser,
    ParsedDocument,
    ParsedSection,
)

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_RE_FRONT_MATTER = re.compile(
    r"\A---[ \t]*\n(.*?\n)---[ \t]*\n",
    re.DOTALL,
)

_RE_HEADING = re.compile(
    r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$",
    re.MULTILINE,
)

_RE_FENCED_BLOCK = re.compile(
    r"^(`{3,}|~{3,})[^\S\n]*([\w.+-]*)[ \t]*\n(.*?)^(?:`{3,}|~{3,})[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

_RE_LINK = re.compile(
    r"\[([^\]]*)\]\(([^)]+)\)",
)

_RE_TABLE_ROW = re.compile(
    r"^\|(.+)\|[ \t]*$",
    re.MULTILINE,
)

_RE_TABLE_SEP = re.compile(
    r"^\|[\s:|-]+\|[ \t]*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_yaml_front_matter(raw: str) -> dict[str, Any]:
    """Minimal YAML front-matter parser (no PyYAML dependency).

    Supports simple ``key: value`` pairs and ``key: [a, b, c]`` lists.
    Nested structures are stored as raw strings.
    """
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Inline list: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            meta[key] = items
        # Quoted string
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            meta[key] = value[1:-1]
        # Boolean-ish
        elif value.lower() in ("true", "yes"):
            meta[key] = True
        elif value.lower() in ("false", "no"):
            meta[key] = False
        # Numeric
        else:
            try:
                meta[key] = int(value)
            except ValueError:
                try:
                    meta[key] = float(value)
                except ValueError:
                    meta[key] = value
    return meta


def _extract_tables(text: str) -> list[dict[str, Any]]:
    """Extract Markdown pipe tables from *text*.

    Returns a list of tables.  Each table is represented as a dict with
    keys ``"headers"`` (list[str]) and ``"rows"`` (list[list[str]]).
    """
    tables: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # A table starts with a row of | cells followed by a separator row.
        if _RE_TABLE_ROW.match(line) and i + 1 < len(lines) and _RE_TABLE_SEP.match(lines[i + 1].strip()):
            headers = [c.strip() for c in line.strip("|").split("|")]
            i += 2  # skip header + separator
            rows: list[list[str]] = []
            while i < len(lines) and _RE_TABLE_ROW.match(lines[i].strip()):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            tables.append({"headers": headers, "rows": rows})
        else:
            i += 1
    return tables


def _extract_code_blocks(text: str) -> list[str]:
    """Return the content of all fenced code blocks in *text*."""
    return [m.group(3) for m in _RE_FENCED_BLOCK.finditer(text)]


def _extract_links(text: str) -> list[str]:
    """Return all ``[text](url)`` link targets found in *text*."""
    return [m.group(2) for m in _RE_LINK.finditer(text)]


def _strip_fenced_blocks(text: str) -> str:
    """Remove fenced code blocks so heading detection ignores them."""
    return _RE_FENCED_BLOCK.sub("", text)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class MarkdownParser(BaseDocParser):
    """Parse ``.md`` files using only regex — zero external dependencies."""

    # -- BaseDocParser interface --------------------------------------------

    def parse(self, path: Path) -> ParsedDocument:  # noqa: C901 (acceptable complexity for a parser)
        """Parse a Markdown file into a :class:`ParsedDocument`."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Markdown file not found: {path}")

        raw = path.read_text(encoding="utf-8", errors="replace")

        # -- Handle empty files --------------------------------------------
        if not raw.strip():
            return ParsedDocument(
                path=path,
                title=path.stem,
                format="markdown",
                sections=[],
                full_text="",
                metadata={"source": str(path)},
                parse_errors=[],
            )

        metadata: dict[str, Any] = {"source": str(path)}
        parse_errors: list[str] = []
        body = raw

        # -- Front matter --------------------------------------------------
        fm_match = _RE_FRONT_MATTER.match(raw)
        if fm_match:
            try:
                fm_data = _parse_yaml_front_matter(fm_match.group(1))
                metadata.update(fm_data)
            except Exception as exc:  # noqa: BLE001
                parse_errors.append(f"Failed to parse front matter: {exc}")
            body = raw[fm_match.end():]

        # -- Identify heading positions in the *code-block-stripped* body --
        stripped = _strip_fenced_blocks(body)
        heading_spans: list[tuple[int, int, str, int]] = []
        # Map positions in stripped text back to original body positions.
        # Because code blocks are only removed for detection, we search
        # the *original* body for the same heading strings found in stripped.
        for m in _RE_HEADING.finditer(stripped):
            level = len(m.group(1))
            title = m.group(2).strip()
            # Find this heading in the original body.  Use the trimmed
            # heading text (without trailing whitespace/newlines that the
            # stripped body may have altered).
            heading_text = m.group(0).rstrip("\n\r ")
            pos = body.find(heading_text)
            if pos == -1:
                # Fallback — use stripped position (rare edge case)
                pos = m.start()
            heading_end = pos + len(heading_text)
            # Skip past the trailing newline so section content starts clean.
            if heading_end < len(body) and body[heading_end] == "\n":
                heading_end += 1
            heading_spans.append((pos, heading_end, title, level))

        # -- Build sections ------------------------------------------------
        sections: list[ParsedSection] = []

        if not heading_spans:
            # No headings — treat whole body as a single section
            content = body.strip()
            sections.append(
                ParsedSection(
                    title="",
                    content=content,
                    level=1,
                    section_type="paragraph",
                    tables=_extract_tables(content),
                    code_blocks=_extract_code_blocks(content),
                    links=_extract_links(content),
                )
            )
        else:
            # Content before the first heading (if any)
            pre_content = body[: heading_spans[0][0]].strip()
            if pre_content:
                sections.append(
                    ParsedSection(
                        title="",
                        content=pre_content,
                        level=1,
                        section_type="paragraph",
                        tables=_extract_tables(pre_content),
                        code_blocks=_extract_code_blocks(pre_content),
                        links=_extract_links(pre_content),
                    )
                )

            for idx, (start, end, title, level) in enumerate(heading_spans):
                # Section content runs from end-of-heading to start-of-next
                next_start = heading_spans[idx + 1][0] if idx + 1 < len(heading_spans) else len(body)
                content = body[end:next_start].strip()
                sections.append(
                    ParsedSection(
                        title=title,
                        content=content,
                        level=level,
                        section_type="heading",
                        tables=_extract_tables(content),
                        code_blocks=_extract_code_blocks(content),
                        links=_extract_links(content),
                    )
                )

        # -- Derive title --------------------------------------------------
        title = metadata.get("title", "")
        if not title:
            for sec in sections:
                if sec.section_type == "heading" and sec.level == 1 and sec.title:
                    title = sec.title
                    break
        if not title:
            title = path.stem

        # -- Full text -----------------------------------------------------
        full_text = "\n\n".join(
            (f"{s.title}\n{s.content}" if s.title else s.content) for s in sections
        ).strip()

        return ParsedDocument(
            path=path,
            title=str(title),
            format="markdown",
            sections=sections,
            full_text=full_text,
            metadata=metadata,
            parse_errors=parse_errors,
        )

    def is_available(self) -> bool:
        """Always available — uses only the standard library."""
        return True

    def missing_dependency_message(self) -> str:
        return "No additional dependencies required for Markdown parsing."

    @property
    def supported_extensions(self) -> list[str]:
        return [".md"]
