"""NS-09: graq_session_resume — load a prior conversation into active context.

Reads a past session from conversations.jsonl and returns its full
turn history as a structured context bundle that can be prepended to
the next graq_chat_turn call.

Design:
- Lookup session_id in conversations.jsonl.
- Return {session_id, summary, turn_count, last_active, status,
          context_bundle: str} where context_bundle is a formatted
  text representation suitable for embedding in a system prompt.
- If session_id not found, return {found: false, session_id: ...}.
- Never raises — always returns a dict.

Invariants:
- Read-only: does not modify conversations.jsonl.
- context_bundle is bounded to max_chars (default 2000) for token safety.
- Compacted records are handled gracefully (summary is already rolled-up).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from graqle.chat.conversation_index import (
    ConversationIndex,
)

_CONTEXT_BUNDLE_MAX_CHARS: int = 2000


def resume_session(
    session_id: str,
    *,
    root: Path | None = None,
    index_path: Path | None = None,
    max_chars: int = _CONTEXT_BUNDLE_MAX_CHARS,
) -> dict[str, Any]:
    """Load context for *session_id* from conversations.jsonl.

    Returns a result dict.  ``found=False`` when session_id is unknown.
    """
    idx = ConversationIndex(root=root, index_path=index_path)
    all_records = idx.load_records()

    session_records = [r for r in all_records if r.id == session_id]

    if not session_records:
        return {
            "found": False,
            "session_id": session_id,
            "context_bundle": "",
        }

    # Sort ascending by last_active to build chronological context
    session_records.sort(key=lambda r: r.last_active)

    # Build context bundle
    bundle = _build_context_bundle(session_records, max_chars=max_chars)

    latest = session_records[-1]
    return {
        "found": True,
        "session_id": session_id,
        "last_active": latest.last_active,
        "turn_count": sum(r.turn_count for r in session_records),
        "status": latest.status,
        "summary": latest.summary,
        "context_bundle": bundle,
    }


def _build_context_bundle(records: list, max_chars: int) -> str:
    """Format turn records into a context string for system-prompt injection."""
    lines: list[str] = ["=== Resumed session context ==="]
    for rec in records:
        status_tag = f"[{rec.status}]" if rec.status != "completed" else ""
        line = f"[{rec.last_active}] {status_tag} {rec.summary}".strip()
        lines.append(line)
    lines.append("=== End resumed context ===")
    bundle = "\n".join(lines)
    if len(bundle) > max_chars:
        bundle = bundle[:max_chars] + "\n[… truncated for token safety]"
    return bundle
