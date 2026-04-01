# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ──────────────────────────────────────────────────────────────────

"""Immutable Reasoning Session Audit Trail.

Mapped from TAMR+ audit_trail.py (SHA-256 chain).
Records every AI reasoning session with tamper-evident hashing.

Every time an AI tool reasons over the codebase (via graq_reason, graq_gate,
or graq_impact), the session is logged immutably. This creates a full audit
trail of what the AI knew, what it decided, and why.

See ADR-105 §Governance Layer: audit_trail.py → governance/audit.py.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.audit
# risk: MEDIUM (impact radius: 4 modules)
# consumers: main, middleware, __init__, test_audit
# dependencies: __future__, hashlib, json, logging, datetime +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("graqle.intelligence.governance.audit")


class AuditEntry(BaseModel):
    """A single entry in the audit trail."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    action: str                        # "reason", "gate", "impact", "verify", "learn"
    tool: str = ""                     # "graq_reason", "graq_gate", etc.
    module: str = ""                   # target module
    input_summary: str = ""            # what was asked
    output_summary: str = ""           # what was decided
    evidence_count: int = 0            # how many evidence items supported this
    nodes_consulted: int = 0           # how many KG nodes were read
    duration_ms: float = 0.0
    caller: str = ""                   # which AI tool / agent
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Integrity
    entry_hash: str = ""               # SHA-256 of this entry's content
    prev_hash: str = ""                # SHA-256 of previous entry (chain)

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this entry's content."""
        content = json.dumps({
            "timestamp": self.timestamp,
            "action": self.action,
            "tool": self.tool,
            "module": self.module,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "prev_hash": self.prev_hash,
        }, sort_keys=True)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class AuditSession(BaseModel):
    """A reasoning session — a sequence of audit entries for one task."""

    session_id: str
    started: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    task: str = ""                     # "Modify auth middleware", "Review PR #42"
    status: Literal["active", "completed", "failed"] = "active"
    entries: list[AuditEntry] = Field(default_factory=list)
    drace_score: float | None = None   # Computed at session end

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def total_nodes_consulted(self) -> int:
        return sum(e.nodes_consulted for e in self.entries)

    @property
    def total_evidence(self) -> int:
        return sum(e.evidence_count for e in self.entries)

    def add_entry(self, entry: AuditEntry) -> AuditEntry:
        """Add an entry to the session with chain integrity."""
        if self.entries:
            entry.prev_hash = self.entries[-1].entry_hash
        entry.entry_hash = entry.compute_hash()
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        """Verify the hash chain integrity of all entries."""
        for i, entry in enumerate(self.entries):
            # Verify hash
            expected = entry.compute_hash()
            if entry.entry_hash != expected:
                logger.warning("Hash mismatch at entry %d: %s != %s", i, entry.entry_hash, expected)
                return False
            # Verify chain
            if i > 0 and entry.prev_hash != self.entries[i - 1].entry_hash:
                logger.warning("Chain break at entry %d", i)
                return False
        return True

    def complete(self, drace_score: float | None = None) -> None:
        """Mark session as completed."""
        self.status = "completed"
        self.drace_score = drace_score


class AuditTrail:
    """Manages the persistent audit trail on disk.

    Stores sessions as JSON in .graqle/governance/audit/.
    Each session is one file. The trail is append-only.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.audit_dir = root / ".graqle" / "governance" / "audit"

    def _ensure_dir(self) -> None:
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def start_session(self, task: str, session_id: str | None = None) -> AuditSession:
        """Start a new audit session."""
        self._ensure_dir()
        if session_id is None:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session = AuditSession(session_id=session_id, task=task)
        self._save_session(session)
        return session

    def log_entry(self, session: AuditSession, entry: AuditEntry) -> AuditEntry:
        """Add an entry to a session and persist."""
        result = session.add_entry(entry)
        self._save_session(session)
        return result

    def complete_session(
        self, session: AuditSession, drace_score: float | None = None
    ) -> None:
        """Complete a session and persist."""
        session.complete(drace_score)
        self._save_session(session)

    def load_session(self, session_id: str) -> AuditSession | None:
        """Load a session from disk."""
        fpath = self.audit_dir / f"{session_id}.json"
        if not fpath.exists():
            return None
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return AuditSession(**data)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent audit sessions (metadata only)."""
        if not self.audit_dir.exists():
            return []

        sessions = []
        for fpath in sorted(self.audit_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id"),
                    "task": data.get("task"),
                    "status": data.get("status"),
                    "started": data.get("started"),
                    "entry_count": len(data.get("entries", [])),
                    "drace_score": data.get("drace_score"),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return sessions

    def _save_session(self, session: AuditSession) -> None:
        """Persist session to disk."""
        self._ensure_dir()
        fpath = self.audit_dir / f"{session.session_id}.json"
        fpath.write_text(
            json.dumps(session.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )


class DebateAuditEvent(AuditEntry):
    """Audit entry for a single debate turn in DRACE branching trails."""

    action: str = Field(default="debate")
    round_number: int = 0
    panelist: str = ""
    position: str = ""  # propose / challenge / synthesize
    cost_usd: float = 0.0
    clearance_level: str = "public"
    branch_parent_id: str | None = None
    gate_decisions: dict[str, Any] = Field(default_factory=dict)
