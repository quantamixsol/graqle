"""Tests for graqle.scanner.parsers.pdf — PDF parser."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_parsers.test_pdf
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pathlib, pytest, pdf
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from pathlib import Path

import pytest

pdfplumber = pytest.importorskip("pdfplumber", reason="pdfplumber not installed")

from graqle.scanner.parsers.pdf import PDFParser


@pytest.fixture
def parser() -> PDFParser:
    return PDFParser()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal PDF using reportlab if available, else pdfplumber test."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        p = tmp_path / "test.pdf"
        c = canvas.Canvas(str(p), pagesize=letter)
        c.drawString(72, 700, "Hello World")
        c.drawString(72, 680, "This is a test PDF document.")
        c.showPage()
        c.drawString(72, 700, "Page 2 content here.")
        c.showPage()
        c.save()
        return p
    except ImportError:
        pytest.skip("reportlab not installed — cannot create test PDF")


class TestPDFParser:
    def test_is_available(self, parser: PDFParser) -> None:
        assert parser.is_available() is True

    def test_supported_extensions(self, parser: PDFParser) -> None:
        assert ".pdf" in parser.supported_extensions

    def test_parse_basic(self, parser: PDFParser, sample_pdf: Path) -> None:
        doc = parser.parse(sample_pdf)
        assert doc.format == "pdf"
        assert doc.path == sample_pdf
        assert len(doc.sections) >= 1
        assert doc.full_text  # non-empty

    def test_parse_metadata(self, parser: PDFParser, sample_pdf: Path) -> None:
        doc = parser.parse(sample_pdf)
        assert "source" in doc.metadata
        assert "page_count" in doc.metadata
        assert doc.metadata["page_count"] >= 2

    def test_parse_pages_as_sections(self, parser: PDFParser, sample_pdf: Path) -> None:
        doc = parser.parse(sample_pdf)
        for section in doc.sections:
            assert section.page is not None
            assert section.page >= 1

    def test_file_not_found(self, parser: PDFParser, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parser.parse(tmp_path / "nonexistent.pdf")

    def test_missing_dependency_message(self, parser: PDFParser) -> None:
        msg = parser.missing_dependency_message()
        assert "pip install" in msg
