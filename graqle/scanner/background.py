"""Background document scan manager.

Runs document scanning in a daemon thread with progress tracking via a
JSON state file.  Designed for ``graq scan all`` (background doc scan)
and ``graq scan docs --background``.

The state file (``.graqle-scan-state.json``) is written after each file
so that ``graq scan status`` / ``graq scan wait`` can report progress
from a separate CLI invocation.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.background
# risk: MEDIUM (impact radius: 1 modules)
# consumers: test_background
# dependencies: a, __future__, calendar, json, logging +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import calendar
import json
import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scanner.background")

_STATE_FILE_NAME = ".graqle-scan-state.json"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class ScanProgress:
    """Snapshot of background scan progress.

    Attributes
    ----------
    status:
        One of ``"idle"``, ``"running"``, ``"completed"``,
        ``"failed"``, ``"cancelled"``.
    total:
        Total number of files to process.
    processed:
        Number of files processed so far.
    current_file:
        Path of the file currently being processed.
    started_at:
        ISO-8601 timestamp when the scan started.
    completed_at:
        ISO-8601 timestamp when the scan finished (or ``""``).
    nodes_added:
        Number of graph nodes added so far.
    edges_added:
        Number of graph edges added so far.
    errors:
        List of error messages.
    duration_seconds:
        Elapsed time in seconds.
    """

    status: str = "idle"
    total: int = 0
    processed: int = 0
    current_file: str = ""
    started_at: str = ""
    completed_at: str = ""
    nodes_added: int = 0
    edges_added: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class BackgroundScanManager:
    """Manages background document scans with progress tracking.

    Parameters
    ----------
    state_dir:
        Directory where the state file is written (typically the project
        root or graph directory).
    """

    def __init__(self, state_dir: str | Path) -> None:
        self._state_dir = Path(state_dir)
        self._state_path = self._state_dir / _STATE_FILE_NAME
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._progress = ScanProgress()

    # -- State persistence ---------------------------------------------------

    def _write_state(self) -> None:
        """Persist current progress to the state file."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            data = json.dumps(asdict(self._progress), indent=2, default=str)
            # Write-then-flush to avoid partial writes on Windows
            with open(self._state_path, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                try:
                    import os
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except OSError as exc:
            logger.warning("Failed to write scan state: %s", exc)

    def _read_state(self) -> ScanProgress:
        """Read progress from the state file."""
        if not self._state_path.is_file():
            return ScanProgress()
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return ScanProgress(**{k: v for k, v in data.items()
                                   if k in ScanProgress.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Corrupt scan state: %s", exc)
            return ScanProgress()

    # -- Public API ----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Return ``True`` if a background scan is currently in progress."""
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        scanner_fn: Callable[[Callable[[Path, int, int], None]], Any],
        total_files: int,
    ) -> None:
        """Launch a background scan in a daemon thread.

        Parameters
        ----------
        scanner_fn:
            A callable that accepts a progress callback
            ``(file_path, index, total) -> None`` and performs the actual
            scanning.  It should return a result object with
            ``nodes_added`` and ``edges_added`` attributes.
        total_files:
            Total number of files that will be scanned (for progress %).
        """
        if self.is_running:
            raise RuntimeError("A background scan is already running.")

        self._cancel_event.clear()
        self._progress = ScanProgress(
            status="running",
            total=total_files,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._write_state()

        def _run() -> None:
            try:
                def progress_cb(path: Path, idx: int, total: int) -> None:
                    if self._cancel_event.is_set():
                        raise _CancelledError("Scan cancelled by user.")
                    self._progress.current_file = str(path)
                    self._progress.processed = idx
                    self._write_state()

                result = scanner_fn(progress_cb)

                self._progress.status = "completed"
                self._progress.processed = self._progress.total
                self._progress.nodes_added = getattr(result, "nodes_added", 0)
                self._progress.edges_added = getattr(result, "edges_added", 0)
                self._progress.completed_at = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
            except _CancelledError:
                self._progress.status = "cancelled"
            except Exception as exc:
                self._progress.status = "failed"
                err_msg = f"{type(exc).__name__}: {exc}"
                self._progress.errors.append(err_msg)
                logger.exception("Background scan failed: %s", err_msg)
            finally:
                t1 = time.time()
                # Parse started_at back to compute duration
                try:
                    t0 = calendar.timegm(time.strptime(
                        self._progress.started_at, "%Y-%m-%dT%H:%M:%SZ"
                    ))
                    self._progress.duration_seconds = t1 - t0
                except (ValueError, OverflowError):
                    pass
                self._write_state()

        # On Windows, daemon threads with file I/O can be killed mid-write
        # when the main process exits, causing hangs or corrupt state files.
        # Use non-daemon threads on Windows so the thread completes safely.
        is_windows = sys.platform == "win32"
        self._thread = threading.Thread(
            target=_run, daemon=not is_windows, name="graqle-doc-scan",
        )
        self._thread.start()

    def get_progress(self) -> ScanProgress:
        """Return current scan progress.

        If called from a different process (e.g. ``graq scan status``),
        reads from the state file.  If called from the same process,
        returns the in-memory progress.
        """
        if self.is_running:
            return self._progress
        return self._read_state()

    def cancel(self) -> None:
        """Request cancellation of the running scan.

        The scan thread checks this flag between files and will stop
        at the next opportunity.
        """
        self._cancel_event.set()
        # Also write cancel request to state file for cross-process
        progress = self._read_state()
        if progress.status == "running":
            progress.status = "cancelled"
            self._progress = progress
            self._write_state()

    def wait(self, timeout: float | None = None) -> ScanProgress:
        """Block until the background scan completes.

        Parameters
        ----------
        timeout:
            Max seconds to wait.  ``None`` = wait forever.

        Returns
        -------
        ScanProgress
            Final progress snapshot.
        """
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self.get_progress()

    def cleanup(self) -> None:
        """Remove the state file."""
        try:
            self._state_path.unlink(missing_ok=True)
        except OSError:
            pass


class _CancelledError(Exception):
    """Internal: raised when the cancel event is set."""
