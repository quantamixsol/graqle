"""ChatAgentLoop v4 GRAQ.md multi-root loader .

Implements the GRAQ.md loader with Claude-Code-equivalent walk-up
precedence. The loader collects all ``GRAQ.md`` files from ``start_dir``
UP to the filesystem root, merges them in order with the most-specific
file winning on conflicts and additive scenario playbooks, and assembles
the final system prompt as:

  1. Built-in floor (graqle/chat/templates/GRAQ_default.md) — immutable
  2. User-global (~/.graqle/GRAQ.md) — sandboxed
  3. Project walk-up (farthest parent first, closest to cwd last) — sandboxed

User-provided content is wrapped in a ``<user_project_instructions
UNTRUSTED=true source="...">...</user_project_instructions>`` block. Any
attempt to close the sandbox tag from inside user content is neutralized
by escaping the closing delimiter to ``[USER_TAG_CLOSE]`` before emission.

Windows / UNC / POSIX root termination is handled explicitly: the walk-up
stops when ``parent.resolve() == current.resolve()`` OR after a defensive
maximum depth of 50 levels, whichever comes first. A visited-canonical-path
set prevents symlink cycles.

This module has zero dependencies on other graqle packages so it can be
imported in isolation by the chat package and by tests.
"""

# ── graqle:intelligence ──
# module: graqle.chat.graq_md_loader
# risk: LOW (impact radius: 0 modules at # consumers: graqle.chat.agent_loop # dependencies: dataclasses, html, importlib.resources, logging, pathlib
# constraints: zero intra-graqle deps; sandbox escaping + Windows root safety
# ── /graqle:intelligence ──

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "SystemPromptBundle",
    "GraqMdLoader",
    "BUILT_IN_TEMPLATE_NAME",
    "MAX_WALK_UP_DEPTH",
    "load_built_in_template",
]

logger = logging.getLogger("graqle.chat.graq_md_loader")

BUILT_IN_TEMPLATE_NAME = "GRAQ_default.md"
MAX_WALK_UP_DEPTH = 50
GRAQ_MD_FILENAME = "GRAQ.md"
USER_GLOBAL_GRAQ_MD = Path.home() / ".graqle" / "GRAQ.md"

# Sandbox tag used to wrap untrusted user content. The closing tag is
# escaped inside user content so producers cannot break out of the
# sandbox by embedding a literal `</user_project_instructions>`.
_SANDBOX_OPEN = '<user_project_instructions UNTRUSTED=true source="{src}">'
_SANDBOX_CLOSE = "</user_project_instructions>"
_SANDBOX_CLOSE_RE = re.compile(
    r"</\s*user_project_instructions\s*>",
    re.IGNORECASE,
)
_SANDBOX_CLOSE_PLACEHOLDER = "[USER_TAG_CLOSE]"


@dataclass(frozen=True)
class SystemPromptBundle:
    """The assembled system prompt for a ChatAgentLoop turn.

    Fields:
        built_in: the immutable built-in template text
        user_global: content of ~/.graqle/GRAQ.md (or empty)
        project_layered: list of (path, content) tuples in walk-up order
            (farthest parent first, closest to cwd last)
        final_text: the fully assembled prompt — built-in + sandboxed
            user sections concatenated
        sources: human-readable source labels matching the final_text
            assembly order
    """

    built_in: str
    user_global: str
    project_layered: list[tuple[Path, str]]
    final_text: str
    sources: list[str]


def _escape_sandbox_content(content: str) -> str:
    """Neutralize closing tags inside user content so sandbox cannot be broken."""
    return _SANDBOX_CLOSE_RE.sub(_SANDBOX_CLOSE_PLACEHOLDER, content)


def _wrap_sandbox(source: str, content: str) -> str:
    """Wrap user content in the sandbox tag with escaped metadata."""
    escaped_source = html.escape(source, quote=True)
    escaped_content = _escape_sandbox_content(content)
    return (
        _SANDBOX_OPEN.format(src=escaped_source)
        + "\n"
        + escaped_content
        + "\n"
        + _SANDBOX_CLOSE
    )


def load_built_in_template() -> str:
    """Load the immutable built-in template from the chat/templates package.

    Uses importlib.resources so the template works both from an installed
    wheel and from a source tree.
    """
    try:
        from importlib.resources import files as _files
        return (_files("graqle.chat.templates") / BUILT_IN_TEMPLATE_NAME).read_text(
            encoding="utf-8"
        )
    except Exception as exc:
        # Fallback to filesystem resolution relative to this module
        logger.warning(
            "importlib.resources failed for %s: %s — falling back to filesystem",
            BUILT_IN_TEMPLATE_NAME, exc,
        )
        fallback = Path(__file__).parent / "templates" / BUILT_IN_TEMPLATE_NAME
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        logger.error(
            "Built-in GRAQ template not found at %s", fallback,
        )
        return "# GraQle ChatAgentLoop v4 — Built-in floor (template missing)\n"


