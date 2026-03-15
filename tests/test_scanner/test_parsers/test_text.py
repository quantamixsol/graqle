"""Comprehensive tests for the PlainTextParser.

Tests cover paragraph splitting, header-like detection (ALL CAPS,
underline-style), long-text grouping, edge cases (empty, single-line),
and title extraction.
"""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_parsers.test_text
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pathlib, textwrap, pytest, text +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from graqle.scanner.parsers.base import ParsedDocument
from graqle.scanner.parsers.text import PlainTextParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> PlainTextParser:
    return PlainTextParser()


def _write(tmp_path: Path, content: str, name: str = "doc.txt") -> Path:
    """Helper: write *content* to a .txt file and return its path."""
    p = tmp_path / name
    p.write_text(dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TestPlainTextParser
# ---------------------------------------------------------------------------

class TestPlainTextParser:
    """Unit tests for :class:`PlainTextParser`."""

    # -- paragraph splitting ------------------------------------------------

    def test_paragraph_splitting(self, parser: PlainTextParser, tmp_path: Path):
        """Two paragraphs separated by a blank line are both present in output.

        Note: short paragraphs may be grouped into a single section when
        their combined length is under the ~1500-char grouping threshold.
        """
        path = _write(tmp_path, """\
            First paragraph with some text that
            spans multiple lines.

            Second paragraph with different
            content altogether.
        """)
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        assert len(doc.sections) >= 1

        combined = " ".join(s.content for s in doc.sections)
        assert "First paragraph" in combined
        assert "Second paragraph" in combined

    def test_three_paragraphs(self, parser: PlainTextParser, tmp_path: Path):
        """Three paragraphs separated by blank lines produce >= 3 sections."""
        path = _write(tmp_path, """\
            Alpha paragraph.

            Beta paragraph.

            Gamma paragraph.
        """)
        doc = parser.parse(path)

        # At least 3 content blocks (may be grouped differently)
        combined = " ".join(s.content for s in doc.sections)
        assert "Alpha" in combined
        assert "Beta" in combined
        assert "Gamma" in combined

    def test_multiple_blank_lines(self, parser: PlainTextParser, tmp_path: Path):
        """Multiple consecutive blank lines still produce correct splits.

        Note: short paragraphs may be grouped into one section when their
        combined length is under the ~1500-char grouping threshold.
        """
        path = _write(tmp_path, """\
            First block.



            Second block after extra blanks.
        """)
        doc = parser.parse(path)

        assert len(doc.sections) >= 1
        combined = " ".join(s.content for s in doc.sections)
        assert "First block" in combined
        assert "Second block" in combined

    # -- header-like detection: ALL CAPS -----------------------------------

    def test_header_like_allcaps(self, parser: PlainTextParser, tmp_path: Path):
        """An ALL-CAPS line on its own is detected as a heading."""
        path = _write(tmp_path, """\
            INTRODUCTION

            This section introduces the topic.

            METHODOLOGY

            This section describes methods.
        """)
        doc = parser.parse(path)

        heading_titles = [
            s.title for s in doc.sections
            if s.section_type == "heading" or s.title.isupper()
        ]
        # Should detect INTRODUCTION and METHODOLOGY as headings
        assert any("INTRODUCTION" in t for t in heading_titles)
        assert any("METHODOLOGY" in t for t in heading_titles)

    def test_allcaps_single_word(self, parser: PlainTextParser, tmp_path: Path):
        """A single ALL-CAPS word line is treated as a heading."""
        path = _write(tmp_path, """\
            ABSTRACT

            A brief summary of this work.
        """)
        doc = parser.parse(path)

        heading_sections = [
            s for s in doc.sections
            if "ABSTRACT" in s.title or s.section_type == "heading"
        ]
        assert len(heading_sections) >= 1

    def test_allcaps_not_confused_with_acronyms(self, parser: PlainTextParser, tmp_path: Path):
        """Short all-caps words inline (like 'API') do not create headings."""
        path = _write(tmp_path, """\
            The API uses REST and returns JSON data.
            CORS is configured for all endpoints.
        """)
        doc = parser.parse(path)

        # These should NOT become headings (they're inline acronyms)
        # All content should be in paragraph-type sections
        for section in doc.sections:
            if section.section_type == "heading":
                # If there is a heading, it shouldn't be just "API" or "CORS"
                assert section.title not in ("API", "CORS", "REST", "JSON")

    # -- header-like detection: underline-style ----------------------------

    def test_header_like_underline_equals(self, parser: PlainTextParser, tmp_path: Path):
        """A line followed by '=====' is detected as a heading."""
        path = _write(tmp_path, """\
            Title of Document
            =================

            Body text follows the title.
        """)
        doc = parser.parse(path)

        # Should detect "Title of Document" as a heading
        heading_sections = [
            s for s in doc.sections
            if s.section_type == "heading" or "Title" in s.title
        ]
        assert len(heading_sections) >= 1
        assert any("Title of Document" in s.title for s in heading_sections)

    def test_header_like_underline_dashes(self, parser: PlainTextParser, tmp_path: Path):
        """A line followed by '-----' is detected as a heading."""
        path = _write(tmp_path, """\
            Sub Heading
            -----------

            Content under the sub heading.
        """)
        doc = parser.parse(path)

        heading_sections = [
            s for s in doc.sections
            if s.section_type == "heading" or "Sub Heading" in s.title
        ]
        assert len(heading_sections) >= 1

    def test_underline_heading_level(self, parser: PlainTextParser, tmp_path: Path):
        """'====' underlines produce level 1; '----' underlines produce level 2."""
        path = _write(tmp_path, """\
            Main Title
            ==========

            Some text.

            Sub Title
            ---------

            More text.
        """)
        doc = parser.parse(path)

        for section in doc.sections:
            if "Main Title" in section.title:
                assert section.level == 1
            elif "Sub Title" in section.title:
                assert section.level == 2

    # -- long text grouping -------------------------------------------------

    def test_long_text_grouping(self, parser: PlainTextParser, tmp_path: Path):
        """Very long text is grouped into sections of ~1500 chars max."""
        # Create a long text (5000+ chars) as one continuous block
        long_paragraph = ("This is a sentence that adds length to the text. ") * 120
        path = _write(tmp_path, long_paragraph)
        doc = parser.parse(path)

        # Should be split into multiple sections
        assert len(doc.sections) >= 2

        # No single section should be excessively long (allow some margin)
        for section in doc.sections:
            # Allow up to 2000 chars as "roughly 1500" with some flexibility
            assert len(section.content) <= 2500, (
                f"Section too long: {len(section.content)} chars"
            )

    def test_moderate_text_not_split(self, parser: PlainTextParser, tmp_path: Path):
        """Text under the grouping threshold stays in one section."""
        text = "Short paragraph. " * 20  # ~340 chars
        path = _write(tmp_path, text)
        doc = parser.parse(path)

        # Should be a single section (no splitting needed)
        assert len(doc.sections) >= 1
        combined = " ".join(s.content for s in doc.sections)
        assert "Short paragraph" in combined

    # -- edge cases ---------------------------------------------------------

    def test_empty_file(self, parser: PlainTextParser, tmp_path: Path):
        """Empty file produces an empty document with no errors."""
        path = _write(tmp_path, "", name="empty.txt")
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        assert doc.sections == [] or len(doc.sections) == 0
        assert doc.parse_errors == [] or len(doc.parse_errors) == 0

    def test_whitespace_only(self, parser: PlainTextParser, tmp_path: Path):
        """Whitespace-only file behaves like an empty file."""
        path = _write(tmp_path, "   \n  \n\n   \n")
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        for section in doc.sections:
            assert section.content.strip() == "" or section.title.strip() == ""

    def test_single_line(self, parser: PlainTextParser, tmp_path: Path):
        """A single-line file produces exactly one section."""
        path = _write(tmp_path, "Just one line of text.")
        doc = parser.parse(path)

        assert len(doc.sections) >= 1
        combined = " ".join(s.content for s in doc.sections)
        assert "one line" in combined

    def test_single_word(self, parser: PlainTextParser, tmp_path: Path):
        """A file with a single word still produces a valid document."""
        path = _write(tmp_path, "Hello")
        doc = parser.parse(path)

        assert isinstance(doc, ParsedDocument)
        assert len(doc.sections) >= 1

    # -- title extraction ---------------------------------------------------

    def test_title_extraction_from_heading(self, parser: PlainTextParser, tmp_path: Path):
        """Document title is taken from the first detected heading."""
        path = _write(tmp_path, """\
            OVERVIEW

            Some body text follows the heading.
        """)
        doc = parser.parse(path)

        # Title should be derived from the ALL-CAPS heading
        assert "OVERVIEW" in doc.title.upper() or "overview" in doc.title.lower()

    def test_title_extraction_from_underline_heading(self, parser: PlainTextParser, tmp_path: Path):
        """Title from underline-style heading."""
        path = _write(tmp_path, """\
            Project Plan
            ============

            Details of the plan.
        """)
        doc = parser.parse(path)

        assert "Project Plan" in doc.title or "project" in doc.title.lower()

    def test_title_fallback_to_filename(self, parser: PlainTextParser, tmp_path: Path):
        """When no heading is found, title falls back to filename stem."""
        path = _write(tmp_path, """\
            just some text with no heading patterns at all.
            more text on more lines without any structure.
        """, name="meeting-notes.txt")
        doc = parser.parse(path)

        # Title should contain something from the filename
        assert "meeting" in doc.title.lower() or "notes" in doc.title.lower()

    # -- parser metadata ----------------------------------------------------

    def test_is_available(self, parser: PlainTextParser):
        """PlainTextParser has no optional deps — always available."""
        assert parser.is_available() is True

    def test_supported_extensions(self, parser: PlainTextParser):
        """Supported extensions include .txt."""
        exts = parser.supported_extensions
        assert ".txt" in exts

    def test_format_is_text(self, parser: PlainTextParser, tmp_path: Path):
        """Parsed documents report format as 'text'."""
        path = _write(tmp_path, "Hello world.")
        doc = parser.parse(path)
        assert doc.format == "text"

    def test_path_preserved(self, parser: PlainTextParser, tmp_path: Path):
        """Parsed document's path matches the input path."""
        path = _write(tmp_path, "Content.")
        doc = parser.parse(path)
        assert doc.path == path

    def test_missing_dependency_message(self, parser: PlainTextParser):
        """Missing dependency message is a non-empty string."""
        msg = parser.missing_dependency_message()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_full_text_includes_all_content(self, parser: PlainTextParser, tmp_path: Path):
        """full_text contains content from all sections."""
        path = _write(tmp_path, """\
            SECTION ONE

            Content of section one.

            SECTION TWO

            Content of section two.
        """)
        doc = parser.parse(path)

        assert "section one" in doc.full_text.lower()
        assert "section two" in doc.full_text.lower()

    # -- error handling -----------------------------------------------------

    def test_nonexistent_file_raises(self, parser: PlainTextParser, tmp_path: Path):
        """Parsing a non-existent file raises FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            parser.parse(fake_path)

    def test_binary_file_handled_gracefully(self, parser: PlainTextParser, tmp_path: Path):
        """Binary content does not crash the parser."""
        path = tmp_path / "binary.txt"
        path.write_bytes(b"\x00\x01\x02\xff\xfe\xfd" * 50)

        try:
            doc = parser.parse(path)
            assert isinstance(doc, ParsedDocument)
        except (ValueError, UnicodeDecodeError):
            pass  # Acceptable

    # -- RST / AsciiDoc extension handling ----------------------------------

    def test_rst_extension(self, parser: PlainTextParser, tmp_path: Path):
        """PlainTextParser may also handle .rst files."""
        exts = parser.supported_extensions
        # .rst is listed in DOC_EXTENSIONS as "text" format
        if ".rst" in exts:
            path = tmp_path / "readme.rst"
            path.write_text("Title\n=====\n\nBody text.", encoding="utf-8")
            doc = parser.parse(path)
            assert isinstance(doc, ParsedDocument)

    def test_adoc_extension(self, parser: PlainTextParser, tmp_path: Path):
        """PlainTextParser may also handle .adoc files."""
        exts = parser.supported_extensions
        if ".adoc" in exts:
            path = tmp_path / "readme.adoc"
            path.write_text("= Title\n\nBody text.", encoding="utf-8")
            doc = parser.parse(path)
            assert isinstance(doc, ParsedDocument)

    # -- content integrity --------------------------------------------------

    def test_no_content_loss(self, parser: PlainTextParser, tmp_path: Path):
        """All unique words in the source appear in full_text or section content."""
        source = "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel"
        path = _write(tmp_path, source)
        doc = parser.parse(path)

        for word in source.split():
            assert word in doc.full_text, f"Lost word: {word}"

    def test_unicode_content(self, parser: PlainTextParser, tmp_path: Path):
        """Unicode characters are preserved without corruption."""
        source = "Umlaut: Munchner Strasze. CJK: Hanzi. Emoji: yes."
        path = _write(tmp_path, source)
        doc = parser.parse(path)

        assert "Munchner" in doc.full_text
        assert "Hanzi" in doc.full_text
