# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8, EP26166054.2, EP26167849.4 (composite),
# owned by Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Cross-Organization Pattern Registry (R21 ADR-204).

Append-only store for privacy-verified abstract governance patterns.
Each entry contains only hashed provenance and structural abstractions.

Storage layout: .graqle/patterns/{YYYY-MM-DD}.jsonl
Index: .graqle/patterns/index.json with metadata only.

Privacy invariants:
- source_org_hash is SHA-256 only (never raw org name)
- Every pattern is re-verified against denylist on read
- Rejected patterns are never stored (fail-closed)

Multi-tenant isolation: Org A cannot query Org B's patterns unless the
caller provides Org B's pattern IDs directly (no pattern enumeration
by org hash from an outsider).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from graqle.governance.pattern_abstractor import AbstractPattern, verify_privacy

logger = logging.getLogger("graqle.governance.pattern_registry")

_DEFAULT_DIR = ".graqle/patterns"
_INDEX_FILE = "index.json"


class RegistryEntry(BaseModel):
    """Index metadata for a stored pattern — no raw data."""

    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    source_org_hash: str
    trace_class: str
    created_at: datetime
    file: str  # daily jsonl filename


class PatternRegistry:
    """Append-only cross-org pattern registry.

    Parameters
    ----------
    store_dir:
        Root directory for pattern storage. Created if missing.
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            store_dir = _DEFAULT_DIR
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._count = 0

    @property
    def store_dir(self) -> Path:
        return self._dir

    @property
    def count(self) -> int:
        """Patterns added in this session."""
        return self._count

    def _current_file(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"{today}.jsonl"

    async def register(self, pattern: AbstractPattern) -> RegistryEntry:
        """Register a pattern. Fails closed on privacy violation.

        Raises
        ------
        ValueError: if pattern fails privacy verification.
        """
        if not verify_privacy(pattern):
            raise ValueError(
                f"Pattern {pattern.pattern_id} failed privacy verification; refusing to register"
            )

        # Serialize
        data = pattern.model_dump(mode="json")
        line = json.dumps(data, default=str) + "\n"

        file_path = self._current_file()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_append, file_path, line)

        entry = RegistryEntry(
            pattern_id=pattern.pattern_id,
            source_org_hash=pattern.source_org_hash,
            trace_class=pattern.trace_class,
            created_at=pattern.provenance.created_at,
            file=file_path.name,
        )

        self._append_index(entry)
        self._count += 1
        logger.debug(
            "Pattern registered: %s (trace_class=%s, org_hash_prefix=%s)",
            pattern.pattern_id,
            pattern.trace_class,
            pattern.source_org_hash[:8],
        )
        return entry

    @staticmethod
    def _sync_append(file_path: Path, line: str) -> None:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def _append_index(self, entry: RegistryEntry) -> None:
        index_path = self._dir / _INDEX_FILE
        existing = self._read_index()
        existing.append(entry.model_dump(mode="json"))
        tmp = index_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, index_path)

    def _read_index(self) -> list[dict[str, Any]]:
        index_path = self._dir / _INDEX_FILE
        if not index_path.exists():
            return []
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def list_patterns(
        self,
        trace_class: str | None = None,
        limit: int = 100,
    ) -> list[RegistryEntry]:
        """List pattern metadata entries (no raw content).

        Parameters
        ----------
        trace_class:
            Filter by trace class (e.g., "reasoning", "generation").
        limit:
            Maximum entries to return.
        """
        entries = self._read_index()
        if trace_class:
            entries = [e for e in entries if e.get("trace_class") == trace_class]
        return [RegistryEntry(**e) for e in entries[-limit:][::-1]]

    def corpus_size(self) -> int:
        """Total patterns across all daily files."""
        total = 0
        for jsonl_file in self._dir.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                total += sum(1 for line in f if line.strip())
        return total

    def load_pattern(self, pattern_id: str) -> AbstractPattern | None:
        """Load a specific pattern by ID.

        Scans daily files until found. Re-verifies privacy on load.
        Returns None if not found or verification fails.
        """
        for jsonl_file in sorted(self._dir.glob("*.jsonl")):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("pattern_id") == pattern_id:
                        try:
                            pattern = AbstractPattern(**data)
                            if not verify_privacy(pattern):
                                logger.warning(
                                    "Loaded pattern %s failed re-verification; rejecting",
                                    pattern_id,
                                )
                                return None
                            return pattern
                        except Exception:
                            return None
        return None

    def find_matches(
        self,
        trace_class: str,
        exclude_org_hash: str | None = None,
        limit: int = 20,
    ) -> list[AbstractPattern]:
        """Find patterns matching a trace class, optionally excluding an org.

        Used by the federated transfer engine to find source patterns
        for a target org. Excludes patterns from the target's own org hash
        so you don't "transfer" a pattern back to its origin.
        """
        matches: list[AbstractPattern] = []
        for entry in self.list_patterns(trace_class=trace_class, limit=500):
            if exclude_org_hash and entry.source_org_hash == exclude_org_hash:
                continue
            pattern = self.load_pattern(entry.pattern_id)
            if pattern is not None:
                matches.append(pattern)
            if len(matches) >= limit:
                break
        return matches
