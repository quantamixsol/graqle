"""GitignoreMatcher — lightweight .gitignore pattern matching.

Extracted from graqle.cli.commands.scan (v0.42.2 hotfix B1) to enable
reuse in graqle.intelligence.pipeline without circular imports.

Limitations
-----------
- No character class [abc] support (treated as literal after re.escape).
  TODO: https://github.com/quantamixsol/graqle/issues/XXX
- No trailing-space rules.
- No nested .gitignore file discovery (caller must instantiate per directory).
  TODO: https://github.com/quantamixsol/graqle/issues/XXX
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("graqle.utils.gitignore")


class _CompiledPattern(NamedTuple):
    """A compiled gitignore pattern with negation flag."""

    regex: re.Pattern[str]
    negated: bool


class GitignoreMatcher:
    """Simple .gitignore pattern matching (covers most common patterns).

    Also reads ``.graqle-ignore`` if present, applying the same syntax.
    Extra patterns can be supplied via *extra_patterns* (e.g. from ``--exclude``).

    Implements last-match-wins semantics: a later ``!pattern`` overrides
    an earlier ``pattern``, matching real gitignore behavior.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        extra_patterns: list[str] | None = None,
    ) -> None:
        self._patterns: list[_CompiledPattern] = []

        for ignore_file in (".gitignore", ".graqle-ignore"):
            gi = repo_root / ignore_file
            if gi.is_file():
                self._load_file(gi)

        if extra_patterns:
            for raw in extra_patterns:
                stripped = raw.strip()
                if stripped and not stripped.startswith("#"):
                    compiled = self._compile(stripped)
                    if compiled is not None:
                        self._patterns.append(compiled)

    def _load_file(self, path: Path) -> None:
        """Load patterns from a gitignore-style file."""
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            compiled = self._compile(line)
            if compiled is not None:
                self._patterns.append(compiled)

    @staticmethod
    def _compile(pattern: str) -> _CompiledPattern | None:
        """Convert a gitignore glob to a compiled regex with negation flag.

        Returns None if the pattern produces invalid regex (logged as warning).
        """
        negated = False
        if pattern.startswith("!"):
            negated = True
            pattern = pattern[1:]

        # Detect anchored pattern BEFORE re.escape (BLOCKER fix: '/' becomes
        # '\\/' after escape, so startswith('/') would always be False)
        anchored = pattern.startswith("/")
        if anchored:
            pattern = pattern[1:]

        pattern = pattern.rstrip("/")

        if not pattern:
            return None

        # Escape ALL regex metacharacters, then selectively restore globs.
        # Order matters: replace \*\* before \* because re.escape('**') == '\\*\\*'
        regex = re.escape(pattern)
        regex = regex.replace(r"\*\*", "__GLOBSTAR__")
        regex = regex.replace(r"\*", "[^/]*")
        # **/ means "zero or more directories" (matches empty too)
        regex = regex.replace("__GLOBSTAR__/", "(.*/)?")
        # Trailing ** matches everything beneath (e.g. dist/**)
        regex = regex.replace("__GLOBSTAR__", "(.*)")
        regex = regex.replace(r"\?", "[^/]")

        # Anchored patterns match only at repo root; unanchored match anywhere
        if anchored:
            regex = "^" + regex
        else:
            regex = f"(?:^|.*/){regex}"

        regex += "(?:/.*)?$"

        try:
            compiled = re.compile(regex)
        except re.error as exc:
            logger.warning("Invalid .gitignore pattern %r: %s", pattern, exc)
            return None

        return _CompiledPattern(regex=compiled, negated=negated)

    def is_ignored(self, rel_path: str) -> bool:
        """Return True if *rel_path* is ignored (last-match-wins semantics).

        Expects a POSIX-style repo-root-relative path (forward slashes, no
        leading './' or '/'). Normalizes Windows backslashes automatically.
        """
        if not rel_path or not isinstance(rel_path, str):
            return False
        # Normalize: always replace backslashes (not just os.sep), strip leading ./
        rel_path = rel_path.replace("\\", "/").lstrip("./")

        ignored = False
        for pat in self._patterns:
            if pat.regex.search(rel_path):
                ignored = not pat.negated
        return ignored
