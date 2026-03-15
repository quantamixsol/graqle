"""Document scanner subsystem for Graqle.

Provides type registries, file-format detection, pluggable parsers,
incremental manifest tracking, auto-linking, and a high-level
:class:`DocumentScanner` orchestrator for converting documents
(Markdown, PDF, DOCX, PPTX, XLSX, plain text) into structured graph
nodes and edges.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: types
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.types import (
    DOC_EDGE_TYPES,
    DOC_EXTENSIONS,
    DOC_NODE_TYPES,
    SCAN_PRIORITY,
)

__all__ = [
    "DOC_EDGE_TYPES",
    "DOC_EXTENSIONS",
    "DOC_NODE_TYPES",
    "SCAN_PRIORITY",
]
