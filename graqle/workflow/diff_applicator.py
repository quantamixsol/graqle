# graqle/workflow/diff_applicator.py
"""
DiffApplicator: atomic diff application with git-stash rollback.

Wraps graqle.core.file_writer.apply_diff for LoopController use.
Adds git-stash based rollback for failed test recovery.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graqle.workflow.action_agent_protocol import ExecutionResult

logger = logging.getLogger("graqle.workflow.diff_applicator")

# Protected file patterns — never allow autonomous modification
# These protect trade secrets (internal-pattern-A..internal-pattern-D) and IP-sensitive code
_PROTECTED_PATTERNS: frozenset[str] = frozenset({
    ".env",
    ".env.local",
    "credentials",
    "secrets",
    ".pypirc",
    "ip_gate",
    "trade_secret",
    "ts_values",
    "patent",
})


def _is_protected_file(file_path: str | Path) -> bool:
    """Check if a file matches protected patterns (trade secrets, credentials).

    Uses Path.resolve() to prevent path traversal bypass (e.g., ../../../.env).
    Fails CLOSED: if path resolution fails, the file is treated as protected.
    """
    # Resolve symlinks and normalize to prevent traversal attacks
    try:
        resolved = str(Path(file_path).resolve()).lower()
    except (OSError, ValueError):
        # Fail closed: unresolvable paths are treated as protected
        logger.warning(
            "Cannot resolve path %r — treating as protected (fail-closed)", file_path
        )
        return True

    # Also check the raw path for partial matches
    raw = str(file_path).lower()

    for pattern in _PROTECTED_PATTERNS:
        if pattern in resolved or pattern in raw:
            return True
    return False


@dataclass
class StashToken:
    """Opaque rollback token backed by git stash."""

    stash_ref: str
    working_dir: str
    files_stashed: list[str]

    def __str__(self) -> str:
        return f"stash:{self.stash_ref}"


class DiffApplicator:
    """
    Apply diffs atomically with git-stash rollback.

    Uses git stash to create rollback points before applying changes.
    If tests fail, rollback() pops the stash to restore the previous state.
    """

    def __init__(self, working_dir: str | Path) -> None:
        self._working_dir = Path(working_dir)

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command in the working directory."""
        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd,
            cwd=str(self._working_dir),
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def _is_git_repo(self) -> bool:
        """Check if working_dir is inside a git repository."""
        try:
            result = self._run_git("rev-parse", "--is-inside-work-tree", check=False)
            return result.returncode == 0 and result.stdout.strip() == "true"
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    @staticmethod
    def _validate_stash_token(token: str) -> bool:
        """Validate stash token format to prevent argument injection."""
        return bool(re.fullmatch(r"stash@\{\d+\}", token))

    @staticmethod
    def _sanitize_message(message: str) -> str:
        """Sanitize stash message to prevent git flag injection."""
        # Strip non-alphanumeric except whitespace and hyphens
        clean = re.sub(r"[^\w\s\-]", "", message)[:80].strip()
        # Prevent leading dashes (git flag injection)
        if clean.startswith("-"):
            clean = "checkpoint-" + clean.lstrip("-")
        return clean or "autoloop-checkpoint"

    def create_stash(self, message: str = "autoloop-checkpoint") -> str | None:
        """
        Create a git stash as a rollback point.

        Returns stash ref string or None if nothing to stash / not a git repo.
        """
        if not self._is_git_repo():
            logger.debug("Not a git repo — skipping stash creation")
            return None

        try:
            safe_message = self._sanitize_message(message)
            # Stage all changes first to include untracked files
            self._run_git("add", "-A", check=False)
            # A-003: exclude KG files from stash to prevent conflicts on pop
            result = self._run_git(
                "stash", "push", "--include-untracked", "-m", safe_message,
                "--",
                ":(exclude)graqle.json",
                ":(exclude).graqle/",
                ":(exclude)*.json.bak*",
                check=False,
            )
            if "No local changes" in result.stdout or result.returncode != 0:
                logger.debug("No changes to stash")
                return None

            # Get the stash ref and validate it
            list_result = self._run_git("stash", "list", "--max-count=1", check=False)
            ref = list_result.stdout.strip().split(":")[0] if list_result.stdout else "stash@{0}"
            if not self._validate_stash_token(ref):
                logger.warning("Unexpected stash ref format: %r — discarding", ref)
                return None
            logger.info("Created stash: %s (%s)", ref, safe_message)
            return ref
        except subprocess.SubprocessError as exc:
            logger.warning("Failed to create stash: %s", exc)
            return None

    def rollback(self, token: str) -> ExecutionResult:
        """
        Rollback to the stash identified by token.

        Parameters
        ----------
        token : str
            Stash reference (e.g., "stash@{0}"). Validated against injection.

        Returns
        -------
        ExecutionResult
        """
        if not self._is_git_repo():
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="Not a git repository — cannot rollback",
            )

        # Validate token format to prevent argument injection
        if not self._validate_stash_token(token):
            logger.error("SECURITY: rejected invalid stash token: %r", token[:50])
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Invalid stash token format: must match stash@{{N}}",
            )

        try:
            # Pop the stash to restore previous state
            result = self._run_git("stash", "pop", token, check=False)
            if result.returncode == 0:
                logger.info("Rolled back via stash pop: %s", token)
                return ExecutionResult(
                    exit_code=0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    rollback_token=token,
                )
            else:
                logger.warning("Stash pop failed: %s", result.stderr)
                return ExecutionResult(
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
        except subprocess.SubprocessError as exc:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Rollback failed: {exc}",
            )

    def apply_diff_atomic(
        self,
        file_path: str | Path,
        unified_diff: str,
        *,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Apply a unified diff atomically using graqle.core.file_writer.

        Includes governance gate: refuses to modify protected files
        (trade secrets, credentials, IP-sensitive patterns).

        Parameters
        ----------
        file_path : str | Path
            Target file for the diff.
        unified_diff : str
            Unified diff content.
        dry_run : bool
            If True, validate without writing.

        Returns
        -------
        ExecutionResult
        """
        # P0 governance gate: block writes to protected files
        if _is_protected_file(file_path):
            logger.error(
                "GOVERNANCE BLOCK: refusing to modify protected file: %s",
                file_path,
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"GOVERNANCE BLOCK: {file_path} matches protected file pattern. "
                       f"Trade secrets, credentials, and IP-sensitive files cannot be "
                       f"modified by the autonomous loop.",
            )

        try:
            from graqle.core.file_writer import apply_diff, ApplyResult

            result: ApplyResult = apply_diff(
                Path(file_path),
                unified_diff,
                dry_run=dry_run,
            )

            if result.success:
                return ExecutionResult(
                    exit_code=0,
                    stdout=f"Applied diff: {result.lines_changed} lines changed",
                    stderr="",
                    modified_files=[str(file_path)],
                    rollback_token=result.backup_path,
                )
            else:
                return ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"Diff application failed: {result.error}",
                )
        except ImportError:
            # Fallback: write content directly if file_writer not available
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="graqle.core.file_writer not available",
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Diff application error: {exc}",
            )

    def write_file_atomic(
        self,
        file_path: str | Path,
        content: str,
    ) -> ExecutionResult:
        """
        Write content to a file atomically (write to .tmp, then rename).

        Used for new files where there is no existing file to diff against.
        Includes governance gate for protected files.
        """
        # P0 governance gate
        if _is_protected_file(file_path):
            logger.error(
                "GOVERNANCE BLOCK: refusing to write protected file: %s",
                file_path,
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"GOVERNANCE BLOCK: {file_path} matches protected file pattern.",
            )

        target = Path(file_path)
        tmp_name = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Use unpredictable temp file to prevent TOCTOU/symlink attacks
            with tempfile.NamedTemporaryFile(
                dir=str(target.parent),
                delete=False,
                suffix=".tmp",
                mode="w",
                encoding="utf-8",
            ) as tf:
                tf.write(content)
                tmp_name = tf.name
            os.replace(tmp_name, str(target))
            logger.info("Wrote file atomically: %s", target)
            return ExecutionResult(
                exit_code=0,
                stdout=f"Wrote {len(content)} bytes to {target}",
                stderr="",
                modified_files=[str(target)],
            )
        except Exception as exc:
            # Cleanup temp file on failure
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="Write operation failed. See server logs for details.",
            )
