# ── graqle:intelligence ──
# module: graqle.core.file_writer
# risk: MEDIUM (writes to disk — blast radius: files touched by graq_edit)
# consumers: mcp_dev_server (_handle_edit), cli.main (graq edit)
# constraints: ALWAYS backup before write; ALWAYS use .tmp → os.replace pattern
# ── /graqle:intelligence ──

"""Atomic diff application with rollback for graq_edit.

Write protocol (copied from graqle.core.graph battle-tested pattern):
  1. Read original file
  2. Apply unified diff → new content
  3. Write new content to .tmp (same dir, same filesystem)
  4. fsync .tmp
  5. os.replace(.tmp, original)  ← near-atomic on all platforms
  6. If ANY step fails → restore from backup

Backup path: .graqle/edit-backup/{timestamp}_{filename}.bak
"""

from __future__ import annotations

import ast
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ApplyResult:
    """Result of applying a diff patch to a file."""

    success: bool
    lines_changed: int          # abs(lines_added + lines_removed)
    backup_path: str            # path to .bak file (empty if backup skipped)
    error: str                  # non-empty on failure
    file_path: str
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "lines_changed": self.lines_changed,
            "backup_path": self.backup_path,
            "error": self.error,
            "file_path": self.file_path,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _backup_path(file_path: Path) -> Path:
    """Return the .bak path for a file."""
    backup_dir = Path(".graqle") / "edit-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    return backup_dir / f"{ts}_{file_path.name}.bak"


def _write_backup(file_path: Path) -> str:
    """Write a backup of file_path. Returns the backup path string."""
    bak = _backup_path(file_path)
    bak.write_bytes(file_path.read_bytes())
    return str(bak)


# ---------------------------------------------------------------------------
# Diff parser
# ---------------------------------------------------------------------------

def _parse_unified_diff(unified_diff: str) -> list[tuple[str, str]]:
    """Parse a unified diff into a list of (operation, line) tuples.

    operation: '+' added, '-' removed, ' ' context
    Returns only the lines from the first hunk (simplified for Phase 1).
    """
    result: list[tuple[str, str]] = []
    in_hunk = False
    for line in unified_diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.append(("+", line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            result.append(("-", line[1:]))
        elif line.startswith(" "):
            result.append((" ", line[1:]))
    return result


def _apply_patch_to_lines(
    original_lines: list[str],
    diff_ops: list[tuple[str, str]],
) -> list[str]:
    """Apply parsed diff operations to original_lines.

    Uses a simple context-matching approach:
    - Walk through diff ops matching context (' ') lines to positions in original
    - Insert '+' lines, skip '-' lines
    """
    result: list[str] = []
    orig_idx = 0
    n = len(original_lines)

    for op, text in diff_ops:
        if op == " ":
            # Context line — advance original pointer until we find it
            while orig_idx < n:
                if original_lines[orig_idx].rstrip("\n") == text.rstrip("\n"):
                    result.append(original_lines[orig_idx])
                    orig_idx += 1
                    break
                else:
                    # Original line not in diff — keep it (handles files with more context)
                    result.append(original_lines[orig_idx])
                    orig_idx += 1
        elif op == "+":
            # Added line — append with newline
            result.append(text if text.endswith("\n") else text + "\n")
        elif op == "-":
            # Removed line — skip next matching original line
            while orig_idx < n:
                if original_lines[orig_idx].rstrip("\n") == text.rstrip("\n"):
                    orig_idx += 1
                    break
                orig_idx += 1

    # Append any remaining original lines not covered by the diff
    result.extend(original_lines[orig_idx:])
    return result


# ---------------------------------------------------------------------------
# Syntax validation
# ---------------------------------------------------------------------------

def _validate_python_syntax(content: str, file_path: Path) -> str | None:
    """Return error string if Python syntax is invalid, else None."""
    if file_path.suffix != ".py":
        return None
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return f"SyntaxError in generated content: {e}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_diff(
    file_path: Path,
    unified_diff: str,
    *,
    dry_run: bool = True,
    skip_syntax_check: bool = False,
) -> ApplyResult:
    """Apply a unified diff to file_path atomically.

    Parameters
    ----------
    file_path:
        Target file. Must exist (Phase 1 — creating new files is Phase 2+).
    unified_diff:
        Standard unified diff string (output of graq_generate).
    dry_run:
        If True, validate and return result WITHOUT writing. Default True.
    skip_syntax_check:
        If True, skip Python AST validation of the result.

    Returns
    -------
    ApplyResult — success/failure, backup path, error message.
    """
    fp = Path(file_path)

    if not fp.exists():
        return ApplyResult(
            success=False,
            lines_changed=0,
            backup_path="",
            error=f"File not found: {fp}",
            file_path=str(fp),
            dry_run=dry_run,
        )

    if not unified_diff.strip():
        return ApplyResult(
            success=False,
            lines_changed=0,
            backup_path="",
            error="unified_diff is empty",
            file_path=str(fp),
            dry_run=dry_run,
        )

    # Parse + apply
    try:
        original_content = fp.read_text(encoding="utf-8")
        original_lines = original_content.splitlines(keepends=True)
        diff_ops = _parse_unified_diff(unified_diff)

        if not diff_ops:
            return ApplyResult(
                success=False,
                lines_changed=0,
                backup_path="",
                error="Diff has no hunks — nothing to apply",
                file_path=str(fp),
                dry_run=dry_run,
            )

        new_lines = _apply_patch_to_lines(original_lines, diff_ops)
        new_content = "".join(new_lines)

        lines_added = sum(1 for op, _ in diff_ops if op == "+")
        lines_removed = sum(1 for op, _ in diff_ops if op == "-")
        lines_changed = lines_added + lines_removed

        # Syntax check (Python only)
        if not skip_syntax_check:
            syntax_err = _validate_python_syntax(new_content, fp)
            if syntax_err:
                return ApplyResult(
                    success=False,
                    lines_changed=lines_changed,
                    backup_path="",
                    error=syntax_err,
                    file_path=str(fp),
                    dry_run=dry_run,
                )

        if dry_run:
            return ApplyResult(
                success=True,
                lines_changed=lines_changed,
                backup_path="",
                error="",
                file_path=str(fp),
                dry_run=True,
            )

        # --- WRITE PATH (dry_run=False only) ---
        backup_path = _write_backup(fp)

        tmp_path: str | None = None
        try:
            dir_path = str(fp.parent) or "."
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=dir_path, suffix=".tmp", delete=False,
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(new_content)
                tmp.flush()
                os.fsync(tmp.fileno())

            # Atomic rename (POSIX) / near-atomic (Windows)
            os.replace(tmp_path, str(fp))
            tmp_path = None  # rename succeeded

        except Exception as write_exc:
            # Rollback from backup
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            try:
                bak = Path(backup_path)
                if bak.exists():
                    bak.replace(fp)
            except Exception:
                pass
            return ApplyResult(
                success=False,
                lines_changed=lines_changed,
                backup_path=backup_path,
                error=f"Write failed (rolled back from backup): {write_exc}",
                file_path=str(fp),
                dry_run=False,
            )

        return ApplyResult(
            success=True,
            lines_changed=lines_changed,
            backup_path=backup_path,
            error="",
            file_path=str(fp),
            dry_run=False,
        )

    except Exception as exc:
        return ApplyResult(
            success=False,
            lines_changed=0,
            backup_path="",
            error=f"Unexpected error: {exc}",
            file_path=str(fp),
            dry_run=dry_run,
        )
