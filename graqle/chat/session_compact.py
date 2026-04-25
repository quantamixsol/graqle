"""NS-08: graq_session_compact — bounded history with summary rollup.

Compacts a conversation's turn history in conversations.jsonl by
replacing N oldest turns with a single rolled-up summary record.
Keeps the total line count bounded so the JSONL never grows unbounded.

Design:
- Read all records for a given session_id (or workspace_fingerprint).
- If turn_count < threshold, return early (nothing to compact).
- Summarise the N oldest turns into a single "compacted" record.
- Rewrite the JSONL atomically: compacted record + remaining turns.
- Returns {compacted: N, retained: M, session_id: str}.

Invariants:
- Compaction is idempotent: running twice yields the same result.
- A compacted record has status="compacted" and summary = rolled-up text.
- Never deletes the most recent `keep_last` turns (default 10).
- Atomic rewrite: temp-file + os.replace (same pattern as ConfigDriftAuditor).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from graqle.chat.conversation_index import (
    DEFAULT_INDEX_RELATIVE,
    ConversationIndex,
    ConversationRecord,
    _utc_now_iso,
)

_COMPACT_KEEP_LAST_DEFAULT: int = 10
_COMPACT_THRESHOLD_DEFAULT: int = 20


def compact_session(
    session_id: str,
    *,
    root: Path | None = None,
    index_path: Path | None = None,
    keep_last: int = _COMPACT_KEEP_LAST_DEFAULT,
    threshold: int = _COMPACT_THRESHOLD_DEFAULT,
) -> dict[str, Any]:
    """Compact turn history for *session_id*, keeping the last *keep_last* turns.

    Returns a result dict with keys: compacted, retained, session_id, skipped.
    ``skipped=True`` when turn_count < threshold (no-op).
    """
    resolved_index = _resolve_index(root, index_path)

    idx = ConversationIndex(root=root, index_path=index_path)
    all_records = idx.load_records()

    # Partition: records for this session vs all others
    session_records = [r for r in all_records if r.id == session_id]
    other_records = [r for r in all_records if r.id != session_id]

    if len(session_records) < threshold:
        return {
            "session_id": session_id,
            "compacted": 0,
            "retained": len(session_records),
            "skipped": True,
            "reason": f"turn_count={len(session_records)} < threshold={threshold}",
        }

    # Sort by last_active ascending so oldest are first
    session_records.sort(key=lambda r: r.last_active)

    to_compact = session_records[: max(0, len(session_records) - keep_last)]
    to_keep = session_records[len(to_compact) :]

    if not to_compact:
        return {
            "session_id": session_id,
            "compacted": 0,
            "retained": len(session_records),
            "skipped": True,
            "reason": "nothing to compact after keep_last filter",
        }

    # Build rolled-up summary from oldest turns
    summaries = [r.summary for r in to_compact if r.summary]
    rolled_summary = _roll_up_summaries(summaries)

    compacted_record = ConversationRecord(
        id=session_id,
        workspace_fingerprint=to_compact[0].workspace_fingerprint,
        last_active=_utc_now_iso(),
        summary=rolled_summary,
        turn_count=sum(r.turn_count for r in to_compact),
        status="compacted",
    )

    # Reconstruct full record list: other sessions + compacted + kept
    new_records = other_records + [compacted_record] + to_keep

    _rewrite_index_atomic(resolved_index, new_records)

    return {
        "session_id": session_id,
        "compacted": len(to_compact),
        "retained": len(to_keep),
        "skipped": False,
    }


def _roll_up_summaries(summaries: list[str]) -> str:
    """Produce a single rolled-up summary from N turn summaries."""
    if not summaries:
        return "[compacted — no summaries]"
    joined = " | ".join(s.strip() for s in summaries if s.strip())
    max_len = 400
    if len(joined) > max_len:
        joined = joined[:max_len] + "…"
    return f"[compacted {len(summaries)} turns] {joined}"


def _resolve_index(root: Path | None, index_path: Path | None) -> Path:
    if index_path is not None:
        return Path(index_path)
    base = Path(root) if root else Path.cwd()
    return base / DEFAULT_INDEX_RELATIVE


def _rewrite_index_atomic(index_path: Path, records: list[ConversationRecord]) -> None:
    """Atomically rewrite conversations.jsonl with *records*."""
    from dataclasses import asdict

    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=index_path.parent, prefix=".conversations_compact_", suffix=".jsonl"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(asdict(rec)) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, index_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
