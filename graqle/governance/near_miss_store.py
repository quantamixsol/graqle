# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26167849.4, owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Near-Miss Corpus Management (R19 ADR-202).

Records predicted governance failures that were PREVENTED before
they occurred. Each prevented failure strengthens the prediction
corpus — creating a proprietary data moat.

Near-miss corpus growth: after 1,000 prevented failures, GraQle has
a failure corpus no competitor can buy.

Storage: append-only JSONL at .graqle/near-misses/{YYYY-MM-DD}.jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("graqle.governance.near_miss_store")

_DEFAULT_DIR = ".graqle/near-misses"


# ---------------------------------------------------------------------------
# Near-Miss Record
# ---------------------------------------------------------------------------


class NearMissRecord(BaseModel):
    """A predicted failure that was prevented.

    Each near-miss is a label for the prediction model:
    "this chain was predicted at probability P and did NOT result in failure
    because intervention X was applied."
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str | None = None
    predicted_chain_id: str | None = None
    predicted_probability: float = 0.0
    chain_summary: str = ""
    root_cause: str | None = None
    prevented_by: str = ""  # "manual_review", "gate_block", "auto_correction", etc.
    outcome: str = "prevented"  # always "prevented" for near-misses
    features_hash: str | None = None  # SHA-256 of feature vector for dedup


# ---------------------------------------------------------------------------
# Near-Miss Store
# ---------------------------------------------------------------------------


class NearMissStore:
    """Append-only near-miss corpus with daily file rotation.

    Storage format: .graqle/near-misses/{YYYY-MM-DD}.jsonl
    Each line is a JSON-serialized NearMissRecord.

    Parameters
    ----------
    store_dir:
        Directory for JSONL files. Created if missing.
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            store_dir = _DEFAULT_DIR
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._count = 0

    @property
    def count(self) -> int:
        """Near-misses recorded in this session."""
        return self._count

    def _current_file(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"{today}.jsonl"

    async def record(self, near_miss: NearMissRecord) -> None:
        """Append a near-miss record to the daily JSONL file."""
        line = json.dumps(near_miss.model_dump(mode="json"), default=str) + "\n"
        file_path = self._current_file()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_append, file_path, line)

        self._count += 1
        logger.debug(
            "Near-miss recorded: chain=%s, prevented_by=%s (total: %d)",
            near_miss.chain_summary[:50],
            near_miss.prevented_by,
            self._count,
        )

    @staticmethod
    def _sync_append(file_path: Path, line: str) -> None:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_near_misses(
        self,
        date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read near-miss records from a daily JSONL file."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        file_path = self._dir / f"{date}.jsonl"
        if not file_path.exists():
            return []

        records: list[dict[str, Any]] = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return records[-limit:][::-1]

    def corpus_size(self) -> int:
        """Total near-misses across all daily files."""
        total = 0
        for jsonl_file in self._dir.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                total += sum(1 for line in f if line.strip())
        return total
