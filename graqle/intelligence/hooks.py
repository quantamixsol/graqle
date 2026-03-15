"""Pre-commit hook generator — Layer C enforcement.

Generates and manages pre-commit hooks that run graq verify
before every commit. This ensures the Quality Gate is always active.

The hook is lightweight: it reads pre-compiled intelligence (no scanning),
so it adds <1 second to commit time.

See ADR-105 §Layer C: Enforcement.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.hooks
# risk: LOW (impact radius: 1 modules)
# consumers: test_hooks
# dependencies: __future__, logging, stat, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import stat
from pathlib import Path

logger = logging.getLogger("graqle.intelligence.hooks")

HOOK_MARKER_START = "# ── graqle:pre-commit ──"
HOOK_MARKER_END = "# ── /graqle:pre-commit ──"

HOOK_SCRIPT = f"""{HOOK_MARKER_START}
# Graqle Quality Gate — pre-commit verification
# Checks staged changes against compiled intelligence.
# Remove with: graq compile --unhook
if command -v graq >/dev/null 2>&1; then
    graq verify --strict
    if [ $? -ne 0 ]; then
        echo ""
        echo "\\033[1;31mGraqle Quality Gate: BLOCKED\\033[0m"
        echo "Run 'graq verify' to see details."
        echo "Use 'git commit --no-verify' to bypass (not recommended)."
        exit 1
    fi
fi
{HOOK_MARKER_END}
"""


def install_hook(root: Path) -> bool:
    """Install the graq verify pre-commit hook.

    Appends to existing pre-commit hook if present.
    Returns True if hook was installed/updated.
    """
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.exists():
        logger.warning("No .git/hooks directory found. Is this a git repository?")
        return False

    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        if HOOK_MARKER_START in content:
            logger.info("Graqle hook already installed.")
            return False
        # Append to existing hook
        new_content = content.rstrip("\n") + "\n\n" + HOOK_SCRIPT + "\n"
    else:
        new_content = "#!/bin/sh\n\n" + HOOK_SCRIPT + "\n"

    hook_path.write_text(new_content, encoding="utf-8")

    # Make executable (Unix)
    try:
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
    except OSError:
        pass  # Windows doesn't need this

    return True


def uninstall_hook(root: Path) -> bool:
    """Remove the graq verify pre-commit hook.

    Only removes the Graqle section, preserving other hooks.
    Returns True if hook was removed.
    """
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False

    content = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER_START not in content:
        return False

    # Remove the Graqle section
    import re
    pattern = (
        r"\n?" + re.escape(HOOK_MARKER_START) +
        r".*?" + re.escape(HOOK_MARKER_END) + r"\n?"
    )
    new_content = re.sub(pattern, "", content, count=1, flags=re.DOTALL)

    # If only shebang remains, remove the file
    if new_content.strip() == "#!/bin/sh" or not new_content.strip():
        hook_path.unlink()
    else:
        hook_path.write_text(new_content, encoding="utf-8")

    return True


def has_hook(root: Path) -> bool:
    """Check if the Graqle pre-commit hook is installed."""
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    content = hook_path.read_text(encoding="utf-8")
    return HOOK_MARKER_START in content
