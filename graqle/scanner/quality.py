"""Document quality gate — reject low-value documents before scanning."""

# ── graqle:intelligence ──
# module: graqle.scanner.quality
# risk: LOW (impact radius: 1 modules)
# consumers: test_quality
# dependencies: __future__, hashlib, dataclasses, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class QualityAssessment:
    """Result of quality assessment."""
    accepted: bool
    reason: str
    score: float  # 0.0 - 1.0 quality score


def assess_document_quality(
    full_text: str,
    sections_count: int,
    file_path: str | Path,
    *,
    existing_hashes: set[str] | None = None,
) -> QualityAssessment:
    """Assess whether a document contributes meaningful knowledge."""
    path_str = str(file_path).lower()

    # Too short
    if len(full_text.strip()) < 50:
        return QualityAssessment(False, "Too short (< 50 chars)", 0.0)

    # Binary/garbled
    non_ascii = sum(1 for c in full_text if ord(c) > 127)
    ratio = non_ascii / max(len(full_text), 1)
    if ratio > 0.5:
        return QualityAssessment(False, f"Binary/garbled content ({ratio:.0%} non-ASCII)", 0.1)

    # No structure
    if sections_count == 0:
        return QualityAssessment(False, "No parseable structure", 0.2)

    # Test fixture/mock
    fixture_markers = ("fixture", "mock", "__fixtures__", "testdata", "test_data")
    if any(marker in path_str for marker in fixture_markers):
        return QualityAssessment(False, "Test fixture/mock data", 0.1)

    # Duplicate by hash
    if existing_hashes is not None:
        doc_hash = hashlib.sha256(full_text.strip().encode()).hexdigest()[:16]
        if doc_hash in existing_hashes:
            return QualityAssessment(False, "Duplicate content (hash match)", 0.0)

    # Compute quality score
    score = min(1.0, 0.3 + (sections_count * 0.1) + min(len(full_text) / 5000, 0.4))
    return QualityAssessment(True, "OK", score)


def compute_content_hash(text: str) -> str:
    """Compute a content hash for deduplication."""
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]
