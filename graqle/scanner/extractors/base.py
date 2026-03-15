"""Base extractor protocol for JSON knowledge extraction."""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.base
# risk: MEDIUM (impact radius: 31 modules)
# consumers: api, fallback, gemini, llamacpp_backend, local +26 more
# dependencies: __future__, dataclasses, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedNode:
    """A node produced by a JSON extractor."""

    id: str
    label: str
    entity_type: str
    description: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedEdge:
    """An edge produced by a JSON extractor."""

    source_id: str
    target_id: str
    relationship: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Output of a single JSON file extraction."""

    nodes: list[ExtractedNode] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BaseExtractor:
    """Abstract base for category-specific JSON extractors."""

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        """Extract nodes and edges from parsed JSON *data*.

        Parameters
        ----------
        data:
            Parsed JSON content (already loaded).
        file_path:
            Absolute path to the source file.
        rel_path:
            Relative path from project root (used in node IDs).
        """
        raise NotImplementedError
