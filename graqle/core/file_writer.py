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
    created: bool = False       # GH-67: True when a new file was created from /dev/null diff

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "lines_changed": self.lines_changed,
            "backup_path": self.backup_path,
            "error": self.error,
            "file_path": self.file_path,
            "dry_run": self.dry_run,
            "created": self.created,
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


class DiffApplicationError(Exception):
    """Raised when a diff cannot be applied correctly to the target file."""
    pass


def _apply_patch_to_lines(
    original_lines: list[str],
    diff_ops: list[tuple[str, str]],
    *,
    context_match_threshold: float = 0.5,
    max_gap: int = 0,
) -> list[str]:
    """Apply parsed diff operations to original_lines.

    Single-pass design: scans forward through original_lines matching context
    and delete lines, inserting additions, tracking match positions for
    validation. All validation happens inline before any irreversible mutation.

    - fix: track context match rate and FAIL if too many mismatches
      (previously silently appended code at EOF on mismatch)
    - hardening: track match positions and validate positional coherence
      to catch greedy forward-scan mis-matches on duplicate/similar lines.

    Parameters
    ----------
    context_match_threshold:
        Minimum fraction of context lines that must match, in (0.0, 1.0].
        Default 0.5 — at least half the context lines must be found.
    max_gap:
        Maximum allowed gap between consecutive matched positions (context +
        delete lines). Default 0 means auto: max(50, len(original_lines)//5).
    """
    # --- Input validation ---
    if not 0.0 < context_match_threshold <= 1.0:
        raise ValueError(
            f"context_match_threshold must be in (0.0, 1.0], got {context_match_threshold}"
        )
    if max_gap < 0:
        raise ValueError(f"max_gap must be >= 0, got {max_gap}")

    n = len(original_lines)
    effective_max_gap = max_gap if max_gap > 0 else max(50, n // 5)

    # --- Single pass: match, validate, and build result simultaneously ---
    result: list[str] = []
    orig_idx = 0
    context_total = 0
    context_matched = 0
    match_positions: list[int] = []  # positions of ALL matched ' ' and '-' lines

    for op, text in diff_ops:
        if op == " ":
            context_total += 1
            # Context line — advance original pointer until we find it
            found = False
            while orig_idx < n:
                if original_lines[orig_idx].rstrip("\n") == text.rstrip("\n"):
                    result.append(original_lines[orig_idx])
                    match_positions.append(orig_idx)
                    orig_idx += 1
                    context_matched += 1
                    found = True
                    break
                else:
                    # Original line not in diff — keep it
                    result.append(original_lines[orig_idx])
                    orig_idx += 1
            if not found:
                # Context line not found — tracked for threshold check below
                pass
        elif op == "+":
            # Added line — append with newline
            result.append(text if text.endswith("\n") else text + "\n")
        elif op == "-":
            # Removed line — find and skip it, keeping intervening lines
            found = False
            while orig_idx < n:
                if original_lines[orig_idx].rstrip("\n") == text.rstrip("\n"):
                    match_positions.append(orig_idx)
                    orig_idx += 1
                    found = True
                    break
                else:
                    # Keep non-matching lines between edits
                    result.append(original_lines[orig_idx])
                    orig_idx += 1
            if not found:
                raise DiffApplicationError(
                    f"Diff delete line not found in original file: {text.rstrip()!r}. "
                    f"The diff was generated against a different version of the file."
                )

    # --- Post-loop validation (on the SAME positions used to build result) ---

    # fix: check context match rate
    if context_total > 0:
        match_rate = context_matched / context_total
        if match_rate < context_match_threshold:
            raise DiffApplicationError(
                f"Diff context mismatch: only {context_matched}/{context_total} "
                f"context lines matched ({match_rate:.0%}). "
                f"The diff was likely generated without reading the actual file content. "
                f"Refusing to apply — this would append code at EOF instead of editing in place."
            )

    # hardening: positional coherence check
    # match_positions is strictly monotone (single forward scan guarantees this)
    if len(match_positions) >= 2:
        gaps = [
            match_positions[i + 1] - match_positions[i]
            for i in range(len(match_positions) - 1)
        ]
        largest_gap = max(gaps)
        if largest_gap > effective_max_gap:
            pos_display = match_positions[:10]
            suffix = f"... ({len(match_positions)} total)" if len(match_positions) > 10 else ""
            raise DiffApplicationError(
                f"Diff context lines matched at non-contiguous positions "
                f"(max gap: {largest_gap} lines, allowed: {effective_max_gap}). "
                f"Matched positions: {pos_display}{suffix}. "
                f"The diff likely matched wrong occurrences of similar lines."
            )

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
        # GH-67 Fix 1: Support creating new files from /dev/null diffs
        # Only check header lines (before first @@) to avoid false positives
        _diff_lines = unified_diff.splitlines()
        _header_lines = []
        for _hl in _diff_lines:
            if _hl.startswith("@@"):
                break
            _header_lines.append(_hl)
        _is_new_file = any(line.strip() == "--- /dev/null" for line in _header_lines)

        if _is_new_file:
            # CWE-22: Path traversal containment — reject paths outside CWD
            _resolved = fp.resolve()
            _project_root = Path.cwd().resolve()
            try:
                _resolved.relative_to(_project_root)
            except ValueError:
                return ApplyResult(
                    success=False,
                    lines_changed=0,
                    backup_path="",
                    error=f"Path traversal rejected: {_resolved} is outside {_project_root}",
                    file_path=str(fp),
                    dry_run=dry_run,
                )

            # Parse added lines — handle CRLF, skip no-newline markers
            _no_newline_at_eof = any(
                line.startswith("\\ No newline") for line in _diff_lines
            )
            added_lines = [
                line[1:].rstrip("\r")
                for line in _diff_lines
                if line.startswith("+") and not line.startswith("+++")
            ]
            lines_changed = len(added_lines)
            if dry_run:
                return ApplyResult(
                    success=True,
                    lines_changed=lines_changed,
                    backup_path="",
                    error="",
                    file_path=str(fp),
                    dry_run=True,
                    created=True,
                )
            # Create parent dirs + atomic write
            fp.parent.mkdir(parents=True, exist_ok=True)
            new_content = "\n".join(added_lines)
            if added_lines and not _no_newline_at_eof:
                new_content += "\n"
            try:
                _tmp = tempfile.NamedTemporaryFile(
                    dir=fp.parent, delete=False, suffix=".tmp", mode="w",
                    encoding="utf-8",
                )
                _tmp.write(new_content)
                _tmp.close()
                os.replace(_tmp.name, str(fp))  # atomic on POSIX; best-effort same-volume Windows
            except Exception:
                try:
                    os.unlink(_tmp.name)
                except OSError:
                    pass
                raise
            return ApplyResult(
                success=True,
                lines_changed=lines_changed,
                backup_path="",
                error="",
                file_path=str(fp),
                dry_run=False,
                created=True,
            )

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

        try:
            new_lines = _apply_patch_to_lines(original_lines, diff_ops)
        except DiffApplicationError as e:
            return ApplyResult(
                success=False,
                lines_changed=0,
                backup_path="",
                error=str(e),
                file_path=str(fp),
                dry_run=dry_run,
            )
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
