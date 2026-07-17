"""Warn-only usage meter — CR-LIC-01 (ADR-244).

Persists a per-project **high-water mark** of graph node count in
``.graqle/meter.json`` and reports where the current count sits relative to the
resolved :class:`~graqle.licensing.limits.EffectiveLimits`.

Design constraints (constitutional for this CR):

* **Never blocks, never raises out of** :meth:`UsageMeter.record` — this CR is
  telemetry + messaging only. Enforcement arrives in CR-LIC-03 behind the
  ``GRAQLE_ENFORCE_CAPS`` environment flag (reserved here, intentionally
  unread).
* **High-water mark, not current count** — deleting nodes or re-scanning a
  pruned tree does not lower the recorded peak, so the meter cannot be gamed
  by shrink-then-grow cycles.
* **Corruption-tolerant** — a damaged meter file is treated as empty and
  rewritten; a read-only filesystem degrades to in-memory readings. In the
  warn-only phase, metering failure must never break a scan.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from graqle.licensing.limits import EffectiveLimits

logger = logging.getLogger("graqle.licensing.meter")

__all__ = ["ENFORCE_ENV", "METER_FILENAME", "MeterStatus", "MeterReading", "UsageMeter"]

# Reserved for CR-LIC-03 enforcement. This module never reads it.
ENFORCE_ENV = "GRAQLE_ENFORCE_CAPS"

METER_FILENAME = "meter.json"
_SCHEMA_VERSION = 1


class MeterStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"          # >= warn threshold (80% of cap by default)
    AT_CAP = "AT_CAP"      # >= cap (informational only in CR-LIC-01)


@dataclass(frozen=True)
class MeterReading:
    status: MeterStatus
    node_count: int
    high_water_mark: int
    max_nodes: int | None

    @property
    def percent_used(self) -> int | None:
        """Whole-percent usage of the cap, or ``None`` when uncapped."""
        if not self.max_nodes:
            return None
        return int(self.node_count / self.max_nodes * 100)


class UsageMeter:
    """High-water-mark meter persisted under a project's ``.graqle`` directory."""

    def __init__(self, graqle_dir: Path | str):
        self._path = Path(graqle_dir) / METER_FILENAME

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
        except (OSError, ValueError):
            return {}

    def _store(self, data: dict) -> None:
        """Atomic write (tmpfile → fsync → replace). Failures are logged, not raised."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".meter-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except OSError as exc:
            logger.debug("meter persistence skipped: %s", exc)

    def _ensure_gitignore(self) -> None:
        """Self-ignore the meter file so it never lands in shared-repo diffs.

        Only creates ``.gitignore`` when the directory has none — an existing
        file (user-managed) is never touched.
        """
        try:
            gi = self._path.parent / ".gitignore"
            if not gi.exists():
                gi.write_text("meter.json\n", encoding="utf-8")
        except OSError as exc:
            logger.debug("meter gitignore skipped: %s", exc)

    # -- public API --------------------------------------------------------

    @property
    def high_water_mark(self) -> int:
        raw = self._load().get("high_water_mark", 0)
        return raw if isinstance(raw, int) and raw >= 0 else 0

    def record(self, node_count: int, limits: EffectiveLimits) -> MeterReading:
        """Record ``node_count``, advance the high-water mark, classify status.

        Never raises. Warn-only: callers may print the status but nothing in
        this CR blocks on it.
        """
        try:
            count = max(0, int(node_count))
        except (TypeError, ValueError):
            count = 0

        prev_hwm = self.high_water_mark
        hwm = max(prev_hwm, count)
        # Write only when the high-water mark advances (or on first record):
        # a scan that changes nothing must not dirty a committed working tree
        # (shared-repo diff churn — CR-LIC-01 pre-merge debate, point 3).
        if hwm > prev_hwm or not self._path.exists():
            self._store(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "high_water_mark": hwm,
                    "last_node_count": count,
                    "limit_source": limits.source,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._ensure_gitignore()

        if limits.unlimited:
            status = MeterStatus.OK
        elif count >= (limits.max_nodes or 0):
            status = MeterStatus.AT_CAP
        else:
            warn_at = limits.warn_threshold()
            status = (
                MeterStatus.WARN
                if warn_at is not None and count >= warn_at
                else MeterStatus.OK
            )
        return MeterReading(
            status=status,
            node_count=count,
            high_water_mark=hwm,
            max_nodes=limits.max_nodes,
        )
