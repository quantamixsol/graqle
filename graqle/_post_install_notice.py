"""First-run discoverability notice for `graq`.

H-7 (v0.51.2): When the user runs any `graq` command in a directory that has
Claude Code present (`.claude/` exists) but no governance gate installed
(`.claude/hooks/graqle-gate.py` missing), print a single one-line suggestion
to run `graq gate-install`. Silent on subsequent runs via a sentinel file.

Design goals:
- Single-line, non-blocking, non-interactive
- Silent after first run (sentinel at ~/.graqle/.first_run_shown)
- Silent when called FROM within `graq init` (which auto-invokes gate-install)
- Silent when no Claude Code detected (.claude/ absent)
- Silent when gate already installed (hook + settings.json both present)
- Never raise — failure to check is never user-visible
"""
# ── graqle:intelligence ──
# module: graqle._post_install_notice
# risk: LOW (impact radius: 1 modules)
# consumers: cli.main
# dependencies: __future__, os, pathlib, sys
# constraints: must never raise (swallow all errors); must be <10ms on hot path
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import sys
from pathlib import Path


SENTINEL_ENV_VAR = "GRAQLE_SKIP_FIRST_RUN_NOTICE"
"""If this env var is set (any truthy value), suppress the notice.

Set automatically by `graq init` to avoid double-notice during its own
auto-install flow. Callers may also set it in CI to keep logs clean.
"""

SENTINEL_FILENAME = ".first_run_shown"
"""Touch-file name in ~/.graqle/ that marks the notice as shown."""


def _sentinel_path() -> Path:
    """Resolve ~/.graqle/.first_run_shown without raising on exotic homes."""
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        # Path.home() can raise if HOME/USERPROFILE is unset. Fall back to cwd
        # so the sentinel still works in sandboxed environments.
        home = Path.cwd()
    return home / ".graqle" / SENTINEL_FILENAME


def _should_show_notice(cwd: Path | None = None) -> bool:
    """Decide whether to show the first-run notice.

    Returns True only when ALL of the following hold:
      - SENTINEL_ENV_VAR is not set (suppression escape hatch)
      - Sentinel file does not exist (not shown before)
      - .claude/ directory exists in cwd (Claude Code is in use here)
      - .claude/hooks/graqle-gate.py is MISSING or .claude/settings.json is MISSING
        (gate is not installed or only half-installed)

    Never raises. Any error short-circuits to False (stay silent).
    """
    try:
        if os.environ.get(SENTINEL_ENV_VAR):
            return False
        if _sentinel_path().exists():
            return False
        root = cwd if cwd is not None else Path.cwd()
        claude_dir = root / ".claude"
        if not claude_dir.is_dir():
            return False
        hook = claude_dir / "hooks" / "graqle-gate.py"
        settings = claude_dir / "settings.json"
        # Show notice if either piece is missing — hook alone without
        # settings.json is a half-install (CG-08 territory).
        return not (hook.exists() and settings.exists())
    except (OSError, ValueError):
        return False


def _mark_shown() -> None:
    """Create the sentinel file so the notice never fires again. Never raises."""
    try:
        p = _sentinel_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=True)
    except OSError:
        pass


def maybe_show_first_run_notice(cwd: Path | None = None) -> bool:
    """Show the discoverability notice if conditions are met. Return whether shown.

    This is the public entry point. Call once near the top of the `graq` CLI
    dispatcher. Returns True if the notice was printed (useful for tests).
    """
    if not _should_show_notice(cwd):
        return False
    # Keep the message single-line and low-noise. Writes to stderr so it
    # doesn't pollute stdout-captured tool output.
    try:
        sys.stderr.write(
            "[graqle] Claude Code detected but governance gate not installed. "
            "Run: graq gate-install\n"
        )
    except (OSError, ValueError):
        # Output failure — don't block the real command.
        return False
    _mark_shown()
    return True
