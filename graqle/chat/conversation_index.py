"""NS-07 (Wave 2 Phase 9): ConversationIndex — per-turn session metadata store.

Append-only JSONL file at ``.graqle/conversations.jsonl`` records one
row per completed chat turn. The ``graq_session_list`` MCP tool reads
this file, reconstructs latest-state-per-id, and returns sorted results.

## Data model

Each line in conversations.jsonl is a JSON object with keys:
  - ``id``: str               — the turn_id (also conversation id in Phase 9)
  - ``workspace_fingerprint``: str — SHA-256 of resolved project root
  - ``last_active``: str      — ISO-8601 UTC (with Z suffix)
  - ``summary``: str          — first 200 chars of user message
  - ``turn_count``: int       — 1 for new, increments on re-append
  - ``status``: str           — "completed" | "error" | "fast-path"

## Concurrency

Module-level ``RLock`` guards ``append_record`` and ``load_records``.
Single-process thread-safe. Multi-process out of scope (same contract
as Phase 3 ConfigDriftAuditor).

## Resilience

- Corrupt JSONL lines are silently skipped during load (log debug).
- Missing file returns empty list, not an error.
- Parent directory created on first append.
- Atomic append via ``open(..., "a")`` + flush (single-line writes are
  atomic on POSIX + Windows for writes <= PIPE_BUF).

## NOT R18

This is a Phase 9 bridge — once R18 GETC merges (PR #46), NS-04 will
consume ``GovernedTrace`` for richer records. NS-07's JSONL format is
intentionally simple so future phases can migrate it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.chat.conversation_index")


# ── Module constants ──────────────────────────────────────────────────

DEFAULT_INDEX_RELATIVE: Path = Path(".graqle") / "conversations.jsonl"
_INDEX_LOCK = threading.RLock()
_SUMMARY_MAX_LEN: int = 200
_LIST_LIMIT_DEFAULT: int = 50
_LIST_LIMIT_MAX: int = 500


# ── Helpers ───────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with trailing 'Z'."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _fingerprint_workspace(root: Path) -> str:
    """Return SHA-256 hex digest of the absolute, resolved root path.

    Deterministic — same path yields same fingerprint. No PII (the
    path itself is hashed, not recorded in cleartext). Used to isolate
    conversations per workspace in multi-project setups.
    """
    resolved = str(root.resolve()).encode("utf-8")
    return hashlib.sha256(resolved).hexdigest()


def _truncate_summary(message: Any) -> str:
    """Return first _SUMMARY_MAX_LEN chars of a user message. Non-strings
    are coerced via str(). None/empty yields empty string."""
    if message is None:
        return ""
    if not isinstance(message, str):
        message = str(message)
    return message[:_SUMMARY_MAX_LEN]


# ── ConversationRecord ────────────────────────────────────────────────


@dataclass(frozen=True)
class ConversationRecord:
    """One row in conversations.jsonl.

    Fields are JSON-serializable. Immutable (frozen=True) so callers
    cannot mutate a record after append.
    """

    id: str
    workspace_fingerprint: str
    last_active: str
    summary: str
    turn_count: int = 1
    status: str = "completed"  # "completed" | "error" | "fast-path"

    def to_json_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json_line(cls, line: str) -> "ConversationRecord":
        """Parse a single JSON line. Raises json.JSONDecodeError on bad input.
        Missing optional fields default. Required fields missing → KeyError.
        """
        data = json.loads(line)
        return cls(
            id=data["id"],
            workspace_fingerprint=data["workspace_fingerprint"],
            last_active=data["last_active"],
            summary=data.get("summary", ""),
            turn_count=int(data.get("turn_count", 1)),
            status=data.get("status", "completed"),
        )


# ── ConversationIndex ─────────────────────────────────────────────────


class ConversationIndex:
    """Append-only JSONL-backed index of chat turns.

    Single-process thread-safe. Multi-process out of scope.
    """

    def __init__(
        self,
        root: Path | None = None,
        index_path: Path | None = None,
    ) -> None:
        self.root: Path = (root or Path.cwd()).resolve()
        if index_path is not None:
            self.index_path: Path = Path(index_path).resolve()
        else:
            self.index_path = (self.root / DEFAULT_INDEX_RELATIVE).resolve()

    # ── public API ────────────────────────────────────────────────────

    def append_record(self, record: ConversationRecord) -> None:
        """Append a record to the JSONL file. Creates parent dir if missing.

        Fire-and-forget: caller is expected to wrap this in try/except
        to prevent recording failures from propagating to the chat turn.
        """
        with _INDEX_LOCK:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.index_path, "a", encoding="utf-8") as f:
                f.write(record.to_json_line())
                f.write("\n")
                f.flush()

    def load_records(self) -> list[ConversationRecord]:
        """Return all parseable records from disk. Corrupt lines skipped.

        Missing file returns empty list. Order: file order (append
        order, oldest first).
        """
        with _INDEX_LOCK:
            if not self.index_path.exists():
                return []
            records: list[ConversationRecord] = []
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    for line_num, raw in enumerate(f, start=1):
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            records.append(ConversationRecord.from_json_line(line))
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                            logger.debug(
                                "NS-07: skipping corrupt line %d: %s",
                                line_num, exc,
                            )
                            continue
            except OSError as exc:
                logger.debug("NS-07: failed to read index: %s", exc)
                return []
            return records

    def list_sessions(
        self,
        *,
        workspace_fingerprint: str | None = None,
        limit: int = _LIST_LIMIT_DEFAULT,
    ) -> list[dict[str, Any]]:
        """Return most-recent-first list of latest-state-per-id.

        Optional filter by ``workspace_fingerprint`` (exact match).
        ``limit`` clamped to [1, _LIST_LIMIT_MAX].
        """
        # Clamp limit
        if not isinstance(limit, int):
            limit = _LIST_LIMIT_DEFAULT
        limit = max(1, min(limit, _LIST_LIMIT_MAX))

        records = self.load_records()

        # Fold: keep latest record per id (last-write-wins).
        latest: dict[str, ConversationRecord] = {}
        for rec in records:
            # Filter by workspace if requested
            if (
                workspace_fingerprint is not None
                and rec.workspace_fingerprint != workspace_fingerprint
            ):
                continue
            # last-write-wins: replay order = append order
            existing = latest.get(rec.id)
            if existing is None:
                latest[rec.id] = rec
            else:
                # Increment turn_count if we've seen this id before
                merged = ConversationRecord(
                    id=rec.id,
                    workspace_fingerprint=rec.workspace_fingerprint,
                    last_active=rec.last_active,
                    summary=rec.summary,
                    turn_count=existing.turn_count + 1,
                    status=rec.status,
                )
                latest[rec.id] = merged

        # Sort by last_active descending (most-recent first)
        sorted_records = sorted(
            latest.values(),
            key=lambda r: r.last_active,
            reverse=True,
        )
        return [asdict(r) for r in sorted_records[:limit]]


# ── Instrumentation helper for handle_chat_turn ───────────────────────


def record_turn(
    *,
    turn_id: str,
    message: str,
    status: str = "completed",
    root: Path | None = None,
) -> None:
    """Fire-and-forget record of a completed chat turn.

    Called from ``handle_chat_turn`` after the turn exits. Failure is
    logged at debug level but never raises — recording is observational
    and must not break the chat turn.

    Typical call:
        try:
            record_turn(turn_id=tid, message=msg, status="completed")
        except Exception as exc:
            logger.debug("NS-07 record_turn failed: %s", exc)
    """
    try:
        idx = ConversationIndex(root=root)
        rec = ConversationRecord(
            id=turn_id,
            workspace_fingerprint=_fingerprint_workspace(idx.root),
            last_active=_utc_now_iso(),
            summary=_truncate_summary(message),
            turn_count=1,
            status=status,
        )
        idx.append_record(rec)
    except Exception as exc:
        logger.debug("NS-07: record_turn failed: %s", exc)


# ── MCP response helper ───────────────────────────────────────────────


def build_session_list_response(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shape the graq_session_list response envelope."""
    return {
        "conversations": sessions,
        "count": len(sessions),
    }
