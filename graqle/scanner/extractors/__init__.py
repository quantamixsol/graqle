"""JSON file extractors — category-specific knowledge extraction.

Each extractor receives parsed JSON data and returns typed nodes and edges
for the knowledge graph. Extractors are registered in the ``EXTRACTOR_MAP``
and dispatched by the ``JSONParser`` classifier.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.scanner.extractors.base import BaseExtractor

# Category → (module_path, class_name)
_EXTRACTOR_MAP: dict[str, tuple[str, str]] = {
    "DEPENDENCY_MANIFEST": (
        "graqle.scanner.extractors.dependency",
        "DependencyExtractor",
    ),
    "API_SPEC": (
        "graqle.scanner.extractors.api_spec",
        "APISpecExtractor",
    ),
    "INFRA_CONFIG": (
        "graqle.scanner.extractors.infra",
        "InfraExtractor",
    ),
    "TOOL_CONFIG": (
        "graqle.scanner.extractors.tool_config",
        "ToolConfigExtractor",
    ),
    "APP_CONFIG": (
        "graqle.scanner.extractors.app_config",
        "AppConfigExtractor",
    ),
}


def get_extractor(category: str) -> BaseExtractor | None:
    """Return an extractor instance for *category*, or ``None``."""
    import importlib

    entry = _EXTRACTOR_MAP.get(category)
    if entry is None:
        return None

    module_path, class_name = entry
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return None

    cls = getattr(module, class_name, None)
    if cls is None:
        return None

    return cls()
