"""Lazy parser registry for the document scanner.

Parsers for formats that require heavy optional dependencies (PDF, DOCX,
PPTX, XLSX) are imported **only** when first requested, so that the core
scanner package stays lightweight.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.parsers.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, importlib, logging, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graqle.scanner.parsers.base import BaseDocParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry: extension -> (module_path, class_name)
# ---------------------------------------------------------------------------

_PARSER_MAP: dict[str, tuple[str, str]] = {
    # Zero-dependency parsers (always available)
    ".md": ("graqle.scanner.parsers.markdown", "MarkdownParser"),
    ".txt": ("graqle.scanner.parsers.text", "PlainTextParser"),
    ".rst": ("graqle.scanner.parsers.text", "PlainTextParser"),
    ".adoc": ("graqle.scanner.parsers.text", "PlainTextParser"),
    # Optional-dependency parsers (may not be installed)
    ".pdf": ("graqle.scanner.parsers.pdf", "PDFParser"),
    ".docx": ("graqle.scanner.parsers.docx", "DOCXParser"),
    ".pptx": ("graqle.scanner.parsers.pptx", "PPTXParser"),
    ".xlsx": ("graqle.scanner.parsers.xlsx", "XLSXParser"),
}

# Cache instantiated parsers so each is created at most once.
_PARSER_CACHE: dict[str, BaseDocParser | None] = {}


def get_parser(extension: str) -> BaseDocParser | None:
    """Return a parser instance for *extension*, or ``None``.

    Returns ``None`` if:
    * The extension is not in the registry, **or**
    * The parser's required dependencies are not installed.

    Parsers are lazily imported and cached on first access.

    Parameters
    ----------
    extension:
        File extension **including the leading dot** (e.g. ``".md"``).
    """
    ext = extension.lower()

    # Fast path — already resolved (may be None if deps missing)
    if ext in _PARSER_CACHE:
        return _PARSER_CACHE[ext]

    entry = _PARSER_MAP.get(ext)
    if entry is None:
        _PARSER_CACHE[ext] = None
        return None

    module_path, class_name = entry

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        logger.debug(
            "Cannot import parser module %s for %s: %s",
            module_path,
            ext,
            exc,
        )
        _PARSER_CACHE[ext] = None
        return None

    parser_cls = getattr(module, class_name, None)
    if parser_cls is None:
        logger.warning(
            "Module %s does not export class %s",
            module_path,
            class_name,
        )
        _PARSER_CACHE[ext] = None
        return None

    instance: BaseDocParser = parser_cls()

    if not instance.is_available():
        logger.info(
            "Parser %s is not available: %s",
            class_name,
            instance.missing_dependency_message(),
        )
        _PARSER_CACHE[ext] = None
        return None

    _PARSER_CACHE[ext] = instance
    return instance


def available_formats() -> dict[str, bool]:
    """Return ``{extension: is_available}`` for every registered format.

    Useful for CLI ``--list-formats`` output and health checks.
    """
    result: dict[str, bool] = {}
    for ext in _PARSER_MAP:
        parser = get_parser(ext)
        result[ext] = parser is not None
    return result
