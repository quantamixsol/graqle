"""CorrectionRecord persistence layer — append-only JSONL with fsync guarantee."""

# ── graqle:intelligence ──
# module: graqle.intent.correction_store
# risk: MEDIUM (impact radius: 3 modules)
# consumers: intent_router, correction_feedback, training_pipeline
# dependencies: __future__, json, logging, os, time, typing, graqle.intent.types
# constraints: fsync after every write, corruption-resilient reads, dedup within window
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

from graqle.intent.types import CorrectionRecord

logger = logging.getLogger("graqle.intent.correction_store")


# ---------------------------------------------------------------------------
# RingBuffer — fixed-size circular buffer for O(1) online dedup
# ---------------------------------------------------------------------------


class RingBuffer:
    """Fixed-size circular buffer of :class:`CorrectionRecord` for O(1) online access."""

    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max(1, max_size)
        self._buffer: list[CorrectionRecord] = []
        self._index: int = 0
        self._full: bool = False

    def append(self, record: CorrectionRecord) -> None:
        """Append *record* in O(1), evicting the oldest entry when full."""
        if self._full:
            self._buffer[self._index] = record
        else:
            self._buffer.append(record)
        self._index = (self._index + 1) % self._max_size
        if not self._full and len(self._buffer) == self._max_size:
            self._full = True

    def recent(self, window_seconds: int = 60) -> List[CorrectionRecord]:
        """Return records whose timestamp falls within *window_seconds* of now."""
        cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
        results: list[CorrectionRecord] = []
        for r in self._buffer:
            try:
                record_ts = datetime.fromisoformat(r.timestamp).timestamp()
                if record_ts >= cutoff:
                    results.append(r)
            except (ValueError, TypeError):
                continue
        return results

    def __len__(self) -> int:
        return len(self._buffer)


# ---------------------------------------------------------------------------
# CorrectionStore — append-only JSONL persistence with fsync
# ---------------------------------------------------------------------------


class CorrectionStore:
    """Append-only JSONL persistence for :class:`CorrectionRecord` with dedup."""

    # ── persistence ───────────────────────────────────────────

    @staticmethod
    def persist_correction(
        record: CorrectionRecord,
        path: str = "corrections.jsonl",
        ring_buffer: Optional[RingBuffer] = None,
    ) -> None:
        """Append *record* to *path* with an fsync durability guarantee.

        Silently skips duplicate corrections (same ``normalized_query`` and
        ``corrected_tool`` within 60 s) when a *ring_buffer* is provided.
        """
        if CorrectionStore.is_duplicate(record, ring_buffer, window_seconds=60):
            logger.debug("Duplicate correction skipped: %s", record.normalized_query)
            return

        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

        if ring_buffer is not None:
            ring_buffer.append(record)

    # ── loading ───────────────────────────────────────────────

    @staticmethod
    def load_corrections(path: str = "corrections.jsonl") -> List[CorrectionRecord]:
        """Load all corrections from *path*, skipping malformed lines.

        Returns an empty list when the file does not exist.  Malformed lines
        are logged as warnings — the store never crashes on partial corruption.
        """
        records: list[CorrectionRecord] = []

        if not os.path.exists(path):
            return records

        with open(path, "r", encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = json.loads(raw_line)
                    records.append(CorrectionRecord.from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed line %d in %s: %s",
                        lineno,
                        path,
                        exc,
                    )

        return records

    # ── deduplication ─────────────────────────────────────────

    @staticmethod
    def is_duplicate(
        record: CorrectionRecord,
        ring_buffer: Optional[RingBuffer],
        window_seconds: int = 60,
    ) -> bool:
        """Return ``True`` if an identical correction exists within *window_seconds*.

        Identity is defined as matching ``normalized_query`` **and**
        ``corrected_tool``.  Without a *ring_buffer* no dedup is performed.
        """
        if ring_buffer is None:
            return False

        for existing in ring_buffer.recent(window_seconds):
            if (
                existing.normalized_query == record.normalized_query
                and existing.corrected_tool == record.corrected_tool
            ):
                return True

        return False
