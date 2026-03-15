"""Document chunking engine.

Splits :class:`~graqle.scanner.parsers.base.ParsedDocument` instances into
graph-ready :class:`DocumentChunk` objects suitable for embedding, indexing,
or knowledge-graph ingestion.

Chunking strategy
-----------------
* **Tables** are always emitted as standalone chunks (structure must survive).
* **Code blocks** are always emitted as standalone chunks.
* Remaining prose is split on paragraph boundaries (double newline).
* Small consecutive paragraphs are merged up to *max_chunk_chars*.
* Oversized paragraphs are split at sentence boundaries.
* Adjacent chunks from the same section receive configurable character
  overlap so that context is not lost at boundaries.
* ``heading_path`` tracks the nested heading hierarchy at every point in the
  document, giving each chunk a breadcrumb trail back to its position.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.chunker
# risk: LOW (impact radius: 2 modules)
# consumers: docs, test_chunker
# dependencies: __future__, re, dataclasses, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from graqle.scanner.parsers.base import ParsedDocument, ParsedSection

# Pre-compiled regex: split at sentence-ending punctuation followed by
# whitespace or end-of-string.  The positive look-behind keeps the
# punctuation attached to the preceding sentence.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DocumentChunk:
    """One graph-ready chunk of document content.

    Attributes
    ----------
    text:
        The chunk body text.
    chunk_type:
        Structural category — ``"heading"``, ``"paragraph"``, ``"table"``,
        ``"code_block"``, or ``"list"``.
    source_section:
        Title of the section this chunk was extracted from.
    heading_path:
        Breadcrumb list of ancestor headings, e.g.
        ``["Architecture", "Backend", "Auth"]``.
    page:
        1-based page number where the chunk originates (``None`` when the
        source format has no concept of pages).
    token_estimate:
        Rough token count — word-count of *text*.
    metadata:
        Arbitrary key/value pairs carried from the source section or
        injected by the chunker.
    """

    text: str
    chunk_type: str
    source_section: str
    heading_path: list[str]
    page: int | None = None
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """Stateless, configurable document chunker.

    Parameters
    ----------
    max_chunk_chars:
        Target upper-bound on chunk length in characters.  Chunks may exceed
        this when a single table or code block is larger (those are never
        split).
    min_chunk_chars:
        Paragraphs shorter than this are merged with the next paragraph.
    overlap_chars:
        Number of characters copied from the tail of the previous chunk to
        the head of the next chunk inside the same section.
    """

    def __init__(
        self,
        max_chunk_chars: int = 1500,
        min_chunk_chars: int = 100,
        overlap_chars: int = 100,
    ) -> None:
        if max_chunk_chars < 1:
            raise ValueError("max_chunk_chars must be >= 1")
        if min_chunk_chars < 0:
            raise ValueError("min_chunk_chars must be >= 0")
        if overlap_chars < 0:
            raise ValueError("overlap_chars must be >= 0")
        if min_chunk_chars >= max_chunk_chars:
            raise ValueError(
                "min_chunk_chars must be strictly less than max_chunk_chars"
            )

        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_chars = min_chunk_chars
        self.overlap_chars = overlap_chars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_document(self, doc: ParsedDocument) -> list[DocumentChunk]:
        """Chunk a full parsed document.

        Iterates over every :class:`ParsedSection`, maintains a heading-path
        stack based on heading levels, delegates to :meth:`chunk_section`,
        and applies overlap between adjacent chunks within each section.

        Parameters
        ----------
        doc:
            A fully parsed document.

        Returns
        -------
        list[DocumentChunk]
            Ordered list of chunks covering the entire document.
        """
        all_chunks: list[DocumentChunk] = []
        # heading_path is a stack that tracks the current nesting.
        # When we encounter a heading at level N we pop back to level N-1
        # and push the new heading.
        heading_stack: list[tuple[int, str]] = []  # (level, title)

        for section in doc.sections:
            # ---- Update heading stack ----
            heading_stack = self._update_heading_stack(
                heading_stack, section.level, section.title
            )
            heading_path = [title for _, title in heading_stack]

            section_chunks = self.chunk_section(section, heading_path)
            section_chunks = self._add_overlap(section_chunks)
            all_chunks.extend(section_chunks)

        return all_chunks

    def chunk_section(
        self,
        section: ParsedSection,
        heading_path: list[str],
    ) -> list[DocumentChunk]:
        """Chunk a single section.

        Tables and code blocks become their own chunks first; the remaining
        prose is paragraph-split, merged, or further split as needed.

        Parameters
        ----------
        section:
            The parsed section to chunk.
        heading_path:
            Current breadcrumb path of ancestor headings.

        Returns
        -------
        list[DocumentChunk]
            Ordered chunks for this section.
        """
        chunks: list[DocumentChunk] = []

        # --- Tables: always standalone ---
        for table in section.tables:
            table_text = self._table_to_text(table)
            chunks.append(
                DocumentChunk(
                    text=table_text,
                    chunk_type="table",
                    source_section=section.title,
                    heading_path=list(heading_path),
                    page=section.page,
                    token_estimate=len(table_text.split()),
                    metadata=dict(section.metadata),
                )
            )

        # --- Code blocks: always standalone ---
        for code_block in section.code_blocks:
            chunks.append(
                DocumentChunk(
                    text=code_block,
                    chunk_type="code_block",
                    source_section=section.title,
                    heading_path=list(heading_path),
                    page=section.page,
                    token_estimate=len(code_block.split()),
                    metadata=dict(section.metadata),
                )
            )

        # --- Remaining prose ---
        prose = section.content.strip()
        if prose:
            paragraphs = self._split_by_paragraphs(prose)
            merged = self._merge_small_chunks(paragraphs)

            for para in merged:
                if len(para) > self.max_chunk_chars:
                    sub_parts = self._split_large_chunk(para)
                    for part in sub_parts:
                        chunks.append(
                            self._make_prose_chunk(
                                part, section, heading_path
                            )
                        )
                else:
                    chunks.append(
                        self._make_prose_chunk(para, section, heading_path)
                    )

        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_heading_stack(
        stack: list[tuple[int, str]],
        level: int,
        title: str,
    ) -> list[tuple[int, str]]:
        """Maintain heading-path stack.

        When the new heading level is equal to or shallower than the
        current top, pop back; then push the new heading.
        """
        # Pop entries that are at the same or deeper level.
        while stack and stack[-1][0] >= level:
            stack.pop()
        if title:
            stack.append((level, title))
        return stack

    def _make_prose_chunk(
        self,
        text: str,
        section: ParsedSection,
        heading_path: list[str],
    ) -> DocumentChunk:
        """Build a prose :class:`DocumentChunk`."""
        # Determine chunk_type from the section type or fall back to
        # "paragraph".
        chunk_type = section.section_type
        if chunk_type not in ("heading", "paragraph", "list"):
            chunk_type = "paragraph"
        return DocumentChunk(
            text=text,
            chunk_type=chunk_type,
            source_section=section.title,
            heading_path=list(heading_path),
            page=section.page,
            token_estimate=len(text.split()),
            metadata=dict(section.metadata),
        )

    # ------------------------------------------------------------------
    # Paragraph splitting / merging / splitting-large
    # ------------------------------------------------------------------

    @staticmethod
    def _split_by_paragraphs(text: str) -> list[str]:
        """Split *text* on double newlines.

        Single newlines are preserved within paragraphs.  Leading and
        trailing whitespace on each paragraph is stripped; empty results
        are discarded.
        """
        raw = re.split(r"\n{2,}", text)
        return [p.strip() for p in raw if p.strip()]

    def _merge_small_chunks(self, paragraphs: list[str]) -> list[str]:
        """Merge consecutive paragraphs that are shorter than *min_chunk_chars*.

        Merging stops when adding the next paragraph would exceed
        *max_chunk_chars*.
        """
        if not paragraphs:
            return []

        merged: list[str] = []
        buffer = paragraphs[0]

        for para in paragraphs[1:]:
            combined_len = len(buffer) + 1 + len(para)  # +1 for joining \n
            if (
                len(buffer) < self.min_chunk_chars
                and combined_len <= self.max_chunk_chars
            ):
                buffer = buffer + "\n\n" + para
            else:
                merged.append(buffer)
                buffer = para

        merged.append(buffer)
        return merged

    def _split_large_chunk(self, text: str) -> list[str]:
        """Split *text* that exceeds *max_chunk_chars* at sentence boundaries.

        If no sentence boundary exists within the limit the chunk is split
        at the last whitespace character before the limit.  As a last
        resort (e.g. a single unbroken token) the text is hard-sliced.
        """
        if len(text) <= self.max_chunk_chars:
            return [text]

        sentences = _SENTENCE_BOUNDARY_RE.split(text)
        parts: list[str] = []
        buffer = ""

        for sentence in sentences:
            candidate = (buffer + " " + sentence).strip() if buffer else sentence
            if len(candidate) <= self.max_chunk_chars:
                buffer = candidate
            else:
                # Flush current buffer if non-empty.
                if buffer:
                    parts.append(buffer)
                # The sentence itself might still be too long — force-split.
                if len(sentence) > self.max_chunk_chars:
                    parts.extend(self._force_split(sentence))
                    buffer = ""
                else:
                    buffer = sentence

        if buffer:
            parts.append(buffer)

        return parts

    def _force_split(self, text: str) -> list[str]:
        """Hard-split *text* at whitespace or, failing that, at *max_chunk_chars*.

        This is the fallback when no sentence boundary exists within the
        character budget.
        """
        parts: list[str] = []
        remaining = text

        while len(remaining) > self.max_chunk_chars:
            # Try to break at whitespace.
            split_at = remaining.rfind(" ", 0, self.max_chunk_chars)
            if split_at <= 0:
                # No whitespace found — hard cut.
                split_at = self.max_chunk_chars
            parts.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()

        if remaining:
            parts.append(remaining)

        return parts

    # ------------------------------------------------------------------
    # Overlap
    # ------------------------------------------------------------------

    def _add_overlap(
        self, chunks: list[DocumentChunk]
    ) -> list[DocumentChunk]:
        """Prepend overlap text from the previous chunk to each chunk.

        Only prose chunks (``"paragraph"``, ``"heading"``, ``"list"``)
        receive overlap.  Tables and code blocks are never modified.
        Overlap is taken from the *tail* of the previous chunk's text.
        """
        if self.overlap_chars <= 0 or len(chunks) < 2:
            return chunks

        non_prose_types = {"table", "code_block"}
        result = [chunks[0]]

        for i in range(1, len(chunks)):
            current = chunks[i]
            previous = chunks[i - 1]

            if (
                current.chunk_type in non_prose_types
                or previous.chunk_type in non_prose_types
            ):
                result.append(current)
                continue

            # Take the last N characters from the previous chunk.
            overlap_text = previous.text[-self.overlap_chars :].lstrip()
            if overlap_text and overlap_text != current.text[: len(overlap_text)]:
                new_text = overlap_text + " " + current.text
                result.append(
                    DocumentChunk(
                        text=new_text,
                        chunk_type=current.chunk_type,
                        source_section=current.source_section,
                        heading_path=list(current.heading_path),
                        page=current.page,
                        token_estimate=len(new_text.split()),
                        metadata=dict(current.metadata),
                    )
                )
            else:
                result.append(current)

        return result

    # ------------------------------------------------------------------
    # Table formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _table_to_text(table: dict[str, Any]) -> str:
        """Convert a table dict to a readable text representation.

        Supports two common table shapes:

        1. **list-of-dicts** — ``[{"col": "val", ...}, ...]``
        2. **dict with headers + rows** — ``{"headers": [...], "rows": [[...], ...]}``

        Falls back to ``str(table)`` for anything else.
        """
        if isinstance(table, list):
            # list-of-dicts
            if not table:
                return ""
            headers = list(table[0].keys())
            lines = [" | ".join(headers)]
            lines.append(" | ".join("---" for _ in headers))
            for row in table:
                lines.append(" | ".join(str(row.get(h, "")) for h in headers))
            return "\n".join(lines)

        if isinstance(table, dict):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if headers and rows:
                lines = [" | ".join(str(h) for h in headers)]
                lines.append(" | ".join("---" for _ in headers))
                for row in rows:
                    lines.append(" | ".join(str(c) for c in row))
                return "\n".join(lines)

        return str(table)
