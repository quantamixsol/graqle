"""Scheduler-grade CLI contract — exit codes and machine-readable run reports.

CR-010.R6. Enterprise schedulers (cron, Airflow/DAG platforms, CI runners) drive
GraQle unattended. They cannot read rich text: they branch on the **exit code** and
parse a **JSON run report**. This module is the single place both are defined, so
every command that opts in speaks one contract.

The contract
------------
=====  ===================================================================
Code   Meaning
=====  ===================================================================
0      SUCCESS      — the command ran and *work was performed*
1      FAILURE      — a hard error; the step did not complete
2      USAGE        — the invocation itself was wrong (bad flags, no TTY)
3      EMPTY_DELTA  — the command ran, there was *nothing to do*, no error
=====  ===================================================================

``EMPTY_DELTA`` is deliberately distinct from ``SUCCESS``. R6's acceptance
criterion is that "a failed step is distinguishable from an empty delta by exit
code alone"; collapsing both onto 0 would also make "did work actually happen?"
unanswerable without parsing stdout, which defeats the point of an exit-code
contract (a scheduler cannot gate a downstream deploy on "the graph changed").

Design notes
------------
* ``exit_code`` is **derived** from ``status`` (never set independently), so the
  two can never disagree inside a serialized report.
* Reports are PII-safe by construction: ``errors`` carries exception **type**
  names only — never messages, paths, or credential material. This mirrors the
  rule already enforced on ``.graqle/govern.health.json``
  (``govern_serve.py`` — "counts, ticks, queue depth, exception TYPE names").
* ``--report-json`` writes atomically (tempfile in the destination directory +
  ``os.replace``) and cleans up an orphaned tempfile on failure — the same
  pattern the governance health snapshot uses, for the same reason: a scheduler
  must never read a half-written file.
"""

# ── graqle:intelligence ──
# module: graqle.cli.headless
# risk: LOW (new module; no existing consumers)
# consumers: cli.commands.rebuild, cli.commands.govern_serve
# dependencies: __future__, dataclasses, datetime, enum, json, os, sys, tempfile
# constraints: report payloads must stay PII-safe (exception type names only)
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, NoReturn

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "ExitCode",
    "RunReport",
    "RunStatus",
    "HeadlessPromptError",
    "emit_and_exit",
    "guard_no_prompt",
    "utc_now_iso",
]

#: Report schema version. Matches the existing SDK idiom (``compliance.py`` emits
#: ``"schema_version": "1"``). Bump only on a breaking payload change.
REPORT_SCHEMA_VERSION = "1"


class ExitCode(IntEnum):
    """Process exit codes for scheduler-driven invocations."""

    SUCCESS = 0
    FAILURE = 1
    USAGE = 2
    EMPTY_DELTA = 3


class RunStatus(str, Enum):
    """Outcome of a run. ``ExitCode`` is derived from this — never set directly."""

    SUCCESS = "success"
    EMPTY_DELTA = "empty_delta"
    FAILURE = "failure"
    USAGE_ERROR = "usage_error"

    @property
    def exit_code(self) -> ExitCode:
        """The exit code this status maps to. Total function — no default branch."""
        return _STATUS_TO_EXIT[self]


_STATUS_TO_EXIT: dict[RunStatus, ExitCode] = {
    RunStatus.SUCCESS: ExitCode.SUCCESS,
    RunStatus.EMPTY_DELTA: ExitCode.EMPTY_DELTA,
    RunStatus.FAILURE: ExitCode.FAILURE,
    RunStatus.USAGE_ERROR: ExitCode.USAGE,
}


class HeadlessPromptError(RuntimeError):
    """Raised when a code path would prompt while running under ``--headless``.

    Scheduler runs have no TTY. Blocking on input would hang the job until the
    platform's timeout fires, which reads as a stall rather than a failure. We
    fail fast with ``USAGE`` instead.
    """


def utc_now_iso() -> str:
    """Timezone-aware UTC timestamp, ISO-8601, second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class RunReport:
    """A machine-readable record of one command invocation.

    Frozen: a report describes a run that already happened, so it is a value
    object. Build it once at the end of the run and hand it to
    :func:`emit_and_exit`.
    """

    command: str
    status: RunStatus
    started_at: str
    duration_s: float
    counters: Mapping[str, int] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    schema_version: str = REPORT_SCHEMA_VERSION

    @property
    def exit_code(self) -> ExitCode:
        """Derived from :attr:`status`. Cannot disagree with it."""
        return self.status.exit_code

    def to_dict(self) -> dict[str, Any]:
        """Serializable payload. Key order is stable for golden-file tests."""
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "status": self.status.value,
            "exit_code": int(self.exit_code),
            "started_at": self.started_at,
            "duration_s": round(float(self.duration_s), 3),
            "counters": {str(k): int(v) for k, v in sorted(self.counters.items())},
            "errors": list(self.errors),
        }

    def to_json(self) -> str:
        """Compact-but-readable JSON. ``sort_keys=False`` preserves :meth:`to_dict` order."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)


def guard_no_prompt(headless: bool, what: str) -> None:
    """Refuse to prompt under ``--headless``.

    Call this immediately before any interactive read. ``rebuild`` and
    ``govern serve`` have no prompts today, so this is a forward-looking guard:
    it makes a future prompt fail loudly in CI instead of hanging a scheduled job.
    """
    if headless:
        raise HeadlessPromptError(
            f"{what} requires interactive input, which is unavailable under --headless"
        )


def _write_report_atomically(report: RunReport, destination: Path) -> None:
    """Write *report* to *destination* atomically.

    Tempfile lives in the destination directory so ``os.replace`` is atomic on
    every platform (a cross-device rename is not). An orphaned tempfile is
    removed on failure so repeated errors cannot fill the directory.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as fh:
            fh.write(report.to_json())
            tmp_path = fh.name
        os.replace(tmp_path, destination)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def emit_and_exit(
    report: RunReport,
    *,
    json_out: bool = False,
    report_path: Path | str | None = None,
) -> NoReturn:
    """Emit *report* per the caller's flags, then exit with its derived code.

    ``json_out`` and ``report_path`` are independent: stdout JSON is for a
    scheduler reading the pipe, the file is for one archiving the artefact.

    A failure to persist the report never masks the run's own outcome — the
    write error is surfaced on stderr and the original exit code still stands.
    A scheduler must see why the *step* failed, not why the bookkeeping did.
    """
    import typer

    if json_out:
        sys.stdout.write(report.to_json() + "\n")
        sys.stdout.flush()

    if report_path is not None:
        try:
            _write_report_atomically(report, Path(report_path))
        except OSError as exc:
            sys.stderr.write(
                f"warning: could not write run report to {report_path}: "
                f"{type(exc).__name__}\n"
            )

    raise typer.Exit(int(report.exit_code))
