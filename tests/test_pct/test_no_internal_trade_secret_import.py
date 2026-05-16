"""Constitutional guard: graqle.pct.* MUST NOT import GraQle-internal
trade-secret-bearing modules (CR-010 PR-010b-1 ADR-205 §8 AC-10).

Per the OPSF spec compliance + the operator-owned + patent-clean
positioning, the entire ``graqle.pct`` package must be importable
without pulling in any module that touches Q-function weight values,
agreement-threshold formulas, STG rules, or fold-back derivation.

This test does a static import-graph audit of the package files. It
does NOT import the trade-secret modules itself — that would defeat the
purpose. It just scans the source for forbidden import patterns.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PCT_DIR = Path(__file__).parent.parent.parent / "graqle" / "pct"

#: Forbidden module-import patterns. Each tuple is (regex-style substring, reason).
_FORBIDDEN_IMPORT_PATTERNS = [
    ("graqle.orchestration", "trade-secret reasoning orchestration"),
    ("graqle.routing", "trade-secret routing weights"),
    ("graqle.activation.scorer", "trade-secret activation scoring"),
    # Allow graqle.activation.health_probe (PUBLIC per ADR-MARKETING-002).
    ("graqle.governance.aggregation", "trade-secret aggregation weights"),
    ("graqle.governance.calibration", "trade-secret calibration internals"),
]


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _collect_imports(path: Path) -> set[str]:
    """Return the set of dotted import sources reached from ``path``."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(f"{path} is not valid Python: {exc}")
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            out.add(module)
    return out


@pytest.mark.parametrize("py_file", list(_iter_python_files(_PCT_DIR)))
def test_pct_module_does_not_import_forbidden(py_file):
    imports = _collect_imports(py_file)
    for pattern, reason in _FORBIDDEN_IMPORT_PATTERNS:
        offenders = [imp for imp in imports if pattern in imp]
        assert not offenders, (
            f"{py_file.relative_to(_PCT_DIR.parent.parent)} imports "
            f"{offenders!r} which contains forbidden pattern {pattern!r} "
            f"({reason}). PCT package must be operator-owned + patent-clean "
            f"per ADR-205 §8 AC-10."
        )


def test_pct_init_re_exports_public_surface():
    """Sanity: graqle.pct.__init__ re-exports the documented public API."""
    init = (_PCT_DIR / "__init__.py").read_text(encoding="utf-8")
    for name in (
        "PctIssueRequest",
        "PctValidationResult",
        "issue_pct",
        "validate_pct",
    ):
        assert name in init, f"{name} not re-exported from graqle.pct.__init__"
