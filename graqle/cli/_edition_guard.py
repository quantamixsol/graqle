"""Graceful-degrade guard for edition-gated CLI commands (WS-C C1).

The Community ``graqle`` wheel ships WITHOUT the proprietary implementation
packages (``graqle.cloud`` / ``graqle.leads`` / ``graqle.studio`` /
``graqle.server`` — excluded at build time, see ``pyproject.toml``
``[tool.hatch.build.targets.wheel] exclude``). The thin ``cli/commands/*`` wrappers
still ship, and they import those packages **lazily** (inside command bodies),
so the CLI starts fine on Community. The only thing that must not happen is a raw
``ModuleNotFoundError`` traceback when a user invokes a command whose backend
isn't installed.

This module provides :func:`requires_package` — a decorator that wraps a command
body, catches the *specific* "proprietary package absent" import error, and exits
with a clean, actionable message naming the package to install. Any OTHER
``ModuleNotFoundError`` (a real bug, a genuinely-missing third-party dep) is
re-raised untouched, so we never mask unrelated failures.

Design notes:
* This helper itself imports nothing proprietary — it is pure stdlib + the
  shared CLI console, so it is safe in the Community wheel.
* The message intentionally does NOT hardcode a marketing URL (the editions page
  is a future site deliverable, AUD-029); it gives the actionable ``pip install``
  path. A TODO marks where the URL slots in once the page ships.
* Edition is reported (not enforced) via :func:`graqle.edition.detect_edition`;
  actual entitlement gating (verifying a licence) is a separate concern (WS-D).
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

import typer

# Map each proprietary top-level package to the distribution that provides it.
# Used to turn an absent-package import error into an actionable install hint.
_PACKAGE_TO_DISTRIBUTION: dict[str, str] = {
    "graqle.cloud": "graqle-studio",
    "graqle.leads": "graqle-studio",
    "graqle.studio": "graqle-studio",
    "graqle.server": "graqle-studio",
}

F = TypeVar("F", bound=Callable[..., Any])


def _distribution_for(module_name: str) -> str:
    """Return the pip distribution that provides ``module_name`` (or a default).

    Matches the longest configured prefix so e.g. ``graqle.cloud.credentials``
    resolves to the ``graqle.cloud`` → ``graqle-studio`` mapping.
    """
    best = ""
    for pkg in _PACKAGE_TO_DISTRIBUTION:
        if (module_name == pkg or module_name.startswith(pkg + ".")) and len(pkg) > len(best):
            best = pkg
    return _PACKAGE_TO_DISTRIBUTION.get(best, "graqle-studio")


def _is_proprietary_absence(exc: ModuleNotFoundError) -> str | None:
    """If ``exc`` is an absent PROPRIETARY package, return its name; else None.

    Distinguishes "the Community wheel correctly omits a proprietary backend"
    (degrade gracefully) from "some other module is genuinely missing" (a real
    error we must NOT swallow). ``exc.name`` is the dotted module that failed to
    import; we match it against the proprietary prefixes only.
    """
    missing = exc.name or ""
    for pkg in _PACKAGE_TO_DISTRIBUTION:
        if missing == pkg or missing.startswith(pkg + ".") or pkg.startswith(missing + "."):
            return missing
    return None


def _degrade_message(missing_module: str, command_label: str) -> str:
    """Build the clean, actionable degrade message (no dead URLs — AUD-029)."""
    dist = _distribution_for(missing_module)
    # TODO(WS-H): append the editions overview URL (e.g. https://graqle.com/editions)
    # once the site page ships. Until then, give only the actionable install path —
    # never a dead link (honesty / journey-trace rule).
    return (
        f"[bold yellow]'{command_label}' requires a GraQle commercial edition.[/bold yellow]\n\n"
        f"This is part of GraQle Studio/Enterprise and is not included in the free "
        f"Community edition.\n\n"
        f"To enable it, install the commercial package:\n"
        f"    [cyan]pip install {dist}[/cyan]\n\n"
        f"The free Community edition includes reasoning, governance, tamper-evidence, "
        f"the offline verifier, and local anchoring — all unchanged."
    )


def requires_package(command_label: str) -> Callable[[F], F]:
    """Decorate a CLI command so an absent proprietary backend degrades cleanly.

    Wraps the command body. If invoking it raises a ``ModuleNotFoundError`` for a
    proprietary package that the Community wheel omits, print an actionable
    message and ``raise typer.Exit(code=2)`` (a usage/configuration error). Any
    other exception — including a ``ModuleNotFoundError`` for a non-proprietary
    module — propagates unchanged.

    ``command_label`` is the human-facing command name (e.g. ``"graq cloud status"``)
    used in the message.
    """

    def _decorator(func: F) -> F:
        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except ModuleNotFoundError as exc:
                missing = _is_proprietary_absence(exc)
                if missing is None:
                    raise  # a real missing-dependency error — never mask it
                from graqle.cli.console import create_console

                create_console().print(_degrade_message(missing, command_label))
                raise typer.Exit(code=2) from None

        return _wrapper  # type: ignore[return-value]

    return _decorator
