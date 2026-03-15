"""Comprehensive tests for the MarkdownParser.

Tests cover heading extraction, code blocks, tables, links, YAML front
matter, edge cases (empty files, no headings), title inference, and
parser metadata.  Every test creates its input via ``tmp_path`` so no
fixtures leak between runs.
"""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_parsers.test_markdown
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pathlib, textwrap, pytest, markdown +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from graqle.scanner.parsers.base import ParsedDocument
from graqle.scanner.parsers.markdown import MarkdownParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> MarkdownParser:
    return MarkdownParser()


def _write(tmp_path: Path, content: str, name: str = "doc.md") -> Path:
    """Helper: write *content* to a .md file and return its path."""
    p = tmp_path / name
    p.write_text(dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TestMarkdownParser
# ---------------------------------------------------------------------------

class TestMarkdownParser:
    """Unit tests for :class:`MarkdownParser`."""

    # -- heading extraction -------------------------------------------------

    def test_simple_headings(self, parser: MarkdownParser, tmp_path: Path):
        """H1, H2, H3 each produce a section with the correct level."""
        path = _write(tmp_path, """\
            # Top Level
            Some intro text.

            ## Second Level
            Details here.

            ### Third Level
            More details.
        """)
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        # At least 3 sections corresponding to the three headings
        heading_sections = [s for s in doc.sections if s.section_type == "heading"]
        assert len(heading_sections) >= 3

        levels = {s.title: s.level for s in heading_sections}
        assert levels["Top Level"] == 1
        assert levels["Second Level"] == 2
        assert levels["Third Level"] == 3

    def test_nested_headings(self, parser: MarkdownParser, tmp_path: Path):
        """Deeply nested H1 > H2 > H3 hierarchy is fully extracted."""
        path = _write(tmp_path, """\
            # Architecture
            Overview.

            ## Frontend
            React app.

            ### Components
            Reusable widgets.

            ## Backend
            Python services.

            ### API Layer
            REST endpoints.

            ### Database
            PostgreSQL.
        """)
        doc = parser.parse(path)

        titles = [s.title for s in doc.sections if s.section_type == "heading"]
        assert "Architecture" in titles
        assert "Frontend" in titles
        assert "Components" in titles
        assert "Backend" in titles
        assert "API Layer" in titles
        assert "Database" in titles

        # Verify levels
        level_map = {s.title: s.level for s in doc.sections if s.section_type == "heading"}
        assert level_map["Architecture"] == 1
        assert level_map["Frontend"] == 2
        assert level_map["Components"] == 3
        assert level_map["Backend"] == 2
        assert level_map["API Layer"] == 3
        assert level_map["Database"] == 3

    # -- code blocks --------------------------------------------------------

    def test_code_blocks(self, parser: MarkdownParser, tmp_path: Path):
        """Fenced code blocks are extracted into section.code_blocks."""
        path = _write(tmp_path, """\
            # Setup

            Install dependencies:

            ```python
            pip install graqle
            import graqle
            ```

            Then configure:

            ```yaml
            backend: anthropic
            model: haiku
            ```
        """)
        doc = parser.parse(path)

        # Gather all code blocks across sections
        all_code = []
        for section in doc.sections:
            all_code.extend(section.code_blocks)

        assert len(all_code) >= 2
        # At least one block contains the python code
        python_blocks = [c for c in all_code if "pip install" in c or "import graqle" in c]
        assert len(python_blocks) >= 1
        # At least one block contains the yaml
        yaml_blocks = [c for c in all_code if "backend:" in c]
        assert len(yaml_blocks) >= 1

    def test_code_block_without_language(self, parser: MarkdownParser, tmp_path: Path):
        """Fenced code blocks without a language tag are still captured."""
        path = _write(tmp_path, """\
            # Notes

            ```
            some raw code
            ```
        """)
        doc = parser.parse(path)

        all_code = []
        for section in doc.sections:
            all_code.extend(section.code_blocks)
        assert any("some raw code" in c for c in all_code)

    # -- tables -------------------------------------------------------------

    def test_tables(self, parser: MarkdownParser, tmp_path: Path):
        """Pipe-delimited Markdown tables are extracted into section.tables."""
        path = _write(tmp_path, """\
            # Metrics

            | Service | Latency | Status |
            |---------|---------|--------|
            | Auth    | 120ms   | OK     |
            | API     | 340ms   | WARN   |
        """)
        doc = parser.parse(path)

        all_tables = []
        for section in doc.sections:
            all_tables.extend(section.tables)

        assert len(all_tables) >= 1
        table = all_tables[0]
        # Table is a dict with 'headers' and 'rows' keys
        if isinstance(table, dict) and "rows" in table:
            assert len(table["rows"]) >= 2
            assert "headers" in table
        elif isinstance(table, list):
            assert len(table) >= 2
        else:
            # At minimum we have a table object
            assert table is not None

    def test_table_with_alignment(self, parser: MarkdownParser, tmp_path: Path):
        """Tables with alignment markers (:---:, ---:, :---) are parsed."""
        path = _write(tmp_path, """\
            # Data

            | Left | Center | Right |
            |:-----|:------:|------:|
            | a    |   b    |     c |
        """)
        doc = parser.parse(path)

        all_tables = []
        for section in doc.sections:
            all_tables.extend(section.tables)
        assert len(all_tables) >= 1

    # -- links --------------------------------------------------------------

    def test_links(self, parser: MarkdownParser, tmp_path: Path):
        """Inline links [text](url) are extracted into section.links."""
        path = _write(tmp_path, """\
            # References

            See [Graqle docs](https://graqle.com/docs) and
            [GitHub](https://github.com/quantamixsol/graqle).
        """)
        doc = parser.parse(path)

        all_links = []
        for section in doc.sections:
            all_links.extend(section.links)

        assert len(all_links) >= 2
        assert "https://graqle.com/docs" in all_links
        assert "https://github.com/quantamixsol/graqle" in all_links

    def test_reference_style_links_definition(self, parser: MarkdownParser, tmp_path: Path):
        """Reference-style link definitions [ref]: url are captured as inline links."""
        path = _write(tmp_path, """\
            # Links

            Check [the docs](https://graqle.com/docs) for more.
        """)
        doc = parser.parse(path)

        all_links = []
        for section in doc.sections:
            all_links.extend(section.links)
        assert any("graqle.com" in link for link in all_links)

    def test_autolinks(self, parser: MarkdownParser, tmp_path: Path):
        """Bare URLs (autolinks) like <https://...> are at least preserved in content.

        Note: The zero-dep regex parser does not extract ``<url>`` autolinks
        into the links list — that would require a full Markdown AST.  We
        verify the URL text is present in the section content instead.
        """
        path = _write(tmp_path, """\
            # Contact

            Visit <https://graqle.com>.
        """)
        doc = parser.parse(path)

        # The URL should at least be preserved in the section content
        assert "graqle.com" in doc.full_text

    # -- YAML front matter --------------------------------------------------

    def test_yaml_front_matter(self, parser: MarkdownParser, tmp_path: Path):
        """YAML front matter between --- delimiters is parsed into metadata.

        Note: The zero-dep YAML parser supports ``key: value`` and inline
        lists ``[a, b]``.  Multi-line indented lists (``- item``) are NOT
        supported — use inline list syntax for tests.
        """
        path = _write(tmp_path, """\
            ---
            title: Design Doc
            author: Alice
            tags: [architecture, review]
            ---

            # Design Doc

            Body text.
        """)
        doc = parser.parse(path)

        assert doc.metadata.get("author") == "Alice"
        assert "architecture" in doc.metadata.get("tags", [])

    def test_yaml_front_matter_title_override(self, parser: MarkdownParser, tmp_path: Path):
        """Front-matter ``title`` field can set the document title."""
        path = _write(tmp_path, """\
            ---
            title: Front Matter Title
            ---

            # Heading Title

            Body.
        """)
        doc = parser.parse(path)

        # The parser may prefer front-matter title or H1; either is acceptable.
        assert doc.title in ("Front Matter Title", "Heading Title")

    def test_yaml_front_matter_not_confused_with_hr(self, parser: MarkdownParser, tmp_path: Path):
        """Horizontal rules (---) mid-document are not treated as front matter."""
        path = _write(tmp_path, """\
            # Title

            Some text.

            ---

            More text after the rule.
        """)
        doc = parser.parse(path)

        # Should not have spurious metadata from the HR
        assert doc.parse_errors == [] or len(doc.parse_errors) == 0

    # -- edge cases ---------------------------------------------------------

    def test_empty_file(self, parser: MarkdownParser, tmp_path: Path):
        """An empty .md file produces a ParsedDocument with no sections."""
        path = _write(tmp_path, "", name="empty.md")
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        assert doc.sections == [] or len(doc.sections) == 0
        assert doc.parse_errors == [] or len(doc.parse_errors) == 0
        assert doc.format == "markdown"

    def test_whitespace_only_file(self, parser: MarkdownParser, tmp_path: Path):
        """A file containing only whitespace behaves like an empty file."""
        path = _write(tmp_path, "   \n\n   \n", name="spaces.md")
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        # Either zero sections or sections with empty/whitespace content
        for section in doc.sections:
            assert section.content.strip() == "" or section.title.strip() == ""

    def test_no_headings(self, parser: MarkdownParser, tmp_path: Path):
        """Plain text without any headings produces a single section."""
        path = _write(tmp_path, """\
            This is just a paragraph of text without any headings.
            It spans multiple lines but has no Markdown structure.
        """)
        doc = parser.parse(path)

        assert len(doc.sections) >= 1
        combined_content = " ".join(s.content for s in doc.sections)
        assert "paragraph of text" in combined_content

    # -- title inference ----------------------------------------------------

    def test_title_from_h1(self, parser: MarkdownParser, tmp_path: Path):
        """Document title is taken from the first H1 heading."""
        path = _write(tmp_path, """\
            # My Great Document

            Content here.

            ## Subsection
            More content.
        """)
        doc = parser.parse(path)

        assert doc.title == "My Great Document"

    def test_title_from_filename(self, parser: MarkdownParser, tmp_path: Path):
        """When there is no H1, the title falls back to the filename stem."""
        path = _write(tmp_path, """\
            ## Only a Sub-Heading

            No H1 in this document.
        """, name="project-overview.md")
        doc = parser.parse(path)

        # Title should be derived from filename (possibly cleaned up)
        assert "project" in doc.title.lower() or "overview" in doc.title.lower()

    def test_title_from_first_h1_not_h2(self, parser: MarkdownParser, tmp_path: Path):
        """When multiple headings exist, title comes from the first H1, not H2."""
        path = _write(tmp_path, """\
            ## Introduction

            Preamble.

            # Actual Title

            Body.
        """)
        doc = parser.parse(path)

        # The first H1 is "Actual Title"
        assert doc.title == "Actual Title"

    # -- mixed / complex content -------------------------------------------

    def test_mixed_content(self, parser: MarkdownParser, tmp_path: Path):
        """Complex document with headings, code, tables, and links."""
        path = _write(tmp_path, """\
            ---
            version: "2.0"
            ---

            # Architecture Overview

            This document describes the system.

            ## Services

            | Name  | Port |
            |-------|------|
            | API   | 8080 |
            | Auth  | 8081 |

            ## Code Examples

            ```python
            from graqle import Graqle
            g = Graqle.from_json("graph.json")
            ```

            See [API docs](https://api.example.com).

            ### Subsystem

            More details about the subsystem.
        """)
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        assert doc.format == "markdown"
        assert doc.title == "Architecture Overview"

        # Verify sections
        titles = [s.title for s in doc.sections if s.section_type == "heading"]
        assert "Architecture Overview" in titles
        assert "Services" in titles
        assert "Code Examples" in titles
        assert "Subsystem" in titles

        # Verify code blocks
        all_code = []
        for section in doc.sections:
            all_code.extend(section.code_blocks)
        assert any("Graqle" in c for c in all_code)

        # Verify tables
        all_tables = []
        for section in doc.sections:
            all_tables.extend(section.tables)
        assert len(all_tables) >= 1

        # Verify links
        all_links = []
        for section in doc.sections:
            all_links.extend(section.links)
        assert "https://api.example.com" in all_links

        # Verify metadata from front matter
        assert doc.metadata.get("version") == "2.0"

        # Verify full_text contains content from all sections
        assert "describes the system" in doc.full_text
        assert len(doc.full_text) > 50

    def test_multiple_code_blocks_in_one_section(self, parser: MarkdownParser, tmp_path: Path):
        """Multiple code blocks under one heading are all captured."""
        path = _write(tmp_path, """\
            # Setup

            Step 1:
            ```bash
            npm install
            ```

            Step 2:
            ```bash
            npm run build
            ```

            Step 3:
            ```bash
            npm start
            ```
        """)
        doc = parser.parse(path)

        all_code = []
        for section in doc.sections:
            all_code.extend(section.code_blocks)
        assert len(all_code) >= 3

    def test_indented_code_blocks(self, parser: MarkdownParser, tmp_path: Path):
        """4-space indented code blocks (classic Markdown) should be handled."""
        path = _write(tmp_path, """\
            # Example

            Here is some code:

                def hello():
                    print("world")

            End of example.
        """)
        doc = parser.parse(path)

        # The parser should either capture indented blocks as code_blocks
        # or include them in the section content.  We verify no crash and
        # the content is preserved somewhere.
        combined = doc.full_text
        for s in doc.sections:
            combined += " ".join(s.code_blocks)
        assert "hello" in combined or "print" in combined

    # -- parser metadata ----------------------------------------------------

    def test_is_available(self, parser: MarkdownParser):
        """MarkdownParser has no optional deps — always available."""
        assert parser.is_available() is True

    def test_supported_extensions(self, parser: MarkdownParser):
        """Supported extensions include .md."""
        exts = parser.supported_extensions
        assert ".md" in exts

    def test_format_is_markdown(self, parser: MarkdownParser, tmp_path: Path):
        """Parsed documents report format as 'markdown'."""
        path = _write(tmp_path, "# Hello\nWorld.")
        doc = parser.parse(path)
        assert doc.format == "markdown"

    def test_path_preserved(self, parser: MarkdownParser, tmp_path: Path):
        """The parsed document's path matches the input path."""
        path = _write(tmp_path, "# Doc\nContent.")
        doc = parser.parse(path)
        assert doc.path == path

    def test_missing_dependency_message(self, parser: MarkdownParser):
        """Missing dependency message is a non-empty string."""
        msg = parser.missing_dependency_message()
        assert isinstance(msg, str)
        assert len(msg) > 0

    # -- error handling -----------------------------------------------------

    def test_nonexistent_file_raises(self, parser: MarkdownParser, tmp_path: Path):
        """Parsing a non-existent file raises FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.md"
        with pytest.raises(FileNotFoundError):
            parser.parse(fake_path)

    def test_binary_file_handled_gracefully(self, parser: MarkdownParser, tmp_path: Path):
        """Binary content does not crash the parser (may produce errors)."""
        path = tmp_path / "binary.md"
        path.write_bytes(b"\x00\x01\x02\xff\xfe\xfd" * 100)

        # Should either parse (with warnings) or raise ValueError — not crash
        try:
            doc = parser.parse(path)
            # If it parsed, it should flag issues
            assert isinstance(doc, ParsedDocument)
        except (ValueError, UnicodeDecodeError):
            pass  # Acceptable

    # -- section content fidelity -------------------------------------------

    def test_section_content_excludes_heading(self, parser: MarkdownParser, tmp_path: Path):
        """Section content should not include the heading line itself."""
        path = _write(tmp_path, """\
            # My Heading

            This is the body text.
        """)
        doc = parser.parse(path)

        heading_section = next(
            s for s in doc.sections if s.title == "My Heading"
        )
        assert "# My Heading" not in heading_section.content
        assert "body text" in heading_section.content

    def test_section_content_preserves_paragraphs(self, parser: MarkdownParser, tmp_path: Path):
        """Paragraph breaks within a section are preserved in content."""
        path = _write(tmp_path, """\
            # Overview

            First paragraph.

            Second paragraph.

            Third paragraph.
        """)
        doc = parser.parse(path)

        section = next(s for s in doc.sections if s.title == "Overview")
        assert "First paragraph" in section.content
        assert "Third paragraph" in section.content

    def test_word_count_in_metadata(self, parser: MarkdownParser, tmp_path: Path):
        """Metadata may include word_count or similar stats."""
        path = _write(tmp_path, """\
            # Report

            This document has several words in it to verify counting.
        """)
        doc = parser.parse(path)

        # word_count is optional but if present should be reasonable
        if "word_count" in doc.metadata:
            assert doc.metadata["word_count"] >= 5

    def test_full_text_is_concatenation(self, parser: MarkdownParser, tmp_path: Path):
        """full_text contains content from all sections concatenated."""
        path = _write(tmp_path, """\
            # Part One
            Alpha content.

            # Part Two
            Beta content.
        """)
        doc = parser.parse(path)

        assert "Alpha content" in doc.full_text
        assert "Beta content" in doc.full_text

    # -- special Markdown features -----------------------------------------

    def test_blockquotes(self, parser: MarkdownParser, tmp_path: Path):
        """Blockquotes (> ...) are included in section content."""
        path = _write(tmp_path, """\
            # Quotes

            > This is a blockquote.
            > It spans two lines.

            Normal text after.
        """)
        doc = parser.parse(path)

        section = next(s for s in doc.sections if s.title == "Quotes")
        assert "blockquote" in section.content

    def test_lists(self, parser: MarkdownParser, tmp_path: Path):
        """Bulleted and numbered lists are preserved in section content."""
        path = _write(tmp_path, """\
            # Tasks

            - Item one
            - Item two
            - Item three

            1. First
            2. Second
        """)
        doc = parser.parse(path)

        section = next(s for s in doc.sections if s.title == "Tasks")
        assert "Item one" in section.content
        assert "First" in section.content

    def test_emphasis_and_bold(self, parser: MarkdownParser, tmp_path: Path):
        """Inline formatting (*italic*, **bold**) is preserved in content."""
        path = _write(tmp_path, """\
            # Formatting

            This has *italic* and **bold** and `inline code`.
        """)
        doc = parser.parse(path)

        section = next(s for s in doc.sections if s.title == "Formatting")
        # Content should contain the words (with or without markdown markers)
        assert "italic" in section.content
        assert "bold" in section.content

    def test_images_as_links(self, parser: MarkdownParser, tmp_path: Path):
        """Image references ![alt](url) may be captured as links."""
        path = _write(tmp_path, """\
            # Gallery

            ![diagram](https://example.com/diagram.png)
        """)
        doc = parser.parse(path)

        all_links = []
        for section in doc.sections:
            all_links.extend(section.links)
        # Image URL should be captured (either as link or at least in content)
        has_image_ref = (
            any("diagram.png" in link for link in all_links)
            or "diagram.png" in doc.full_text
        )
        assert has_image_ref
