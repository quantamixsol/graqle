"""Abstract base class for document parsers.

Every concrete parser (Markdown, PDF, DOCX, ...) inherits from
:class:`BaseDocParser` and implements its four abstract members.
The two dataclasses — :class:`ParsedSection` and :class:`ParsedDocument` —
form the canonical intermediate representation that downstream graph
builders consume.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.parsers.base
# risk: HIGH (impact radius: 31 modules)
# consumers: api, fallback, gemini, llamacpp_backend, local +26 more
# dependencies: __future__, abc, dataclasses, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedSection:
    """One logical section inside a parsed document.

    Parameters
    ----------
    title:
        Section heading text (may be empty for untitled paragraphs).
    content:
        Full text content of the section, excluding the heading itself.
    level:
        Heading depth — 1 for H1 / top-level, 2 for H2, etc.
    section_type:
        Structural category: ``"heading"``, ``"slide"``, ``"sheet"``,
        ``"paragraph"``.
    page:
        1-based page number where the section starts (``None`` when the
        format has no concept of pages).
    tables:
        List of tables found in this section.  Each table is a list-of-dicts
        representation (one dict per row, keys = column headers).
    code_blocks:
        Verbatim contents of fenced code blocks found in this section.
    links:
        URLs or cross-references found in this section.
    metadata:
        Arbitrary key/value pairs specific to the parser or format.
    """

    title: str
    content: str
    level: int
    section_type: str
    page: int | None = None
    tables: list[dict[str, Any]] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """Complete parse result for a single document file.

    Parameters
    ----------
    path:
        Absolute or relative path to the source file.
    title:
        Document title — derived from the first heading, front-matter, or
        the filename as a fallback.
    format:
        Canonical format name (``"pdf"``, ``"docx"``, ``"markdown"``, etc.).
    sections:
        Ordered list of :class:`ParsedSection` instances.
    full_text:
        Concatenation of all section content (useful for full-text search
        or embedding generation).
    metadata:
        Document-level metadata — e.g. author, created, modified,
        page_count, word_count.
    parse_errors:
        Non-fatal warnings or errors encountered during parsing.  An empty
        list means the parse completed without issues.
    """

    path: Path
    title: str
    format: str
    sections: list[ParsedSection]
    full_text: str
    metadata: dict[str, Any]
    parse_errors: list[str] = field(default_factory=list)


class BaseDocParser(ABC):
    """Abstract base for all document parsers.

    Subclasses **must** implement every abstract member.  The scanner
    framework calls :meth:`is_available` before :meth:`parse` so that
    missing optional dependencies (``pdfplumber``, ``python-docx``, ...)
    produce a helpful message instead of an import error.
    """

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """Parse a document file and return structured output.

        Parameters
        ----------
        path:
            Path to the file on disk.  The file **must** exist; the caller
            is responsible for checking.

        Returns
        -------
        ParsedDocument
            Structured representation of the document content.

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        ValueError
            If the file cannot be parsed (corrupt, wrong format, etc.).
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if all required dependencies are installed."""
        ...

    @abstractmethod
    def missing_dependency_message(self) -> str:
        """Human-readable instructions for installing missing deps.

        Example return value::

            "Install pdfplumber: pip install graqle[pdf]"
        """
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this parser handles (including the dot).

        Example::

            [".md"]
        """
        ...
