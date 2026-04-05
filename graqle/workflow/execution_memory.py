# graqle/workflow/execution_memory.py
"""
ExecutionMemory: filesystem state tracking across LoopController attempts.

Wraps file_writer.py atomic primitives without modifying that module.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.workflow.execution_memory")


@dataclass
class FileSnapshot:
    path: str
    content_hash: str
    size_bytes: int
    exists: bool


@dataclass
class MemoryEntry:
    attempt: int
    diff_applied: str
    result_exit_code: int
    test_output: str
    modified_files: list[str]
    error_message: str = ""
    snapshots_before: dict[str, FileSnapshot] = field(default_factory=dict)
    snapshots_after: dict[str, FileSnapshot] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "diff_len": len(self.diff_applied),
            "result_exit_code": self.result_exit_code,
            "test_output_len": len(self.test_output),
            "modified_files": self.modified_files,
            "error_message": self.error_message,
            "files_changed": [
                p for p in self.modified_files
                if self.snapshots_before.get(p) != self.snapshots_after.get(p)
            ],
        }


class ExecutionMemory:
    """
    Tracks filesystem state across LoopController iterations.
    Provides error context for FIX->GENERATE re-entry and rollback support.
    """

    def __init__(self, working_dir: str | Path) -> None:
        self._working_dir = Path(working_dir)
        self._history: list[MemoryEntry] = []

    @property
    def working_dir(self) -> Path:
        return self._working_dir

    @property
    def history(self) -> list[MemoryEntry]:
        return list(self._history)

    @property
    def attempt_count(self) -> int:
        return len(self._history)

    # -- Snapshot ---------------------------------------------------------------

    def snapshot(self, paths: list[str]) -> dict[str, FileSnapshot]:
        """Capture current content hashes for the given relative paths."""
        snaps: dict[str, FileSnapshot] = {}
        for rel in paths:
            p = self._working_dir / rel
            if p.exists():
                content = p.read_bytes()
                snaps[rel] = FileSnapshot(
                    path=rel,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    exists=True,
                )
            else:
                snaps[rel] = FileSnapshot(
                    path=rel, content_hash="", size_bytes=0, exists=False
                )
        return snaps

    def changed_since_snapshot(
        self, paths: list[str], baseline: dict[str, FileSnapshot]
    ) -> list[str]:
        """Return paths whose content differs from the baseline snapshot."""
        changed: list[str] = []
        for rel in paths:
            p = self._working_dir / rel
            current_hash = (
                hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""
            )
            snap = baseline.get(rel)
            if snap is None or snap.content_hash != current_hash:
                changed.append(rel)
        return changed

    # -- History ----------------------------------------------------------------

    def record(
        self,
        *,
        attempt: int,
        diff_applied: str,
        result_exit_code: int,
        test_output: str,
        modified_files: list[str],
        error_message: str = "",
        snapshots_before: dict[str, FileSnapshot] | None = None,
        snapshots_after: dict[str, FileSnapshot] | None = None,
    ) -> MemoryEntry:
        """Record an iteration's results for diagnosis and context."""
        entry = MemoryEntry(
            attempt=attempt,
            diff_applied=diff_applied,
            result_exit_code=result_exit_code,
            test_output=test_output,
            modified_files=modified_files,
            error_message=error_message,
            snapshots_before=snapshots_before or {},
            snapshots_after=snapshots_after or {},
        )
        self._history.append(entry)
        logger.info(
            "ExecutionMemory: recorded attempt=%d, exit_code=%d, files=%d",
            attempt,
            result_exit_code,
            len(modified_files),
        )
        return entry

    def error_context_for_retry(self) -> str:
        """Build error context string for the FIX->GENERATE re-entry."""
        if not self._history:
            return ""

        last = self._history[-1]
        parts = [
            f"Attempt {last.attempt} failed (exit_code={last.result_exit_code}).",
        ]
        if last.error_message:
            parts.append(f"Error: {last.error_message}")
        if last.test_output:
            # Truncate test output to last 2000 chars for LLM context
            truncated = last.test_output[-2000:]
            parts.append(f"Test output (last 2000 chars):\n{truncated}")
        if last.modified_files:
            parts.append(f"Files modified: {', '.join(last.modified_files)}")

        return "\n".join(parts)

    def summary(self) -> dict[str, Any]:
        """Return a summary of all recorded iterations."""
        return {
            "total_attempts": len(self._history),
            "working_dir": str(self._working_dir),
            "entries": [e.to_dict() for e in self._history],
        }

    def clear(self) -> None:
        """Reset memory (e.g., for a new task)."""
        self._history.clear()
