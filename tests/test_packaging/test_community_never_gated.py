"""Guardrail: Community-core surfaces must NEVER be entitlement-gated (WS-D D2).

The free core stays unconditionally available. This AST gate fails the build if
``@requires_edition`` / ``@requires_feature`` (the WS-D D2 entitlement gates) or
the legacy ``@require_license`` decorator is applied to a function/method in a
Community-CORE module. Proprietary surfaces (excluded from the Community wheel)
and the licensing/entitlement machinery itself are exempt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_GATING_DECORATORS = {"requires_edition", "requires_feature", "require_license"}

# Community CORE that must remain free + ungated. Conservative allowlist of the
# subtrees the open-core promise protects (ADR-BIZ-001 §3.3).
_CORE_PREFIXES = (
    "core",
    "reasoning",
    "governance/tamper_evidence",
    "governance/runtime",
    "verify",
    "metering",
    "edition.py",
)

# Exempt: the proprietary backends (not in the Community wheel) + the
# licensing/entitlement machinery (which legitimately references the decorators).
_EXEMPT_PREFIXES = ("cloud", "leads", "studio", "server", "licensing", "entitlement.py")


def _graqle_root() -> Path:
    return Path(__file__).resolve().parents[2] / "graqle"


def _is_core(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if any(rel == e or rel.startswith(e + "/") or rel.startswith(e) for e in _EXEMPT_PREFIXES):
        return False
    return any(rel == p or rel.startswith(p + "/") or rel.startswith(p) for p in _CORE_PREFIXES)


def _decorator_name(node: ast.expr) -> str | None:
    """Extract the decorator's callable name (handles @x, @x(...), @mod.x, @mod.x(...))."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _gated_defs(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                name = _decorator_name(dec)
                if name in _GATING_DECORATORS:
                    offenders.append(f"{node.name} (@{name})")
    return offenders


def test_no_community_core_surface_is_entitlement_gated():
    root = _graqle_root()
    violations: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        if not _is_core(rel):
            continue
        gated = _gated_defs(path)
        if gated:
            violations[rel] = gated
    assert not violations, (
        "WS-D guardrail violation: Community-core surfaces must NEVER be gated. "
        "Remove the entitlement decorator (the free core is unconditional):\n"
        + "\n".join(f"  {m}: {d}" for m, d in violations.items())
    )


# ---- meta-tests: the gate actually fires / classifies correctly --------------


def test_gate_detects_planted_gated_core(tmp_path):
    f = tmp_path / "planted.py"
    f.write_text("@requires_edition(Edition.STUDIO)\ndef core_thing():\n    pass\n", encoding="utf-8")
    assert _gated_defs(f) == ["core_thing (@requires_edition)"]


def test_gate_handles_plain_and_attribute_decorators(tmp_path):
    f = tmp_path / "p.py"
    f.write_text(
        "@require_license\ndef a():\n    pass\n"
        "@mod.requires_feature('x')\ndef b():\n    pass\n",
        encoding="utf-8",
    )
    names = _gated_defs(f)
    assert "a (@require_license)" in names and "b (@requires_feature)" in names


def test_core_classification():
    assert _is_core("core/graph.py")
    assert _is_core("metering/events.py")
    assert _is_core("edition.py")
    assert not _is_core("licensing/manager.py")   # exempt (machinery)
    assert not _is_core("entitlement.py")          # exempt (defines the gates)
    assert not _is_core("studio/app.py")           # proprietary
    assert not _is_core("cli/commands/cloud.py")   # not core (proprietary surface)
