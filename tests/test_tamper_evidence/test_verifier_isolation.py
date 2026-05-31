"""WS-A3 — import-isolation CI gate for the standalone verifier (moat M2).

This is the *static* half of the moat-M2 isolation invariant (the runtime
``_assert_isolated`` guard in verifier.py is the dynamic half — defense in depth).
It performs an AST import-graph audit and **fails the build** if the verifier or
its user-facing surface imports anything OUTSIDE a frozen allowlist:

    {merkle, canonicalize, custody.ed25519_key_manifest, errors} (the four
    tamper-evidence primitives the verifier composes) + the standard library +
    ``cryptography``.

An allowlist (not a denylist) is used deliberately: a denylist only catches the
forbidden imports we thought to name, whereas an allowlist catches ANY new
dependency — including a future ``graqle.server``/``graqle.studio``/network
import that a denylist would miss. A regression that smuggles a proprietary or
networked dependency into the verifier breaks the "survive-our-disappearance"
guarantee silently; this gate makes CI red instead.

The companion subprocess-invariant tests (verify in a studio-free interpreter)
live in test_verifier.py (AC-1/AC-3) and test_verify_surface.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_GRAQLE_ROOT = Path(__file__).parent.parent.parent / "graqle"
_VERIFIER = _GRAQLE_ROOT / "governance" / "tamper_evidence" / "verifier.py"
_VERIFY_PKG = _GRAQLE_ROOT / "verify"

# The four tamper-evidence primitives the verifier is allowed to compose.
_ALLOWED_GRAQLE_MODULES = {
    "graqle.governance.tamper_evidence.merkle",
    "graqle.governance.tamper_evidence.canonicalize",
    "graqle.governance.tamper_evidence.errors",
    "graqle.governance.custody.ed25519_key_manifest",
}

# The verify surface (CLI + module entrypoint) additionally composes the verifier
# itself + the verify core; these stay inside the isolation domain.
_ALLOWED_SURFACE_MODULES = _ALLOWED_GRAQLE_MODULES | {
    "graqle.governance.tamper_evidence.verifier",
    "graqle.verify",
    "graqle.cli.console",  # console helper is stdlib+rich only (UI shell)
}

# Third-party packages the verifier may use. cryptography is a core dependency;
# typer/rich are the CLI shell (surface only, not the verifier core).
_ALLOWED_THIRD_PARTY = {"cryptography"}
_ALLOWED_SURFACE_THIRD_PARTY = _ALLOWED_THIRD_PARTY | {"typer", "rich", "click"}

# Anything matching these is an immediate, explicit FAIL regardless of allowlist
# (a belt-and-braces check that names the exact moat breakers).
_FORBIDDEN_PREFIXES = ("graqle.server", "graqle.studio")


def _stdlib_module_names() -> set[str]:
    """Top-level standard-library module names available on this interpreter."""
    names = set(sys.stdlib_module_names)
    names.add("__future__")
    return names


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def _collect_import_modules(path: Path) -> set[str]:
    """Return the set of fully-dotted module sources imported by ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # Only absolute imports matter for isolation; relative imports
            # (level>0) stay inside the package and carry no module string.
            if node.level == 0 and node.module:
                out.add(node.module)
    return out


def _check_isolation(
    path: Path,
    *,
    allowed_graqle: set[str],
    allowed_third_party: set[str],
) -> None:
    stdlib = _stdlib_module_names()
    imports = _collect_import_modules(path)
    offenders: list[str] = []
    for module in sorted(imports):
        top = _top(module)
        # Explicit moat-breaker check first.
        if any(module == p or module.startswith(p + ".") for p in _FORBIDDEN_PREFIXES):
            offenders.append(f"{module} (FORBIDDEN proprietary/server surface)")
            continue
        if top == "graqle":
            if module not in allowed_graqle:
                offenders.append(f"{module} (graqle module not in isolation allowlist)")
            continue
        if top in stdlib:
            continue
        if top in allowed_third_party:
            continue
        offenders.append(f"{module} (third-party not in allowlist)")
    assert not offenders, (
        f"{path.name} imports outside the isolation allowlist: {offenders}. "
        f"The standalone verifier (moat M2) may import only the four "
        f"tamper-evidence primitives, the standard library, and cryptography. "
        f"Adding any other dependency breaks the survive-our-disappearance "
        f"invariant — see WS-A1 verifier.py module docstring."
    )


def test_verifier_imports_are_isolated():
    """verifier.py imports only {merkle, canonicalize, errors, manifest} + stdlib + cryptography."""
    _check_isolation(
        _VERIFIER,
        allowed_graqle=_ALLOWED_GRAQLE_MODULES,
        allowed_third_party=_ALLOWED_THIRD_PARTY,
    )


@pytest.mark.parametrize(
    "surface_file",
    [p for p in _VERIFY_PKG.rglob("*.py") if "__pycache__" not in p.parts],
    ids=lambda p: p.name,
)
def test_verify_surface_imports_are_isolated(surface_file):
    """The python -m graqle.verify surface stays inside the isolation domain."""
    _check_isolation(
        surface_file,
        allowed_graqle=_ALLOWED_SURFACE_MODULES,
        allowed_third_party=_ALLOWED_SURFACE_THIRD_PARTY,
    )


def test_attest_cli_does_not_import_server_or_studio():
    """The graq attest sub-app must not pull server/studio into the import graph."""
    attest = _GRAQLE_ROOT / "cli" / "commands" / "attest.py"
    imports = _collect_import_modules(attest)
    for module in imports:
        assert not any(
            module == p or module.startswith(p + ".") for p in _FORBIDDEN_PREFIXES
        ), f"attest.py imports forbidden module {module!r} (moat M2 breaker)"


def test_allowlist_actually_constrains():
    """Meta-test: a hypothetical forbidden import would be caught.

    Guards against the gate silently passing everything (e.g. if the allowlist
    accidentally became all-encompassing). We synthesize a tiny module that
    imports graqle.server and assert the checker flags it.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write("import graqle.server.lambda_handler\n")
        bad_path = Path(fh.name)
    try:
        with pytest.raises(AssertionError):
            _check_isolation(
                bad_path,
                allowed_graqle=_ALLOWED_GRAQLE_MODULES,
                allowed_third_party=_ALLOWED_THIRD_PARTY,
            )
    finally:
        bad_path.unlink()
