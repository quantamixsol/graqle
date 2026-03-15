"""Document scanner type registries.

Defines node types, edge types, supported file extensions, and scan
priorities for the document scanner subsystem.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.types
# risk: MEDIUM (impact radius: 27 modules)
# consumers: __init__, base_agent, slm_agent, registry, benchmark_runner +22 more
# dependencies: __future__
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

# ---------------------------------------------------------------------------
# Node types that the document scanner can emit
# ---------------------------------------------------------------------------

DOC_NODE_TYPES: dict[str, str] = {
    "Document": (
        "A complete document file (PDF, DOCX, Markdown, etc.) treated as "
        "a top-level knowledge artifact."
    ),
    "Section": (
        "A structural subdivision of a document — heading, slide, sheet, "
        "or logical paragraph grouping."
    ),
    "Decision": (
        "An explicit decision recorded in the document, including rationale "
        "and alternatives considered."
    ),
    "Requirement": (
        "A stated requirement, constraint, or acceptance criterion extracted "
        "from the document."
    ),
    "Procedure": (
        "A step-by-step process, workflow, or standard operating procedure "
        "described in the document."
    ),
    "Definition": (
        "A term definition, glossary entry, or concept explanation found "
        "in the document."
    ),
    "Stakeholder": (
        "A person, team, organisation, or role referenced as an owner, "
        "reviewer, or responsible party."
    ),
    "Timeline": (
        "A date, deadline, milestone, or temporal reference extracted "
        "from the document."
    ),
}

# ---------------------------------------------------------------------------
# Edge types that the document scanner can emit
# ---------------------------------------------------------------------------

DOC_EDGE_TYPES: dict[str, str] = {
    "DESCRIBES": (
        "Source node provides descriptive content about the target node."
    ),
    "DECIDED_BY": (
        "A decision node that was made or approved by a stakeholder node."
    ),
    "CONSTRAINED_BY": (
        "Target node imposes a constraint or requirement on the source node."
    ),
    "IMPLEMENTS": (
        "Source node implements, fulfils, or satisfies the target requirement "
        "or procedure."
    ),
    "REFERENCED_IN": (
        "Source node is explicitly referenced within the target document "
        "or section."
    ),
    "SECTION_OF": (
        "Source section node is a structural child of the target document "
        "or parent section."
    ),
    "OWNED_BY": (
        "Source node is owned by, assigned to, or the responsibility of "
        "the target stakeholder."
    ),
    "SUPERSEDES": (
        "Source node replaces or supersedes the target node (e.g. a newer "
        "version of a document or decision)."
    ),
    "DEPENDS_ON_DOC": (
        "Source node has an explicit dependency on the target document "
        "or artifact."
    ),
}

# ---------------------------------------------------------------------------
# File extensions recognised by the document scanner
# ---------------------------------------------------------------------------

DOC_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".md": "markdown",
    ".txt": "text",
    ".rst": "text",
    ".adoc": "text",
}

# ---------------------------------------------------------------------------
# Scan priority — lower number means the format is cheaper / faster to parse
# ---------------------------------------------------------------------------

SCAN_PRIORITY: dict[str, int] = {
    "markdown": 1,
    "text": 2,
    "pdf": 3,
    "docx": 4,
    "pptx": 5,
    "xlsx": 6,
}

# ---------------------------------------------------------------------------
# JSON node types (bridge layer between code and documents)
# ---------------------------------------------------------------------------

JSON_NODE_TYPES: dict[str, str] = {
    "Dependency": "External package dependency with version and manager.",
    "Script": "Build/run script from a package manager (npm, pip, etc.).",
    "Endpoint": "API endpoint from OpenAPI/Swagger spec with method and route.",
    "Schema": "Data schema from API spec or JSON Schema definition.",
    "Resource": "Cloud infrastructure resource (Lambda, DynamoDB, S3, etc.).",
    "ToolRule": "Linting, compiler, or formatter configuration rule.",
    "Config": "Application configuration key-value pair.",
}

# ---------------------------------------------------------------------------
# JSON edge types
# ---------------------------------------------------------------------------

JSON_EDGE_TYPES: dict[str, str] = {
    "DEPENDS_ON": "Project depends on external package.",
    "RETURNS": "Endpoint returns this schema type.",
    "ACCEPTS": "Endpoint accepts this schema as request body.",
    "IMPLEMENTED_BY": "Spec entity implemented by code.",
    "CONSUMED_BY": "Config value consumed by code module.",
    "TRIGGERS": "Resource triggers another resource.",
    "READS_FROM": "Resource reads from data store.",
    "APPLIES_TO": "Tool rule applies to file type.",
    "INVOKES": "Script invokes a command.",
}
