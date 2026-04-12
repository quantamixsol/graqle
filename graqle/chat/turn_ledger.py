"""ChatAgentLoop v4 turn ledger .

TurnLedger is the immutable append-only audit log for chat turns. It lives
at ``.graqle/chat/ledger/turn_<id>.jsonl`` (one file per turn) and is
intentionally OUTSIDE the three-graph editorial rule (GRAQ.md / TCG / RCAG)
per — historical metadata is a plain log, not a graph.

Observable guarantees (the contract; do not over-couple to the
graqle.security.audit pattern):

- Durability: every ``append`` flushes and fsyncs before returning.
- Append-only: ``append`` never overwrites or rewrites existing lines.
- Fail-soft: file errors are logged via logger.warning and swallowed.
  Audit must never raise from inside the chat hot path. Reads return [].
- Thread-safe: all writes serialize through a per-instance Lock so
  concurrent producers cannot interleave lines.
- Crash recovery: ``read_turn`` skips malformed/truncated JSONL lines and
  continues; never raises on a corrupt tail.
- Deterministic ordering on read: each record carries a monotonic ``seq``
  field; ``read_turn`` sorts by seq so a crashed-then-recovered transcript
  reads in the same order it was written.

This module has zero dependencies on other graqle packages so it can be
imported in isolation by the chat package and by tests.
"""

# ── graqle:intelligence ──
# module: graqle.chat.turn_ledger
# risk: LOW (impact radius: 0 modules at # consumers: graqle.chat.agent_loop # dependencies: json, logging, threading, pathlib
# constraints: zero intra-graqle deps; fail-soft never-raise audit semantics
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

__all__ = ["TurnLedger"]

logger = logging.getLogger("graqle.chat.turn_ledger")

_DEFAULT_LEDGER_DIR = Path(".graqle") / "chat" / "ledger"


class TurnLedger:
    """Append-only JSONL audit log for chat turns.

    Each turn gets its own file at ``<base_dir>/turn_<turn_id>.jsonl``.
    Records are written one JSON object per line with a monotonic ``seq``
    field per turn so reads can deterministically reconstruct order even
    after a crash that left a malformed trailing line.

    Example:
        >>> ledger = TurnLedger(base_dir=Path("./.graqle/chat/ledger"))
        >>> ledger.append("turn-1", {"type": "user_message", "data": {"text": "hi"}})
        >>> ledger.read_turn("turn-1")
        [{'seq': 0, 'type': 'user_message', 'data': {'text': 'hi'}, 'logged_at': ...}]
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base = Path(base_dir) if base_dir is not None else _DEFAULT_LEDGER_DIR
        self._lock = threading.Lock()
        # Per-turn next-sequence allocator. Lazy: filled on first append for a turn.
        self._seq_counters: dict[str, int] = {}
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "TurnLedger cannot create base dir %s: %s", self._base, exc
            )

    @property
    def base_dir(self) -> Path:
        return self._base

    # ── public API ───────────────────────────────────────────────────

    def path_for(self, turn_id: str) -> Path:
        """Return the JSONL file path for a turn (does not create it)."""
        return self._base / f"turn_{turn_id}.jsonl"

    def append(self, turn_id: str, record: dict[str, Any]) -> int:
        """Append a record to the turn's ledger file. Returns the record's seq.

        Fail-soft: any IO/OS error is logged at WARNING and swallowed.
        Returns -1 on write failure so the caller can detect it (but
        critically does NOT raise — audit must never break the chat path).
        """
        with self._lock:
            seq = self._seq_counters.get(turn_id)
            if seq is None:
                # First append for this turn — initialize from existing
                # file if there is one (recovery path).
                seq = self._compute_next_seq_unlocked(turn_id)

            payload = dict(record)
            payload["seq"] = seq
            payload.setdefault("logged_at", _utc_iso_now())

            try:
                line = json.dumps(payload, default=str, ensure_ascii=False) + "\n"
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "TurnLedger could not serialize record for %s: %s",
                    turn_id, exc,
                )
                return -1

            path = self.path_for(turn_id)
            try:
                # Append, flush, fsync — durable per-record semantics.
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    try:
                        import os as _os
                        _os.fsync(fh.fileno())
                    except OSError:
                        # Some filesystems / Windows pipes do not support fsync.
                        pass
            except OSError as exc:
                logger.warning(
                    "TurnLedger append failed for %s: %s", turn_id, exc,
                )
                return -1

            self._seq_counters[turn_id] = seq + 1
            return seq

    def read_turn(self, turn_id: str) -> list[dict[str, Any]]:
        """Read all records for a turn, sorted by seq.

        Skips malformed/truncated JSONL lines with a logger.warning. Returns
        an empty list if the file does not exist. Never raises.
        """
        path = self.path_for(turn_id)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        try:
            with self._lock:
                with path.open("r", encoding="utf-8") as fh:
                    for lineno, raw in enumerate(fh, start=1):
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning(
                                "TurnLedger skipping malformed line %d in turn %s",
                                lineno, turn_id,
                            )
                            continue
                        if isinstance(obj, dict):
                            records.append(obj)
        except OSError as exc:
            logger.warning(
                "TurnLedger could not read turn %s: %s", turn_id, exc,
            )
            return []

        # Deterministic order — sort by seq if present, else file order.
        records.sort(key=lambda r: r.get("seq", 0))
        return records

    def list_turns(self) -> list[str]:
        """Return all turn_ids that have ledger files in base_dir."""
        if not self._base.exists():
            return []
        try:
            with self._lock:
                return sorted(
                    p.stem.removeprefix("turn_")
                    for p in self._base.glob("turn_*.jsonl")
                )
        except OSError as exc:
            logger.warning("TurnLedger list_turns failed: %s", exc)
            return []

    def iter_turn(self, turn_id: str) -> Iterator[dict[str, Any]]:
        """Yield records one at a time (still sorted, still fail-soft)."""
        for r in self.read_turn(turn_id):
            yield r

    # ── internals ────────────────────────────────────────────────────

    def _compute_next_seq_unlocked(self, turn_id: str) -> int:
        """Compute the next seq for a turn, recovering from any existing file.

        Caller must hold ``self._lock``. Inspects the existing file (if any)
        and returns max(seq) + 1, or 0 if no file or no parseable records.
        """
        path = self.path_for(turn_id)
        if not path.exists():
            return 0
        max_seq = -1
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        s = obj.get("seq")
                        if isinstance(s, int) and s > max_seq:
                            max_seq = s
        except OSError:
            return 0
        return max_seq + 1


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
