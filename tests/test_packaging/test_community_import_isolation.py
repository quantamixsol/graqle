"""Import-direction CI gate for the Community wheel (WS-C C1, ADR-BIZ-001).

The Community (Apache-2.0) ``graqle`` wheel ships WITHOUT the proprietary
backends (``graqle.cloud`` / ``graqle.leads`` / ``graqle.studio`` /
``graqle.server`` — excluded in ``pyproject.toml`` ``[tool.hatch.build.targets.wheel]``).
For that wheel to import and run, **no Community-kept module may import a
proprietary package at MODULE LEVEL (eagerly)** — proprietary access must stay
inside function bodies (lazy), so the import only happens if the user actually
invokes a commercial command (where ``graqle.cli._edition_guard`` degrades
gracefully).

This test is the gate that LOCKS that invariant: it AST-scans every Community
module and fails if a top-level ``import graqle.cloud`` (or leads/studio/server)
is introduced. It mirrors the WS-A3 verifier-isolation AST gate.

Scope boundary (do not conflate):
* This gate = Community-wheel import-direction (open-core packaging).
* ``scripts/ci/ip_content_scan.py`` = patent/SHA reference scanning.
* (S3) WS-F trade-secret gate = TAMR+ calibration internals.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Proprietary top-level packages excluded from the Community wheel.
_PROPRIETARY = ("graqle.cloud", "graqle.leads", "graqle.studio", "graqle.server")

# Directories that ARE proprietary (their own internal cross-imports are fine —
# they ship together in the proprietary distribution, never in Community).
_PROPRIETARY_DIRS = ("cloud", "leads", "studio", "server")


def _graqle_root() -> Path:
    # tests/test_packaging/this_file -> repo_root/graqle
    return Path(__file__).resolve().parents[2] / "graqle"


def _community_modules() -> list[Path]:
    """All .py files under graqle/ EXCEPT the proprietary dirs themselves."""
    root = _graqle_root()
    out: list[Path] = []
    for p in root.rglob("*.py"):
        rel_parts = p.relative_to(root).parts
        if rel_parts and rel_parts[0] in _PROPRIETARY_DIRS:
            continue  # proprietary module — its imports are not Community's concern
        out.append(p)
    return out


def _is_proprietary(module: str | None) -> bool:
    if not module:
        return False
    return any(module == p or module.startswith(p + ".") for p in _PROPRIETARY)


def _eager_proprietary_imports(path: Path) -> list[str]:
    """Return module-level (eager) proprietary imports in ``path``.

    A module-level import is one whose AST node is a direct child of the module
    body (``ast.Module``) — i.e. NOT nested inside a function/method/try-in-func.
    Lazy imports (inside a ``def``) are allowed and intentionally ignored.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    offenders: list[str] = []

    # Only inspect direct children of the module body + bodies of module-level
    # try/if blocks (still eager at import time). Function/class bodies are lazy.
    def _module_level_nodes(body: list[ast.stmt]):
        for node in body:
            yield node
            # module-level try/if/with still execute at import — recurse into them,
            # but NOT into FunctionDef/AsyncFunctionDef/ClassDef (those are lazy).
            if isinstance(node, (ast.Try, ast.If, ast.With)):
                for sub in ast.iter_child_nodes(node):
                    if isinstance(sub, ast.stmt) and not isinstance(
                        sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        yield sub

    for node in _module_level_nodes(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_proprietary(alias.name):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module
            if node.level == 0 and _is_proprietary(mod):
                offenders.append(f"from {mod} import ...")
    return offenders


def test_no_community_module_eagerly_imports_proprietary():
    """The gate: no Community module may eagerly import a proprietary package."""
    violations: dict[str, list[str]] = {}
    for path in _community_modules():
        offenders = _eager_proprietary_imports(path)
        if offenders:
            violations[str(path)] = offenders
    assert not violations, (
        "Community-wheel import-direction violation (WS-C C1): these modules "
        "import a proprietary package at MODULE LEVEL, which would crash the "
        "Community wheel that omits it. Move the import inside the function body "
        "(lazy) and guard it via graqle.cli._edition_guard:\n"
        + "\n".join(f"  {m}: {imps}" for m, imps in violations.items())
    )


def test_gate_detects_a_planted_eager_import(tmp_path):
    """Meta-test: the gate FIRES on a planted module-level proprietary import."""
    planted = tmp_path / "planted.py"
    planted.write_text("import graqle.cloud\n", encoding="utf-8")
    assert _eager_proprietary_imports(planted) == ["import graqle.cloud"]


def test_gate_ignores_lazy_import(tmp_path):
    """Meta-test: a function-body (lazy) proprietary import is NOT flagged."""
    lazy = tmp_path / "lazy.py"
    lazy.write_text(
        "def cmd():\n"
        "    from graqle.cloud.credentials import load_credentials\n"
        "    return load_credentials()\n",
        encoding="utf-8",
    )
    assert _eager_proprietary_imports(lazy) == []


def test_gate_ignores_from_import_with_level(tmp_path):
    """Meta-test: a relative import (level>0) is never a proprietary top-level import."""
    rel = tmp_path / "rel.py"
    rel.write_text("from . import something\n", encoding="utf-8")
    assert _eager_proprietary_imports(rel) == []


def test_gate_flags_module_level_try_import(tmp_path):
    """Meta-test: an eager import hidden in a module-level try/except still fires."""
    t = tmp_path / "t.py"
    t.write_text(
        "try:\n"
        "    import graqle.studio\n"
        "except ImportError:\n"
        "    graqle = None\n",
        encoding="utf-8",
    )
    assert _eager_proprietary_imports(t) == ["import graqle.studio"]
