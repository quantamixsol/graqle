# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Append-Only Governed Trace Store (R18 ADR-201).

Persists GovernedTrace records to JSONL (JSON Lines) files with
append-only semantics. Historical traces are never mutated.

Trace corpus growth is monotonic: T(n+1) = T(n) U {t_n}
Retrieval quality is non-decreasing: R(T(n+1)) >= R(T(n))

The store writes to .graqle/traces/{YYYY-MM-DD}.jsonl with daily rotation.
KG ingestion is triggered asynchronously after each append.

TS-2 Gate: Trace files contain governance_decisions (internal IP).
Store files must not be committed to public repositories.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from graqle.governance.trace_schema import GovernedTrace

logger = logging.getLogger("graqle.governance.trace_store")

# Default trace directory relative to project root
_DEFAULT_TRACE_DIR = ".graqle/traces"


class TraceStore:
    """Append-only trace persistence with daily file rotation.

    Each day's traces go into a separate JSONL file:
        .graqle/traces/2026-04-09.jsonl

    Traces are serialized using to_internal_dict() (includes governance_decisions).
    Files are opened in append mode -- never truncated or overwritten.

    Parameters
    ----------
    trace_dir:
        Directory for JSONL trace files. Created if missing.
    on_trace:
        Optional callback invoked after each successful append.
        Signature: (trace: GovernedTrace) -> None.
        Use for KG ingestion hooks.
    """

    def __init__(
        self,
        trace_dir: str | Path | None = None,
        on_trace: Callable[[GovernedTrace], None] | None = None,
    ) -> None:
        if trace_dir is None:
            trace_dir = _DEFAULT_TRACE_DIR
        self._trace_dir = Path(trace_dir)
        self._on_trace = on_trace
        self._count = 0
        # Ensure directory exists
        self._trace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def trace_dir(self) -> Path:
        """Path to the trace storage directory."""
        return self._trace_dir

    @property
    def count(self) -> int:
        """Number of traces appended in this session."""
        return self._count

    def _current_file(self) -> Path:
        """Get the JSONL file path for today (UTC)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._trace_dir / f"{today}.jsonl"

    async def append(self, trace: GovernedTrace) -> None:
        """Append a trace record to the daily JSONL file.

        This is the primary write path. It:
        1. Serializes the trace using to_internal_dict()
        2. Appends one JSON line to the daily file
        3. Increments the session counter
        4. Invokes the on_trace callback (if set)

        The write is performed in a thread executor to avoid
        blocking the async event loop.
        """
        line = json.dumps(trace.to_internal_dict(), default=str) + "\n"
        file_path = self._current_file()

        # Write in executor to keep async non-blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_append, file_path, line)

        self._count += 1
        logger.debug("Trace appended: %s (total: %d)", trace.tool_name, self._count)

        # Fire callback (best-effort, non-blocking)
        if self._on_trace is not None:
            try:
                self._on_trace(trace)
            except Exception:
                logger.warning("on_trace callback failed", exc_info=True)

    @staticmethod
    def _sync_append(file_path: Path, line: str) -> None:
        """Synchronous append with fsync for durability."""
        fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_traces(
        self,
        date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read traces from a daily JSONL file.

        Parameters
        ----------
        date:
            ISO date string (YYYY-MM-DD). Defaults to today (UTC).
        limit:
            Maximum number of traces to return (most recent first).

        Returns
        -------
        List of trace dicts (internal format including governance_decisions).
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        file_path = self._trace_dir / f"{date}.jsonl"
        if not file_path.exists():
            return []

        traces: list[dict[str, Any]] = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Corrupt trace line in %s", file_path)
                    continue

        # Return most recent first, limited
        return traces[-limit:][::-1]

    def corpus_size(self) -> int:
        """Count total traces across all daily files.

        This scans all .jsonl files in the trace directory.
        Used for AC-3 verification (monotonic growth).
        """
        total = 0
        for jsonl_file in self._trace_dir.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                total += sum(1 for line in f if line.strip())
        return total

    def list_dates(self) -> list[str]:
        """List all dates that have trace files, sorted ascending."""
        dates = []
        for jsonl_file in sorted(self._trace_dir.glob("*.jsonl")):
            stem = jsonl_file.stem  # "2026-04-09"
            dates.append(stem)
        return dates