class GraqMdLoader:
    """Multi-root GRAQ.md loader with Claude-Code-equivalent precedence.

    Usage:
        bundle = GraqMdLoader().load()                     # cwd walk-up
        bundle = GraqMdLoader().load(Path("/some/dir"))    # explicit start
    """

    def __init__(
        self,
        *,
        user_global_path: Path | None = None,
        max_depth: int = MAX_WALK_UP_DEPTH,
    ) -> None:
        self._user_global_path = (
            user_global_path if user_global_path is not None else USER_GLOBAL_GRAQ_MD
        )
        self._max_depth = max_depth

    # ── public API ───────────────────────────────────────────────────

    def load(self, start_dir: Path | str | None = None) -> SystemPromptBundle:
        """Load the full bundle: built-in floor + user-global + project walk-up."""
        start = Path(start_dir) if start_dir is not None else Path.cwd()

        built_in = load_built_in_template()
        user_global = self._read_user_global()
        project_layered = self._walk_up_collect(start)

        return self._assemble(built_in, user_global, project_layered)

    # ── helpers ──────────────────────────────────────────────────────

    def _read_user_global(self) -> str:
        """Read ~/.graqle/GRAQ.md if present; return '' otherwise."""
        try:
            if self._user_global_path.exists():
                return self._user_global_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "GraqMdLoader could not read user-global %s: %s",
                self._user_global_path, exc,
            )
        return ""

    def _walk_up_collect(self, start: Path) -> list[tuple[Path, str]]:
        """Walk UP from start_dir to filesystem root, collecting GRAQ.md files.

        Returns a list of (canonical_path, content) tuples in walk-up order:
        FARTHEST-parent-first, so that the closest-to-cwd file is the LAST
        entry and "wins" on ordering (matches Claude Code CLAUDE.md behavior).

        Termination:
            - parent.resolve() == current.resolve() (filesystem root, POSIX/Windows/UNC)
            - depth >= self._max_depth (defensive cap)
            - canonical path already visited (symlink cycle guard)
        """
        collected: list[tuple[Path, str]] = []
        visited: set[str] = set()
        current = start
        try:
            current_resolved = current.resolve()
        except OSError:
            current_resolved = current
        depth = 0

        while depth < self._max_depth:
            depth += 1
            key = str(current_resolved)
            if key in visited:
                logger.debug(
                    "GraqMdLoader walk-up visited %s already — breaking cycle",
                    key,
                )
                break
            visited.add(key)

            candidate = current_resolved / GRAQ_MD_FILENAME
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                    collected.append((candidate, content))
                except OSError as exc:
                    logger.warning(
                        "GraqMdLoader could not read %s: %s", candidate, exc,
                    )

            try:
                parent = current_resolved.parent
                parent_resolved = parent.resolve()
            except OSError:
                break
            # Filesystem root reached — POSIX Path("/").parent == Path("/"),
            # Windows Path("C:\\").parent == Path("C:\\"),
            # UNC Path("\\\\server\\share").parent == Path("\\\\server\\share").
            if parent_resolved == current_resolved:
                break
            current_resolved = parent_resolved

        # Reverse: walker goes near → far, we want far → near
        collected.reverse()
        return collected

    def _assemble(
        self,
        built_in: str,
        user_global: str,
        project_layered: list[tuple[Path, str]],
    ) -> SystemPromptBundle:
        """Assemble the final prompt: built-in floor + sandboxed user sections.

        The built-in is immutable and goes first. Every user section is
        wrapped in a sandbox tag with an escaped source label.
        """
        parts: list[str] = [built_in]
        sources: list[str] = ["built-in:GRAQ_default.md"]

        if user_global.strip():
            parts.append("")
            parts.append(_wrap_sandbox("user-global:~/.graqle/GRAQ.md", user_global))
            sources.append("user-global:~/.graqle/GRAQ.md")

        for path, content in project_layered:
            if not content.strip():
                continue
            parts.append("")
            parts.append(_wrap_sandbox(f"project:{path}", content))
            sources.append(f"project:{path}")

        final_text = "\n".join(parts)
        return SystemPromptBundle(
            built_in=built_in,
            user_global=user_global,
            project_layered=project_layered,
            final_text=final_text,
            sources=sources,
        )
