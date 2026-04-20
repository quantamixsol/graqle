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

    @staticmethod
    def _resolve_worktree_main_repo(start: Path) -> Path | None:
        """SDK-B5 — if `start` is inside a git worktree, return the main repo root.

        A git worktree is identified by a `.git` *file* (not a directory) at the
        worktree root containing `gitdir: <abs_path>`. The gitdir points at
        `<main_repo>/.git/worktrees/<name>`, so the main repo root is two
        parents up from the gitdir.

        Returns None if `start` is not in a worktree (or detection fails —
        fail-closed: caller falls back to regular walk-up).
        """
        try:
            resolved = start.resolve()
        except OSError:
            return None

        # Walk up from start looking for a `.git` file (not dir)
        candidate = resolved
        for _ in range(32):  # defensive cap same shape as _max_depth
            git_path = candidate / ".git"
            if git_path.is_file():
                try:
                    text = git_path.read_text(encoding="utf-8")
                except OSError:
                    return None
                # Format: "gitdir: <abs_path>\n"
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("gitdir:"):
                        gitdir_raw = line.split(":", 1)[1].strip()
                        if not gitdir_raw:
                            return None
                        try:
                            gitdir = Path(gitdir_raw).resolve()
                        except OSError:
                            return None
                        # gitdir = <main>/.git/worktrees/<name>
                        # main repo root = gitdir.parent.parent.parent
                        try:
                            main_git_dir = gitdir.parent.parent  # /.../.git
                            main_repo = main_git_dir.parent
                            # Sanity check: the main repo's .git should be a directory
                            if (main_repo / ".git").is_dir():
                                return main_repo
                        except (OSError, IndexError):
                            return None
                        return None
                return None
            if git_path.is_dir():
                # Regular repo, not a worktree
                return None
            parent = candidate.parent
            try:
                parent_resolved = parent.resolve()
            except OSError:
                return None
            if parent_resolved == candidate:
                return None  # reached filesystem root without finding .git
            candidate = parent_resolved
        return None

    def _walk_up_collect(self, start: Path) -> list[tuple[Path, str]]:
        """Walk UP from start_dir to filesystem root, collecting GRAQ.md files.

        Returns a list of (canonical_path, content) tuples in walk-up order:
        FARTHEST-parent-first, so that the closest-to-cwd file is the LAST
        entry and "wins" on ordering (matches Claude Code CLAUDE.md behavior).

        SDK-B5 (2026-04-20): if `start` is inside a git worktree, the main
        repo's walk-up chain is prepended so the main repo's GRAQ.md is
        inherited (farther-ancestor semantics: less specific than worktree-
        local GRAQ.md, which still wins). Worktree-local GRAQ.md takes
        precedence because it is collected later in the list.

        Termination:
            - parent.resolve() == current.resolve() (filesystem root, POSIX/Windows/UNC)
            - depth >= self._max_depth (defensive cap)
            - canonical path already visited (symlink cycle guard)
        """
        collected: list[tuple[Path, str]] = []
        visited: set[str] = set()

        # SDK-B5 (2026-04-20): worktree-main-repo resolution.
        # If start is inside a git worktree, record the main repo root so
        # we can walk it AFTER the worktree walk finishes (see below —
        # the final `.reverse()` flips near→far into far→near, so main-
        # repo items must be appended LAST to become FARTHEST after reverse).
        main_repo = self._resolve_worktree_main_repo(start)

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

        # SDK-B5: append the main-repo walk-up chain AFTER the worktree walk.
        # After the final `.reverse()` below, main-repo items end up at the
        # FRONT of the returned list (farthest ancestors), so worktree-local
        # GRAQ.md is closest-to-cwd and wins on override.
        if main_repo is not None:
            try:
                _mr_current = main_repo.resolve()
            except OSError:
                _mr_current = main_repo
            _mr_depth = 0
            while _mr_depth < self._max_depth:
                _mr_depth += 1
                _mr_key = str(_mr_current)
                if _mr_key in visited:
                    break
                visited.add(_mr_key)
                _mr_candidate = _mr_current / GRAQ_MD_FILENAME
                if _mr_candidate.is_file():
                    try:
                        _mr_content = _mr_candidate.read_text(encoding="utf-8")
                        collected.append((_mr_candidate, _mr_content))
                    except OSError as _mr_exc:
                        logger.warning(
                            "GraqMdLoader could not read main-repo %s: %s",
                            _mr_candidate, _mr_exc,
                        )
                try:
                    _mr_parent = _mr_current.parent
                    _mr_parent_resolved = _mr_parent.resolve()
                except OSError:
                    break
                if _mr_parent_resolved == _mr_current:
                    break
                _mr_current = _mr_parent_resolved

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
