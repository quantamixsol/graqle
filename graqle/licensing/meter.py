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

__all__ = [
    "ENFORCE_ENV",
    "GRACE_ENV",
    "METER_FILENAME",
    "MeterStatus",
    "MeterReading",
    "NodeCapExceeded",
    "UsageMeter",
    "enforcement_enabled",
]

# CR-LIC-03a hard enforcement (ADR-245). Enforcement is ON BY DEFAULT — this env
# var is an OPT-OUT for our own CI/tests only (set to a falsy value). "User must
# set a flag to be enforced" would be a trivial bypass and is deliberately rejected.
ENFORCE_ENV = "GRAQLE_ENFORCE_CAPS"
# Grace window (days) after a project FIRST hits the cap: the meter warns during
# grace, then blocks. Gives an existing user time to upgrade instead of a scan
# breaking on the day enforcement lands. Overridable for tests.
GRACE_ENV = "GRAQLE_ENFORCE_GRACE_DAYS"
_DEFAULT_GRACE_DAYS = 7

_FALSY = frozenset({"0", "false", "no", "off", ""})

METER_FILENAME = "meter.json"
_SCHEMA_VERSION = 1


class NodeCapExceeded(Exception):
    """Raised when a WRITE would push the graph past the plan's node cap.

    Carries the numbers so the CLI can render a clean upgrade message. Reads are
    NEVER blocked — only operations that would GROW the graph past the cap.
    """

    def __init__(self, node_count: int, max_nodes: int, plan_source: str) -> None:
        super().__init__(
            f"graph would reach {node_count:,} nodes, over the "
            f"{max_nodes:,}-node cap on the current plan ({plan_source})"
        )
        self.node_count = node_count
        self.max_nodes = max_nodes
        self.plan_source = plan_source


def enforcement_enabled() -> bool:
    """True unless explicitly opted out via GRACE_ENV=falsy. Default: ON.

    ADR-245: enforcement is on by default; the env var only DISABLES it (for CI).
    """
    raw = os.environ.get(ENFORCE_ENV)
    if raw is None:
        return True  # default ON
    return raw.strip().lower() not in _FALSY


def _grace_days() -> int:
    raw = os.environ.get(GRACE_ENV)
    if raw:
        try:
            v = int(raw)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    return _DEFAULT_GRACE_DAYS


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
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "high_water_mark": hwm,
                "last_node_count": count,
                "limit_source": limits.source,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # CR-LIC-03a: preserve the enforcement grace stamp across HWM writes —
            # a scan that advances the HWM must NOT reset the grace clock, or a user
            # could dodge the block forever by growing the graph one node at a time.
            existing = self._load()
            if existing.get("cap_first_hit_at"):
                payload["cap_first_hit_at"] = existing["cap_first_hit_at"]
            self._store(payload)
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

    def enforce(self, reading: MeterReading, limits: EffectiveLimits) -> None:
        """Hard-enforce the node cap on a WRITE (CR-LIC-03a, ADR-245). May raise.

        Contract:
          - Enforcement is ON BY DEFAULT (``enforcement_enabled()``); ``record`` itself
            still never raises — callers opt into hard-block by calling this.
          - Never blocks reads or uncapped tiers (unlimited → no-op).
          - Grace window: the FIRST time a project is AT_CAP we stamp
            ``cap_first_hit_at`` and WARN (do not raise); once the grace window has
            elapsed, subsequent AT_CAP writes raise :class:`NodeCapExceeded`.
          - High-water-mark based (via ``reading``): deleting nodes cannot dodge it.

        Raises
        ------
        NodeCapExceeded
            when enforcement is on, the tier is capped, the graph is AT_CAP, and the
            grace window has elapsed.
        """
        if not enforcement_enabled():
            return
        if limits.unlimited or limits.max_nodes is None:
            return
        if reading.status is not MeterStatus.AT_CAP:
            return

        now = datetime.now(timezone.utc)
        data = self._load()
        first_hit_raw = data.get("cap_first_hit_at")

        if not first_hit_raw:
            # First time at cap → start the grace window, warn (no raise this scan).
            data["cap_first_hit_at"] = now.isoformat()
            self._store(data)
            self._ensure_gitignore()
            return

        try:
            first_hit = datetime.fromisoformat(str(first_hit_raw))
            if first_hit.tzinfo is None:
                first_hit = first_hit.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            # Corrupt stamp → treat NOW as the start of grace (fail-open on grace,
            # not on the block: we never harden retroactively off a bad timestamp).
            # WARN so a surgical "reset only the grace clock" tamper leaves an audit
            # trail (MAJOR-1) — the accepted local-bypass class; server-side later.
            logger.warning(
                "meter: cap_first_hit_at was unparseable (%r) — restarting the grace "
                "window. If this recurs, the local meter may be being tampered with.",
                first_hit_raw,
            )
            data["cap_first_hit_at"] = now.isoformat()
            self._store(data)
            return

        grace_days = _grace_days()
        elapsed_days = (now - first_hit).total_seconds() / 86400.0
        if elapsed_days < grace_days:
            return  # still within grace — warn-only handled by the caller

        raise NodeCapExceeded(
            node_count=reading.node_count,
            max_nodes=limits.max_nodes,
            plan_source=limits.source,
        )
