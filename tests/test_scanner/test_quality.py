"""Tests for document quality gate."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_quality
# risk: LOW (impact radius: 0 modules)
# dependencies: quality
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.quality import assess_document_quality, compute_content_hash


class TestAssessDocumentQuality:

    def test_accepts_good_document(self):
        result = assess_document_quality(
            "This is a well-structured document about authentication.\n" * 5,
            sections_count=3,
            file_path="docs/architecture.md",
        )
        assert result.accepted is True
        assert result.score > 0.5

    def test_rejects_too_short(self):
        result = assess_document_quality("Hi", 1, "doc.md")
        assert result.accepted is False
        assert "short" in result.reason.lower()

    def test_rejects_empty(self):
        result = assess_document_quality("", 0, "doc.md")
        assert result.accepted is False

    def test_rejects_garbled_content(self):
        garbled = "".join(chr(200 + i % 50) for i in range(200))
        result = assess_document_quality(garbled, 1, "doc.md")
        assert result.accepted is False
        assert "binary" in result.reason.lower() or "garbled" in result.reason.lower()

    def test_rejects_no_sections(self):
        result = assess_document_quality("a" * 100, 0, "doc.md")
        assert result.accepted is False
        assert "structure" in result.reason.lower()

    def test_rejects_fixture_path(self):
        result = assess_document_quality("x" * 100, 3, "tests/fixtures/mock_data.md")
        assert result.accepted is False
        assert "fixture" in result.reason.lower() or "mock" in result.reason.lower()

    def test_rejects_mock_path(self):
        result = assess_document_quality("x" * 100, 3, "tests/mock/response.md")
        assert result.accepted is False

    def test_rejects_duplicate_hash(self):
        text = "This is a document about auth\n" * 10
        hash_val = compute_content_hash(text)
        result = assess_document_quality(
            text, 3, "doc.md",
            existing_hashes={hash_val},
        )
        assert result.accepted is False
        assert "duplicate" in result.reason.lower()

    def test_accepts_when_hash_different(self):
        result = assess_document_quality(
            "Unique document content about payments\n" * 5,
            3, "doc.md",
            existing_hashes={"abc123"},
        )
        assert result.accepted is True

    def test_quality_score_increases_with_content(self):
        short = assess_document_quality("x" * 100, 1, "a.md")
        long = assess_document_quality("x" * 5000, 10, "b.md")
        assert long.score > short.score


class TestComputeContentHash:

    def test_same_content_same_hash(self):
        assert compute_content_hash("hello") == compute_content_hash("hello")

    def test_different_content_different_hash(self):
        assert compute_content_hash("hello") != compute_content_hash("world")

    def test_whitespace_stripped(self):
        assert compute_content_hash("  hello  ") == compute_content_hash("hello")

    def test_returns_16_chars(self):
        assert len(compute_content_hash("test")) == 16
