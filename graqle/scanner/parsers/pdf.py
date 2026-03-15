"""PDF document parser — requires ``pdfplumber``.

Extracts text, tables, and metadata from PDF files using the
``pdfplumber`` library.  Falls back gracefully when the library
is not installed.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.parsers.pdf
# risk: LOW (impact radius: 1 modules)
# consumers: test_pdf
# dependencies: __future__, pathlib, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path
from typing import Any

from graqle.scanner.parsers.base import (
    BaseDocParser,
    ParsedDocument,
    ParsedSection,
)


class PDFParser(BaseDocParser):
    """Parse ``.pdf`` files using ``pdfplumber``."""

    def parse(self, path: Path) -> ParsedDocument:
        """Parse a PDF file into a :class:`ParsedDocument`."""
        import pdfplumber

        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        sections: list[ParsedSection] = []
        full_text_parts: list[str] = []
        metadata: dict[str, Any] = {"source": str(path)}
        parse_errors: list[str] = []

        try:
            with pdfplumber.open(path) as pdf:
                metadata["page_count"] = len(pdf.pages)
                if pdf.metadata:
                    for key in ("Title", "Author", "Subject", "Creator"):
                        val = pdf.metadata.get(key)
                        if val:
                            metadata[key.lower()] = val

                for page_num, page in enumerate(pdf.pages, start=1):
                    try:
                        text = page.extract_text() or ""
                    except Exception as exc:
                        parse_errors.append(f"Page {page_num}: {exc}")
                        text = ""

                    # Extract tables
                    tables: list[dict[str, Any]] = []
                    try:
                        raw_tables = page.extract_tables() or []
                        for raw_table in raw_tables:
                            if raw_table and len(raw_table) >= 2:
                                headers = [str(h or "").strip() for h in raw_table[0]]
                                rows = [
                                    [str(c or "").strip() for c in row]
                                    for row in raw_table[1:]
                                ]
                                tables.append({"headers": headers, "rows": rows})
                    except Exception as exc:
                        parse_errors.append(f"Table extraction page {page_num}: {exc}")

                    if text.strip():
                        sections.append(
                            ParsedSection(
                                title=f"Page {page_num}",
                                content=text.strip(),
                                level=1,
                                section_type="paragraph",
                                page=page_num,
                                tables=tables,
                                code_blocks=[],
                                links=[],
                            )
                        )
                        full_text_parts.append(text.strip())

        except Exception as exc:
            raise ValueError(f"Failed to parse PDF: {exc}") from exc

        title = metadata.get("title", path.stem)
        full_text = "\n\n".join(full_text_parts)

        if not sections:
            return ParsedDocument(
                path=path,
                title=str(title),
                format="pdf",
                sections=[],
                full_text="",
                metadata=metadata,
                parse_errors=parse_errors,
            )

        return ParsedDocument(
            path=path,
            title=str(title),
            format="pdf",
            sections=sections,
            full_text=full_text,
            metadata=metadata,
            parse_errors=parse_errors,
        )

    def is_available(self) -> bool:
        try:
            import pdfplumber  # noqa: F401
            return True
        except ImportError:
            return False

    def missing_dependency_message(self) -> str:
        return "Install pdfplumber: pip install graqle[docs]"

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]
