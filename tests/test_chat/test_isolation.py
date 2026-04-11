"""TB-F1.6 isolation test: the chat submodules must not import
graqle.core, graqle.backends, or other heavy graqle packages directly.

This is the MAJOR-4 concern from the pre-impl graq_review: the chat
package must stay self-contained at the SOURCE LEVEL so future TB-F*
modules don't silently grow cross-package dependencies.

Note: ``graqle/__init__.py`` itself eagerly imports ``graqle.core.*``
and several other subpackages, so ANY ``import graqle.chat`` transitively
loads them. That is a parent-package concern, not a chat-module concern.
The right isolation assertion is SOURCE-LEVEL: no file under
``graqle/chat/`` contains a direct ``from graqle.core``/``graqle.backends``
etc. import. That is what this test checks.
"""

# ── graqle:intelligence ──
# module: tests.test_chat.test_isolation
# risk: LOW (impact radius: 0 modules)
# dependencies: pytest, pathlib, re
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from pathlib import Path

import pytest


# Any import from these prefixes at the TB-F1 layer indicates a direct
# dependency that was not part of the spec. TB-F2+ may relax specific
# entries once the corresponding module lands (e.g. TB-F3 RCAG will need
# graqle.core.graph via IS-A Graqle).
# Globally-allowed shared core modules — TB-F2 onward needs Graqle/CogniNode
# /CogniEdge to subclass and build the TCG/RCAG. Everything else in graqle.core
# stays forbidden.
_ALLOWED_CORE_MODULES = {
    "graqle.core.graph",
    "graqle.core.node",
    "graqle.core.edge",
    "graqle.core.types",
    "graqle.core.message",
    "graqle.core.state",
}

_FORBIDDEN_IMPORT_PREFIXES_TB_F1 = [
    "graqle.core",
    "graqle.backends",
    "graqle.orchestration",
    "graqle.reasoning",
    "graqle.intelligence",
    "graqle.plugins",
    "graqle.connectors",
]

_IMPORT_RE = re.compile(
    r"""^\s*(?:from\s+(?P<from>[\w.]+)\s+import|import\s+(?P<imp>[\w.]+))""",
    re.MULTILINE,
)

_CHAT_DIR = Path(__file__).resolve().parent.parent.parent / "graqle" / "chat"


def _scan_imports(py_file: Path) -> set[str]:
    """Return the set of top-level module prefixes a file imports."""
    text = py_file.read_text(encoding="utf-8")
    modules: set[str] = set()
    for m in _IMPORT_RE.finditer(text):
        name = m.group("from") or m.group("imp")
        if name:
            modules.add(name)
    return modules


def _chat_py_files() -> list[Path]:
    """Return every .py file in graqle/chat/ (excluding templates/)."""
    return [
        p for p in _CHAT_DIR.rglob("*.py")
        if "templates" not in p.parts
    ]


def test_chat_dir_exists() -> None:
    assert _CHAT_DIR.is_dir(), f"chat dir not found: {_CHAT_DIR}"
    files = _chat_py_files()
    # At TB-F1.6 there should be 5 foundation .py files + __init__.py = 6 total
    assert len(files) >= 5, f"expected >= 5 chat .py files, found {len(files)}"


def test_chat_submodules_do_not_import_forbidden_packages() -> None:
    """Source-level isolation: no TB-F1 module may import graqle.core/backends/etc.

    The parent ``graqle/__init__.py`` still pulls those in at runtime,
    but THAT is a parent-package concern. The chat foundation modules
    themselves must stay source-clean so TB-F2/F3/F7 can tell at a glance
    what the layering is.
    """
    leaks: dict[str, set[str]] = {}
    for py_file in _chat_py_files():
        imports = _scan_imports(py_file)
        bad = set()
        for name in imports:
            # Allowlist short-circuit: legitimate shared core modules.
            if name in _ALLOWED_CORE_MODULES:
                continue
            for fp in _FORBIDDEN_IMPORT_PREFIXES_TB_F1:
                if name == fp or name.startswith(fp + "."):
                    bad.add(name)
                    break
        if bad:
            leaks[str(py_file.relative_to(_CHAT_DIR))] = bad

    assert not leaks, (
        "TB-F1 chat foundation modules must not import graqle.core/backends/"
        f"orchestration/reasoning/plugins. Leaks: {leaks}"
    )


def test_chat_init_imports_only_chat_internals() -> None:
    """graqle/chat/__init__.py specifically must only re-export chat internals."""
    init_file = _CHAT_DIR / "__init__.py"
    imports = _scan_imports(init_file)
    # Every import that starts with 'graqle.' must be a chat-internal import
    graqle_imports = [i for i in imports if i.startswith("graqle.")]
    bad = [i for i in graqle_imports if not i.startswith("graqle.chat")]
    assert not bad, (
        f"graqle/chat/__init__.py must only re-export from graqle.chat.*, "
        f"found: {bad}"
    )


def test_chat_public_api_all_importable() -> None:
    """Every symbol in graqle.chat.__all__ is a real object."""
    import graqle.chat as chat_pkg
    for name in chat_pkg.__all__:
        obj = getattr(chat_pkg, name, None)
        assert obj is not None, f"graqle.chat.{name} is None"


def test_chat_all_list_has_no_duplicates() -> None:
    import graqle.chat as chat_pkg
    assert len(chat_pkg.__all__) == len(set(chat_pkg.__all__))


def test_chat_all_sorted() -> None:
    """__all__ should be alphabetically sorted for readability."""
    import graqle.chat as chat_pkg
    assert list(chat_pkg.__all__) == sorted(chat_pkg.__all__)
